"""舌象分析降级方案（M2-5）。

算法/LLM 服务不可用时的兜底：基于特征字典的**确定性规则**生成可读结论，
保证采集与分析链路不中断（PRD §6.1.4 异常：结果仍保留、可重试）。

权重来源对齐《开发任务文档》§3.4 `feature_dictionaries.weight`（此处常量占位，
字典表落地后改为查表 + 版本化 `rule_version`）。
"""

from __future__ import annotations

#: 舌诊整体置信度权重（PRD §7.2 加权均值）
FEATURE_WEIGHTS: dict[str, float] = {
    "tongue_color": 0.35,
    "coating_color": 0.25,
    "coating_texture": 0.20,
    "tongue_shape": 0.20,
}

MODEL_VERSION = "tongue_mock_v1"


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
    """由特征生成舌象解读（总结 / 主次证 / 治则 / 建议）。`language` 预留多语。"""
    labels = {feature.get("name"): feature.get("label") for feature in features}
    tongue_color = labels.get("tongue_color", "淡红")
    coating_color = labels.get("coating_color", "白")
    coating_texture = labels.get("coating_texture", "薄")
    tongue_shape = labels.get("tongue_shape", "正常")

    summary = (
        f"舌质{tongue_color}，舌苔{coating_color}{coating_texture}，舌体{tongue_shape}。"
        f"{_interpretation(tongue_color, coating_color, coating_texture, tongue_shape)}"
    )

    main, secondary = _syndromes(tongue_color, coating_color, coating_texture, tongue_shape)
    principles = _principles(main["name"])
    recommendations = [
        {"category": "饮食", "text": _diet_advice(main["name"])},
        {"category": "作息", "text": "规律作息、避免熬夜，适度进行有氧运动以助气血运行。"},
        {"category": "复诊", "text": "建议 2 周后复诊对比舌象变化，评估调理效果。"},
    ]

    return {
        "tongue_summary": summary,
        "main_syndrome": main,
        "secondary_syndromes": secondary,
        "treatment_principles": principles,
        "recommendations": recommendations,
        "model_version": MODEL_VERSION,
    }


def _interpretation(
    tongue_color: str, coating_color: str, coating_texture: str, tongue_shape: str
) -> str:
    parts: list[str] = []
    if tongue_color in {"淡白", "淡红"}:
        parts.append("舌色偏淡，提示气血或阳气不足")
    if tongue_color in {"红", "绛红"}:
        parts.append("舌色偏红，提示热象或阴虚")
    if tongue_color == "青紫":
        parts.append("舌色青紫，提示血行不畅")
    if coating_color == "黄":
        parts.append("苔色偏黄，提示内有湿热")
    if coating_texture in {"腻", "厚"}:
        parts.append("苔质偏腻厚，提示湿浊内蕴")
    if tongue_shape in {"齿痕", "胖大"}:
        parts.append("舌体胖大伴齿痕，提示脾虚湿盛")
    if not parts:
        parts.append("舌象大致平和，暂未见明显偏颇")
    return "，".join(parts) + "。"


def _syndromes(
    tongue_color: str, coating_color: str, coating_texture: str, tongue_shape: str
) -> tuple[dict, list[dict]]:
    candidates: list[dict] = []
    if tongue_color == "青紫":
        candidates.append({"name": "血瘀证", "confidence": 0.78})
    if tongue_color in {"红", "绛红"} and coating_color == "黄":
        candidates.append({"name": "湿热证", "confidence": 0.82})
    if coating_texture in {"腻", "厚"}:
        candidates.append({"name": "湿盛困脾证", "confidence": 0.72})
    if tongue_shape in {"齿痕", "胖大"} or tongue_color in {"淡白", "淡红"}:
        candidates.append({"name": "脾气虚证", "confidence": 0.84})

    if not candidates:
        candidates.append({"name": "平和质倾向", "confidence": 0.60})

    candidates.sort(key=lambda item: item["confidence"], reverse=True)
    return candidates[0], candidates[1:]


def _principles(main_name: str) -> list[str]:
    return {
        "脾气虚证": ["健脾益气", "化湿"],
        "湿盛困脾证": ["健脾祛湿", "理气化浊"],
        "湿热证": ["清热利湿", "调理脾胃"],
        "血瘀证": ["活血化瘀", "行气通络"],
        "平和质倾向": ["调和气血", "平衡阴阳"],
    }.get(main_name, ["辨证论治", "调理脏腑"])


def _diet_advice(main_name: str) -> str:
    return {
        "脾气虚证": "宜健脾祛湿，可食山药、薏苡仁、扁豆，少食生冷油腻。",
        "湿盛困脾证": "宜清淡易消化，少食甜腻，适量饮用薏米赤小豆汤。",
        "湿热证": "宜清热利湿，少食辛辣煎炸，多食冬瓜、绿豆等。",
        "血瘀证": "宜行气活血，可适量食用山楂、黑木耳，忌久坐少动。",
        "平和质倾向": "饮食均衡有节，五味不偏，保持规律进餐。",
    }.get(main_name, "饮食清淡有节，定时定量，避免过饥过饱。")