"""用户与鉴权数据访问层（Repository）。

职责：仅封装 SQL 读写，不含业务规则；事务由调用方（service）控制。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import (
    PasswordResetToken,
    RefreshToken,
    User,
    VerificationCode,
)


class UserRepository:
    """`users` 表读写。"""

    @staticmethod
    async def get_by_id(db: AsyncSession, user_id: int) -> User | None:
        stmt = select(User).where(User.id == user_id, User.deleted_at.is_(None))
        return await db.scalar(stmt)

    @staticmethod
    async def get_by_username(db: AsyncSession, username: str) -> User | None:
        stmt = select(User).where(User.username == username, User.deleted_at.is_(None))
        return await db.scalar(stmt)

    @staticmethod
    async def get_by_account(db: AsyncSession, account: str) -> User | None:
        """按用户名 / 邮箱 / 手机号匹配账号（A2 登录、A7/A8 找回）。"""
        stmt = select(User).where(
            User.deleted_at.is_(None),
            (User.username == account) | (User.email == account) | (User.phone == account),
        )
        return await db.scalar(stmt)

    @staticmethod
    async def exists_username(db: AsyncSession, username: str) -> bool:
        stmt = select(User.id).where(User.username == username)
        return await db.scalar(stmt) is not None

    @staticmethod
    async def exists_email(db: AsyncSession, email: str) -> bool:
        stmt = select(User.id).where(User.email == email)
        return await db.scalar(stmt) is not None

    @staticmethod
    async def exists_phone(db: AsyncSession, phone: str) -> bool:
        stmt = select(User.id).where(User.phone == phone)
        return await db.scalar(stmt) is not None

    @staticmethod
    async def get_by_phone(db: AsyncSession, phone: str) -> User | None:
        stmt = select(User).where(User.phone == phone, User.deleted_at.is_(None))
        return await db.scalar(stmt)

    @staticmethod
    async def create(db: AsyncSession, user: User) -> User:
        """插入用户；`user_no` 依赖自增 id，flush 后回填（如 `d_10086`）。"""
        user.user_no = f"tmp_{uuid.uuid4().hex[:24]}"
        db.add(user)
        await db.flush()
        user.user_no = f"d_{user.id}"
        await db.flush()
        # 回填 server_default 生成的 created_at/role/status 等字段
        await db.refresh(user)
        return user

    @staticmethod
    async def touch_last_login(db: AsyncSession, user_id: int) -> None:
        await db.execute(
            update(User)
            .where(User.id == user_id)
            .values(last_login_at=datetime.now(timezone.utc))
        )

    @staticmethod
    async def update_password_hash(db: AsyncSession, user_id: int, password_hash: str) -> None:
        await db.execute(
            update(User).where(User.id == user_id).values(password_hash=password_hash)
        )

    @staticmethod
    async def update_profile(db: AsyncSession, user_id: int, fields: dict[str, object]) -> None:
        """按提交的字段做局部更新；空字典直接返回（避免误清空未提交字段）。"""
        if not fields:
            return
        await db.execute(update(User).where(User.id == user_id).values(**fields))

    @staticmethod
    async def update_avatar_ref(db: AsyncSession, user_id: int, avatar_ref: str | None) -> None:
        await db.execute(
            update(User).where(User.id == user_id).values(avatar_ref=avatar_ref)
        )


class RefreshTokenRepository:
    """`refresh_tokens` 表读写（只存摘要，支持旋转与吊销）。"""

    @staticmethod
    async def create(
        db: AsyncSession,
        *,
        user_id: int,
        token_hash: str,
        expires_at: datetime,
        device_info: str | None = None,
        ip: str | None = None,
    ) -> RefreshToken:
        record = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
            device_info=device_info,
            ip=ip,
        )
        db.add(record)
        await db.flush()
        return record

    @staticmethod
    async def get_active_by_hash(db: AsyncSession, token_hash: str) -> RefreshToken | None:
        stmt = select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked_at.is_(None),
        )
        return await db.scalar(stmt)

    @staticmethod
    async def revoke(db: AsyncSession, token_hash: str) -> bool:
        """吊销指定刷新令牌，返回是否命中未吊销记录。"""
        result = await db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(timezone.utc))
        )
        return result.rowcount > 0

    @staticmethod
    async def revoke_all_for_user(db: AsyncSession, user_id: int) -> int:
        """吊销某用户全部有效刷新令牌（重置 / 修改密码后）。"""
        result = await db.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(timezone.utc))
        )
        return result.rowcount


class VerificationCodeRepository:
    """`verification_codes` 表读写。"""

    @staticmethod
    async def create(
        db: AsyncSession,
        *,
        target: str,
        scene: str,
        code_hash: str,
        expires_at: datetime,
    ) -> VerificationCode:
        record = VerificationCode(
            target=target, scene=scene, code_hash=code_hash, expires_at=expires_at
        )
        db.add(record)
        await db.flush()
        return record

    @staticmethod
    async def get_latest_active(
        db: AsyncSession, *, target: str, scene: str
    ) -> VerificationCode | None:
        stmt = (
            select(VerificationCode)
            .where(
                VerificationCode.target == target,
                VerificationCode.scene == scene,
                VerificationCode.used_at.is_(None),
            )
            .order_by(VerificationCode.created_at.desc())
            .limit(1)
        )
        return await db.scalar(stmt)

    @staticmethod
    async def mark_used(db: AsyncSession, code_id: int) -> None:
        await db.execute(
            update(VerificationCode)
            .where(VerificationCode.id == code_id)
            .values(used_at=datetime.now(timezone.utc))
        )


class PasswordResetTokenRepository:
    """`password_reset_tokens` 表读写。"""

    @staticmethod
    async def create(
        db: AsyncSession,
        *,
        user_id: int,
        token_hash: str,
        expires_at: datetime,
    ) -> PasswordResetToken:
        record = PasswordResetToken(
            user_id=user_id, token_hash=token_hash, expires_at=expires_at
        )
        db.add(record)
        await db.flush()
        return record

    @staticmethod
    async def get_active_by_hash(db: AsyncSession, token_hash: str) -> PasswordResetToken | None:
        stmt = select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used_at.is_(None),
        )
        return await db.scalar(stmt)

    @staticmethod
    async def mark_used(db: AsyncSession, token_id: int) -> None:
        await db.execute(
            update(PasswordResetToken)
            .where(PasswordResetToken.id == token_id)
            .values(used_at=datetime.now(timezone.utc))
        )