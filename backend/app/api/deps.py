"""FastAPI 依赖注入：当前用户与角色校验（《开发任务文档》M0-3 / §3 权限）。

认证契约：`Authorization: Bearer <access_token>`（§4.1 通用约定）。
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import ErrorCode
from app.core.response import BusinessError
from app.core.security import decode_token
from app.models.user import User, UserRole, UserStatus
from app.repositories.user import UserRepository

bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    """解析 Bearer 令牌并返回当前用户；缺失/失效/被禁用均抛 40100。"""
    if credentials is None or not credentials.credentials:
        raise BusinessError(ErrorCode.UNAUTHORIZED)

    claims = decode_token(credentials.credentials, expected_type="access")
    user = await UserRepository.get_by_id(db, int(claims["sub"]))
    if user is None:
        raise BusinessError(ErrorCode.UNAUTHORIZED)
    if user.status != UserStatus.ACTIVE:
        raise BusinessError(ErrorCode.UNAUTHORIZED, "账号已被禁用")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable[..., Coroutine[Any, Any, User]]:
    """角色校验依赖工厂：`Depends(require_roles(UserRole.ADMIN))` 无权限返回 40300。"""

    async def _guard(user: CurrentUser) -> User:
        if user.role not in roles:
            raise BusinessError(ErrorCode.FORBIDDEN)
        return user

    return _guard