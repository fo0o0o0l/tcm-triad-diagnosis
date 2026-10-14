"""统一响应与错误码单元测试（§4.1）。"""

from __future__ import annotations

import pytest

from app.core.errors import ErrorCode, default_message, http_status
from app.core.response import BusinessError, failure, success


@pytest.mark.parametrize(
    ("code", "expected_http"),
    [
        (ErrorCode.SUCCESS, 200),
        (ErrorCode.PARAM_INVALID, 400),
        (ErrorCode.UNAUTHORIZED, 401),
        (ErrorCode.FORBIDDEN, 403),
        (ErrorCode.NOT_FOUND, 404),
        (ErrorCode.CONFLICT, 409),
        (ErrorCode.IMAGE_QUALITY, 422),
        (ErrorCode.TOO_MANY_REQUESTS, 429),
        (ErrorCode.INTERNAL_ERROR, 500),
        (ErrorCode.ALGO_UNAVAILABLE, 503),
    ],
)
def test_error_code_http_mapping(code: ErrorCode, expected_http: int) -> None:
    assert http_status(code) == expected_http


def test_unknown_error_code_falls_back_to_500() -> None:
    assert http_status(99999) == 500


def test_success_response_shape() -> None:
    body = success({"a": 1})

    assert body["code"] == 0
    assert body["message"] == "ok"
    assert body["data"] == {"a": 1}
    assert set(body) == {"code", "message", "data", "trace_id"}


def test_failure_uses_default_message() -> None:
    body = failure(ErrorCode.NOT_FOUND)

    assert body["code"] == 40400
    assert body["message"] == default_message(ErrorCode.NOT_FOUND)
    assert body["data"] is None


def test_business_error_carries_http_status() -> None:
    with pytest.raises(BusinessError) as excinfo:
        raise BusinessError(ErrorCode.CONFLICT, "分析进行中")

    assert excinfo.value.code == 40901
    assert excinfo.value.http_status == 409
    assert excinfo.value.message == "分析进行中"


def test_business_error_allows_http_status_override() -> None:
    err = BusinessError(ErrorCode.IMAGE_QUALITY, http_code=200)

    assert err.http_status == 200
    assert err.code == 42201
