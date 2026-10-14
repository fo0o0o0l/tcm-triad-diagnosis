"""舌诊请求 / 响应模型（《开发任务文档》§4.5 T1~T5；PRD §9.2）。

字段与响应示例严格对齐 PRD §9.2，供前端直接消费。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.diagnosis import AnalysisStatus, ModuleStatus

#: 四类舌象特征字段名（PRD §6.1.3）
TongueFeatureName = Literal["tongue_color", "coating_color", "coating_texture", "tongue_shape"]

#: 默认识别特征项（T3 未显式传入时）
DEFAULT_TONGUE_FEATURES = ["tongue_color", "coating_color", "coating_texture", "tongue_shape"]


# ---- 通用结构 ----
class FeatureItem(BaseModel):
    """单个舌象特征项 `{name, label, confidence}`。"""

    name: str
    label: str
    confidence: float = Field(ge=0, le=1)


class Syndrome(BaseModel):
    """证候倾向 `{name, confidence}`。"""

    name: str
    confidence: float = Field(ge=0, le=1)


class Recommendation(BaseModel):
    """调理建议 `{category, text}`。"""

    category: str
    text: str


# ---- T1 上传 ----
class QualityResult(BaseModel):
    """质量校验结果（PRD §7.1）。"""

    passed: bool
    clearness: float = Field(ge=0, le=1)
    lighting: float = Field(ge=0, le=1)
    composition: float = Field(ge=0, le=1)
    suggestions: list[str] = []


class TongueImageResponse(BaseModel):
    """T1 响应 `data`。"""

    record_id: str
    image_ref: str
    quality: QualityResult


# ---- T2 舌体区域提取 ----
class ExtractRequest(BaseModel):
    record_id: str = Field(min_length=1)


class ExtractResponse(BaseModel):
    """T2 响应 `data`；`status` 区分 成功 / 低可信（不阻断）。"""

    record_id: str
    mask_ref: str
    confidence: float = Field(ge=0, le=1)
    status: ModuleStatus


# ---- T3 舌象特征识别 ----
class AnalyzeRequest(BaseModel):
    record_id: str = Field(min_length=1)
    features: list[str] = Field(default_factory=lambda: list(DEFAULT_TONGUE_FEATURES))


class AnalyzeResponse(BaseModel):
    """T3 响应 `data`。"""

    record_id: str
    overall_confidence: float = Field(ge=0, le=1)
    features: list[FeatureItem]


# ---- T4 舌象 AI 分析（异步）----
class AiAnalysisRequest(BaseModel):
    record_id: str = Field(min_length=1)
    language: str = "zh-CN"


class AiAnalysisResponse(BaseModel):
    """T4 响应 `data`（返回任务，前端轮询 T5）。"""

    task_id: str
    analysis_status: AnalysisStatus


# ---- T5 查询分析结果 ----
class AnalysisResult(BaseModel):
    """AI 解读结果（PRD §6.1.4 输出字段）。"""

    tongue_summary: str
    main_syndrome: Syndrome | None = None
    secondary_syndromes: list[Syndrome] = []
    treatment_principles: list[str] = []
    recommendations: list[Recommendation] = []


class AnalysisQueryResponse(BaseModel):
    """T5 响应 `data`。"""

    model_config = ConfigDict(from_attributes=True)

    tongue_id: str
    record_id: str
    status: AnalysisStatus
    result: AnalysisResult | None = None
    model_version: str | None = None
    retryable: bool = True


# ---- T0 查询采集状态（页面重新挂载时恢复进度）----
class RecordStateResponse(BaseModel):
    """会话当前舌诊采集状态快照；用于切换模块后返回时恢复进度。

    无采集记录时接口返回 `data=null`（非错误）。
    """

    record_id: str
    image_ref: str
    quality: QualityResult
    extract: ExtractResponse | None = None
    analyze: AnalyzeResponse | None = None
    analysis: AnalysisQueryResponse | None = None