"""面诊请求 / 响应模型（《开发任务文档》§4.6 F1~F5；PRD §9.3）。

字段与响应示例严格对齐 PRD §9.3，供前端直接消费。与舌诊（`schemas/tongue.py`）的差异：
- 质量校验结果额外含 `face_detected` / `single_face`；
- F2 为面部区域检测（`face_count` + `regions[]`）而非舌体提取；
- F3 特征中痘痘 / 斑点额外输出 `area`（分布区域）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.diagnosis import AnalysisStatus, ModuleStatus

#: 四类面象特征字段名（PRD §6.2.3）
FaceFeatureName = Literal["face_color", "luster", "acne", "spots"]

#: 默认识别特征项（F3 未显式传入时）
DEFAULT_FACE_FEATURES = ["face_color", "luster", "acne", "spots"]


# ---- 通用结构 ----
class FeatureItem(BaseModel):
    """单个面象特征项 `{name, label, confidence, area?}`；`area` 仅痘痘/斑点输出。"""

    name: str
    label: str
    confidence: float = Field(ge=0, le=1)
    area: list[str] | None = None


class Syndrome(BaseModel):
    """证候倾向 `{name, confidence}`。"""

    name: str
    confidence: float = Field(ge=0, le=1)


class Recommendation(BaseModel):
    """调理建议 `{category, text}`。"""

    category: str
    text: str


class Region(BaseModel):
    """面部区域 `{name, bbox}`；`bbox` 为 `[x0, y0, x1, y1]`。"""

    name: str
    bbox: list[int] = Field(min_length=4, max_length=4)


# ---- F1 上传 ----
class QualityResult(BaseModel):
    """质量校验结果（PRD §7.1）；面诊额外含面部相关维度。"""

    passed: bool
    clearness: float = Field(ge=0, le=1)
    lighting: float = Field(ge=0, le=1)
    composition: float = Field(ge=0, le=1)
    face_detected: bool
    single_face: bool
    suggestions: list[str] = []


class FaceImageResponse(BaseModel):
    """F1 响应 `data`。"""

    record_id: str
    image_ref: str
    quality: QualityResult


# ---- F2 面部区域检测 ----
class DetectRequest(BaseModel):
    record_id: str = Field(min_length=1)


class DetectResponse(BaseModel):
    """F2 响应 `data`；非单脸已在接口层 42201 阻断。"""

    record_id: str
    face_count: int
    regions: list[Region]
    detect_confidence: float = Field(ge=0, le=1)
    status: ModuleStatus


# ---- F3 面象特征识别 ----
class AnalyzeRequest(BaseModel):
    record_id: str = Field(min_length=1)
    features: list[str] = Field(default_factory=lambda: list(DEFAULT_FACE_FEATURES))


class AnalyzeResponse(BaseModel):
    """F3 响应 `data`。"""

    record_id: str
    overall_confidence: float = Field(ge=0, le=1)
    features: list[FeatureItem]


# ---- F4 面象 AI 分析（异步）----
class AiAnalysisRequest(BaseModel):
    record_id: str = Field(min_length=1)
    language: str = "zh-CN"


class AiAnalysisResponse(BaseModel):
    """F4 响应 `data`（返回任务，前端轮询 F5）。"""

    task_id: str
    analysis_status: AnalysisStatus


# ---- F5 查询分析结果 ----
class AnalysisResult(BaseModel):
    """AI 解读结果（PRD §6.2.4 输出字段）。"""

    face_summary: str
    main_syndrome: Syndrome | None = None
    secondary_syndromes: list[Syndrome] = []
    treatment_principles: list[str] = []
    recommendations: list[Recommendation] = []


class AnalysisQueryResponse(BaseModel):
    """F5 响应 `data`。"""

    model_config = ConfigDict(from_attributes=True)

    face_id: str
    record_id: str
    status: AnalysisStatus
    result: AnalysisResult | None = None
    model_version: str | None = None
    retryable: bool = True


# ---- F0 查询采集状态（页面重新挂载时恢复进度）----
class RecordStateResponse(BaseModel):
    """会话当前面诊采集状态快照；用于切换模块后返回时恢复进度。

    无采集记录时接口返回 `data=null`（非错误）。
    """

    record_id: str
    image_ref: str
    quality: QualityResult
    detect: DetectResponse | None = None
    analyze: AnalyzeResponse | None = None
    analysis: AnalysisQueryResponse | None = None