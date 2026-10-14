"""统一错误码（《开发任务文档》§4.1，与 PRD §9 一致）。"""

from __future__ import annotations

from enum import IntEnum


class ErrorCode(IntEnum):
    """业务错误码。`code == 0` 表示成功。"""

    SUCCESS = 0
    PARAM_INVALID = 40001
    UNAUTHORIZED = 40100
    FORBIDDEN = 40300
    NOT_FOUND = 40400
    CONFLICT = 40901
    IMAGE_QUALITY = 42201
    TOO_MANY_REQUESTS = 42900
    INTERNAL_ERROR = 50000
    ALGO_UNAVAILABLE = 50300


#: 业务错误码 → HTTP 状态码
HTTP_STATUS_BY_CODE: dict[int, int] = {
    ErrorCode.SUCCESS: 200,
    ErrorCode.PARAM_INVALID: 400,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.CONFLICT: 409,
    ErrorCode.IMAGE_QUALITY: 422,
    ErrorCode.TOO_MANY_REQUESTS: 429,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.ALGO_UNAVAILABLE: 503,
}

#: HTTP 状态码 → 业务错误码（框架层异常兜底映射）
ERROR_CODE_BY_HTTP_STATUS: dict[int, ErrorCode] = {
    400: ErrorCode.PARAM_INVALID,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    409: ErrorCode.CONFLICT,
    422: ErrorCode.PARAM_INVALID,
    429: ErrorCode.TOO_MANY_REQUESTS,
    500: ErrorCode.INTERNAL_ERROR,
    503: ErrorCode.ALGO_UNAVAILABLE,
}

DEFAULT_MESSAGES: dict[int, str] = {
    ErrorCode.SUCCESS: "ok",
    ErrorCode.PARAM_INVALID: "参数校验失败",
    ErrorCode.UNAUTHORIZED: "未认证或令牌失效",
    ErrorCode.FORBIDDEN: "无权限访问该资源",
    ErrorCode.NOT_FOUND: "资源不存在",
    ErrorCode.CONFLICT: "状态冲突",
    ErrorCode.IMAGE_QUALITY: "图像质量不达标",
    ErrorCode.TOO_MANY_REQUESTS: "请求过于频繁",
    ErrorCode.INTERNAL_ERROR: "服务内部错误",
    ErrorCode.ALGO_UNAVAILABLE: "算法服务不可用",
}


def http_status(code: int | ErrorCode) -> int:
    """业务错误码对应的 HTTP 状态码，未知错误码按 500 处理。"""
    return HTTP_STATUS_BY_CODE.get(int(code), 500)


def default_message(code: int | ErrorCode) -> str:
    """业务错误码的默认中文提示。"""
    return DEFAULT_MESSAGES.get(int(code), "服务内部错误")
