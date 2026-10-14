"""认证请求 / 响应模型（《开发任务文档》§4.3 A1~A9）。"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.user import UserRole, UserStatus
from app.schemas.user import UserBrief

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{4,32}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^\+?\d{6,20}$")

#: `verify_code` 有效期（秒），与 A6 响应 `expires_in` 保持一致
CODE_EXPIRE_SECONDS = 300


def _validate_password_strength(value: str) -> str:
    """注册 / 重置密码强度：≥8 位且同时包含字母与数字。"""
    if len(value) < 8:
        raise ValueError("密码至少 8 位")
    if not re.search(r"[A-Za-z]", value) or not re.search(r"\d", value):
        raise ValueError("密码需同时包含字母与数字")
    return value


# ---- A1 注册 ----
class RegisterRequest(BaseModel):
    username: str = Field(description="登录名，4-32 位字母/数字/下划线")
    password: str
    name: str | None = Field(default=None, max_length=64)
    email: str | None = Field(default=None, max_length=128)
    phone: str | None = Field(default=None, max_length=20)
    department: str | None = Field(default=None, max_length=64)
    verify_code: str = Field(min_length=4, max_length=8)

    @field_validator("username")
    @classmethod
    def _check_username(cls, value: str) -> str:
        if not _USERNAME_RE.match(value):
            raise ValueError("用户名需为 4-32 位字母、数字或下划线")
        return value

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        return _validate_password_strength(value)

    @field_validator("email")
    @classmethod
    def _check_email(cls, value: str | None) -> str | None:
        if value is not None and not _EMAIL_RE.match(value):
            raise ValueError("邮箱格式不正确")
        return value

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, value: str | None) -> str | None:
        if value is not None and not _PHONE_RE.match(value):
            raise ValueError("手机号格式不正确")
        return value

    @model_validator(mode="after")
    def _require_contact(self) -> RegisterRequest:
        if not self.email and not self.phone:
            raise ValueError("邮箱与手机号至少提供一个")
        return self


class RegisterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_no: str
    username: str
    role: UserRole
    status: UserStatus
    created_at: datetime


# ---- A2 登录 ----
class LoginRequest(BaseModel):
    account: str = Field(min_length=1, description="用户名 / 邮箱 / 手机号")
    password: str = Field(min_length=1)
    remember: bool = False


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int
    user: UserBrief


# ---- A3 刷新 ----
class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


# ---- A4 登出 ----
class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class LogoutResponse(BaseModel):
    revoked: bool


# ---- A6 发送验证码 ----
class SendCodeRequest(BaseModel):
    target: str = Field(min_length=1, max_length=128)
    scene: Literal["register", "reset_password"]
    channel: Literal["email", "sms"] = "email"


class SendCodeResponse(BaseModel):
    sent: bool
    expires_in: int = CODE_EXPIRE_SECONDS


# ---- A7 发起找回 ----
class ForgotRequest(BaseModel):
    account: str = Field(min_length=1)
    channel: Literal["email", "sms"] = "email"


class ForgotResponse(BaseModel):
    sent: bool = True


# ---- A8 重置密码 ----
class ResetPasswordRequest(BaseModel):
    account: str = Field(min_length=1)
    new_password: str
    verify_code: str | None = Field(default=None, min_length=4, max_length=8)
    reset_token: str | None = None

    @field_validator("new_password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        return _validate_password_strength(value)

    @model_validator(mode="after")
    def _require_proof(self) -> ResetPasswordRequest:
        if not self.verify_code and not self.reset_token:
            raise ValueError("verify_code 与 reset_token 至少提供一个")
        return self


class ResetPasswordResponse(BaseModel):
    reset: bool


# ---- A9 修改密码 ----
class ChangePasswordRequest(BaseModel):
    old_password: str = Field(min_length=1)
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        return _validate_password_strength(value)


class ChangePasswordResponse(BaseModel):
    changed: bool


# ---- A10 更新个人资料 ----
class UpdateProfileRequest(BaseModel):
    """可编辑字段：姓名 / 手机号 / 科室。

    未提交的字段保持不变；提交空串表示清空（归一化为 `None`）。
    账号（`username` / `user_no`）与角色不在可改范围内（UI/UX §5.8.2）。
    """

    name: str | None = Field(default=None, max_length=64)
    phone: str | None = Field(default=None, max_length=20)
    department: str | None = Field(default=None, max_length=64)

    @field_validator("name", "department")
    @classmethod
    def _normalize_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if not _PHONE_RE.match(value):
            raise ValueError("手机号格式不正确")
        return value