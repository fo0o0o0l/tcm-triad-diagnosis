"""三诊合参模块端到端用例（《开发任务日志》M5-10 / §4.8 G0~G2）。

覆盖：前置校验（三诊全齐否则阻断）、G1 缺诊阻断与幂等拦截、G1→G2 全链路（含报告 8 Tab）、
降级 Mock 与规则层（一致性矛盾、置信度加权、健康等级映射）。
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.diagnosis import (
    AnalysisStatus,
    FaceAnalysis,
    FaceRecord,
    FusionResult,
    ImageSource,
    InquiryAnalysis,
    InquiryRecord,
    ModuleStatus,
    TongueAnalysis,
    TongueRecord,
)
from app.services import auth as auth_service
from app.services import integrated_ai_analysis, integrated_analysis, integrated_mock_analysis

API = "/api/v1"
FIXED_CODE = "123456"
PASSWORD = "Abc@123456"
USERNAME = "fusion_doc"
EMAIL = "fusion_doc@example.com"


@pytest.fixture(autouse=True)
def _stub_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    """固定验证码、屏蔽邮件；算法服务不可用 → 走降级 Mock。"""
    monkeypatch.setattr(auth_service, "generate_numeric_code", lambda length=6: FIXED_CODE)

    async def _noop(*_args: object, **_kwargs: object) -> None:
        return None

    async def _no_algo(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(auth_service, "_dispatch_code", _noop)
    monkeypatch.setattr(integrated_ai_analysis, "_call_algo", _no_algo)


@pytest_asyncio.fixture
async def use_test_session(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    """让后台合参任务复用用例事务会话，保证未提交数据可见。"""

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
            "name": "合参医师",
            "email": EMAIL,
            "verify_code": FIXED_CODE,
        },
    )
    resp = await api_client.post(
        f"{API}/auth/login",
        json={"account": USERNAME, "password": PASSWORD, "remember": False},
    )
    return {"Authorization": f"Bearer {resp.json()['data']['access_token']}"}


async def _seed_modules(
    db: AsyncSession,
    session_id: str,
    *,
    modules: tuple[str, ...] = ("tongue", "face", "inquiry"),
    tongue_color: str = "淡红",
    face_color: str = "红润",
    cold_heat: list[str] | None = None,
) -> None:
    """直接落库三诊记录与当前有效分析，供合参读取。"""
    token = uuid.uuid4().hex[:8]
    if "tongue" in modules:
        record = TongueRecord(
            record_no=f"t_{token}",
            session_id=session_id,
            source=ImageSource.UPLOAD,
            image_ref=f"tongue/{session_id}/raw.png",
            quality_passed=True,
            features=[
                {"name": "tongue_color", "label": tongue_color, "confidence": 0.85},
                {"name": "coating_color", "label": "白", "confidence": 0.86},
                {"name": "coating_texture", "label": "薄", "confidence": 0.80},
                {"name": "tongue_shape", "label": "正常", "confidence": 0.76},
            ],
            overall_confidence=0.84,
        )
        db.add(record)
        await db.flush()
        db.add(
            TongueAnalysis(
                analysis_no=f"ta_{token}",
                record_id=record.id,
                status=AnalysisStatus.COMPLETED,
                tongue_summary="舌质淡红，舌苔白薄，舌体正常。",
                main_syndrome={"name": "脾气虚证", "confidence": 0.84},
                secondary_syndromes=[],
                treatment_principles=["健脾益气"],
                recommendations=[],
                is_current=True,
            )
        )
    if "face" in modules:
        record = FaceRecord(
            record_no=f"f_{token}",
            session_id=session_id,
            source=ImageSource.UPLOAD,
            image_ref=f"face/{session_id}/raw.png",
            quality_passed=True,
            features=[
                {"name": "face_color", "label": face_color, "confidence": 0.84},
                {"name": "luster", "label": "有光泽", "confidence": 0.80},
                {"name": "acne", "label": "无", "confidence": 0.86},
                {"name": "spots", "label": "无", "confidence": 0.86},
            ],
            overall_confidence=0.82,
        )
        db.add(record)
        await db.flush()
        db.add(
            FaceAnalysis(
                analysis_no=f"fa_{token}",
                record_id=record.id,
                status=AnalysisStatus.COMPLETED,
                face_summary="面色红润，皮肤有光泽。",
                main_syndrome={"name": "气血充足", "confidence": 0.78},
                secondary_syndromes=[],
                treatment_principles=["调和气血"],
                recommendations=[],
                is_current=True,
            )
        )
    if "inquiry" in modules:
        record = InquiryRecord(
            record_no=f"q_{token}",
            session_id=session_id,
            template_version="inquiry_v1",
            patient_snapshot={"gender": "女", "age": 34, "height": 165, "weight": 58},
            answers={
                "chief_complaint": "近期乏力、畏寒",
                "cold_heat": cold_heat or ["怕冷畏寒"],
            },
            missing_items=["sweating"],
            status=ModuleStatus.ANALYZED,
        )
        db.add(record)
        await db.flush()
        db.add(
            InquiryAnalysis(
                analysis_no=f"ia_{token}",
                record_id=record.id,
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


# ---- G0 前置校验 ----
async def test_readiness_requires_auth(api_client: AsyncClient) -> None:
    resp = await api_client.get(f"{API}/sessions/s_x/fusion/readiness")
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


async def test_readiness_allows_analyze_when_all_done(
    api_client: AsyncClient, headers: dict[str, str], db_session: AsyncSession
) -> None:
    """三诊全部完成方可合参。"""
    session_id = "s_fusion_all_done"
    await _seed_modules(db_session, session_id)

    data = (
        await api_client.get(f"{API}/sessions/{session_id}/fusion/readiness", headers=headers)
    ).json()["data"]
    assert data["missing_modules"] == []
    assert data["can_analyze"] is True
    assert data["blocking_reason"] is None


async def test_readiness_blocks_when_one_missing(
    api_client: AsyncClient, headers: dict[str, str], db_session: AsyncSession
) -> None:
    """缺任一一诊即阻断，并在提示中点名缺哪一诊（UI/UX §5.4.3）。"""
    session_id = "s_fusion_ready"
    await _seed_modules(db_session, session_id, modules=("tongue", "face"))

    body = (
        await api_client.get(f"{API}/sessions/{session_id}/fusion/readiness", headers=headers)
    ).json()
    assert body["code"] == 0
    data = body["data"]
    assert data["modules"]["tongue"]["done"] is True
    assert data["modules"]["face"]["done"] is True
    assert data["modules"]["inquiry"]["done"] is False
    assert data["missing_modules"] == ["inquiry"]
    assert data["can_analyze"] is False
    assert "问诊录入" in data["blocking_reason"]


async def test_readiness_blocks_when_two_missing(
    api_client: AsyncClient, headers: dict[str, str], db_session: AsyncSession
) -> None:
    session_id = "s_fusion_blocked"
    await _seed_modules(db_session, session_id, modules=("tongue",))

    data = (
        await api_client.get(f"{API}/sessions/{session_id}/fusion/readiness", headers=headers)
    ).json()["data"]
    assert data["can_analyze"] is False
    assert set(data["missing_modules"]) == {"face", "inquiry"}
    assert data["blocking_reason"]


# ---- G1 触发 ----
async def test_analyze_blocked_when_one_missing_returns_40001(
    api_client: AsyncClient, headers: dict[str, str], db_session: AsyncSession
) -> None:
    """接口层同样拦截：缺任一一诊都不可触发合参。"""
    session_id = "s_fusion_analyze_blocked"
    await _seed_modules(db_session, session_id, modules=("tongue", "face"))

    resp = await api_client.post(
        f"{API}/sessions/{session_id}/fusion/analyze", headers=headers, json={}
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == 40001
    assert body["data"]["missing_modules"] == ["inquiry"]
    assert "问诊" in body["message"]


async def test_analyze_blocked_two_missing_returns_40001(
    api_client: AsyncClient, headers: dict[str, str], db_session: AsyncSession
) -> None:
    session_id = "s_fusion_analyze_blocked_two"
    await _seed_modules(db_session, session_id, modules=("tongue",))

    resp = await api_client.post(
        f"{API}/sessions/{session_id}/fusion/analyze", headers=headers, json={}
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == 40001
    assert set(body["data"]["missing_modules"]) == {"face", "inquiry"}


async def test_analyze_conflicts_when_in_progress(
    api_client: AsyncClient, headers: dict[str, str], db_session: AsyncSession
) -> None:
    session_id = "s_fusion_in_progress"
    await _seed_modules(db_session, session_id)
    db_session.add(
        FusionResult(
            fusion_no=f"fu_{uuid.uuid4().hex[:8]}",
            session_id=session_id,
            status=AnalysisStatus.ANALYZING,
            is_current=True,
            task_id="task_busy",
        )
    )
    await db_session.commit()

    resp = await api_client.post(
        f"{API}/sessions/{session_id}/fusion/analyze", headers=headers, json={}
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == 40901


# ---- G1 → G2 全链路 ----
async def test_full_fusion_flow(
    api_client: AsyncClient,
    headers: dict[str, str],
    db_session: AsyncSession,
    use_test_session: None,
) -> None:
    session_id = "s_fusion_ok"
    await _seed_modules(db_session, session_id)

    started = (
        await api_client.post(
            f"{API}/sessions/{session_id}/fusion/analyze",
            headers=headers,
            json={"options": {"include_inquiry": True, "language": "zh-CN"}},
        )
    ).json()
    assert started["code"] == 0
    assert started["data"]["fusion_status"] == "analyzing"
    assert started["data"]["task_id"].startswith("task_")

    result = (
        await api_client.get(f"{API}/sessions/{session_id}/fusion/result", headers=headers)
    ).json()
    assert result["code"] == 0
    data = result["data"]
    assert data["status"] == "completed"
    assert data["fusion_id"].startswith("fu_")
    assert data["overall_confidence"] > 0
    assert data["health_level"] in {"good", "fair", "poor", "bad"}
    assert data["missing_modules"] == []
    assert data["conclusions"]
    assert data["syndrome_points"]
    assert data["suggestions"]

    report = data["report"]
    assert report is not None
    assert report["header"]["session_id"] == session_id
    for tab in (
        "overview",
        "details",
        "indices",
        "therapy",
        "constitution",
        "prevention",
        "advice",
        "emotion",
    ):
        assert tab in report
    assert report["details"]["tongue"]["features"]
    assert report["details"]["inquiry"]["record_id"].startswith("q_")
    assert report["constitution"]["main_syndrome"]["name"]
    assert report["advice"]["suggestions"]


async def test_result_not_found_without_fusion(
    api_client: AsyncClient, headers: dict[str, str]
) -> None:
    resp = await api_client.get(f"{API}/sessions/s_none_fusion/fusion/result", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["code"] == 40400


async def test_result_analyzing_without_report(
    api_client: AsyncClient, headers: dict[str, str], db_session: AsyncSession
) -> None:
    session_id = "s_fusion_analyzing"
    db_session.add(
        FusionResult(
            fusion_no=f"fu_{uuid.uuid4().hex[:8]}",
            session_id=session_id,
            status=AnalysisStatus.ANALYZING,
            is_current=True,
            task_id="task_pending",
        )
    )
    await db_session.commit()

    data = (
        await api_client.get(f"{API}/sessions/{session_id}/fusion/result", headers=headers)
    ).json()["data"]
    assert data["status"] == "analyzing"
    assert data["report"] is None


# ---- 规则层 ----
def _inputs(**modules: dict) -> integrated_analysis.FusionInputs:
    inputs = integrated_analysis.FusionInputs(session_id="s_unit")
    for key, payload in modules.items():
        inputs.modules[key] = integrated_analysis.ModuleInput(key=key, record_no=f"{key}_1", **payload)
    return inputs


def test_conflict_detected_between_pale_tongue_and_flushed_face() -> None:
    inputs = _inputs(
        tongue={"features": [{"name": "tongue_color", "label": "淡白", "confidence": 0.8}]},
        face={"features": [{"name": "face_color", "label": "潮红", "confidence": 0.8}]},
    )
    conflicts = integrated_analysis.detect_conflicts(inputs)
    assert any("tongue" in c["modules"] and "face" in c["modules"] for c in conflicts)


def test_missing_module_lowers_confidence() -> None:
    full = _inputs(
        tongue={"features": [], "overall_confidence": 0.9},
        face={"features": [], "overall_confidence": 0.9},
        inquiry={"answers": {"x": 1}, "overall_confidence": 0.9},
    )
    partial = _inputs(
        tongue={"features": [], "overall_confidence": 0.9},
        face={"features": [], "overall_confidence": 0.9},
    )
    assert integrated_analysis.compute_overall_confidence(
        partial, []
    ) < integrated_analysis.compute_overall_confidence(full, [])


def test_health_level_mapping_thresholds() -> None:
    assert integrated_analysis.map_health_level(0.9, []) == "good"
    assert integrated_analysis.map_health_level(0.75, []) == "fair"
    assert integrated_analysis.map_health_level(0.6, []) == "poor"
    assert integrated_analysis.map_health_level(0.4, []) == "bad"
    # 任一矛盾项即降为「较差」
    assert integrated_analysis.map_health_level(0.9, [{"description": "x"}]) == "poor"


def test_mock_generates_conclusions_and_suggestions() -> None:
    snapshot = {
        "tongue": {
            "features": [
                {"name": "tongue_color", "label": "淡白", "confidence": 0.8},
                {"name": "coating_color", "label": "白", "confidence": 0.86},
                {"name": "coating_texture", "label": "薄", "confidence": 0.8},
            ],
            "main_syndrome": {"name": "脾气虚证", "confidence": 0.84},
        },
        "inquiry": {"answers": {"chief_complaint": "乏力", "cold_heat": ["怕冷畏寒"]}},
    }
    result = integrated_mock_analysis.analyze(
        snapshot, conflicts=[], missing_modules=[], overall_confidence=0.8
    )
    assert result["conclusions"][0]["text"]
    assert any("舌质" in point for point in result["syndrome_points"])
    categories = {item["category"] for item in result["suggestions"]}
    assert {"饮食", "作息", "情志", "复诊"} <= categories