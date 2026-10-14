"""统一响应体与业务异常（《开发任务文档》§4.1）。

所有接口返回：`{ "code": 0, "message": "ok", "data": {...}, "trace_id": "a1b2c3d4" }`
"""

from __future__ import annotations

from typing import Any

from .errors import ErrorCode, default_message, http_status
from .logging import get_trace_id


class BusinessError(Exception):
    """可预期的业务异常，由全局异常处理器转换为统一响应体。"""

    def __init__(
        self,
        code: ErrorCode | int = ErrorCode.INTERNAL_ERROR,
        message: str | None = None,
        data: Any = None,
        *,
        http_code: int | None = None,
    ) -> None:
        self.code = int(code)
        self.message = message or default_message(self.code)
        self.data = data
        self.http_status = http_code or http_status(self.code)
        super().__init__(self.message)


def success(data: Any = None, message: str = "ok") -> dict[str, Any]:
    """构造成功响应体。"""
    return {
        "code": int(ErrorCode.SUCCESS),
        "message": message,
        "data": data,
        "trace_id": get_trace_id(),
    }


def failure(
    code: ErrorCode | int = ErrorCode.INTERNAL_ERROR,
    message: str | None = None,
    data: Any = None,
) -> dict[str, Any]:
    """构造失败响应体。"""
    code_int = int(code)
    return {
        "code": code_int,
        "message": message or default_message(code_int),
        "data": data,
        "trace_id": get_trace_id(),
    }
