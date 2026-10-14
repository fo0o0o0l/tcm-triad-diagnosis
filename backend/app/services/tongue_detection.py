"""舌诊图像处理：质量校验、舌体区域提取、舌象特征识别（M2-2 / M2-3 / M2-4）。

开发期使用 Pillow 实现的**确定性启发式**替代真实 CV 模型，保证前后端可联调演示：
- 质量校验：拉普拉斯/边缘方差（清晰度）、均值亮度（光照）、舌体色域覆盖率（构图）；
- 区域提取：基于舌体色域（偏红、低蓝）生成二值掩膜并给出提取置信度；
- 特征识别：对舌体区域色彩统计映射四类特征标签与置信度。

生产环境将 `extract_region` / `classify_features` 替换为算法服务
（`POST {ALGO_BASE_URL}/tongue/segment` 与 `/tongue/classify`），接口与返回结构保持不变。
"""

from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageFilter, ImageStat

from app.core.config import settings
from app.core.errors import ErrorCode
from app.core.response import BusinessError

#: 色域判定阈值（舌体：偏红、较亮、蓝通道明显低于红通道）
_R_MIN = 105
_RG_MIN = 12
_RB_MIN = 18

#: 舌体覆盖率达此值视为满置信
_FULL_COVERAGE = 0.40
_MIN_COVERAGE = 0.02


def _load_small(source: str | bytes, size: int = 256) -> Image.Image:
    """读取（路径或字节）并等比缩放（限制计算量），统一为 RGB。"""
    stream = BytesIO(source) if isinstance(source, bytes) else source
    image = Image.open(stream).convert("RGB")
    image.thumbnail((size, size))
    return image


def _is_tongue_pixel(r: int, g: int, b: int) -> bool:
    return r >= _R_MIN and (r - g) >= _RG_MIN and (r - b) >= _RB_MIN


def _coverage_and_mean(image: Image.Image) -> tuple[float, tuple[float, float, float]]:
    """返回（舌体色域覆盖率, 舌体像素 RGB 均值）。"""
    pixels = list(image.getdata())
    total = len(pixels)
    count = 0
    sr = sg = sb = 0
    for r, g, b in pixels:
        if _is_tongue_pixel(r, g, b):
            count += 1
            sr += r
            sg += g
            sb += b
    if count == 0:
        return 0.0, (0.0, 0.0, 0.0)
    return count / total, (sr / count, sg / count, sb / count)


# ---- T1 质量校验（PRD §7.1）----
def assess_quality(source: str | bytes) -> dict:
    """返回 `{passed, clearness, lighting, composition, suggestions, score}`。"""
    image = _load_small(source)
    gray = image.convert("L")

    # 清晰度：边缘图标准差越高越清晰
    edges = gray.filter(ImageFilter.FIND_EDGES)
    clearness = _clamp(ImageStat.Stat(edges).stddev[0] / 25.0)

    # 光照：以 150 为理想亮度，偏离越多得分越低
    brightness = ImageStat.Stat(gray).mean[0]
    lighting = _clamp(1.0 - abs(brightness - 150.0) / 150.0)

    # 构图：舌体色域覆盖率
    coverage, _ = _coverage_and_mean(image)
    composition = _clamp(coverage / 0.25)

    suggestions: list[str] = []
    if clearness < 0.5:
        suggestions.append("图像模糊，请保持稳定后重拍")
    if lighting < 0.5:
        suggestions.append("光照不足/过强，请在均匀自然光下拍摄")
    if composition < 0.5:
        suggestions.append("舌体未完整入镜，请调整距离后重拍")

    threshold = settings.DEFAULT_CONFIDENCE_THRESHOLD
    passed = clearness >= threshold and lighting >= threshold and composition >= threshold
    score = round((clearness + lighting + composition) / 3.0, 3)
    return {
        "passed": passed,
        "clearness": round(clearness, 3),
        "lighting": round(lighting, 3),
        "composition": round(composition, 3),
        "suggestions": suggestions,
        "score": score,
    }


# ---- T2 舌体区域提取（PRD §6.1.2）----
def extract_region(source: str | bytes) -> tuple[bytes, float]:
    """生成舌体掩膜（PNG 字节）与提取置信度；未检出舌体抛 42201。"""
    image = _load_small(source, size=320)
    mask = Image.new("L", image.size, 0)
    mask.putdata([255 if _is_tongue_pixel(r, g, b) else 0 for r, g, b in image.getdata()])

    coverage = sum(1 for v in mask.getdata() if v) / (image.width * image.height)
    if coverage < _MIN_COVERAGE:
        raise BusinessError(ErrorCode.IMAGE_QUALITY, "未能识别舌体，请重拍")

    # 轻量平滑，掩膜边缘更自然
    mask = mask.filter(ImageFilter.GaussianBlur(2))
    confidence = round(min(0.95, 0.60 + (coverage / _FULL_COVERAGE) * 0.35), 3)

    buffer = BytesIO()
    mask.convert("RGB").save(buffer, format="PNG")
    return buffer.getvalue(), confidence


# ---- T3 舌象特征识别（PRD §6.1.3）----
def classify_features(source: str | bytes, feature_names: list[str]) -> list[dict]:
    """对舌体区域色彩统计，输出四类特征的 `{name, label, confidence}`。"""
    image = _load_small(source)
    _, (r, g, b) = _coverage_and_mean(image)
    brightness = (r + g + b) / 3.0
    if r == 0.0 and g == 0.0 and b == 0.0:
        # 极端情况：未检出舌体色域，退化为默认结果
        brightness = ImageStat.Stat(image.convert("L")).mean[0]

    label, confidence = _tongue_color(r, g, b)
    coating_label, coating_conf = _coating_color(r, g, b, brightness)

    catalog: dict[str, dict] = {
        "tongue_color": {"name": "tongue_color", "label": label, "confidence": confidence},
        "coating_color": {
            "name": "coating_color",
            "label": coating_label,
            "confidence": coating_conf,
        },
        "coating_texture": {
            "name": "coating_texture",
            "label": "薄",
            "confidence": 0.80,
        },
        "tongue_shape": {"name": "tongue_shape", "label": "正常", "confidence": 0.76},
    }
    # 齿痕启发式：舌体边缘波动较大时判为齿痕
    if _edge_waviness(image) > 0.55:
        catalog["tongue_shape"] = {
            "name": "tongue_shape",
            "label": "齿痕",
            "confidence": 0.74,
        }

    ordered = [name for name in feature_names if name in catalog] or list(catalog)
    return [catalog[name] for name in ordered]


def _tongue_color(r: float, g: float, b: float) -> tuple[str, float]:
    if b >= g * 1.02 and r < 170:
        return "青紫", 0.78
    if r - b > 100:
        return "绛红", 0.82
    if r - b > 60:
        return "红", 0.85
    if r > 200 and abs(r - b) < 55 and g > 150:
        return "淡白", 0.80
    return "淡红", 0.88


def _coating_color(r: float, g: float, b: float, brightness: float) -> tuple[str, float]:
    # 偏黄：绿通道抬升且明显高于蓝
    if g - b > 30 and r - b > 20:
        return "黄", 0.82
    # 暗浊：整体偏暗
    if brightness < 110:
        return "灰黑", 0.76
    return "白", 0.86


def _edge_waviness(image: Image.Image) -> float:
    """舌体区域边缘波动度（0~1），用于齿痕启发式判定。"""
    edges = image.convert("L").filter(ImageFilter.FIND_EDGES)
    return _clamp(ImageStat.Stat(edges).stddev[0] / 45.0)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))