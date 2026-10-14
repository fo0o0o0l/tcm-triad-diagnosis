"""报告对比请求 / 响应模型（P8 数据对比页；UI/UX §5.7）。

选择两份**同一患者**的历史报告，对比三诊特征、健康状态、置信度与综合结论的变化。
变化方向语义 `improved`（改善）/ `worsened`（加重）/ `same`（持平）/ `unknown`（无法判定），
其中 `unknown` 用于特征字典未覆盖的标签，前端按“有变化”中性展示（§5.7.3 方向映射 [TBD]）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.diagnosis import HealthLevel, ReportStatus
from app.schemas.diagnosis import ModuleKey

#: 变化方向语义
ChangeDirection = Literal["improved", "worsened", "same", "unknown"]


class CompareReportSummary(BaseModel):
    """参与对比的一份报告的元信息（对齐历史列表项口径）。"""

    report_id: str
    session_id: str
    patient_name: str | None = None
    anonymous: bool = False
    generated_at: datetime
    health_level: HealthLevel | None = None
    overall_confidence: float | None = None
    status: ReportStatus
    summary: str | None = None


class HealthChange(BaseModel):
    """健康状态变化（两徽标 + 变化语义）。"""

    base_level: HealthLevel | None = None
    target_level: HealthLevel | None = None
    direction: ChangeDirection = "unknown"


class FeatureDiffItem(BaseModel):
    """单个特征项的变化（列：特征 / 上次 / 本次 / 变化）。"""

    name: str
    label: str
    base_value: str | None = None
    target_value: str | None = None
    changed: bool = False
    direction: ChangeDirection = "unknown"
    base_confidence: float | None = None
    target_confidence: float | None = None


class ModuleFeatureDiff(BaseModel):
    """单诊模块的特征对比分组（舌象 / 面象 / 问诊症状）。"""

    module: ModuleKey
    label: str
    items: list[FeatureDiffItem] = Field(default_factory=list)


class ConclusionDiff(BaseModel):
    """综合结论对比：两侧结论并排 + 差异点（新增 / 减轻）。"""

    base_texts: list[str] = Field(default_factory=list)
    target_texts: list[str] = Field(default_factory=list)
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)


class ConfidencePoint(BaseModel):
    """置信度趋势上的一个点（同患者近 N 次报告，按时间升序）。"""

    report_id: str
    generated_at: datetime
    overall_confidence: float | None = None
    health_level: HealthLevel | None = None
    #: 该点在本次对比中的角色（基准 / 对比 / 历史序列）
    role: Literal["base", "target", "history"] = "history"


class CompareResult(BaseModel):
    """R-CMP 响应 `data`：一次返回对比所需的全部渲染数据。"""

    base: CompareReportSummary
    target: CompareReportSummary
    health: HealthChange
    modules: list[ModuleFeatureDiff] = Field(default_factory=list)
    conclusions: ConclusionDiff
    trend: list[ConfidencePoint] = Field(default_factory=list)
