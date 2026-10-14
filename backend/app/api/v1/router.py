"""v1 路由汇总注册（M0-1 / M1）。

后续模块按 M1~M6 顺序在此挂载对应子路由。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import health
from app.api.v1.endpoints import auth, diagnosis, face, inquiry, reports, tongue

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(tongue.router)
api_router.include_router(face.router)
api_router.include_router(inquiry.router)
api_router.include_router(diagnosis.router)
api_router.include_router(reports.router)