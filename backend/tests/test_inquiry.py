"""问诊模块端到端用例（《开发任务日志》M4-10 / §4.7 I1~I5）。

覆盖：模板下发、草稿保存/恢复、P0 必填缺失定位、提交+AI 全链路、
匿名联动、错误码 40001/40100/40400，以及 Mock 规则冲突消解。
"""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.services import auth as auth_service
from app.services import inquiry_ai_analysis, inquiry_mock_analysis

API = "/api/v1"
FIXED_CODE = "123456"
PASSWORD = "Abc@123456"
USERNAME = "inquiry_doc"
EMAIL = "inquiry_doc@example.com"
TEMPLATE_VERSION = "inquiry_v2"


def _answers(**overrides: Any) -> list[dict[str, Any]]:
    """构造一组通过 P0 校验的答案，overrides 以 qid 覆盖 / 增删。"""
    base: dict[str, Any] = {
        "gender": "女",
        "age": 34,
        "height": 165,
        "weight": 58,
        "name": "张三",
        "anonymous": False,
        "chief_complaint": "近期乏力、畏寒",
        "cold_heat": ["怕冷畏寒"],
        "sleep": ["多梦"],
    }
    base.update(overrides)
    return [{"qid": qid, "value": value} for qid, value in base.items() if value is not None]


@pytest.fixture(autouse=True)
def _stub_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    """固定验证码、屏蔽邮件；算法服务不可用 → 走降级 Mock。"""
    monkeypatch.setattr(auth_service, "generate_numeric_code", lambda length=6: FIXED_CODE)

    async def _noop(*_args: object, **_kwargs: object) -> None:
        return None

    async def _no_algo(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(auth_service, "_dispatch_code", _noop)
    monkeypatch.setattr(inquiry_ai_analysis, "_call_algo", _no_algo)


@pytest_asyncio.fixture
async def use_test_session(monkeypatch: pytest.MonkeyPatch, db_session: object) -> None:
    """让后台 AI 任务复用用例事务会话，保证未提交数据可见。"""

    class _Ctx:
        async def __aenter__(self) -> object:
            return db_session

        async def __aexit__(self, *_exc: object) -> bool:
            return False

    monkeypatch.setattr(inquiry_ai_analysis, "AsyncSessionLocal", lambda: _Ctx())


@pytest_asyncio.fixture
async def headers(api_client: AsyncClient) -> dict[str, str]:
    """注册并登录，返回鉴权头。"""
    await api_client.post(
        f"{API}/auth/verify-code",
        json={"target": EMAIL, "scene": "register", "channel": "email"},
    )
    await api_client.post(
        f"{API}/auth/register",
        json={
            "username": USERNAME,
            "password": PASSWORD,
            "name": "问诊医师",
            "email": EMAIL,
            "verify_code": FIXED_CODE,
        },
    )
    resp = await api_client.post(
        f"{API}/auth/login",
        json={"account": USERNAME, "password": PASSWORD, "remember": False},
    )
    return {"Authorization": f"Bearer {resp.json()['data']['access_token']}"}


async def _submit(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    session_id: str = "s_inquiry_0001",
    answers: list[dict[str, Any]] | None = None,
) -> dict:
    return (
        await client.post(
            f"{API}/sessions/{session_id}/inquiry/submit",
            headers=headers,
            json={"template_version": TEMPLATE_VERSION, "answers": answers or _answers()},
        )
    ).json()


# ---- I1 模板 ----
async def test_template_requires_auth(api_client: AsyncClient) -> None:
    resp = await api_client.get(f"{API}/inquiry/template")
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


async def test_template_returns_groups(api_client: AsyncClient, headers: dict[str, str]) -> None:
    body = (await api_client.get(f"{API}/inquiry/template", headers=headers)).json()
    assert body["code"] == 0
    data = body["data"]
    assert data["template_version"] == TEMPLATE_VERSION
    group_ids = [group["group_id"] for group in data["groups"]]
    assert group_ids == [
        "basic",
        "menstruation",
        "chief_symptom",
        "cold_heat",
        "sweating",
        "sleep",
        "diet_taste",
        "excretion",
        "chest_abdomen",
        "other",
    ]
    basic = data["groups"][0]
    assert basic["priority"] == "P0"
    assert {"gender", "age", "height", "weight"} <= {q["qid"] for q in basic["questions"]}

    questions = {q["qid"]: q for group in data["groups"] for q in group["questions"]}
    # v2 新增字段：术语提示 / 「其他」输入 / 互斥选项 / 分组显示条件
    assert questions["cold_heat"]["hint"]
    assert questions["cold_heat"]["allowOther"] is True
    assert questions["cold_heat"]["exclusiveOptions"] == ["无明显寒热"]
    assert questions["gender"]["allowOther"] is False
    menstruation = next(g for g in data["groups"] if g["group_id"] == "menstruation")
    assert menstruation["showWhen"] == {"qid": "gender", "equals": "女"}
    assert all(q["required"] is False for q in menstruation["questions"])


# ---- I2 草稿 ----
async def test_save_draft_and_restore(api_client: AsyncClient, headers: dict[str, str]) -> None:
    session_id = "s_draft_0001"
    resp = await api_client.put(
        f"{API}/sessions/{session_id}/inquiry/draft",
        headers=headers,
        json={"template_version": TEMPLATE_VERSION, "answers": [{"qid": "gender", "value": "男"}]},
    )
    body = resp.json()
    assert body["code"] == 0
    assert body["data"]["saved"] is True

    state = (
        await api_client.get(f"{API}/sessions/{session_id}/inquiry/record", headers=headers)
    ).json()["data"]
    assert state["record"] is None
    assert state["draft"]["answers"]["gender"] == "男"


async def test_draft_requires_auth(api_client: AsyncClient) -> None:
    resp = await api_client.put(
        f"{API}/sessions/s_x/inquiry/draft",
        json={"template_version": TEMPLATE_VERSION, "answers": []},
    )
    assert resp.status_code == 401


# ---- I3 提交 ----
async def test_submit_missing_required_returns_40001(
    api_client: AsyncClient, headers: dict[str, str]
) -> None:
    resp = await api_client.post(
        f"{API}/sessions/s_missing_0001/inquiry/submit",
        headers=headers,
        json={
            "template_version": TEMPLATE_VERSION,
            "answers": _answers(cold_heat=None),
        },
    )
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == 40001
    assert body["data"]["missing"] == ["cold_heat"]
    assert body["data"]["first_missing"] == "cold_heat"


async def test_submit_success_triggers_analysis(
    api_client: AsyncClient, headers: dict[str, str], use_test_session: None
) -> None:
    session_id = "s_submit_0001"
    submitted = await _submit(api_client, headers, session_id=session_id)
    assert submitted["code"] == 0
    assert submitted["data"]["record_id"].startswith("q_")
    assert submitted["data"]["completed"] is True

    analysis = (
        await api_client.get(f"{API}/sessions/{session_id}/inquiry/analysis", headers=headers)
    ).json()
    assert analysis["code"] == 0
    assert analysis["data"]["status"] == "completed"
    assert analysis["data"]["result"]["symptoms_summary"]
    assert analysis["data"]["result"]["main_syndrome"]["name"] == "阳虚证"
    assert "sweating" in analysis["data"]["missing_items"]


async def test_submit_clears_draft(
    api_client: AsyncClient, headers: dict[str, str], use_test_session: None
) -> None:
    session_id = "s_submit_clears_draft"
    await api_client.put(
        f"{API}/sessions/{session_id}/inquiry/draft",
        headers=headers,
        json={"template_version": TEMPLATE_VERSION, "answers": [{"qid": "gender", "value": "男"}]},
    )
    await _submit(api_client, headers, session_id=session_id)

    state = (
        await api_client.get(f"{API}/sessions/{session_id}/inquiry/record", headers=headers)
    ).json()["data"]
    assert state["draft"] is None
    assert state["record"]["record_id"].startswith("q_")


# ---- I4/I5 分析 ----
async def test_analysis_before_submit_returns_404(
    api_client: AsyncClient, headers: dict[str, str]
) -> None:
    resp = await api_client.get(
        f"{API}/sessions/s_none_inquiry/inquiry/analysis", headers=headers
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == 40400


async def test_reanalyze_via_i4(
    api_client: AsyncClient, headers: dict[str, str], use_test_session: None
) -> None:
    session_id = "s_reanalysis_0001"
    record_id = (await _submit(api_client, headers, session_id=session_id))["data"]["record_id"]

    started = (
        await api_client.post(
            f"{API}/sessions/{session_id}/inquiry/ai-analysis",
            headers=headers,
            json={"record_id": record_id, "language": "zh-CN"},
        )
    ).json()
    assert started["code"] == 0
    assert started["data"]["task_id"].startswith("task_")

    result = (
        await api_client.get(f"{API}/sessions/{session_id}/inquiry/analysis", headers=headers)
    ).json()
    assert result["data"]["status"] == "completed"


# ---- 匿名联动 ----
async def test_anonymous_clears_name(
    api_client: AsyncClient, headers: dict[str, str], use_test_session: None
) -> None:
    session_id = "s_anonymous_0001"
    await _submit(
        api_client,
        headers,
        session_id=session_id,
        answers=_answers(anonymous=True, name="李四"),
    )
    state = (
        await api_client.get(f"{API}/sessions/{session_id}/inquiry/record", headers=headers)
    ).json()["data"]
    snapshot = state["record"]["patient_snapshot"]
    assert snapshot["anonymous"] is True
    assert snapshot["name"] is None
    assert state["record"]["answers"]["name"] == ""


# ---- I0 状态恢复 ----
async def test_record_state_null_without_data(
    api_client: AsyncClient, headers: dict[str, str]
) -> None:
    body = (
        await api_client.get(f"{API}/sessions/s_empty_inquiry/inquiry/record", headers=headers)
    ).json()
    assert body["code"] == 0
    assert body["data"] == {"draft": None, "record": None}


async def test_record_state_restores_record(
    api_client: AsyncClient, headers: dict[str, str], use_test_session: None
) -> None:
    session_id = "s_restore_inquiry_0001"
    record_id = (await _submit(api_client, headers, session_id=session_id))["data"]["record_id"]

    data = (
        await api_client.get(f"{API}/sessions/{session_id}/inquiry/record", headers=headers)
    ).json()["data"]
    assert data["record"]["record_id"] == record_id
    assert data["record"]["completed"] is True
    assert data["record"]["answers"]["chief_complaint"] == "近期乏力、畏寒"
    assert data["record"]["analysis"]["status"] == "completed"


# ---- 服务层：Mock 规则 ----
def test_mock_conflicting_cold_heat_keeps_yang_deficiency() -> None:
    result = inquiry_mock_analysis.analyze(
        {"cold_heat": ["怕冷畏寒", "手足心热"]}, missing_items=[]
    )
    assert result["main_syndrome"]["name"] == "阳虚证"
    names = [item["name"] for item in result["secondary_syndromes"]]
    assert "阴虚火旺证" not in names


def test_mock_missing_items_lowers_confidence() -> None:
    answers = {"cold_heat": ["怕冷畏寒"], "chief_complaint": "畏寒"}
    base = inquiry_mock_analysis.analyze(answers, missing_items=[])
    penalized = inquiry_mock_analysis.analyze(
        answers, missing_items=["sweating", "sleep", "diet_taste"]
    )
    assert penalized["main_syndrome"]["confidence"] < base["main_syndrome"]["confidence"]