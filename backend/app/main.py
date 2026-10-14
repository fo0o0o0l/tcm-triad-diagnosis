"""FastAPI 应用入口（开发任务文档 M0-1）。

职责：创建应用实例、注册中间件（CORS / trace_id）、注册全局异常处理器、
挂载 v1 路由。启动：`uvicorn app.main:app --reload --port 8000`
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import ERROR_CODE_BY_HTTP_STATUS, ErrorCode, http_status
from app.core.logging import configure_logging, get_logger
from app.core.middleware import TraceIdMiddleware
from app.core.response import BusinessError, failure

logger = get_logger(__name__)


def create_app() -> FastAPI:
    """应用工厂：便于测试用不同配置实例化。"""
    configure_logging(json_logs=not settings.DEBUG)

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="中医三诊合一分析系统后端 API（舌诊 / 面诊 / 问诊 / 合参 / 报告）",
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Trace-Id"],
    )
    # Starlette 中「后添加者更外层」，故 trace_id 中间件最后添加，保证最外层生效
    app.add_middleware(TraceIdMiddleware)

    _register_exception_handlers(app)

    app.include_router(api_router, prefix=settings.API_PREFIX)
    return app


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(BusinessError)
    async def handle_business_error(_request: Request, exc: BusinessError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.http_status,
            content=jsonable_encoder(failure(exc.code, exc.message, exc.data)),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=http_status(ErrorCode.PARAM_INVALID),
            content=jsonable_encoder(
                failure(
                    ErrorCode.PARAM_INVALID,
                    data={"errors": exc.errors()},
                )
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        _request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = ERROR_CODE_BY_HTTP_STATUS.get(exc.status_code, ErrorCode.INTERNAL_ERROR)
        return JSONResponse(
            status_code=exc.status_code,
            content=jsonable_encoder(failure(code, str(exc.detail))),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error", error=str(exc))
        return JSONResponse(
            status_code=http_status(ErrorCode.INTERNAL_ERROR),
            content=jsonable_encoder(failure(ErrorCode.INTERNAL_ERROR)),
        )


app: FastAPI = create_app()
