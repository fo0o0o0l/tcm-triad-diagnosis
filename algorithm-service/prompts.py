"""四个模块的 prompt 构造（舌诊 / 面诊 / 问诊 / 合参）。

统一约定：只输出一个 JSON 对象、confidence 为 0~1、结论仅供参考非诊断依据；
文末含 "JSON" 关键词以满足 DashScope `response_format=json_object` 的前置要求。
"""

from __future__ import annotations

from typing import Any

#: 特征字段名 → 中文，便于模型理解输入
_FEATURE_CN = {
    "tongue_color": "舌色",
    "coating_color": "苔色",
    "coating_texture": "苔质",
    "tongue_shape": "舌形",
    "face_color": "面色",
    "luster": "光泽",
    "acne": "痘痘",
    "spots": "斑点",
}

_SYSTEM_BASE = (
    "你是一名资深中医辨证助手，精通舌诊、面诊、问诊与八纲辨证，善于给出结构化的辨证结论。\n"
    "必须严格遵守以下规则：\n"
    "1. 只输出一个 JSON 对象，不要输出任何解释文字、Markdown 或代码块。\n"
    "2. 所有 confidence 字段为 0~1 之间的小数。\n"
    "3. 结论仅用于健康调理参考，不作为临床诊断依据。\n"
)


def _language_clause(language: str) -> str:
    if language and not language.lower().startswith("zh"):
        return f"4. 请使用 {language} 语言撰写结论文本。\n"
    return ""


def _render_features(features: Any) -> str:
    lines: list[str] = []
    for feature in features or []:
        if not isinstance(feature, dict):
            continue
        key = str(feature.get("name") or "?")
        value = feature.get("label") or "未知"
        cn = _FEATURE_CN.get(key, key)
        lines.append(f"- {cn}({key})：{value}（置信度 {feature.get('confidence')}）")
    return "\n".join(lines) or "（未提供特征）"


def build_prompt(module: str, payload: dict[str, Any], language: str = "zh-CN") -> tuple[str, str]:
    """返回 `(system, user)` 两条消息内容。"""
    system = _SYSTEM_BASE + _language_clause(language)
    if module == "tongue":
        return system, _tongue_user(payload)
    if module == "face":
        return system, _face_user(payload)
    if module == "inquiry":
        return system, _inquiry_user(payload)
    return system, _fusion_user(payload)


def _tongue_user(payload: dict[str, Any]) -> str:
    return (
        "【输入】舌象特征：\n"
        f"{_render_features(payload.get('features'))}\n\n"
        "请依据以上舌象特征进行辨证，仅输出如下结构的 JSON（字段一个都不能少）：\n"
        "{\n"
        '  "tongue_summary": "舌象整体描述（1~3 句）",\n'
        '  "main_syndrome": {"name": "主证名", "confidence": 0.0},\n'
        '  "secondary_syndromes": [{"name": "次证名", "confidence": 0.0}],\n'
        '  "treatment_principles": ["治则1", "治则2"],\n'
        '  "recommendations": [{"category": "饮食|作息|情志|复诊", "text": "建议内容"}]\n'
        "}"
    )


def _face_user(payload: dict[str, Any]) -> str:
    return (
        "【输入】面象特征：\n"
        f"{_render_features(payload.get('features'))}\n\n"
        "请依据以上面象特征进行辨证，仅输出如下结构的 JSON（字段一个都不能少）：\n"
        "{\n"
        '  "face_summary": "面象整体描述（1~3 句）",\n'
        '  "main_syndrome": {"name": "主证名", "confidence": 0.0},\n'
        '  "secondary_syndromes": [{"name": "次证名", "confidence": 0.0}],\n'
        '  "treatment_principles": ["治则1", "治则2"],\n'
        '  "recommendations": [{"category": "饮食|作息|情志|复诊", "text": "建议内容"}]\n'
        "}"
    )


def _inquiry_user(payload: dict[str, Any]) -> str:
    answers = payload.get("answers") or {}
    missing = payload.get("missing_items") or []
    answer_lines = "\n".join(f"- {key}：{value}" for key, value in answers.items()) or "（未提供）"
    missing_text = "、".join(str(item) for item in missing) if missing else "无"
    return (
        "【输入】问诊回答：\n"
        f"{answer_lines}\n\n"
        f"缺失项：{missing_text}\n"
        "（存在缺失项时，相应结论的 confidence 应相应下调）\n\n"
        "请依据以上问诊信息进行辨证，仅输出如下结构的 JSON（字段一个都不能少）：\n"
        "{\n"
        '  "symptoms_summary": "症状整体描述（1~3 句）",\n'
        '  "main_syndrome": {"name": "主证名", "confidence": 0.0},\n'
        '  "secondary_syndromes": [{"name": "次证名", "confidence": 0.0}],\n'
        '  "treatment_principles": ["治则1", "治则2"],\n'
        '  "recommendations": [{"category": "饮食|作息|情志|复诊", "text": "建议内容"}]\n'
        "}"
    )


def _fusion_user(payload: dict[str, Any]) -> str:
    snapshot = payload.get("snapshot") or {}
    conflicts = payload.get("conflicts") or []
    missing = payload.get("missing_modules") or []
    confidence = payload.get("overall_confidence")

    sections: list[str] = []
    for key, label in (("tongue", "舌诊"), ("face", "面诊"), ("inquiry", "问诊")):
        module = snapshot.get(key)
        if not isinstance(module, dict):
            continue
        main = module.get("main_syndrome") or {}
        sections.append(
            f"- {label}：小结「{module.get('summary') or '暂无'}」，"
            f"主证「{main.get('name') or '未定'}」（置信度 {main.get('confidence')}）"
        )
    snapshot_text = "\n".join(sections) or "（三诊数据不足）"
    conflict_text = (
        "\n".join(f"- {item.get('description')}" for item in conflicts if isinstance(item, dict))
        or "无"
    )
    missing_text = "、".join(str(item) for item in missing) if missing else "无"

    return (
        "【输入】三诊合参信息：\n"
        f"{snapshot_text}\n\n"
        f"跨诊矛盾：\n{conflict_text}\n\n"
        f"缺失诊次：{missing_text}\n"
        f"整体置信度：{confidence}\n"
        "（存在矛盾时须在结论中显式说明相关权重已下调；存在缺失诊次时须说明参考强度有限）\n\n"
        "请综合三诊信息进行辨证，仅输出如下结构的 JSON（字段一个都不能少）：\n"
        "{\n"
        '  "conclusions": [{"text": "综合结论", "confidence": 0.0}],\n'
        '  "syndrome_points": ["辨证要点1", "辨证要点2"],\n'
        '  "suggestions": [{"category": "饮食|作息|情志|复诊", "text": "建议内容"}]\n'
        "}"
    )


# ---- 视觉特征提取（/vision/classify，舌象 / 面象图片 → 结构化特征）----
#
# label 取值严格约束在后端既有枚举集内（前端展示与 mock 降级分析依赖这些标签）；
# 文末含 "JSON" 关键词以满足 `response_format=json_object` 的前置要求。

_VISION_SYSTEM = (
    "你是一名资深中医望诊专家，精通舌诊与面诊，能够客观、细致地观察图像并输出结构化特征。\n"
    "必须严格遵守以下规则：\n"
    "1. 只输出一个 JSON 对象，不要输出任何解释文字、Markdown 或代码块。\n"
    "2. 每个特征的 label 只能从给定的候选值中选择一个，不得自创词汇。\n"
    "3. confidence 为 0~1 之间的小数，反映你对该特征判断的把握程度；"
    "图像模糊、光线不佳或被遮挡时相应下调。\n"
    "4. 仔细观察局部细节（如痘痘、斑点、齿痕、裂纹等小目标），不要只描述整体印象。\n"
)

_VISION_FACE_USER = (
    "请观察这张人脸照片，识别以下四类面象特征：\n"
    "- face_color（面色整体色调）：候选值 [红润, 苍白, 萎黄, 潮红, 晦暗, 青紫]\n"
    "- luster（皮肤光泽度）：候选值 [有光泽, 少光泽, 油光]\n"
    "- acne（痘痘 / 痤疮多少）：候选值 [无, 少量, 中等, 较多]；"
    "非「无」时必须给出 area（分布区域，可多选）："
    "[forehead(额头), left_cheek(左颊), right_cheek(右颊), nose(鼻部), chin(下颌)]\n"
    "- spots（色斑 / 色素沉着多少）：候选值 [无, 少量, 中等, 较多]；"
    "非「无」时同样给出 area\n\n"
    "仅输出如下结构的 JSON（字段一个都不能少，顺序不限）：\n"
    "{\n"
    '  "features": [\n'
    '    {"name": "face_color", "label": "候选值之一", "confidence": 0.0},\n'
    '    {"name": "luster", "label": "候选值之一", "confidence": 0.0},\n'
    '    {"name": "acne", "label": "候选值之一", "confidence": 0.0, "area": ["nose"]},\n'
    '    {"name": "spots", "label": "候选值之一", "confidence": 0.0, "area": ["left_cheek"]}\n'
    "  ]\n"
    "}\n"
    "acne / spots 为「无」时可省略 area 字段。"
)

_VISION_TONGUE_USER = (
    "请观察这张舌象照片，识别以下四类舌象特征：\n"
    "- tongue_color（舌体颜色）：候选值 [淡红, 淡白, 红, 绛红, 青紫]\n"
    "- coating_color（舌苔颜色）：候选值 [白, 黄, 灰黑]\n"
    "- coating_texture（苔质厚薄与质地）：候选值 [薄, 厚, 腻, 少苔]\n"
    "- tongue_shape（舌体形态）：候选值 [正常, 齿痕, 胖大, 裂纹]\n\n"
    "仅输出如下结构的 JSON（字段一个都不能少，顺序不限）：\n"
    "{\n"
    '  "features": [\n'
    '    {"name": "tongue_color", "label": "候选值之一", "confidence": 0.0},\n'
    '    {"name": "coating_color", "label": "候选值之一", "confidence": 0.0},\n'
    '    {"name": "coating_texture", "label": "候选值之一", "confidence": 0.0},\n'
    '    {"name": "tongue_shape", "label": "候选值之一", "confidence": 0.0}\n'
    "  ]\n"
    "}"
)


def build_vision_prompt(module: str) -> tuple[str, str]:
    """视觉特征提取的 `(system, user)`；仅支持 tongue / face。"""
    if module == "tongue":
        return _VISION_SYSTEM, _VISION_TONGUE_USER
    if module == "face":
        return _VISION_SYSTEM, _VISION_FACE_USER
    raise ValueError(f"视觉特征提取不支持模块：{module}")
