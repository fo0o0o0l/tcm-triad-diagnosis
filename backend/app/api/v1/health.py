"""系统类接口：健康检查（X2）。

不放在 business 模块中，供部署探针与联调自检使用。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter

from app.core.config import settings
from app.core.response import success

router = APIRouter(tags=["system"])

_DEPENDENCIES = ("postgres", "redis", "minio")


async def _check_postgres() -> str:
    try:
        import asyncpg  # 延迟导入：未安装/未启动时不影响应用启动

        conn = await asyncpg.connect(
            dsn=settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://"),
            timeout=3,
        )
        try:
            await conn.execute("SELECT 1")
        finally:
            await conn.close()
        return "up"
    except Exception:  # noqa: BLE001 - 探针需吞掉所有异常并降级上报
        return "down"


async def _check_redis() -> str:
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=3)
        try:
            await client.ping()
        finally:
            await client.aclose()
        return "up"
    except Exception:  # noqa: BLE001
        return "down"


async def _check_minio() -> str:
    try:
        import httpx

        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"{settings.S3_ENDPOINT}/minio/health/live")
        return "up" if resp.status_code == 200 else "down"
    except Exception:  # noqa: BLE001
        return "down"


async def _check_dependencies() -> dict[str, str]:
    """探测 PG / Redis / MinIO 连通性。未开启时统一返回 `skipped`。"""
    if not settings.HEALTH_CHECK_DEPENDENCIES:
        return {name: "skipped" for name in _DEPENDENCIES}

    results = await asyncio.gather(_check_postgres(), _check_redis(), _check_minio())
    return dict(zip(_DEPENDENCIES, results))


@router.get("/health", summary="健康检查")
async def health() -> dict:
    """返回服务状态与依赖连通性（统一响应体见 §4.1）。"""
    return success(
        {
            "status": "ok",
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "env": settings.APP_ENV,
            "time": datetime.now(timezone.utc).isoformat(),
            "dependencies": await _check_dependencies(),
        }
    )
