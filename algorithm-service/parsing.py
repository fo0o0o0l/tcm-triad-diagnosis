"""大模型输出的健壮解析与归一化。

大模型可能返回带 Markdown 围栏 / 前后缀说明的文本，或缺字段、置信度越界；
本模块负责「安全解析 JSON」并「补全 / 钳制」为后端可稳定消费的结构，
任何无法解析的情况都抛错，由上层映射 503 交给后端降级到 mock（链路不中断）。
"""

from __future__ import annotations

import json
import re
from typing import Any

from schemas import Advice, Conclusion, FusionOutput, ModuleOutput, Syndrome

#: ```json ... ``` 围栏
_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)

_SUMMARY_KEY = {
    "tongue": "tongue_summary",
    "face": "face_summary",
    "inquiry": "symptoms_summary",
}


def parse_json_safely(raw: str) -> dict[str, Any]:
    """从模型返回文本中提取 JSON 对象；失败则抛 `ValueError`。"""
    text = (raw or "").strip()

    def _loads(candidate: str) -> dict[str, Any] | None:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    direct = _loads(text)
    if direct is not None:
        return direct

    fenced = _FENCE_RE.search(text)
    if fenced:
        inner = _loads(fenced.group(1))
        if inner is not None:
            return inner

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        sliced = _loads(text[start : end + 1])
        if sliced is not None:
            return sliced

    raise ValueError("无法解析大模型返回的 JSON")


def _text(value: Any, default: str = "暂无") -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _confidence(value: Any, default: float = 0.5) -> float:
    """把任意输入钳制为 [0, 1] 内的小数；非法输入回退默认值。"""
    try:
        return round(min(1.0, max(0.0, float(value))), 3)
    except (TypeError, ValueError):
        return default


def _category(value: Any) -> str:
    """把建议分类归一化为非空字符串；非法输入回退「通用」。"""
    return str(value).strip() if isinstance(value, (str, int, float)) else "通用"


def _syndrome(value: Any) -> Syndrome:
    if isinstance(value, dict):
        name = value.get("name")
        name = str(name).strip() if isinstance(name, str) and name.strip() else "平和质倾向"
        return Syndrome(name=name, confidence=_confidence(value.get("confidence")))
    if isinstance(value, str) and value.strip():
        return Syndrome(name=value.strip(), confidence=0.5)
    return Syndrome()


def _syndrome_list(value: Any) -> list[Syndrome]:
    if not isinstance(value, list):
        return []
    return [_syndrome(item) for item in value]


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _advice_list(value: Any) -> list[Advice]:
    """只保留同时具备非空 text 的条目（category 缺省补「通用」）。"""
    if not isinstance(value, list):
        return []
    out: list[Advice] = []
    for item in value:
        if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip():
            out.append(Advice(category=_category(item.get("category")), text=item["text"].strip()))
    return out


def _conclusion_list(value: Any) -> list[Conclusion]:
    if not isinstance(value, list):
        return []
    out: list[Conclusion] = []
    for item in value:
        if isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip():
            out.append(Conclusion(text=item["text"].strip(), confidence=_confidence(item.get("confidence"))))
    return out


def normalize_output(module: str, data: dict[str, Any], *, model_version: str) -> dict[str, Any]:
    """把模型原始 JSON 归一化为后端契约字段；已钳制置信度、补齐缺省字段。"""
    if module == "fusion":
        fusion = FusionOutput(
            conclusions=_conclusion_list(data.get("conclusions")),
            syndrome_points=_str_list(data.get("syndrome_points")),
            suggestions=_advice_list(data.get("suggestions")),
            model_version=model_version,
        )
        return fusion.model_dump()

    summary_key = _SUMMARY_KEY[module]
    output = ModuleOutput(
        **{summary_key: _text(data.get(summary_key))},
        main_syndrome=_syndrome(data.get("main_syndrome")),
        secondary_syndromes=_syndrome_list(data.get("secondary_syndromes")),
        treatment_principles=_str_list(data.get("treatment_principles")),
        recommendations=_advice_list(data.get("recommendations")),
        model_version=model_version,
    )
    # exclude_none：仅保留本模块对应的 summary 字段
    return output.model_dump(exclude_none=True)


# ---- 视觉特征提取归一化（/vision/classify）----

#: 各模块合法特征名（与后端 `schemas/tongue.py` / `schemas/face.py` 默认特征一致）
_VISION_FEATURES = {
    "tongue": ("tongue_color", "coating_color", "coating_texture", "tongue_shape"),
    "face": ("face_color", "luster", "acne", "spots"),
}
#: 可携带分布区域 `area` 的特征（仅面诊痘痘 / 斑点）
_VISION_AREA_FEATURES = {"acne", "spots"}
#: 面部五区（PRD §9.3.2）
_VISION_AREAS = ("forehead", "left_cheek", "right_cheek", "nose", "chin")


def normalize_features(
    module: str, data: dict[str, Any], feature_names: list[str] | None = None
) -> list[dict[str, Any]]:
    """把视觉模型原始 JSON 归一化为特征列表 `[{name, label, confidence, area?}]`。

    - 过滤非法特征名 / 重复项，置信度钳制到 [0, 1]；
    - `area` 仅痘痘 / 斑点保留且只收面部五区取值；
    - 任一被请求的特征缺失时抛 `ValueError`（上层映射 503 交后端降级）。
    """
    allowed = _VISION_FEATURES[module]
    required = [name for name in (feature_names or allowed) if name in allowed]
    if not required:
        required = list(allowed)

    raw = data.get("features")
    if not isinstance(raw, list):
        raise ValueError("视觉模型返回缺少 features 列表")

    by_name: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if name not in allowed or name in by_name:
            continue
        label = str(item.get("label") or "").strip()
        if not label:
            continue
        feature: dict[str, Any] = {
            "name": name,
            "label": label,
            "confidence": _confidence(item.get("confidence")),
        }
        if name in _VISION_AREA_FEATURES:
            areas = [
                area
                for area in (item.get("area") or [])
                if isinstance(area, str) and area in _VISION_AREAS
            ]
            if areas:
                feature["area"] = areas
        by_name[name] = feature

    missing = [name for name in required if name not in by_name]
    if missing:
        raise ValueError(f"视觉模型返回缺少特征：{'、'.join(missing)}")
    return [by_name[name] for name in required]


__all__ = ["parse_json_safely", "normalize_output", "normalize_features"]
