"""三诊合参降级方案（M5-5）。

算法/大模型服务不可用时的兜底：基于归一的合参输入快照与规则引擎的**确定性规则**
生成可读结论、辨证要点与调理建议，保证「触发 → 合参」链路不中断
（PRD §6.4：规则负责一致性校验与加权，大模型负责可读结论生成）。

产物：`conclusions[]` / `syndrome_points[]` / `suggestions[]` / `model_version`。
"""

from __future__ import annotations

from typing import Any

MODEL_VERSION = "fusion_mock_v1"

#: 证候 → 饮食建议
_DIET = {
    "阳虚证": "宜温补，适量食用生姜、羊肉、山药，忌生冷寒凉。",
    "气虚证": "宜益气健脾，可食小米、山药、红枣，少食生冷。",
    "阴虚火旺证": "宜滋阴润燥，可食银耳、百合、梨，少食辛辣煎炸。",
    "脾胃虚弱证": "宜健脾养胃，可食南瓜、山药、小米粥，少食油腻生冷。",
    "脾气虚证": "宜健脾祛湿，可食山药、薏苡仁、扁豆，少食生冷油腻。",
    "湿盛困脾证": "宜清淡易消化，少食甜腻，适量饮用薏米赤小豆汤。",
    "湿热证": "宜清热利湿，少食辛辣煎炸，多食冬瓜、绿豆。",
    "湿热内蕴证": "宜清热利湿，少食甜腻辛辣，多食冬瓜、绿豆、薏米。",
    "血瘀证": "宜行气活血，可适量食用山楂、黑木耳，忌久坐少动。",
    "气滞血瘀证": "宜行气活血，可适量食用山楂、黑木耳，忌久坐少动。",
    "肝郁气滞证": "宜疏肝解郁，可饮玫瑰花茶、少量陈皮，忌暴饮暴食与饮酒。",
    "心脾两虚证": "宜健脾养心安神，可食桂圆、莲子、小米，晚餐不宜过饱。",
    "气血两虚证": "宜益气养血，可食红枣、桂圆、瘦肉，少食生冷。",
    "肺胃热盛（轻）": "宜清淡饮食，少食辛辣、高糖及油炸食品。",
    "平和质倾向": "饮食均衡有节，五味不偏，保持规律进餐。",
    "气血充足": "饮食均衡有节，五味不偏，保持规律进餐。",
}

#: 模块中文名（用于辨证要点/依据摘要）
_MODULE_LABELS = {"tongue": "舌诊", "face": "面诊", "inquiry": "问诊"}


def analyze(
    snapshot: dict[str, Any],
    *,
    conflicts: list[dict] | None = None,
    missing_modules: list[str] | None = None,
    overall_confidence: float = 0.0,
    language: str = "zh-CN",
) -> dict:
    """由合参输入快照生成结论 / 辨证要点 / 建议。`language` 预留多语。"""
    conflicts = list(conflicts or [])
    missing = list(missing_modules or [])

    points = _syndrome_points(snapshot, missing)
    main_name, secondary = _dominant_syndrome(snapshot)
    conclusions = _conclusions(main_name, secondary, conflicts, missing, overall_confidence)
    suggestions = _suggestions(main_name)

    return {
        "conclusions": conclusions,
        "syndrome_points": points,
        "suggestions": suggestions,
        "model_version": MODEL_VERSION,
    }


def _feature_labels(module: dict | None) -> dict[str, str]:
    if not module:
        return {}
    return {
        str(feature.get("name")): str(feature.get("label"))
        for feature in module.get("features", [])
        if feature.get("name")
    }


def _syndrome_points(snapshot: dict, missing: list[str]) -> list[str]:
    """三诊依据摘要（每条对应一诊）。"""
    points: list[str] = []
    tongue = snapshot.get("tongue")
    if tongue:
        labels = _feature_labels(tongue)
        color = labels.get("tongue_color", "淡红")
        coating = labels.get("coating_color", "白")
        texture = labels.get("coating_texture", "薄")
        points.append(f"舌质{color}、舌苔{coating}{texture}")
    face = snapshot.get("face")
    if face:
        labels = _feature_labels(face)
        color = labels.get("face_color", "红润")
        luster = labels.get("luster", "有光泽")
        points.append(f"面色{color}、皮肤{luster}")
    inquiry = snapshot.get("inquiry")
    if inquiry:
        answers = inquiry.get("answers", {}) or {}
        chief = str(answers.get("chief_complaint") or "").strip()
        cold_heat = answers.get("cold_heat")
        extras: list[str] = []
        if isinstance(cold_heat, list):
            extras.extend(str(item) for item in cold_heat if item and item != "无明显寒热")
        detail = "、".join(extras)
        if chief and detail:
            points.append(f"主诉{chief}，兼见{detail}")
        elif chief:
            points.append(f"主诉{chief}")
        elif detail:
            points.append(f"问诊见{detail}")
    if missing:
        points.append("缺少" + "、".join(_MODULE_LABELS.get(key, key) for key in missing))
    return points


def _collect_syndromes(snapshot: dict) -> list[dict]:
    """汇总三诊主/次证（按置信度降序，去重）。"""
    collected: dict[str, float] = {}
    for module in snapshot.values():
        if not isinstance(module, dict):
            continue
        main = module.get("main_syndrome")
        if isinstance(main, dict) and main.get("name"):
            collected.setdefault(str(main["name"]), float(main.get("confidence", 0.0)))
        for item in module.get("secondary_syndromes") or []:
            if isinstance(item, dict) and item.get("name"):
                collected.setdefault(str(item["name"]), float(item.get("confidence", 0.0)))
    ranked = [{"name": name, "confidence": conf} for name, conf in collected.items()]
    ranked.sort(key=lambda item: item["confidence"], reverse=True)
    return ranked


def _dominant_syndrome(snapshot: dict) -> tuple[str, list[dict]]:
    ranked = _collect_syndromes(snapshot)
    if not ranked:
        return "平和质倾向", []
    return ranked[0]["name"], ranked[1:3]


def _conclusions(
    main_name: str,
    secondary: list[dict],
    conflicts: list[dict],
    missing: list[str],
    overall_confidence: float,
) -> list[dict]:
    confidence = round(max(0.3, overall_confidence)) if overall_confidence else 0.6
    modules_text = "舌、面、问诊" if not missing else "、".join(
        _MODULE_LABELS.get(key, key) for key in ("tongue", "face", "inquiry") if key not in missing
    )
    extra = ""
    if secondary:
        extra = f"，兼见{secondary[0]['name']}"
    conclusions = [
        {
            "text": f"综合{modules_text}信息，提示以{main_name}为主{extra}，建议结合临床辨证调理。",
            "confidence": min(0.95, confidence),
        }
    ]
    if conflicts:
        conclusions.append(
            {
                "text": "三诊数据存在寒热指向不一致项，相关结论权重已下调，建议结合临床进一步确认。",
                "confidence": round(max(0.3, confidence - 0.1), 3),
            }
        )
    if missing:
        conclusions.append(
            {
                "text": "本次未含"
                + "、".join(_MODULE_LABELS.get(key, key) for key in missing)
                + "数据，整体参考强度有限，建议补齐后复评。",
                "confidence": round(max(0.3, confidence - 0.05), 3),
            }
        )
    return conclusions


def _suggestions(main_name: str) -> list[dict]:
    return [
        {"category": "饮食", "text": _DIET.get(main_name, "饮食清淡有节，定时定量，避免过饥过饱。")},
        {"category": "作息", "text": "规律作息、避免熬夜，适度进行有氧运动以助气血运行。"},
        {"category": "情志", "text": "保持情绪平稳，避免思虑过度与情志刺激。"},
        {"category": "复诊", "text": "建议 2 周后复诊，对比舌象与症状变化，评估调理效果。"},
    ]