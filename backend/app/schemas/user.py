"""用户相关数据结构（《开发任务文档》§4.3 A1/A2/A5）。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.user import UserRole, UserStatus


class UserBrief(BaseModel):
    """登录响应中的用户简要信息（A2）。"""

    model_config = ConfigDict(from_attributes=True)

    user_no: str
    username: str
    name: str | None = None
    role: UserRole
    avatar_url: str | None = None


class UserStats(BaseModel):
    """个人中心统计（A5）。报告模块完成后填充真实值。"""

    total_reports: int = 0
    month_reports: int = 0


class UserProfile(BaseModel):
    """当前用户资料（A5 `GET /auth/me`）。"""

    model_config = ConfigDict(from_attributes=True)

    user_no: str
    username: str
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    role: UserRole
    status: UserStatus
    department: str | None = None
    avatar_url: str | None = None
    email_verified: bool = False
    created_at: datetime
    last_login_at: datetime | None = None
    stats: UserStats = UserStats()