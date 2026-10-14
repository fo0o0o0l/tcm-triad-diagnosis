"""报告对比端到端用例（P8 数据对比页 R-CMP；UI/UX §5.7）。

覆盖：同患者两份报告的特征/健康/结论变化判定与置信度趋势、跨患者阻断、
参数校验（同号 / 趋势范围）、未软删校验与登录态。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.diagnosis import HealthLevel, Report, ReportStatus
from app.services import auth as auth_service

API = "/api/v1"
FIXED_CODE = "123456"
PASSWORD = "Abc@123456"
USERNAME = "compare_doc"
EMAIL = "compare_doc@example.com"


@pytest.fixture(autouse=True)
def _stub_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_service, "generate_numeric_code", lambda length=6: FIXED_CODE)

    async def _noop(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(auth_service, "_dispatch_code", _noop)


@pytest_asyncio.fixture
async def headers(api_client: AsyncClient) -> dict[str, str]:
    await api_client.post(
        f"{API}/auth/verify-code",
        json={"target": EMAIL, "scene": "register", "channel": "email"},
    )
    await api_client.post(
        f"{API}/auth/register",
        json={
            "username": USERNAME,
            "password": PASSWORD,
            "name": "对比医师",
            "email": EMAIL,
            "verify_code": FIXED_CODE,
        },
    )
    resp = await api_client.post(
        f"{API}/auth/login",
        json={"account": USERNAME, "password": PASSWORD, "remember": False},
    )
    return {"Authorization": f"Bearer {resp.json()['data']['access_token']}"}


def _feature(name: str, label: str, confidence: float = 0.8) -> dict:
    return {"name": name, "label": label, "confidence": confidence}


def _seed_report(
    report_no: str,
    session_id: str,
    *,
    name: str,
    generated_at: datetime,
    health_level: HealthLevel,
    confidence: float,
    conclusion: str,
    tongue_features: list[dict],
    face_features: list[dict],
    answers: dict | None = None,
    deleted: bool = False,
) -> Report:
    """直接落一条带 `report_data` 的报告，用于对比用例（绕过合参）。"""
    report_data = {
        "overview": {"conclusions": [{"text": conclusion, "confidence": confidence}]},
        "details": {
            "tongue": {"features": tongue_features},
            "face": {"features": face_features},
            "inquiry": {"answers": answers or {}},
        },
    }
    return Report(
        report_no=report_no,
        session_id=session_id,
        status=ReportStatus.FINAL,
        patient_snapshot={"name": name, "anonymous": False},
        overall_confidence=confidence,
        health_level=health_level,
        summary=conclusion,
        report_data=report_data,
        generated_at=generated_at,
        deleted_at=generated_at if deleted else None,
    )


async def _seed_pair(db: AsyncSession, name: str) -> tuple[str, str]:
    """播种同患者两次报告（较近 vs 较早），返回 (较早, 较近) 报告号。"""
    token = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    early, late = f"r_e{token}", f"r_l{token}"
    db.add_all(
        [
            _seed_report(
                early,
                f"s_{token}_1",
                name=name,
                generated_at=now - timedelta(days=20),
                health_level=HealthLevel.FAIR,
                confidence=0.72,
                conclusion="脾虚湿盛，兼有寒象",
                tongue_features=[_feature("tongue_color", "淡白"), _feature("coating_color", "白")],
                face_features=[_feature("acne", "中等"), _feature("spots", "无")],
                answers={"sleep": ["多梦"]},
            ),
            _seed_report(
                late,
                f"s_{token}_2",
                name=name,
                generated_at=now,
                health_level=HealthLevel.GOOD,
                confidence=0.9,
                conclusion="气虚为主（寒象减轻）",
                tongue_features=[_feature("tongue_color", "淡红"), _feature("coating_color", "白")],
                face_features=[_feature("acne", "无"), _feature("spots", "无")],
                answers={"sleep": ["正常"]},
            ),
        ]
    )
    await db.commit()
    return early, late


async def test_compare_same_patient_changes(
    api_client: AsyncClient, headers: dict[str, str], db_session: AsyncSession
) -> None:
    name = f"对比患者{uuid.uuid4().hex[:8]}"
    early, late = await _seed_pair(db_session, name)

    resp = await api_client.get(
        f"{API}/reports/compare?base={early}&target={late}", headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    data = body["data"]

    assert data["base"]["report_id"] == early
    assert data["target"]["report_id"] == late
    assert data["base"]["anonymous"] is False

    # 健康状态：一般 → 健康 = 改善
    assert data["health"]["base_level"] == "fair"
    assert data["health"]["target_level"] == "good"
    assert data["health"]["direction"] == "improved"

    # 特征对比：舌色 淡白→淡红 改善；痘痘 中等→无 改善；苔色持平
    modules = {item["module"]: item for item in data["modules"]}
    tongue = {item["name"]: item for item in modules["tongue"]["items"]}
    assert tongue["tongue_color"]["direction"] == "improved"
    assert tongue["tongue_color"]["changed"] is True
    assert tongue["coating_color"]["direction"] == "same"
    assert tongue["coating_color"]["changed"] is False

    face = {item["name"]: item for item in modules["face"]["items"]}
    assert face["acne"]["direction"] == "improved"

    # 问诊症状：睡眠 多梦→正常，标注为“有变化”（方向不臆断）
    inquiry = {item["name"]: item for item in modules["inquiry"]["items"]}
    assert inquiry["sleep"]["changed"] is True
    assert inquiry["sleep"]["direction"] == "unknown"

    # 综合结论：本次新增、上次移除
    assert data["conclusions"]["target_texts"] == ["气虚为主（寒象减轻）"]
    assert data["conclusions"]["added"] == ["气虚为主（寒象减轻）"]
    assert data["conclusions"]["removed"] == ["脾虚湿盛，兼有寒象"]

    # 置信度趋势：同患者按时间升序，base/target 角色标注正确
    trend = data["trend"]
    assert len(trend) >= 2
    assert trend[0]["report_id"] == early and trend[0]["role"] == "base"
    assert trend[-1]["report_id"] == late and trend[-1]["role"] == "target"
    assert trend[0]["overall_confidence"] < trend[-1]["overall_confidence"]


async def test_compare_rejects_cross_patient(
    api_client: AsyncClient, headers: dict[str, str], db_session: AsyncSession
) -> None:
    _, late = await _seed_pair(db_session, f"患者甲{uuid.uuid4().hex[:8]}")
    token = uuid.uuid4().hex[:8]
    other = f"r_o{token}"
    db_session.add(
        _seed_report(
            other,
            f"s_{token}_o",
            name=f"患者乙{token}",
            generated_at=datetime.now(timezone.utc),
            health_level=HealthLevel.FAIR,
            confidence=0.75,
            conclusion="阴虚内热",
            tongue_features=[_feature("tongue_color", "红")],
            face_features=[_feature("acne", "无")],
        )
    )
    await db_session.commit()

    resp = await api_client.get(
        f"{API}/reports/compare?base={late}&target={other}", headers=headers
    )
    assert resp.json()["code"] == 40001


async def test_compare_param_validation(
    api_client: AsyncClient, headers: dict[str, str], db_session: AsyncSession
) -> None:
    early, late = await _seed_pair(db_session, f"参数患者{uuid.uuid4().hex[:8]}")

    same = await api_client.get(
        f"{API}/reports/compare?base={early}&target={early}", headers=headers
    )
    assert same.json()["code"] == 40001

    out_of_range = await api_client.get(
        f"{API}/reports/compare?base={early}&target={late}&trend=1", headers=headers
    )
    assert out_of_range.json()["code"] == 40001


async def test_compare_unknown_report_404(
    api_client: AsyncClient, headers: dict[str, str], db_session: AsyncSession
) -> None:
    _, late = await _seed_pair(db_session, f"缺失患者{uuid.uuid4().hex[:8]}")
    resp = await api_client.get(
        f"{API}/reports/compare?base=r_9999&target={late}", headers=headers
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == 40400


async def test_compare_requires_auth(api_client: AsyncClient) -> None:
    resp = await api_client.get(f"{API}/reports/compare?base=r_1&target=r_2")
    assert resp.status_code == 401
