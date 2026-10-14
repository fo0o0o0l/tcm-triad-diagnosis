"""结构化日志与 trace_id 上下文（开发任务文档 M0-1）。

trace_id 通过 `contextvars` 在单次请求内贯穿：中间件写入 → 日志与响应体读取，
保证 `{code, message, data, trace_id}` 与日志可相互回溯。
"""

from __future__ import annotations

import contextvars
import logging
import sys
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import structlog

from app.core.config import settings

_trace_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="-")


def new_trace_id() -> str:
    """生成 8 位短 trace_id（§4.1 示例格式：a1b2c3d4）。"""
    return uuid.uuid4().hex[:8]


def set_trace_id(trace_id: str) -> contextvars.Token[str]:
    """写入当前上下文 trace_id，返回用于还原的 token。"""
    return _trace_id_ctx.set(trace_id)


def reset_trace_id(token: contextvars.Token[str]) -> None:
    _trace_id_ctx.reset(token)


def get_trace_id() -> str:
    """读取当前上下文 trace_id（无请求上下文时为 `-`）。"""
    return _trace_id_ctx.get()


def _add_trace_id(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    event_dict["trace_id"] = get_trace_id()
    return event_dict


def _log_file() -> Path:
    """日志文件路径（目录不存在时自动创建）。"""
    directory = Path(settings.LOG_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / settings.LOG_FILE


def configure_logging(*, level: int = logging.INFO, json_logs: bool = False) -> None:
    """初始化日志：终端输出 + 同步落盘滚动文件。

    structlog 经 stdlib 集成输出，使结构化事件（带 `trace_id`）与 uvicorn 访问
    日志复用同一组 handler，二者一并落盘，便于长期回溯；开发期终端渲染为可读
    文本，生产（`DEBUG=false`）渲染为 JSON。
    """
    renderer: Any = (
        structlog.processors.JSONRenderer(ensure_ascii=False)
        if json_logs
        else structlog.dev.ConsoleRenderer()
    )
    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_trace_id,
    ]
    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if settings.LOG_TO_FILE:
        handlers.append(
            RotatingFileHandler(
                _log_file(),
                maxBytes=settings.LOG_MAX_BYTES,
                backupCount=settings.LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
        )
    for handler in handlers:
        handler.setFormatter(formatter)

    logging.basicConfig(level=level, handlers=handlers, force=True)

    # uvicorn 自带 logger 默认不向 root 传播，需显式挂同一组 handler，
    # 否则访问日志只进终端、不进日志文件。
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = list(handlers)
        uvicorn_logger.propagate = False


def get_logger(name: str | None = None) -> Any:
    """获取带 trace_id 的结构化 logger。"""
    return structlog.get_logger(name)
