"""算法服务请求 / 响应模型。

契约对齐《开发任务文档》§4.10：`POST /llm/analyze` 入参 `{module, payload, language}`，
出参为各诊/合参的可读结论（字段与后端 `*_ai_analysis.py` 的 `_call_algo` 归一化字段一致）。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Module = Literal["tongue", "face", "inquiry", "fusion"]


class AnalyzeRequest(BaseModel):
    """`/llm/analyze` 请求体（由后端 `_call_algo` 构造）。"""

    module: Module
    payload: dict[str, Any] = Field(default_factory=dict)
    language: str = "zh-CN"


#: 视觉特征提取支持的模块（图片 → 结构化特征）
VisionModule = Literal["tongue", "face"]


class VisionClassifyRequest(BaseModel):
    """`/vision/classify` 请求体（由后端 F3/T3 特征识别构造）。

    `image_base64` 为 JPEG/PNG 的 base64 编码（不含 data URL 前缀）；
    `feature_names` 为空时返回该模块全部特征。
    """

    module: VisionModule
    image_base64: str = Field(min_length=1)
    feature_names: list[str] = Field(default_factory=list)


def _clamp(value: Any, default: float = 0.5) -> float:
    """把任意输入钳制为 [0, 1] 内的小数；非法输入回退默认值。"""
    try:
        return round(min(1.0, max(0.0, float(value))), 3)
    except (TypeError, ValueError):
        return default


class Syndrome(BaseModel):
    """证候（主证 / 次证）。"""

    name: str = "平和质倾向"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, value: Any) -> float:
        return _clamp(value)


class Advice(BaseModel):
    """调理建议条目。"""

    category: str = "通用"
    text: str

    @field_validator("category", mode="before")
    @classmethod
    def _coerce_category(cls, value: Any) -> str:
        return str(value).strip() if isinstance(value, (str, int, float)) else "通用"


class Conclusion(BaseModel):
    """合参结论条目。"""

    text: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("confidence", mode="before")
    @classmethod
    def _clamp_confidence(cls, value: Any) -> float:
        return _clamp(value)


class ModuleOutput(BaseModel):
    """舌/面/问三诊通用输出（summary 字段名按模块不同，未命中的字段不序列化）。"""

    model_config = ConfigDict(extra="ignore")

    tongue_summary: str | None = None
    face_summary: str | None = None
    symptoms_summary: str | None = None
    main_syndrome: Syndrome = Syndrome()
    secondary_syndromes: list[Syndrome] = Field(default_factory=list)
    treatment_principles: list[str] = Field(default_factory=list)
    recommendations: list[Advice] = Field(default_factory=list)
    model_version: str = ""


class FusionOutput(BaseModel):
    """三诊合参输出。"""

    model_config = ConfigDict(extra="ignore")

    conclusions: list[Conclusion] = Field(default_factory=list)
    syndrome_points: list[str] = Field(default_factory=list)
    suggestions: list[Advice] = Field(default_factory=list)
    model_version: str = ""
