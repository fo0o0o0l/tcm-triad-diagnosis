"""报告管理端到端用例（M6：R3 导出 PDF / R4 历史查询 / R5 归档 / R6 删除；PRD §6.5）。

覆盖：合参完成自动建档、G2 回填 report_id/status、PDF 下载（Content-Type/文件名/魔数）、
归档状态流转与幂等、未知报告 404、未登录 401；
R4 报告历史的分页结构、患者/关键词（多词 AND）/时间/匿名/状态过滤与分页参数校验；
R6 软删后详情/PDF 不可访问、重复删除 404、历史列表不再返回。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.diagnosis import (
    AnalysisStatus,
    FaceAnalysis,
    FaceRecord,
    HealthLevel,
    ImageSource,
    InquiryAnalysis,
    InquiryRecord,
    ModuleStatus,
    Report,
    ReportStatus,
    TongueAnalysis,
    TongueRecord,
)
from app.services import auth as auth_service
from app.services import integrated_ai_analysis

API = "/api/v1"
FIXED_CODE = "123456"
PASSWORD = "Abc@123456"
USERNAME = "report_doc"
EMAIL = "report_doc@example.com"


@pytest.fixture(autouse=True)
def _stub_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_service, "generate_numeric_code", lambda length=6: FIXED_CODE)

    async def _noop(*_args: object, **_kwargs: object) -> None:
        return None

    async def _no_algo(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(auth_service, "_dispatch_code", _noop)
    monkeypatch.setattr(integrated_ai_analysis, "_call_algo", _no_algo)


@pytest_asyncio.fixture
async def use_test_session(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    """让后台合参/建报任务复用用例事务会话。"""

    class _Ctx:
        async def __aenter__(self) -> object:
            return db_session

        async def __aexit__(self, *_exc: object) -> bool:
            return False

    monkeypatch.setattr(integrated_ai_analysis, "AsyncSessionLocal", lambda: _Ctx())


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
            "name": "报告医师",
            "email": EMAIL,
            "verify_code": FIXED_CODE,
        },
    )
    resp = await api_client.post(
        f"{API}/auth/login",
        json={"account": USERNAME, "password": PASSWORD, "remember": False},
    )
    return {"Authorization": f"Bearer {resp.json()['data']['access_token']}"}


async def _seed_and_run_fusion(
    api_client: AsyncClient,
    db: AsyncSession,
    headers: dict[str, str],
    session_id: str,
) -> dict:
    """落三诊数据 → 触发合参（后台自动建档）→ 返回 G2 结果 data。"""
    token = uuid.uuid4().hex[:8]

    tongue = TongueRecord(
        record_no=f"t_{token}",
        session_id=session_id,
        source=ImageSource.UPLOAD,
        image_ref=f"tongue/{session_id}/raw.png",
        quality_passed=True,
        features=[
            {"name": "tongue_color", "label": "淡红", "confidence": 0.85},
            {"name": "coating_color", "label": "白", "confidence": 0.86},
            {"name": "coating_texture", "label": "薄", "confidence": 0.80},
            {"name": "tongue_shape", "label": "正常", "confidence": 0.76},
        ],
        overall_confidence=0.84,
    )
    db.add(tongue)
    await db.flush()
    db.add(
        TongueAnalysis(
            analysis_no=f"ta_{token}",
            record_id=tongue.id,
            status=AnalysisStatus.COMPLETED,
            tongue_summary="舌质淡红，舌苔白薄。",
            main_syndrome={"name": "脾气虚证", "confidence": 0.84},
            secondary_syndromes=[],
            treatment_principles=["健脾益气"],
            recommendations=[],
            is_current=True,
        )
    )

    face = FaceRecord(
        record_no=f"f_{token}",
        session_id=session_id,
        source=ImageSource.UPLOAD,
        image_ref=f"face/{session_id}/raw.png",
        quality_passed=True,
        features=[
            {"name": "face_color", "label": "红润", "confidence": 0.84},
            {"name": "luster", "label": "有光泽", "confidence": 0.80},
            {"name": "acne", "label": "无", "confidence": 0.86},
            {"name": "spots", "label": "无", "confidence": 0.86},
        ],
        overall_confidence=0.82,
    )
    db.add(face)
    await db.flush()
    db.add(
        FaceAnalysis(
            analysis_no=f"fa_{token}",
            record_id=face.id,
            status=AnalysisStatus.COMPLETED,
            face_summary="面色红润，皮肤有光泽。",
            main_syndrome={"name": "气血充足", "confidence": 0.78},
            secondary_syndromes=[],
            treatment_principles=["调和气血"],
            recommendations=[],
            is_current=True,
        )
    )

    inquiry = InquiryRecord(
        record_no=f"q_{token}",
        session_id=session_id,
        template_version="inquiry_v1",
        patient_snapshot={"name": "张三", "gender": "女", "age": 34, "height": 165, "weight": 58},
        answers={"chief_complaint": "乏力、畏寒", "cold_heat": ["怕冷畏寒"]},
        missing_items=[],
        status=ModuleStatus.ANALYZED,
    )
    db.add(inquiry)
    await db.flush()
    db.add(
        InquiryAnalysis(
            analysis_no=f"ia_{token}",
            record_id=inquiry.id,
            status=AnalysisStatus.COMPLETED,
            symptoms_summary="主诉乏力、畏寒。",
            main_syndrome={"name": "阳虚证", "confidence": 0.82},
            secondary_syndromes=[],
            treatment_principles=["温阳散寒"],
            recommendations=[],
            is_current=True,
        )
    )
    await db.commit()

    await api_client.post(f"{API}/sessions/{session_id}/fusion/analyze", headers=headers, json={})
    return (
        await api_client.get(f"{API}/sessions/{session_id}/fusion/result", headers=headers)
    ).json()["data"]


async def test_fusion_result_exposes_report_id(
    api_client: AsyncClient,
    headers: dict[str, str],
    db_session: AsyncSession,
    use_test_session: None,
) -> None:
    data = await _seed_and_run_fusion(api_client, db_session, headers, "s_report_auto")
    assert data["status"] == "completed"
    assert data["report_id"] and data["report_id"].startswith("r_")
    assert data["report_status"] == "final"
    assert data["report"]["header"]["session_id"] == "s_report_auto"


async def test_export_pdf(
    api_client: AsyncClient,
    headers: dict[str, str],
    db_session: AsyncSession,
    use_test_session: None,
) -> None:
    data = await _seed_and_run_fusion(api_client, db_session, headers, "s_report_pdf")
    report_id = data["report_id"]

    resp = await api_client.get(f"{API}/reports/{report_id}/pdf", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/pdf")
    assert resp.content[:5] == b"%PDF-"
    assert len(resp.content) > 1000
    disposition = resp.headers.get("content-disposition", "")
    assert "attachment" in disposition
    assert "2026" in disposition  # 文件名含 yyyyMMdd


async def test_archive_report_flow(
    api_client: AsyncClient,
    headers: dict[str, str],
    db_session: AsyncSession,
    use_test_session: None,
) -> None:
    data = await _seed_and_run_fusion(api_client, db_session, headers, "s_report_archive")
    report_id = data["report_id"]

    archived = (
        await api_client.post(f"{API}/reports/{report_id}/archive", headers=headers)
    ).json()
    assert archived["code"] == 0
    assert archived["data"]["status"] == "archived"
    assert archived["data"]["archived_at"] is not None

    # 幂等：重复归档不报错且状态保持
    again = (await api_client.post(f"{API}/reports/{report_id}/archive", headers=headers)).json()
    assert again["data"]["status"] == "archived"

    # 归档后 PDF 仍可下载；G2 回填归档状态
    pdf = await api_client.get(f"{API}/reports/{report_id}/pdf", headers=headers)
    assert pdf.status_code == 200
    result = (
        await api_client.get(f"{API}/sessions/s_report_archive/fusion/result", headers=headers)
    ).json()["data"]
    assert result["report_status"] == "archived"


async def test_pdf_unknown_report_returns_404(
    api_client: AsyncClient, headers: dict[str, str]
) -> None:
    resp = await api_client.get(f"{API}/reports/r_9999/pdf", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["code"] == 40400


async def test_report_endpoints_require_auth(api_client: AsyncClient) -> None:
    pdf = await api_client.get(f"{API}/reports/r_1/pdf")
    assert pdf.status_code == 401
    archive = await api_client.post(f"{API}/reports/r_1/archive")
    assert archive.status_code == 401


# ===== R4 报告历史查询 =====
def _seed_report(
    token: str,
    session_id: str,
    *,
    name: str,
    summary: str,
    generated_at: datetime,
    anonymous: bool = False,
    status: ReportStatus = ReportStatus.FINAL,
) -> Report:
    """直接落一条报告（绕过合参），用于历史检索用例。"""
    return Report(
        report_no=f"r_{token}",
        session_id=session_id,
        status=status,
        patient_snapshot={"name": name, "anonymous": anonymous},
        overall_confidence=0.8,
        health_level=HealthLevel.FAIR,
        summary=summary,
        report_data={},
        generated_at=generated_at,
    )


async def test_report_history_pagination(
    api_client: AsyncClient, headers: dict[str, str], db_session: AsyncSession
) -> None:
    # 真实库存在历史数据，用例用唯一 token 隔离自己播种的记录
    token = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            _seed_report(
                f"h1{token}", f"s_{token}_1", name=f"张三{token}",
                summary=f"{token} 气虚为主，兼有寒象", generated_at=now,
            ),
            _seed_report(
                f"h2{token}", f"s_{token}_2", name=f"李四{token}",
                summary=f"{token} 脾虚湿盛", generated_at=now - timedelta(days=1),
            ),
            _seed_report(
                f"h3{token}", f"s_{token}_3", name=f"王五{token}",
                summary=f"{token} 阴虚内热", generated_at=now - timedelta(days=2),
            ),
        ]
    )
    await db_session.commit()

    resp = await api_client.get(f"{API}/reports?keyword={token}", headers=headers)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] == 3
    assert data["page"] == 1 and data["page_size"] == 20
    assert len(data["items"]) == 3
    assert data["items"][0]["session_id"] == f"s_{token}_1"  # 生成时间倒序
    assert data["items"][0]["patient_name"] == f"张三{token}"
    assert data["items"][0]["status"] == "final"
    assert data["items"][0]["health_level"] == "fair"
    assert data["items"][0]["report_id"].startswith("r_")

    first = (
        await api_client.get(f"{API}/reports?keyword={token}&page=1&page_size=2", headers=headers)
    ).json()["data"]
    assert first["total"] == 3 and len(first["items"]) == 2
    second = (
        await api_client.get(f"{API}/reports?keyword={token}&page=2&page_size=2", headers=headers)
    ).json()["data"]
    assert len(second["items"]) == 1 and second["items"][0]["session_id"] == f"s_{token}_3"


async def test_report_history_filters(
    api_client: AsyncClient, headers: dict[str, str], db_session: AsyncSession
) -> None:
    token = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    db_session.add_all(
        [
            _seed_report(
                f"f1{token}", f"s_{token}_a", name=f"甲{token}",
                summary=f"{token} 气虚为主，兼有寒象", generated_at=now,
            ),
            _seed_report(
                f"f2{token}", f"s_{token}_b", name=f"乙{token}",
                summary=f"{token} 脾虚湿盛", generated_at=now - timedelta(days=2),
            ),
            _seed_report(
                f"f3{token}", f"s_{token}_c", name="",
                summary=f"{token} 阴虚内热", generated_at=now - timedelta(days=10),
                anonymous=True, status=ReportStatus.ARCHIVED,
            ),
        ]
    )
    await db_session.commit()

    base = f"{API}/reports?keyword={token}"

    by_name = (await api_client.get(f"{base}&patient_name=甲{token}", headers=headers)).json()["data"]
    assert by_name["total"] == 1 and by_name["items"][0]["session_id"] == f"s_{token}_a"

    # 多词 AND：token 与「气虚」需同时命中
    multi = (await api_client.get(f"{base}&keyword=气虚", headers=headers)).json()["data"]
    assert multi["total"] == 1 and multi["items"][0]["session_id"] == f"s_{token}_a"

    # 关键词命中会话号，且匿名记录姓名置空
    by_session = (
        await api_client.get(f"{API}/reports?keyword=s_{token}_c", headers=headers)
    ).json()["data"]
    assert by_session["total"] == 1
    assert by_session["items"][0]["anonymous"] is True
    assert by_session["items"][0]["patient_name"] is None

    # 时间范围（近 3 天）命中前两条
    date_from = (now - timedelta(days=3)).date().isoformat()
    by_time = (await api_client.get(f"{base}&from={date_from}", headers=headers)).json()["data"]
    assert by_time["total"] == 2

    by_anon = (await api_client.get(f"{base}&anonymous=true", headers=headers)).json()["data"]
    assert by_anon["total"] == 1 and by_anon["items"][0]["session_id"] == f"s_{token}_c"

    by_status = (await api_client.get(f"{base}&status=archived", headers=headers)).json()["data"]
    assert by_status["total"] == 1 and by_status["items"][0]["status"] == "archived"


async def test_report_history_pagination_validation(
    api_client: AsyncClient, headers: dict[str, str]
) -> None:
    assert (await api_client.get(f"{API}/reports?page=0", headers=headers)).json()["code"] == 40001
    assert (
        await api_client.get(f"{API}/reports?page_size=200", headers=headers)
    ).json()["code"] == 40001


async def test_report_history_requires_auth(api_client: AsyncClient) -> None:
    resp = await api_client.get(f"{API}/reports")
    assert resp.status_code == 401


# ===== R6 删除报告 =====
async def test_delete_report_flow(
    api_client: AsyncClient,
    headers: dict[str, str],
    db_session: AsyncSession,
    use_test_session: None,
) -> None:
    data = await _seed_and_run_fusion(api_client, db_session, headers, "s_report_delete")
    report_id = data["report_id"]
    session_id = data["session_id"]

    deleted = (await api_client.delete(f"{API}/reports/{report_id}", headers=headers)).json()
    assert deleted["code"] == 0
    assert deleted["data"]["report_id"] == report_id
    assert deleted["data"]["deleted"] is True

    # 软删后：详情 / PDF 不可访问，重复删除 404，历史列表不再返回该报告
    assert (await api_client.get(f"{API}/reports/{report_id}/pdf", headers=headers)).status_code == 404
    assert (await api_client.delete(f"{API}/reports/{report_id}", headers=headers)).status_code == 404
    listing = (
        await api_client.get(f"{API}/reports?keyword={session_id}", headers=headers)
    ).json()["data"]
    assert listing["total"] == 0


async def test_delete_report_requires_auth(api_client: AsyncClient) -> None:
    resp = await api_client.delete(f"{API}/reports/r_1")
    assert resp.status_code == 401