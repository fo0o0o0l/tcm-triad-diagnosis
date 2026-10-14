"""工程骨架自检：健康检查、统一响应体、trace_id（对应 §2.7 联调自检清单 #1/#4）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings

HEALTH_URL = "/api/v1/health"


def test_health_returns_unified_response(client: TestClient) -> None:
    resp = client.get(HEALTH_URL)

    assert resp.status_code == 200
    body = resp.json()
    # 统一响应结构：{code, message, data, trace_id}
    assert set(body) == {"code", "message", "data", "trace_id"}
    assert body["code"] == 0
    assert body["message"] == "ok"


def test_health_reports_service_metadata(client: TestClient) -> None:
    data = client.get(HEALTH_URL).json()["data"]

    assert data["status"] == "ok"
    assert data["env"] == "dev"
    assert data["version"]
    assert "time" in data


def test_health_dependencies_skipped_without_infra(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """关闭依赖探测时（`HEALTH_CHECK_DEPENDENCIES=false`），依赖项应标记为 skipped。"""
    monkeypatch.setattr(settings, "HEALTH_CHECK_DEPENDENCIES", False)
    dependencies = client.get(HEALTH_URL).json()["data"]["dependencies"]

    assert set(dependencies) == {"postgres", "redis", "minio"}
    assert set(dependencies.values()) == {"skipped"}


def test_trace_id_is_generated_and_returned_in_header(client: TestClient) -> None:
    resp = client.get(HEALTH_URL)

    trace_id = resp.headers.get("X-Trace-Id")
    assert trace_id and len(trace_id) == 8
    # 响应体与响应头使用同一个 trace_id
    assert resp.json()["trace_id"] == trace_id


def test_incoming_trace_id_is_reused(client: TestClient) -> None:
    resp = client.get(HEALTH_URL, headers={"X-Trace-Id": "deadbeef"})

    assert resp.headers["X-Trace-Id"] == "deadbeef"
    assert resp.json()["trace_id"] == "deadbeef"


def test_unknown_route_uses_unified_error_response(client: TestClient) -> None:
    resp = client.get("/api/v1/not-exist")

    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == 40400
    assert set(body) == {"code", "message", "data", "trace_id"}


def test_openapi_schema_available(client: TestClient) -> None:
    """自动 OpenAPI 文档可用（§2.4：访问 /docs 查看）。"""
    resp = client.get("/openapi.json")

    assert resp.status_code == 200
    assert HEALTH_URL in resp.json()["paths"]
