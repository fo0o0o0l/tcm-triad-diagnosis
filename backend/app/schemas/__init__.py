"""数据模型（Pydantic）汇总导出。"""

from __future__ import annotations

from app.schemas.auth import (
    ChangePasswordRequest,
    ChangePasswordResponse,
    ForgotRequest,
    ForgotResponse,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    LogoutResponse,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
    SendCodeRequest,
    SendCodeResponse,
)
from app.schemas.user import UserBrief, UserProfile, UserStats

__all__ = [
    "RegisterRequest",
    "RegisterResponse",
    "LoginRequest",
    "LoginResponse",
    "RefreshRequest",
    "LogoutRequest",
    "LogoutResponse",
    "SendCodeRequest",
    "SendCodeResponse",
    "ForgotRequest",
    "ForgotResponse",
    "ResetPasswordRequest",
    "ResetPasswordResponse",
    "ChangePasswordRequest",
    "ChangePasswordResponse",
    "UserBrief",
    "UserProfile",
    "UserStats",
]