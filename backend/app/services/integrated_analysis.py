"""三诊合参数据融合（M5-2 / M5-3）。

职责：
- **三诊输入归一**：把舌诊/面诊的特征项与 AI 分析、问诊结构化答案统一为合参输入快照
  （可追溯，落 `fusion_results.inputs_snapshot`）；
- **一致性校验**：识别跨诊矛盾（寒热指向不一致等）写入 `conflicts`，并据此折减置信度；
- **前置校验**：三诊完成态判定，**三诊未全部完成即阻断合参**（PRD §6.4 / UI/UX §5.4.3）；
- **置信度与健康等级**：三诊整体置信度按可配置权重加权（缺失诊次权重按比例分摊），
  映射 UI/UX §3.1 报告健康等级色板。

本模块仅做确定性规则计算，不依赖算法服务，便于离线测试。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.diagnosis import (
    FaceAnalysis,
    FaceRecord,
    HealthLevel,
    InquiryAnalysis,
    InquiryRecord,
    TongueAnalysis,
    TongueRecord,
)

#: 三诊模块键与权重（PRD §7.2 合参权重，[TBD] 可配置 + 版本化）
MODULE_KEYS: tuple[str, ...] = ("tongue", "face", "inquiry")
MODULE_WEIGHTS: dict[str, float] = {"tongue": 0.35, "face": 0.30, "inquiry": 0.35}
RULE_VERSION = "fusion_rule_v1"

#: 诊位中文名（缺诊提示文案使用）
MODULE_LABELS: dict[str, str] = {"tongue": "舌诊采集", "face": "面诊采集", "inquiry": "问诊录入"}
#: 缺少诊次 / 存在跨诊矛盾 时的置信度折减（封顶避免过度压低）
_MISSING_PENALTY = 0.04
_CONFLICT_PENALTY = 0.03
_MAX_PENALTY = 0.15
_MIN_CONFIDENCE = 0.30
#: 单诊无整体置信度时的兜底值（有记录但未做特征识别）
_DEFAULT_MODULE_CONFIDENCE = 0.60

#: 寒热指向词表（用于跨诊一致性校验）
_HEAT_TONGUE = {"红", "绛红"}
_COLD_TONGUE = {"淡白"}
_HEAT_FACE = {"潮红"}
_COLD_FACE = {"苍白"}
_HEAT_INQUIRY = {"怕热喜凉", "手足心热"}
_COLD_INQUIRY = {"怕冷畏寒", "手足不温"}
_HEAT_SYNDROMES = {"湿热证", "湿热内蕴证", "阴虚火旺证", "肺胃热盛（轻）"}
_COLD_SYNDROMES = {"阳虚证", "气虚证", "气血两虚证", "脾胃虚弱证"}


@dataclass
class ModuleInput:
    """单诊归一输入（图像诊含 features；问诊含 answers）。"""

    key: str
    record_no: str
    overall_confidence: float | None = None
    features: list[dict] = field(default_factory=list)
    image_ref: str | None = None
    summary: str | None = None
    main_syndrome: dict | None = None
    secondary_syndromes: list[dict] = field(default_factory=list)
    treatment_principles: list[str] = field(default_factory=list)
    model_version: str | None = None
    # 问诊专有
    patient_snapshot: dict = field(default_factory=dict)
    answers: dict = field(default_factory=dict)
    missing_items: list[str] = field(default_factory=list)


@dataclass
class FusionInputs:
    """会话三诊输入集合（缺诊时对应字段为 None）。"""

    session_id: str
    modules: dict[str, ModuleInput] = field(default_factory=dict)

    @property
    def missing_modules(self) -> list[str]:
        return [key for key in MODULE_KEYS if key not in self.modules]


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _analysis_summary(analysis: Any, attr: str) -> str | None:
    return getattr(analysis, attr, None) if analysis is not None else None


async def _current_tongue(db: AsyncSession, session_id: str) -> ModuleInput | None:
    record = await db.scalar(
        select(TongueRecord).where(
            TongueRecord.session_id == session_id, TongueRecord.deleted_at.is_(None)
        )
    )
    if record is None:
        return None
    analysis = await db.scalar(
        select(TongueAnalysis).where(
            TongueAnalysis.record_id == record.id, TongueAnalysis.is_current.is_(True)
        )
    )
    return ModuleInput(
        key="tongue",
        record_no=record.record_no,
        overall_confidence=_as_float(record.overall_confidence),
        features=list(record.features or []),
        image_ref=record.image_ref,
        summary=_analysis_summary(analysis, "tongue_summary"),
        main_syndrome=(analysis.main_syndrome if analysis else None),
        secondary_syndromes=list((analysis.secondary_syndromes if analysis else None) or []),
        treatment_principles=list((analysis.treatment_principles if analysis else None) or []),
        model_version=(analysis.model_version if analysis else None),
    )


async def _current_face(db: AsyncSession, session_id: str) -> ModuleInput | None:
    record = await db.scalar(
        select(FaceRecord).where(
            FaceRecord.session_id == session_id, FaceRecord.deleted_at.is_(None)
        )
    )
    if record is None:
        return None
    analysis = await db.scalar(
        select(FaceAnalysis).where(
            FaceAnalysis.record_id == record.id, FaceAnalysis.is_current.is_(True)
        )
    )
    return ModuleInput(
        key="face",
        record_no=record.record_no,
        overall_confidence=_as_float(record.overall_confidence),
        features=list(record.features or []),
        image_ref=record.image_ref,
        summary=_analysis_summary(analysis, "face_summary"),
        main_syndrome=(analysis.main_syndrome if analysis else None),
        secondary_syndromes=list((analysis.secondary_syndromes if analysis else None) or []),
        treatment_principles=list((analysis.treatment_principles if analysis else None) or []),
        model_version=(analysis.model_version if analysis else None),
    )


async def _current_inquiry(db: AsyncSession, session_id: str) -> ModuleInput | None:
    record = await db.scalar(
        select(InquiryRecord).where(
            InquiryRecord.session_id == session_id, InquiryRecord.deleted_at.is_(None)
        )
    )
    if record is None:
        return None
    analysis = await db.scalar(
        select(InquiryAnalysis).where(
            InquiryAnalysis.record_id == record.id, InquiryAnalysis.is_current.is_(True)
        )
    )
    return ModuleInput(
        key="inquiry",
        record_no=record.record_no,
        summary=_analysis_summary(analysis, "symptoms_summary"),
        main_syndrome=(analysis.main_syndrome if analysis else None),
        secondary_syndromes=list((analysis.secondary_syndromes if analysis else None) or []),
        treatment_principles=list((analysis.treatment_principles if analysis else None) or []),
        model_version=(analysis.model_version if analysis else None),
        patient_snapshot=dict(record.patient_snapshot or {}),
        answers=dict(record.answers or {}),
        missing_items=list(record.missing_items or []),
    )


async def collect_inputs(db: AsyncSession, session_id: str) -> FusionInputs:
    """读取会话三诊记录并按模块归一（缺诊时不写入对应键）。"""
    inputs = FusionInputs(session_id=session_id)
    for collector in (_current_tongue, _current_face, _current_inquiry):
        module = await collector(db, session_id)
        if module is not None:
            inputs.modules[module.key] = module
    return inputs


def is_done(module: ModuleInput) -> bool:
    """单诊是否「已完成」：图像诊需特征识别完成，问诊需已提交（含作答）。"""
    if module.key == "inquiry":
        return bool(module.answers)
    return bool(module.features)


def module_states(inputs: FusionInputs) -> dict[str, dict]:
    """返回三诊就绪状态（供 G0 / P5 右侧卡片）。"""
    states: dict[str, dict] = {}
    for key in MODULE_KEYS:
        module = inputs.modules.get(key)
        states[key] = {
            "done": module is not None and is_done(module),
            "overall_confidence": module.overall_confidence if module else None,
            "summary": module.summary if module else None,
        }
    return states


def can_analyze(inputs: FusionInputs) -> tuple[bool, str | None]:
    """前置校验：三诊需全部完成方可合参（PRD §6.4 / UI/UX §5.4.3）。

    缺诊降级能力仍保留在报告标注与置信度折减中，但本期不允许缺诊进入合参：
    只要存在未完成的诊位即阻断，并在 `blocking_reason` 中逐项点名。
    """
    missing = inputs.missing_modules
    if missing:
        names = "、".join(MODULE_LABELS.get(key, key) for key in missing)
        return False, f"尚未完成：{names}（需三诊全部完成后方可合参）"
    return True, None


def normalize(inputs: FusionInputs) -> dict:
    """归一为可序列化的合参输入快照（落 `inputs_snapshot`，供报告可追溯）。"""
    snapshot: dict[str, Any] = {}
    for key, module in inputs.modules.items():
        entry: dict[str, Any] = {
            "record_id": module.record_no,
            "summary": module.summary,
            "main_syndrome": module.main_syndrome,
            "secondary_syndromes": module.secondary_syndromes,
            "treatment_principles": module.treatment_principles,
            "model_version": module.model_version,
        }
        if key == "inquiry":
            entry["patient_snapshot"] = module.patient_snapshot
            entry["answers"] = module.answers
            entry["missing_items"] = module.missing_items
        else:
            entry["overall_confidence"] = module.overall_confidence
            entry["features"] = module.features
            entry["image_ref"] = module.image_ref
        snapshot[key] = entry
    return snapshot


def _labels(module: ModuleInput | None) -> dict[str, str]:
    if module is None:
        return {}
    return {
        str(feature.get("name")): str(feature.get("label"))
        for feature in module.features
        if feature.get("name")
    }


def detect_conflicts(inputs: FusionInputs) -> list[dict]:
    """识别跨诊矛盾项，返回 `[{modules, description}]`（去重）。"""
    tongue, face, inquiry = (
        inputs.modules.get("tongue"),
        inputs.modules.get("face"),
        inputs.modules.get("inquiry"),
    )
    tongue_color = _labels(tongue).get("tongue_color")
    face_color = _labels(face).get("face_color")
    cold_heat = set()
    if inquiry is not None:
        raw = inquiry.answers.get("cold_heat")
        if isinstance(raw, list):
            cold_heat = {str(item) for item in raw}

    conflicts: list[dict] = []

    def add(modules: list[str], description: str) -> None:
        if not any(item["description"] == description for item in conflicts):
            conflicts.append({"modules": modules, "description": description})

    if tongue_color in _COLD_TONGUE and face_color in _HEAT_FACE:
        add(["tongue", "face"], "舌色淡白提示虚寒，面色潮红提示热象，寒热指向不一致")
    if tongue_color in _HEAT_TONGUE and face_color in _COLD_FACE:
        add(["tongue", "face"], "舌色偏红提示热象，面色苍白提示虚寒，寒热指向不一致")
    if tongue_color in _COLD_TONGUE and cold_heat & _HEAT_INQUIRY:
        add(["tongue", "inquiry"], "舌色淡白提示虚寒，问诊见热象表现，寒热指向不一致")
    if tongue_color in _HEAT_TONGUE and cold_heat & _COLD_INQUIRY:
        add(["tongue", "inquiry"], "舌色偏红提示热象，问诊见畏寒表现，寒热指向不一致")
    if face_color in _COLD_FACE and cold_heat & _HEAT_INQUIRY:
        add(["face", "inquiry"], "面色苍白提示虚寒，问诊见热象表现，寒热指向不一致")
    if face_color in _HEAT_FACE and cold_heat & _COLD_INQUIRY:
        add(["face", "inquiry"], "面色潮红提示热象，问诊见畏寒表现，寒热指向不一致")

    # 证候层面寒热方向矛盾（跨诊主证）
    syndrome_names = {
        key: (module.main_syndrome or {}).get("name")
        for key, module in inputs.modules.items()
        if module.main_syndrome
    }
    heat_keys = [k for k, name in syndrome_names.items() if name in _HEAT_SYNDROMES]
    cold_keys = [k for k, name in syndrome_names.items() if name in _COLD_SYNDROMES]
    if heat_keys and cold_keys and set(heat_keys) != set(cold_keys):
        add(
            sorted(set(heat_keys) | set(cold_keys)),
            "各诊主证寒热方向不一致（兼见热证与寒证倾向），结论需结合临床判断",
        )

    return conflicts


def compute_overall_confidence(
    inputs: FusionInputs, conflicts: list[dict]
) -> float:
    """三诊整体置信度：权重加权 + 缺失诊次权重分摊 + 缺诊/矛盾折减（PRD §7.2）。"""
    present = [key for key in MODULE_KEYS if key in inputs.modules]
    if not present:
        return 0.0

    total_weight = sum(MODULE_WEIGHTS[key] for key in present)
    acc = 0.0
    for key in present:
        module = inputs.modules[key]
        confidence = module.overall_confidence
        if confidence is None:
            confidence = _DEFAULT_MODULE_CONFIDENCE
        acc += confidence * (MODULE_WEIGHTS[key] / total_weight)

    penalty = min(
        _MAX_PENALTY,
        _MISSING_PENALTY * len(inputs.missing_modules) + _CONFLICT_PENALTY * len(conflicts),
    )
    return round(max(_MIN_CONFIDENCE, acc * (1 - penalty)), 3)


def map_health_level(overall_confidence: float, conflicts: list[dict]) -> HealthLevel:
    """由整体置信度与矛盾数映射报告健康等级（UI/UX §3.1 色板）。"""
    if overall_confidence < 0.55 or len(conflicts) >= 2:
        return HealthLevel.BAD
    if overall_confidence < 0.70 or conflicts:
        return HealthLevel.POOR
    if overall_confidence < 0.85:
        return HealthLevel.FAIR
    return HealthLevel.GOOD


def summarize(inputs: FusionInputs) -> dict:
    """一次性产出合参所需的确定性中间结果（供 AI/降级服务复用）。"""
    snapshot = normalize(inputs)
    conflicts = detect_conflicts(inputs)
    overall = compute_overall_confidence(inputs, conflicts)
    missing = inputs.missing_modules
    return {
        "snapshot": snapshot,
        "conflicts": conflicts,
        "overall_confidence": overall,
        "health_level": map_health_level(overall, conflicts),
        "missing_modules": missing,
        "rule_version": RULE_VERSION,
    }


def ranked_syndromes(inputs: FusionInputs) -> list[dict]:
    """汇总三诊主/次证并按置信度降序去重（供报告的体质辨证 Tab）。"""
    collected: dict[str, float] = {}
    for module in inputs.modules.values():
        main = module.main_syndrome
        if main and main.get("name"):
            collected.setdefault(str(main["name"]), float(main.get("confidence", 0.0)))
        for item in module.secondary_syndromes:
            if item.get("name"):
                collected.setdefault(str(item["name"]), float(item.get("confidence", 0.0)))
    ranked = [{"name": name, "confidence": conf} for name, conf in collected.items()]
    ranked.sort(key=lambda item: item["confidence"], reverse=True)
    return ranked