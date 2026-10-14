"""面象分析降级方案（M3-5）。

算法/LLM 服务不可用时的兜底：基于特征字典的**确定性规则**生成可读结论，
保证采集与分析链路不中断（PRD §6.2.4 异常：结果仍保留、可重试）。

权重来源对齐《开发任务文档》§3.4 `feature_dictionaries.weight`（此处常量占位，
字典表落地后改为查表 + 版本化 `rule_version`）。
"""

from __future__ import annotations

#: 面诊整体置信度权重（PRD §7.2 加权均值）
FEATURE_WEIGHTS: dict[str, float] = {
    "face_color": 0.35,
    "luster": 0.25,
    "acne": 0.20,
    "spots": 0.20,
}

MODEL_VERSION = "face_mock_v1"


def weighted_confidence(features: list[dict]) -> float:
    """各特征置信度按权重求加权均值；无权重命中时退化为算术均值。"""
    total_weight = 0.0
    acc = 0.0
    for feature in features:
        weight = FEATURE_WEIGHTS.get(feature.get("name", ""))
        if weight is None:
            continue
        acc += float(feature.get("confidence", 0.0)) * weight
        total_weight += weight
    if total_weight == 0:
        if not features:
            return 0.0
        return round(sum(float(f.get("confidence", 0.0)) for f in features) / len(features), 3)
    return round(acc / total_weight, 3)


def analyze(features: list[dict], *, language: str = "zh-CN") -> dict:
    """由特征生成面象解读（总结 / 主次证 / 治则 / 建议）。`language` 预留多语。"""
    labels = {feature.get("name"): feature.get("label") for feature in features}
    face_color = labels.get("face_color", "红润")
    luster = labels.get("luster", "有光泽")
    acne = labels.get("acne", "无")
    spots = labels.get("spots", "无")

    summary = (
        f"面色{face_color}，皮肤{luster}，痘痘{acne}，斑点{spots}。"
        f"{_interpretation(face_color, luster, acne, spots)}"
    )

    main, secondary = _syndromes(face_color, luster, acne, spots)
    principles = _principles(main["name"])
    recommendations = [
        {"category": "饮食", "text": _diet_advice(main["name"])},
        {"category": "作息", "text": "保证睡眠、规律作息，注意面部清洁与防晒。"},
        {"category": "复诊", "text": "建议 2 周后复诊对比面象变化，评估调理效果。"},
    ]

    return {
        "face_summary": summary,
        "main_syndrome": main,
        "secondary_syndromes": secondary,
        "treatment_principles": principles,
        "recommendations": recommendations,
        "model_version": MODEL_VERSION,
    }


def _interpretation(face_color: str, luster: str, acne: str, spots: str) -> str:
    parts: list[str] = []
    if face_color == "红润":
        parts.append("面色红润，提示气血尚充")
    if face_color == "苍白":
        parts.append("面色苍白，提示气血不足或阳气偏虚")
    if face_color == "萎黄":
        parts.append("面色萎黄，提示脾胃虚弱、气血生化不足")
    if face_color == "潮红":
        parts.append("面色潮红，提示热象或阴虚火旺")
    if face_color == "晦暗":
        parts.append("面色晦暗，提示气滞血瘀")
    if face_color == "青紫":
        parts.append("面色青紫，提示血行不畅或寒凝")
    if luster == "油光":
        parts.append("皮肤油光，多与湿热内蕴相关")
    if luster == "少光泽":
        parts.append("皮肤少光泽，提示气血濡养不足")
    if acne in {"中等", "较多"}:
        parts.append("痤疮偏多，多提示肺胃热盛")
    if spots in {"中等", "较多"}:
        parts.append("斑点较多，多提示肝郁或血瘀")
    if not parts:
        parts.append("面象大致平和，暂未见明显偏颇")
    return "，".join(parts) + "。"


def _syndromes(
    face_color: str, luster: str, acne: str, spots: str
) -> tuple[dict, list[dict]]:
    candidates: list[dict] = []
    if face_color == "红润":
        candidates.append({"name": "气血充足", "confidence": 0.78})
    if face_color == "苍白":
        candidates.append({"name": "气血两虚证", "confidence": 0.76})
    if face_color == "萎黄":
        candidates.append({"name": "脾胃虚弱证", "confidence": 0.78})
    if face_color == "潮红":
        candidates.append({"name": "阴虚火旺证", "confidence": 0.74})
    if face_color in {"晦暗", "青紫"}:
        candidates.append({"name": "气滞血瘀证", "confidence": 0.76})
    if acne in {"中等", "较多"}:
        candidates.append({"name": "肺胃热盛（轻）", "confidence": 0.62})
    if spots in {"中等", "较多"}:
        candidates.append({"name": "肝郁气滞证", "confidence": 0.60})
    if luster == "油光":
        candidates.append({"name": "湿热内蕴证", "confidence": 0.58})

    if not candidates:
        candidates.append({"name": "平和质倾向", "confidence": 0.60})

    candidates.sort(key=lambda item: item["confidence"], reverse=True)
    return candidates[0], candidates[1:]


def _principles(main_name: str) -> list[str]:
    return {
        "气血充足": ["调和气血", "清淡饮食"],
        "气血两虚证": ["益气养血", "健脾和胃"],
        "脾胃虚弱证": ["健脾益气", "养血"],
        "阴虚火旺证": ["滋阴降火", "清心除烦"],
        "气滞血瘀证": ["行气活血", "疏肝解郁"],
        "肺胃热盛（轻）": ["清肺胃热", "调理饮食"],
        "肝郁气滞证": ["疏肝理气", "活血化瘀"],
        "湿热内蕴证": ["清热利湿", "调理脾胃"],
        "平和质倾向": ["调和气血", "平衡阴阳"],
    }.get(main_name, ["辨证论治", "调理脏腑"])


def _diet_advice(main_name: str) -> str:
    return {
        "气血充足": "饮食均衡有节，五味不偏，保持规律进餐。",
        "气血两虚证": "宜益气养血，可食红枣、桂圆、瘦肉，少食生冷。",
        "脾胃虚弱证": "宜健脾养胃，可食山药、小米、南瓜，少食生冷油腻。",
        "阴虚火旺证": "宜滋阴降火，可食百合、银耳、梨，少食辛辣煎炸。",
        "气滞血瘀证": "宜行气活血，可适量食用山楂、黑木耳，忌久坐少动。",
        "肺胃热盛（轻）": "宜清淡饮食，少食辛辣、高糖及油炸食品。",
        "肝郁气滞证": "宜疏肝解郁，可饮玫瑰花茶，保持情绪舒畅。",
        "湿热内蕴证": "宜清热利湿，少食甜腻辛辣，多食冬瓜、绿豆。",
        "平和质倾向": "饮食均衡有节，五味不偏，保持规律进餐。",
    }.get(main_name, "饮食清淡有节，定时定量，避免过饥过饱。")