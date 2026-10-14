"""面诊图像处理：质量校验、面部区域检测、面象特征识别（M3-2 / M3-3 / M3-4）。

开发期使用 Pillow 实现的**确定性启发式**替代真实 CV 模型，保证前后端可联调演示：
- 质量校验：拉普拉斯/边缘方差（清晰度）、均值亮度（光照）、肤色覆盖率（构图），
  并按肤色连通域数量估计人脸数（单脸）与遮挡（面部框内肤色占比）；
- 区域检测：输出 `face_count` 与面部五区（额头/左颊/右颊/鼻部/下颌）bbox，非单脸抛 42201；
- 特征识别：对面部区域肤色统计，映射四类面象特征（面色/光泽/痘痘/斑点），
  痘痘/斑点额外输出分布区域 `area`。

生产环境将 `detect_regions` / `classify_features` 替换为算法服务
（`POST {ALGO_BASE_URL}/face/detect` 与 `/face/classify`），接口与返回结构保持不变。
"""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageFilter, ImageStat

from app.core.config import settings
from app.core.errors import ErrorCode
from app.core.response import BusinessError

#: 肤色判定（RGB 经典规则，适配中偏暖肤色）
_SKIN_MIN_COVERAGE = 0.05
#: 单个肤色连通域达图面积此比例才计为一张脸
_COMPONENT_MIN_RATIO = 0.03
#: 面部框内肤色占比低于此值判为遮挡
_OCCLUSION_MIN_RATIO = 0.55

#: 面部五区（PRD §9.3.2 额头/左颊/右颊/鼻部/下颌）
FACE_REGION_NAMES = ["forehead", "left_cheek", "right_cheek", "nose", "chin"]


def _load_small(source: str | bytes, size: int = 256) -> Image.Image:
    """读取（路径或字节）并等比缩放（限制计算量），统一为 RGB。"""
    stream = BytesIO(source) if isinstance(source, bytes) else source
    image = Image.open(stream).convert("RGB")
    image.thumbnail((size, size))
    return image


def _is_skin(r: int, g: int, b: int) -> bool:
    """经典 RGB 肤色规则：偏红、暖色、通道差显著。"""
    return (
        r > 95
        and g > 40
        and b > 20
        and max(r, g, b) - min(r, g, b) > 15
        and abs(r - g) > 15
        and r > g
        and r > b
    )


def _skin_mask(image: Image.Image) -> list[bool]:
    return [_is_skin(r, g, b) for r, g, b in image.getdata()]


def _label_components(
    mask: list[bool], width: int, height: int
) -> list[tuple[int, int, int, int, int]]:
    """肤色连通域标记（4 邻域洪水填充），返回 `[(area, x0, y0, x1, y1)]`（含式边界）。"""
    seen = [False] * (width * height)
    components: list[tuple[int, int, int, int, int]] = []
    for start in range(width * height):
        if not mask[start] or seen[start]:
            continue
        stack = [start]
        seen[start] = True
        area = 0
        x0 = y0 = 1 << 30
        x1 = y1 = -1
        while stack:
            index = stack.pop()
            x = index % width
            y = index // width
            area += 1
            if x < x0:
                x0 = x
            if x > x1:
                x1 = x
            if y < y0:
                y0 = y
            if y > y1:
                y1 = y
            if x > 0 and mask[index - 1] and not seen[index - 1]:
                seen[index - 1] = True
                stack.append(index - 1)
            if x < width - 1 and mask[index + 1] and not seen[index + 1]:
                seen[index + 1] = True
                stack.append(index + 1)
            if y > 0 and mask[index - width] and not seen[index - width]:
                seen[index - width] = True
                stack.append(index - width)
            if y < height - 1 and mask[index + width] and not seen[index + width]:
                seen[index + width] = True
                stack.append(index + width)
        components.append((area, x0, y0, x1, y1))
    return components


def _significant_components(
    components: list[tuple[int, int, int, int, int]], width: int, height: int
) -> list[tuple[int, int, int, int, int]]:
    min_area = _COMPONENT_MIN_RATIO * width * height
    return [c for c in components if c[0] >= min_area]


def _face_box(pixels: list, width: int, height: int) -> tuple[int, int, int, int] | None:
    """返回主要人脸 bbox；未检出返回 None。"""
    mask = [_is_skin(r, g, b) for r, g, b in pixels]
    big = _significant_components(_label_components(mask, width, height), width, height)
    if not big:
        return None
    _, x0, y0, x1, y1 = max(big, key=lambda c: c[0])
    return x0, y0, x1, y1


# ---- 区域划分 ----
def _split_regions(x0: int, y0: int, x1: int, y1: int) -> list[dict]:
    """按面部框比例切分五区，返回 `[{name, bbox}]`。"""
    w = x1 - x0
    h = y1 - y0
    boxes = {
        "forehead": (x0 + 0.20 * w, y0, x1 - 0.20 * w, y0 + 0.30 * h),
        "left_cheek": (x0, y0 + 0.45 * h, x0 + 0.42 * w, y0 + 0.90 * h),
        "right_cheek": (x1 - 0.42 * w, y0 + 0.45 * h, x1, y0 + 0.90 * h),
        "nose": (x0 + 0.35 * w, y0 + 0.28 * h, x1 - 0.35 * w, y0 + 0.65 * h),
        "chin": (x0 + 0.25 * w, y0 + 0.72 * h, x1 - 0.25 * w, y1),
    }
    return [
        {
            "name": name,
            "bbox": [
                int(round(boxes[name][0])),
                int(round(boxes[name][1])),
                int(round(boxes[name][2])),
                int(round(boxes[name][3])),
            ],
        }
        for name in FACE_REGION_NAMES
    ]


# ---- F1 质量校验（PRD §7.1）----
def assess_quality(source: str | bytes) -> dict:
    """返回 `{passed, clearness, lighting, composition, face_detected, single_face, suggestions, score}`。"""
    image = _load_small(source)
    width, height = image.size
    gray = image.convert("L")

    # 清晰度：边缘图标准差越高越清晰
    edges = gray.filter(ImageFilter.FIND_EDGES)
    clearness = _clamp(ImageStat.Stat(edges).stddev[0] / 25.0)

    # 光照：以 150 为理想亮度，偏离越多得分越低
    brightness = ImageStat.Stat(gray).mean[0]
    lighting = _clamp(1.0 - abs(brightness - 150.0) / 150.0)

    # 构图：肤色覆盖率（面部占比）
    mask = _skin_mask(image)
    coverage = sum(mask) / (width * height)
    composition = _clamp(coverage / 0.25)

    # 人脸数与遮挡：肤色连通域数量 / 面部框内肤色占比
    big = _significant_components(_label_components(mask, width, height), width, height)
    face_count = len(big)
    face_detected = coverage >= _SKIN_MIN_COVERAGE and face_count >= 1
    single_face = face_count == 1
    occlusion_ok = True
    if big:
        area, x0, y0, x1, y1 = max(big, key=lambda c: c[0])
        box_area = max(1, (x1 - x0 + 1) * (y1 - y0 + 1))
        occlusion_ok = (area / box_area) >= _OCCLUSION_MIN_RATIO

    suggestions: list[str] = []
    if clearness < 0.5:
        suggestions.append("图像模糊，请保持稳定后重拍")
    if lighting < 0.5:
        suggestions.append("光照不足/过强，请在均匀自然光下拍摄")
    if composition < 0.5:
        suggestions.append("面部未完整入镜，请调整距离后重拍")
    if not face_detected:
        suggestions.append("未检测到面部，请正对镜头、避免侧脸后重拍")
    elif not single_face:
        suggestions.append("请确保画面中仅一张清晰正脸")
    if face_detected and single_face and not occlusion_ok:
        suggestions.append("请摘除口罩/头发等遮挡物后重拍")

    threshold = settings.DEFAULT_CONFIDENCE_THRESHOLD
    passed = (
        clearness >= threshold
        and lighting >= threshold
        and composition >= threshold
        and face_detected
        and single_face
        and occlusion_ok
    )
    score = round((clearness + lighting + composition) / 3.0, 3)
    return {
        "passed": passed,
        "clearness": round(clearness, 3),
        "lighting": round(lighting, 3),
        "composition": round(composition, 3),
        "face_detected": face_detected,
        "single_face": single_face,
        "suggestions": suggestions,
        "score": score,
    }


# ---- F2 面部区域检测（PRD §9.3.2）----
def detect_regions(source: str | bytes) -> tuple[int, list[dict], float]:
    """返回 `(face_count, regions, detect_confidence)`；非单脸抛 42201。"""
    image = _load_small(source, size=320)
    width, height = image.size
    mask = _skin_mask(image)
    big = _significant_components(_label_components(mask, width, height), width, height)
    face_count = len(big)
    if face_count != 1:
        message = (
            "未检测到面部，请重拍" if face_count == 0 else "画面需包含且仅包含一张清晰正脸"
        )
        raise BusinessError(
            ErrorCode.IMAGE_QUALITY,
            message,
            data={"face_count": face_count, "suggestions": ["请确保单人正脸、五官无遮挡"]},
        )

    area, x0, y0, x1, y1 = big[0]
    regions = _split_regions(x0, y0, x1, y1)
    coverage = area / (width * height)
    confidence = round(min(0.95, 0.60 + (coverage / 0.40) * 0.35), 3)
    return face_count, regions, confidence


# ---- F3 面象特征识别（PRD §6.2.3）----
def _scan_box(pixels: list, width: int, box: tuple[int, int, int, int], dark_threshold: float) -> dict:
    """统计面部框内肤色像素：数量、RGB 均值累计、高光/泛红/暗沉计数。"""
    x0, y0, x1, y1 = box
    skin = sr = sg = sb = highlight = red = dark = 0
    for y in range(max(0, y0), min(y1 + 1, len(pixels) // width)):
        row = y * width
        for x in range(max(0, x0), min(x1 + 1, width)):
            r, g, b = pixels[row + x]
            if not _is_skin(r, g, b):
                continue
            skin += 1
            sr += r
            sg += g
            sb += b
            if min(r, g, b) >= 200:
                highlight += 1
            if (r - g) >= 50 and r >= 150:
                red += 1
            if (r + g + b) / 3.0 < dark_threshold:
                dark += 1
    return {
        "skin": skin,
        "r": sr,
        "g": sg,
        "b": sb,
        "highlight": highlight,
        "red": red,
        "dark": dark,
    }


def classify_features(source: str | bytes, feature_names: list[str]) -> list[dict]:
    """对面部区域肤色统计，输出四类面象特征的 `{name, label, confidence, area?}`。"""
    image = _load_small(source)
    width, height = image.size
    pixels = list(image.getdata())
    box = _face_box(pixels, width, height) or (0, 0, width - 1, height - 1)

    base = _scan_box(pixels, width, box, dark_threshold=0.0)
    skin = base["skin"]
    if skin:
        r = base["r"] / skin
        g = base["g"] / skin
        b = base["b"] / skin
        mean_bright = (r + g + b) / 3.0
    else:
        # 未检出肤色：退化为全图亮度，避免除零
        r = g = b = mean_bright = ImageStat.Stat(image.convert("L")).mean[0]

    dark_threshold = _clamp(mean_bright - 45, 70, 150)
    stats = _scan_box(pixels, width, box, dark_threshold)
    denom = stats["skin"] or 1
    highlight_frac = stats["highlight"] / denom
    red_frac = stats["red"] / denom
    dark_frac = stats["dark"] / denom

    regions = _split_regions(*box)
    region_stats = {
        region["name"]: _scan_box(pixels, width, tuple(region["bbox"]), dark_threshold)
        for region in regions
    }

    face_color, color_conf = _face_color(r, g, b, mean_bright)
    luster, luster_conf = _luster(highlight_frac)
    acne, acne_conf, acne_area = _lesion(red_frac, region_stats, "red", 0.03, "痤疮")
    spots, spots_conf, spots_area = _lesion(dark_frac, region_stats, "dark", 0.04, "斑点")

    catalog: dict[str, dict] = {
        "face_color": {
            "name": "face_color",
            "label": face_color,
            "confidence": color_conf,
        },
        "luster": {"name": "luster", "label": luster, "confidence": luster_conf},
        "acne": {"name": "acne", "label": acne, "confidence": acne_conf, "area": acne_area},
        "spots": {"name": "spots", "label": spots, "confidence": spots_conf, "area": spots_area},
    }

    ordered = [name for name in feature_names if name in catalog] or list(catalog)
    return [catalog[name] for name in ordered]


def _face_color(r: float, g: float, b: float, brightness: float) -> tuple[str, float]:
    if b >= g:
        return "青紫", 0.74
    if brightness < 120:
        return "晦暗", 0.76
    if (r - b) >= 95 and brightness >= 150:
        return "潮红", 0.80
    if (g - b) >= 46 and (r - g) < 55:
        return "萎黄", 0.75
    if brightness >= 205 and (r - b) < 55:
        return "苍白", 0.78
    return "红润", 0.84


def _luster(highlight_frac: float) -> tuple[str, float]:
    if highlight_frac >= 0.12:
        return "油光", 0.78
    if highlight_frac >= 0.03:
        return "有光泽", 0.80
    return "少光泽", 0.77


def _lesion(
    fraction: float,
    region_stats: dict[str, dict],
    key: str,
    region_min: float,
    _label: str,
) -> tuple[str, float, list[str] | None]:
    """痘痘/斑点的程度与分布区域。"""
    if fraction >= 0.10:
        label, confidence = "较多", 0.83
    elif fraction >= 0.05:
        label, confidence = "中等", 0.82
    elif fraction >= 0.015:
        label, confidence = "少量", 0.81
    else:
        return "无", 0.86, None

    areas = [
        name
        for name, stat in region_stats.items()
        if (stat[key] / (stat["skin"] or 1)) >= region_min
    ]
    return label, confidence, areas


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))