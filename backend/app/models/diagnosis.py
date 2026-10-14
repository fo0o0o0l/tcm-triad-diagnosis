"""舌诊相关 ORM 模型（《开发任务文档》§3.4 ⑥⑦）。

表：`tongue_records`（舌诊采集记录，1:1 会话）/ `tongue_analyses`（舌象 AI 分析，版本化）。

> 说明：会话服务（M0 `sessions` 表）尚未接入，本模块将 `session_id` 作为**不透明业务标识**
> （VARCHAR，如 `s_20261012_0001`）存储，暂不建立外键约束；待 M0 会话模块落地后，
> 由迁移脚本补齐 `session_id → sessions.id` 外键与去重索引，业务层无需改动。
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ImageSource(str, enum.Enum):
    """采集来源（PG `image_source`）。"""

    UPLOAD = "upload"
    CAMERA = "camera"


class ModuleStatus(str, enum.Enum):
    """单诊子流程状态（PG `module_status`）。"""

    PENDING = "pending"
    COLLECTING = "collecting"
    EXTRACTING = "extracting"
    ANALYZED = "analyzed"
    FAILED = "failed"


class AnalysisStatus(str, enum.Enum):
    """AI 分析状态（PG `analysis_status`）。"""

    PENDING = "pending"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    FAILED = "failed"


class HealthLevel(str, enum.Enum):
    """报告综合评估健康等级（PG `health_level`，UI/UX §3.1 色板）。

    仅表达评估等级，不代表医疗诊断结论。
    """

    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    BAD = "bad"


class ReportStatus(str, enum.Enum):
    """报告状态（PG `report_status`）：草稿 / 定稿 / 已归档。"""

    DRAFT = "draft"
    FINAL = "final"
    ARCHIVED = "archived"


def _pg_enum(enum_cls: type[enum.Enum], name: str) -> SAEnum:
    """构造按“值”存库的 PG 原生枚举（与 user.py 保持一致）。"""
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda e: [m.value for m in e],
        native_enum=True,
        validate_strings=True,
    )


class TongueRecord(Base):
    """舌诊采集记录（1:1 会话）：图像、质量、掩膜、四类特征与整体置信度。"""

    __tablename__ = "tongue_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    record_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    session_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source: Mapped[ImageSource] = mapped_column(_pg_enum(ImageSource, "image_source"))
    image_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    quality_passed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    quality_score: Mapped[float | None] = mapped_column(Numeric(4, 3))
    quality_detail: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    mask_ref: Mapped[str | None] = mapped_column(String(255))
    extract_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    extract_status: Mapped[ModuleStatus] = mapped_column(
        _pg_enum(ModuleStatus, "module_status"),
        nullable=False,
        server_default=ModuleStatus.PENDING.value,
    )
    features: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    overall_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    rule_version: Mapped[str | None] = mapped_column(String(32))
    idempotency_key: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))

    analyses: Mapped[list[TongueAnalysis]] = relationship(
        back_populates="record", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index(
            "uq_tongue_session",
            "session_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class TongueAnalysis(Base):
    """舌象 AI 分析（版本化）：`is_current=true` 为当前有效版本。"""

    __tablename__ = "tongue_analyses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    analysis_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    record_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("tongue_records.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[AnalysisStatus] = mapped_column(
        _pg_enum(AnalysisStatus, "analysis_status"),
        nullable=False,
        server_default=AnalysisStatus.PENDING.value,
    )
    tongue_summary: Mapped[str | None] = mapped_column(Text)
    main_syndrome: Mapped[dict | None] = mapped_column(JSONB)
    secondary_syndromes: Mapped[list | None] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    treatment_principles: Mapped[list | None] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    recommendations: Mapped[list | None] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    model_version: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(16))
    retryable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    task_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    record: Mapped[TongueRecord] = relationship(back_populates="analyses")

    __table_args__ = (
        Index("idx_tongue_analysis_record", "record_id", "is_current"),
        Index(
            "uq_tongue_analysis_current",
            "record_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )


class FaceRecord(Base):
    """面诊采集记录（1:1 会话）：图像、质量、面部区域、四类面象特征与整体置信度。

    结构对齐《开发任务文档》§3.4 ⑧ `face_records`；与舌诊差异在于以 `regions`（面部区域）
    取代舌体掩膜，并提供 `face_count` / `detect_confidence` 用于单脸校验。
    """

    __tablename__ = "face_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    record_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    session_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source: Mapped[ImageSource] = mapped_column(_pg_enum(ImageSource, "image_source"))
    image_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    quality_passed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    quality_score: Mapped[float | None] = mapped_column(Numeric(4, 3))
    quality_detail: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    face_count: Mapped[int | None] = mapped_column()
    regions: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    detect_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    detect_status: Mapped[ModuleStatus] = mapped_column(
        _pg_enum(ModuleStatus, "module_status"),
        nullable=False,
        server_default=ModuleStatus.PENDING.value,
    )
    features: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    overall_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    rule_version: Mapped[str | None] = mapped_column(String(32))
    idempotency_key: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))

    analyses: Mapped[list[FaceAnalysis]] = relationship(
        back_populates="record", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index(
            "uq_face_session",
            "session_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class FaceAnalysis(Base):
    """面象 AI 分析（版本化）：`is_current=true` 为当前有效版本。"""

    __tablename__ = "face_analyses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    analysis_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    record_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("face_records.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[AnalysisStatus] = mapped_column(
        _pg_enum(AnalysisStatus, "analysis_status"),
        nullable=False,
        server_default=AnalysisStatus.PENDING.value,
    )
    face_summary: Mapped[str | None] = mapped_column(Text)
    main_syndrome: Mapped[dict | None] = mapped_column(JSONB)
    secondary_syndromes: Mapped[list | None] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    treatment_principles: Mapped[list | None] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    recommendations: Mapped[list | None] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    model_version: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(16))
    retryable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    task_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    record: Mapped[FaceRecord] = relationship(back_populates="analyses")

    __table_args__ = (
        Index("idx_face_analysis_record", "record_id", "is_current"),
        Index(
            "uq_face_analysis_current",
            "record_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )


class InquiryRecord(Base):
    """问诊记录（1:1 会话）：模板版本、患者快照、结构化答案与未答项。

    结构对齐《开发任务文档》§3.4 ⑩ `inquiry_records`；与舌诊/面诊差异在于**无图像**，
    以 `template_version` + `answers`（`{qid: value}`）+ `patient_snapshot` 承载问诊数据。
    `session_id` 与会话服务接入前一致，作为不透明业务标识（VARCHAR）存储。
    """

    __tablename__ = "inquiry_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    record_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    session_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    template_version: Mapped[str] = mapped_column(String(32), nullable=False)
    patient_snapshot: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    answers: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    missing_items: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    status: Mapped[ModuleStatus] = mapped_column(
        _pg_enum(ModuleStatus, "module_status"),
        nullable=False,
        server_default=ModuleStatus.PENDING.value,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    analyses: Mapped[list[InquiryAnalysis]] = relationship(
        back_populates="record", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index(
            "uq_inquiry_session",
            "session_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class InquiryAnalysis(Base):
    """问诊 AI 分析（版本化）：`is_current=true` 为当前有效版本。"""

    __tablename__ = "inquiry_analyses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    analysis_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    record_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("inquiry_records.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[AnalysisStatus] = mapped_column(
        _pg_enum(AnalysisStatus, "analysis_status"),
        nullable=False,
        server_default=AnalysisStatus.PENDING.value,
    )
    symptoms_summary: Mapped[str | None] = mapped_column(Text)
    main_syndrome: Mapped[dict | None] = mapped_column(JSONB)
    secondary_syndromes: Mapped[list | None] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    treatment_principles: Mapped[list | None] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    recommendations: Mapped[list | None] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    model_version: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(16))
    retryable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    task_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    record: Mapped[InquiryRecord] = relationship(back_populates="analyses")

    __table_args__ = (
        Index("idx_inquiry_analysis_record", "record_id", "is_current"),
        Index(
            "uq_inquiry_analysis_current",
            "record_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )


class InquiryTemplate(Base):
    """问诊模板（版本化，驱动前端表单）：`status=active` 为当前生效版本。"""

    __tablename__ = "inquiry_templates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    # 列名 `schema` 为保留语义，Python 属性改用 `template_schema` 避免歧义
    template_schema: Mapped[dict] = mapped_column("schema", JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="active"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class InquiryDraft(Base):
    """服务端问诊草稿（按会话唯一，与前端 localStorage 双写，服务端为准）。"""

    __tablename__ = "inquiry_drafts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    template_version: Mapped[str] = mapped_column(String(32), nullable=False)
    answers: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (Index("uq_inquiry_draft_session", "session_id", unique=True),)


class FusionResult(Base):
    """三诊合参结果（版本化）：`is_current=true` 为该会话当前有效版本。

    结构对齐《开发任务文档》§3.4 ⑭ `fusion_results`；与三诊单模块的差异在于
    以 `conclusions`（综合结论）/ `syndrome_points`（辨证要点）/ `conflicts`（跨诊矛盾）
    承载融合输出，并保留 `inputs_snapshot` 供报告可追溯（PRD §6.4）。
    `session_id` 与会话服务接入前一致，作为不透明业务标识（VARCHAR）存储。
    """

    __tablename__ = "fusion_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    fusion_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    session_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[AnalysisStatus] = mapped_column(
        _pg_enum(AnalysisStatus, "analysis_status"),
        nullable=False,
        server_default=AnalysisStatus.PENDING.value,
    )
    overall_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    health_level: Mapped[HealthLevel | None] = mapped_column(_pg_enum(HealthLevel, "health_level"))
    missing_modules: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    conflicts: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    conclusions: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    syndrome_points: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    suggestions: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    inputs_snapshot: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    rule_version: Mapped[str | None] = mapped_column(String(32))
    model_version: Mapped[str | None] = mapped_column(String(64))
    error_code: Mapped[str | None] = mapped_column(String(16))
    retryable: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    task_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        Index("idx_fusion_session", "session_id", "is_current"),
        Index(
            "uq_fusion_current",
            "session_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )


class Report(Base):
    """综合诊断报告（M6，版本化）：`report_data` 一次性承载 8 Tab 渲染数据。

    结构对齐《开发任务文档》§3.4 ⑮ `reports`；`fusion_id` 关联生成该报告的合参结果，
    同一合参结果仅对应一份报告（重复分析产生新合参 → 新报告版本）。
    归档为状态流转（`final → archived`），归档后只读（PRD §6.5）。
    """

    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    report_no: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    session_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    fusion_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("fusion_results.id", ondelete="SET NULL")
    )
    status: Mapped[ReportStatus] = mapped_column(
        _pg_enum(ReportStatus, "report_status"),
        nullable=False,
        server_default=ReportStatus.DRAFT.value,
    )
    patient_snapshot: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    overall_confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    health_level: Mapped[HealthLevel | None] = mapped_column(_pg_enum(HealthLevel, "health_level"))
    summary: Mapped[str | None] = mapped_column(String(255))
    report_data: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    pdf_ref: Mapped[str | None] = mapped_column(String(255))
    rule_version: Mapped[str | None] = mapped_column(String(32))
    model_version: Mapped[str | None] = mapped_column(String(64))
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (Index("idx_reports_session", "session_id", "generated_at"),)