"""三诊合参请求 / 响应模型（《开发任务文档》§4.8 G1~G2；PRD §6.4 / §9.5）。

- G0 前置校验：返回三诊完成态与缺诊降级判定（缺两诊阻断）；
- G1 触发合参：返回任务（前端轮询 P5 分析中页）；
- G2 查询结果：返回综合结论 / 辨证要点 / 建议 / 缺诊 / 跨诊矛盾，并附报告 8 Tab 数据。

报告 `report_data` 一次性包含 P6 报告页 8 个 Tab 的渲染数据（§5.5.3）；缺失维度以空结构
返回，前端展示空状态，不隐藏 Tab。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.diagnosis import AnalysisStatus, HealthLevel, ReportStatus

#: 三诊模块键
ModuleKey = Literal["tongue", "face", "inquiry"]
#: 报告 Tab 键（UI/UX §5.5.3，顺序即打印串行顺序）
ReportTabKey = Literal[
    "overview",
    "details",
    "indices",
    "therapy",
    "constitution",
    "prevention",
    "advice",
    "emotion",
]


# ---- 通用结构 ----
class Syndrome(BaseModel):
    """证候倾向 `{name, confidence}`。"""

    name: str
    confidence: float = Field(ge=0, le=1)


class Recommendation(BaseModel):
    """调理建议 `{category, text}`。"""

    category: str
    text: str


class FeatureItem(BaseModel):
    """特征项 `{name, label, confidence, area?}`（面诊的痘痘/斑点带分布区域）。"""

    name: str
    label: str
    confidence: float = Field(ge=0, le=1)
    area: list[str] | None = None


class Conclusion(BaseModel):
    """综合诊断结论 `{text, confidence}`。"""

    text: str
    confidence: float = Field(ge=0, le=1)


class Conflict(BaseModel):
    """跨诊矛盾项 `{modules, description}`（PRD §6.4 一致性校验）。"""

    modules: list[ModuleKey] = []
    description: str


class Suggestion(BaseModel):
    """调理建议 `{category, text}`（与单诊 Recommendation 结构一致）。"""

    category: str
    text: str


# ---- G0 前置校验 ----
class ModuleState(BaseModel):
    """单诊就绪状态（用于 P5 右侧「三诊依据」卡片）。"""

    done: bool
    overall_confidence: float | None = None
    summary: str | None = None


class ReadinessResponse(BaseModel):
    """G0 响应 `data`：三诊完成态 + 缺诊判定 + 是否可触发合参。"""

    session_id: str
    modules: dict[str, ModuleState]
    missing_modules: list[str]
    can_analyze: bool
    blocking_reason: str | None = None


# ---- G1 触发合参 ----
class FusionOptions(BaseModel):
    """合参选项（PRD §9.5 请求体）。"""

    include_inquiry: bool = True
    language: str = "zh-CN"


class FusionAnalyzeRequest(BaseModel):
    """G1 请求。"""

    options: FusionOptions = Field(default_factory=FusionOptions)


class FusionAnalyzeResponse(BaseModel):
    """G1 响应 `data`（异步任务，前端轮询 G2）。"""

    fusion_status: AnalysisStatus
    task_id: str


# ---- G2 查询结果 ----
class FusionResultData(BaseModel):
    """G2 响应 `data`（PRD §9.5 字段 + 报告数据）。"""

    fusion_id: str
    session_id: str
    status: AnalysisStatus
    overall_confidence: float | None = None
    health_level: HealthLevel | None = None
    missing_modules: list[str] = []
    conflicts: list[Conflict] = []
    conclusions: list[Conclusion] = []
    syndrome_points: list[str] = []
    suggestions: list[Suggestion] = []
    rule_version: str | None = None
    model_version: str | None = None
    retryable: bool = True
    # 报告记录标识与状态（合参完成后自动生成；供导出 PDF / 归档使用）
    report_id: str | None = None
    report_status: ReportStatus | None = None
    report: ReportData | None = None


# ---- 报告数据（P6 8 Tab，UI/UX §5.5.3）----
class PatientSnapshot(BaseModel):
    """患者快照（由问诊答案归一；匿名时姓名置空）。"""

    name: str | None = None
    gender: str | None = None
    age: float | None = None
    height: float | None = None
    weight: float | None = None
    anonymous: bool = False


class ReportHeader(BaseModel):
    """报告头（UI/UX §5.5.2）。"""

    session_id: str
    patient_snapshot: PatientSnapshot | None = None
    generated_at: datetime | None = None
    overall_confidence: float | None = None
    health_level: HealthLevel | None = None
    rule_version: str | None = None
    model_version: str | None = None
    status: str = "final"


class OverviewTab(BaseModel):
    """综合概览：主结论卡 + 辨证要点 + 三诊依据摘要。"""

    conclusions: list[Conclusion] = []
    syndrome_points: list[str] = []
    overall_confidence: float | None = None
    evidence_summary: list[str] = []


class ModuleDetail(BaseModel):
    """舌 / 面详情：原图 + 特征表 + 单诊小结。"""

    module: ModuleKey
    record_id: str
    image_ref: str
    features: list[FeatureItem] = []
    summary: str | None = None
    main_syndrome: Syndrome | None = None
    secondary_syndromes: list[Syndrome] = []
    treatment_principles: list[str] = []
    model_version: str | None = None


class InquiryDetail(BaseModel):
    """问诊详情：患者快照 + 关键答案摘要 + AI 小结。"""

    record_id: str
    patient_snapshot: PatientSnapshot | None = None
    answers: dict[str, Any] = {}
    missing_items: list[str] = []
    summary: str | None = None
    main_syndrome: Syndrome | None = None
    secondary_syndromes: list[Syndrome] = []
    treatment_principles: list[str] = []
    model_version: str | None = None


class DetailsTab(BaseModel):
    """三诊详情。"""

    tongue: ModuleDetail | None = None
    face: ModuleDetail | None = None
    inquiry: InquiryDetail | None = None


class IndexItem(BaseModel):
    """派生指数项（如 BMI）。"""

    name: str
    value: str
    reference: str | None = None
    level: str = "fair"


class IndicesTab(BaseModel):
    """基础指数。"""

    items: list[IndexItem] = []


class TherapyItem(BaseModel):
    """理疗参数项。"""

    name: str
    value: str
    note: str | None = None


class TherapyTab(BaseModel):
    """理疗参数（如适用）。"""

    items: list[TherapyItem] = []


class ConstitutionTab(BaseModel):
    """体质辨证。"""

    main_syndrome: Syndrome | None = None
    secondary_syndromes: list[Syndrome] = []
    description: str | None = None


class PreventionGroup(BaseModel):
    """治未病建议分组。"""

    title: str
    items: list[str] = []


class PreventionTab(BaseModel):
    """治未病（未病先防类建议）。"""

    groups: list[PreventionGroup] = []


class AdviceTab(BaseModel):
    """调理建议（按 category 分组展示）。"""

    suggestions: list[Suggestion] = []


class EmotionDimension(BaseModel):
    """情绪维度条。"""

    name: str
    score: float = Field(ge=0, le=1)
    note: str | None = None


class EmotionTab(BaseModel):
    """情绪分析（依问诊情志项与 AI 输出）。"""

    dimensions: list[EmotionDimension] = []
    summary: str | None = None


class ReportData(BaseModel):
    """报告 8 Tab 渲染数据（一次性返回，缺失维度为空结构）。"""

    model_config = ConfigDict(populate_by_name=True)

    header: ReportHeader
    overview: OverviewTab
    details: DetailsTab
    indices: IndicesTab
    therapy: TherapyTab
    constitution: ConstitutionTab
    prevention: PreventionTab
    advice: AdviceTab
    emotion: EmotionTab


# `FusionResultData.report` 前向引用 `ReportData`（定义在其后），显式重建以完成解析
FusionResultData.model_rebuild()


# ---- R4 报告历史查询（PRD §6.5.4 / §9.6）----
class ReportHistoryItem(BaseModel):
    """历史列表项：报告元信息 + 患者标识 + 结论摘要（供 P7 列表卡片渲染）。"""

    report_id: str
    session_id: str
    patient_name: str | None = None
    anonymous: bool = False
    generated_at: datetime
    overall_confidence: float | None = None
    health_level: HealthLevel | None = None
    status: ReportStatus
    summary: str | None = None


class ReportHistoryList(BaseModel):
    """R4 响应 `data`：分页结构 `{total, page, page_size, items[]}`（开发任务文档 §4.1）。"""

    total: int
    page: int
    page_size: int
    items: list[ReportHistoryItem] = []