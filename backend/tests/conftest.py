"""pytest 公共夹具。

- `client`：同步 TestClient（无需数据库，用于健康检查 / 统一响应等骨架自检）。
- `db_session` / `api_client`：异步夹具，为认证等数据库相关用例提供
  「外层事务 + 保存点」隔离会话，每个用例结束回滚，互不污染。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.database import Base, get_db
from app.main import app


@pytest.fixture(scope="session")
def client() -> TestClient:
    """进程内测试客户端（无需启动 uvicorn）。"""
    with TestClient(app) as test_client:
        yield test_client


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """独立引擎 + 外层事务，用例结束整体回滚。"""
    engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )
    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()
        await engine.dispose()


@pytest_asyncio.fixture
async def api_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """以 ASGI 传输的异步 HTTP 客户端，并注入与用例共享的数据库会话。"""

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _reset_login_limiter() -> None:
    """登录限流为进程内状态，用例间需清空避免相互影响。"""
    from app.services import auth as auth_service

    auth_service._limiter._failures.clear()