"""安全工具：密码哈希、JWT 签发/校验、令牌与验证码摘要（《开发任务文档》M0-3）。

说明：`passlib 1.7.4` 与 `bcrypt 5.x` 不兼容（读取 `bcrypt.__about__` 失败），
故直接使用 `bcrypt` 库；bcrypt 单次输入上限 72 字节，超长口令先截断。
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings
from app.core.errors import ErrorCode
from app.core.response import BusinessError

TokenType = Literal["access", "refresh"]

_BCRYPT_MAX_BYTES = 72


# ---- 密码 ----
def hash_password(password: str) -> str:
    """使用 bcrypt 生成密码哈希（rounds 取自配置）。"""
    raw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=settings.PASSWORD_HASH_ROUNDS)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    """校验明文密码与哈希是否匹配（异常一律视为不匹配）。"""
    raw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    try:
        return bcrypt.checkpw(raw, password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


# ---- 摘要（刷新令牌 / 重置令牌 / 验证码）----
def hash_token(value: str) -> str:
    """把令牌或验证码转为不可逆摘要后入库（不落明文）。"""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def generate_numeric_code(length: int = 6) -> str:
    """生成定长数字验证码。"""
    return "".join(secrets.choice("0123456789") for _ in range(length))


def generate_urlsafe_token(nbytes: int = 32) -> str:
    """生成 URL 安全的随机令牌（用于密码重置链接）。"""
    return secrets.token_urlsafe(nbytes)


# ---- JWT ----
def _create_token(subject: str | int, token_type: TokenType, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def access_expire_delta() -> timedelta:
    return timedelta(minutes=settings.JWT_ACCESS_EXPIRE_MINUTES)


def refresh_expire_delta(*, remember: bool = False) -> timedelta:
    """刷新令牌有效期；`remember` 时按配置的长效值（UI/UX §5.1.4）。"""
    return timedelta(days=settings.JWT_REFRESH_EXPIRE_DAYS)


def create_access_token(user_id: int) -> str:
    return _create_token(user_id, "access", access_expire_delta())


def create_refresh_token(user_id: int, *, remember: bool = False) -> str:
    return _create_token(user_id, "refresh", refresh_expire_delta(remember=remember))


def decode_token(token: str, *, expected_type: TokenType | None = None) -> dict[str, Any]:
    """解码并校验 JWT；失败或类型不符时抛出 40100 业务异常。"""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:  # 过期 / 签名错误 / 格式错误
        raise BusinessError(ErrorCode.UNAUTHORIZED) from exc

    if expected_type is not None and payload.get("type") != expected_type:
        raise BusinessError(ErrorCode.UNAUTHORIZED)
    if not payload.get("sub"):
        raise BusinessError(ErrorCode.UNAUTHORIZED)
    return payload