"""数据库连接与会话管理（《开发任务文档》M0-2 / M1-1）。

- `engine`：进程内单例异步引擎（懒连接，导入时不触发网络）。
- `AsyncSessionLocal`：会话工厂，`expire_on_commit=False` 便于提交后继续读取属性。
- `get_db`：FastAPI 依赖，按请求提供会话并保证异常回滚。

迁移由 Alembic 管理（`backend/migrations/`），应用启动不自动建表：
`alembic upgrade head`。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    """所有 ORM 模型的声明式基类，供 Alembic autogenerate 采集元数据。"""


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """请求级数据库会话依赖。"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise