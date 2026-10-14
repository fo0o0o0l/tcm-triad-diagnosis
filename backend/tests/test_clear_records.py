"""清空采集记录接口用例（T6 / F6 / I6）。

修复背景：三诊页面「重新采集 / 重置表单」此前只清前端本地态，后端记录仍在，
浏览器刷新后由 T0/F0/I0 按会话回填出旧数据。本用例覆盖新增的清空接口：
软删成功后再次查询应为空、重复清空幂等（`deleted=false`）、问诊草稿同步删除、未登录 401。
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.diagnosis import (
    FaceRecord,
    ImageSource,
    InquiryDraft,
    InquiryRecord,
    TongueRecord,
)
from app.services import auth as auth_service

API = "/api/v1"
FIXED_CODE = "123456"
PASSWORD = "Abc@123456"
USERNAME = "clear_doc"
EMAIL = "clear_doc@example.com"


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
            "name": "清空医师",
            "email": EMAIL,
            "verify_code": FIXED_CODE,
        },
    )
    resp = await api_client.post(
        f"{API}/auth/login",
        json={"account": USERNAME, "password": PASSWORD, "remember": False},
    )
    return {"Authorization": f"Bearer {resp.json()['data']['access_token']}"}


async def test_clear_tongue_record(
    api_client: AsyncClient, headers: dict[str, str], db_session: AsyncSession
) -> None:
    token = uuid.uuid4().hex[:8]
    session_id = f"s_clear_t_{token}"
    db_session.add(
        TongueRecord(
            record_no=f"t_{token}",
            session_id=session_id,
            source=ImageSource.UPLOAD,
            image_ref=f"tongue/{session_id}/raw.png",
            quality_passed=True,
            features=[],
        )
    )
    await db_session.commit()

    before = (
        await api_client.get(f"{API}/sessions/{session_id}/tongue/record", headers=headers)
    ).json()["data"]
    assert before["record_id"] == f"t_{token}"

    cleared = (
        await api_client.delete(f"{API}/sessions/{session_id}/tongue/record", headers=headers)
    ).json()
    assert cleared["code"] == 0
    assert cleared["data"]["deleted"] is True

    # 清空后刷新（再次查询）应回到未采集态
    after = (
        await api_client.get(f"{API}/sessions/{session_id}/tongue/record", headers=headers)
    ).json()["data"]
    assert after is None

    # 幂等：重复清空不报错且 deleted=False
    again = (
        await api_client.delete(f"{API}/sessions/{session_id}/tongue/record", headers=headers)
    ).json()["data"]
    assert again["deleted"] is False


async def test_clear_face_record(
    api_client: AsyncClient, headers: dict[str, str], db_session: AsyncSession
) -> None:
    token = uuid.uuid4().hex[:8]
    session_id = f"s_clear_f_{token}"
    db_session.add(
        FaceRecord(
            record_no=f"f_{token}",
            session_id=session_id,
            source=ImageSource.UPLOAD,
            image_ref=f"face/{session_id}/raw.png",
            quality_passed=True,
            features=[],
        )
    )
    await db_session.commit()

    before = (
        await api_client.get(f"{API}/sessions/{session_id}/face/record", headers=headers)
    ).json()["data"]
    assert before["record_id"] == f"f_{token}"

    cleared = (
        await api_client.delete(f"{API}/sessions/{session_id}/face/record", headers=headers)
    ).json()
    assert cleared["code"] == 0 and cleared["data"]["deleted"] is True

    after = (
        await api_client.get(f"{API}/sessions/{session_id}/face/record", headers=headers)
    ).json()["data"]
    assert after is None


async def test_clear_inquiry_record_and_draft(
    api_client: AsyncClient, headers: dict[str, str], db_session: AsyncSession
) -> None:
    token = uuid.uuid4().hex[:8]
    session_id = f"s_clear_i_{token}"
    db_session.add(
        InquiryRecord(
            record_no=f"q_{token}",
            session_id=session_id,
            template_version="inquiry_v2",
            answers={"gender": "女"},
        )
    )
    db_session.add(
        InquiryDraft(
            session_id=session_id,
            template_version="inquiry_v2",
            answers={"gender": "女", "age": 30},
        )
    )
    await db_session.commit()

    before = (
        await api_client.get(f"{API}/sessions/{session_id}/inquiry/record", headers=headers)
    ).json()["data"]
    assert before["record"]["record_id"] == f"q_{token}"
    assert before["draft"]["answers"]["age"] == 30

    cleared = (
        await api_client.delete(f"{API}/sessions/{session_id}/inquiry/record", headers=headers)
    ).json()
    assert cleared["code"] == 0 and cleared["data"]["deleted"] is True

    # 记录与草稿均被清空，刷新后不再回填
    after = (
        await api_client.get(f"{API}/sessions/{session_id}/inquiry/record", headers=headers)
    ).json()["data"]
    assert after["record"] is None
    assert after["draft"] is None


async def test_clear_records_require_auth(api_client: AsyncClient) -> None:
    assert (
        await api_client.delete(f"{API}/sessions/s_x/tongue/record")
    ).status_code == 401
    assert (await api_client.delete(f"{API}/sessions/s_x/face/record")).status_code == 401
    assert (
        await api_client.delete(f"{API}/sessions/s_x/inquiry/record")
    ).status_code == 401
