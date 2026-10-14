"""问诊分析降级方案（M4-5）。

算法/LLM 服务不可用时的兜底：基于结构化答案的**确定性规则**生成可读结论，
保证「提交 → 分析」链路不中断（PRD §6.3.5 异常：记录仍视为提交成功、分析可重试）。

结论由寒热/汗出/睡眠/饮食/二便/胸腹等维度组合推导，缺失 P1/P2 项按比例折减置信度。
"""

from __future__ import annotations

from typing import Any

MODEL_VERSION = "inquiry_mock_v1"

#: 每缺一项可选题对置信度的折减；封顶避免置信度被过度压低。
_MISSING_PENALTY = 0.05
_MAX_MISSING_PENALTY = 0.25
#: 置信度下限，保证结果仍具参考价值。
_MIN_CONFIDENCE = 0.3


def analyze(
    answers: dict[str, Any],
    *,
    missing_items: list[str] | None = None,
    language: str = "zh-CN",
) -> dict:
    """由问诊答案生成证候判读（总结 / 主次证 / 治则 / 建议）。`language` 预留多语。"""
    missing = list(missing_items or [])
    values = _normalize(answers)
    main, secondary = _syndromes(values)

    penalty = min(_MAX_MISSING_PENALTY, _MISSING_PENALTY * len(missing))
    main = {"name": main["name"], "confidence": _adjust(main["confidence"], penalty)}
    secondary = [
        {"name": item["name"], "confidence": _adjust(item["confidence"], penalty)}
        for item in secondary
    ]

    return {
        "symptoms_summary": _summary(values),
        "main_syndrome": main,
        "secondary_syndromes": secondary,
        "treatment_principles": _principles(main["name"]),
        "recommendations": _recommendations(main["name"]),
        "model_version": MODEL_VERSION,
    }


def _adjust(confidence: float, penalty: float) -> float:
    return round(max(_MIN_CONFIDENCE, confidence * (1 - penalty)), 2)


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    if isinstance(value, str):
        return [value] if value else []
    return [str(value)]


def _as_str(value: Any) -> str:
    if value is None or isinstance(value, bool):
        return ""
    return str(value).strip()


def _normalize(answers: dict[str, Any]) -> dict[str, Any]:
    """把答案归一为按 qid 取值、multi 为列表的字典，缺失键给空值。"""
    return {
        "chief_complaint": _as_str(answers.get("chief_complaint")),
        "cold_heat": _as_list(answers.get("cold_heat")),
        "sweating": _as_list(answers.get("sweating")),
        "sleep": _as_list(answers.get("sleep")),
        "taste": _as_list(answers.get("taste")),
        "chest_abdomen": _as_list(answers.get("chest_abdomen")),
        "appetite": _as_str(answers.get("appetite")),
        "thirst": _as_str(answers.get("thirst")),
        "stool": _as_str(answers.get("stool")),
        "urine": _as_str(answers.get("urine")),
    }


def _summary(values: dict[str, Any]) -> str:
    parts: list[str] = []
    if values["chief_complaint"]:
        parts.append(f"主诉：{values['chief_complaint']}。")

    symptoms: list[str] = []
    for qid, positive_only in (
        ("cold_heat", "无明显寒热"),
        ("sweating", "正常"),
        ("sleep", "正常"),
        ("taste", "正常"),
        ("chest_abdomen", "无明显不适"),
    ):
        picked = [item for item in values[qid] if item != positive_only]
        if picked:
            symptoms.append("、".join(picked))
    if values["appetite"] and values["appetite"] != "正常":
        symptoms.append(values["appetite"])
    if values["thirst"] and values["thirst"] != "不渴":
        symptoms.append(values["thirst"])
    if values["stool"] and values["stool"] != "正常":
        symptoms.append(f"大便{values['stool']}")
    if values["urine"] and values["urine"] != "正常":
        symptoms.append(f"小便{values['urine']}")

    if symptoms:
        parts.append("伴随" + "；".join(symptoms) + "。")
    if not parts:
        parts.append("本次问诊未见明显异常主诉。")
    return "".join(parts)


def _syndromes(values: dict[str, Any]) -> tuple[dict, list[dict]]:
    cold = set(values["cold_heat"])
    sweat = set(values["sweating"])
    sleep = set(values["sleep"])
    taste = set(values["taste"])
    chest = set(values["chest_abdomen"])
    appetite = values["appetite"]
    thirst = values["thirst"]
    stool = values["stool"]
    urine = values["urine"]

    candidates: list[dict] = []
    if cold & {"怕冷畏寒", "手足不温"}:
        candidates.append({"name": "阳虚证", "confidence": 0.82})
    if "手足心热" in cold or thirst == "口渴喜冷饮" or "盗汗" in sweat:
        candidates.append({"name": "阴虚火旺证", "confidence": 0.76})
    if "自汗" in sweat or stool == "便溏" or appetite == "食欲不振":
        candidates.append({"name": "气虚证", "confidence": 0.78})
    if sleep & {"多梦", "易醒", "入睡困难"} and appetite == "食欲不振":
        candidates.append({"name": "心脾两虚证", "confidence": 0.7})
    if chest & {"胸闷", "胁痛"} or "口苦" in taste:
        candidates.append({"name": "肝郁气滞证", "confidence": 0.72})
    if urine == "黄赤" or ("口苦" in taste and thirst == "口渴喜冷饮"):
        candidates.append({"name": "湿热内蕴证", "confidence": 0.66})
    if stool == "便溏" or appetite == "食欲不振":
        candidates.append({"name": "脾胃虚弱证", "confidence": 0.74})
    if chest & {"心悸", "腹痛"}:
        candidates.append({"name": "气滞血瘀证", "confidence": 0.62})

    candidates = _dedupe(candidates)
    candidates = _resolve_conflicts(candidates)

    if not candidates:
        return {"name": "平和质倾向", "confidence": 0.6}, []

    candidates.sort(key=lambda item: item["confidence"], reverse=True)
    return candidates[0], candidates[1:3]


def _dedupe(candidates: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for item in candidates:
        seen.setdefault(item["name"], item)
    return list(seen.values())


def _resolve_conflicts(candidates: list[dict]) -> list[dict]:
    """寒热方向互斥：阳虚与阴虚并存时仅保留置信度更高者。"""
    names = {item["name"] for item in candidates}
    if {"阳虚证", "阴虚火旺证"} <= names:
        return [item for item in candidates if item["name"] != "阴虚火旺证"]
    return candidates


def _principles(main_name: str) -> list[str]:
    return {
        "阳虚证": ["温阳散寒", "益气健脾"],
        "阴虚火旺证": ["滋阴降火", "清心除烦"],
        "气虚证": ["益气健脾", "补中益气"],
        "心脾两虚证": ["健脾养心", "益气补血"],
        "肝郁气滞证": ["疏肝理气", "解郁安神"],
        "湿热内蕴证": ["清热利湿", "调理脾胃"],
        "脾胃虚弱证": ["健脾益气", "和胃消食"],
        "气滞血瘀证": ["行气活血", "通络止痛"],
        "平和质倾向": ["调和气血", "平衡阴阳"],
    }.get(main_name, ["辨证论治", "调理脏腑"])


def _recommendations(main_name: str) -> list[dict]:
    return [
        {"category": "饮食", "text": _diet_advice(main_name)},
        {"category": "作息", "text": "规律作息，避免熬夜，劳逸结合。"},
        {"category": "情志", "text": "保持情绪平稳，避免思虑过度与情志刺激。"},
        {"category": "复诊", "text": "建议 2 周后复诊，评估症状变化并调整调理方案。"},
    ]


def _diet_advice(main_name: str) -> str:
    return {
        "阳虚证": "宜温补，适量食用生姜、羊肉、山药，忌生冷寒凉。",
        "阴虚火旺证": "宜滋阴润燥，可食银耳、百合、梨，少食辛辣煎炸。",
        "气虚证": "宜益气健脾，可食小米、山药、红枣，少食生冷。",
        "心脾两虚证": "宜健脾养心安神，可食桂圆、莲子、小米，晚餐不宜过饱。",
        "肝郁气滞证": "宜疏肝解郁，可饮玫瑰花茶、少量陈皮，忌暴饮暴食与饮酒。",
        "湿热内蕴证": "宜清热利湿，少食甜腻辛辣，多食冬瓜、绿豆、薏米。",
        "脾胃虚弱证": "宜健脾养胃，可食南瓜、山药、小米粥，少食油腻生冷。",
        "气滞血瘀证": "宜行气活血，可适量食用山楂、黑木耳，忌久坐少动。",
        "平和质倾向": "饮食均衡有节，五味不偏，保持规律进餐。",
    }.get(main_name, "饮食清淡有节，定时定量，避免过饥过饱。")