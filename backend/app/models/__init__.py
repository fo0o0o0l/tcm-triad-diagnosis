"""ORM 模型汇总导出（供 Alembic `target_metadata` 与业务层引用）。"""

from __future__ import annotations

from app.core.database import Base
from app.models.diagnosis import (
    AnalysisStatus,
    FaceAnalysis,
    FaceRecord,
    FusionResult,
    HealthLevel,
    ImageSource,
    InquiryAnalysis,
    InquiryDraft,
    InquiryRecord,
    InquiryTemplate,
    ModuleStatus,
    Report,
    ReportStatus,
    TongueAnalysis,
    TongueRecord,
)
from app.models.user import (
    PasswordResetToken,
    RefreshToken,
    User,
    UserRole,
    UserStatus,
    VerificationCode,
)

__all__ = [
    "Base",
    "User",
    "UserRole",
    "UserStatus",
    "RefreshToken",
    "PasswordResetToken",
    "VerificationCode",
    "TongueRecord",
    "TongueAnalysis",
    "FaceRecord",
    "FaceAnalysis",
    "InquiryRecord",
    "InquiryAnalysis",
    "InquiryTemplate",
    "InquiryDraft",
    "FusionResult",
    "Report",
    "ImageSource",
    "ModuleStatus",
    "AnalysisStatus",
    "HealthLevel",
    "ReportStatus",
]