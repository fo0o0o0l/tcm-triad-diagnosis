"""认证模块端到端用例（《开发任务文档》M1-9 / §4.3 A1~A11）。

覆盖：注册→登录→刷新→登出闭环，错误码 40001/40100/42900，找回与改密、资料更新与头像。
"""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.diagnosis import Report, ReportStatus
from app.services import auth as auth_service

API = "/api/v1/auth"
FIXED_CODE = "123456"
PASSWORD = "Abc@123456"
NEW_PASSWORD = "NewPwd@2026"
EMAIL = "doctor_a@example.com"
USERNAME = "doctor_a"


@pytest.fixture(autouse=True)
def _stub_external_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    """固定验证码并屏蔽邮件发送，保证用例不依赖 MailHog。"""
    monkeypatch.setattr(auth_service, "generate_numeric_code", lambda length=6: FIXED_CODE)

    async def _noop(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(auth_service, "_dispatch_code", _noop)


async def _register(
    client: AsyncClient,
    *,
    username: str = USERNAME,
    email: str = EMAIL,
    password: str = PASSWORD,
) -> dict:
    resp = await client.post(
        f"{API}/verify-code",
        json={"target": email, "scene": "register", "channel": "email"},
    )
    assert resp.json()["code"] == 0

    resp = await client.post(
        f"{API}/register",
        json={
            "username": username,
            "password": password,
            "name": "李某某",
            "email": email,
            "department": "中医内科",
            "verify_code": FIXED_CODE,
        },
    )
    return resp.json()


@pytest_asyncio.fixture
async def registered(api_client: AsyncClient) -> dict:
    """预置一个已注册医师账号。"""
    return await _register(api_client)


async def _login(
    client: AsyncClient, *, account: str = USERNAME, password: str = PASSWORD
) -> dict:
    resp = await client.post(
        f"{API}/login", json={"account": account, "password": password, "remember": False}
    )
    return {"status": resp.status_code, **resp.json()}


# ---- A1 注册 ----
async def test_register_success(registered: dict) -> None:
    assert registered["code"] == 0
    data = registered["data"]
    assert data["user_no"].startswith("d_")
    assert data["username"] == USERNAME
    assert data["role"] == "doctor"
    assert data["status"] == "active"


async def test_register_duplicate_username_returns_40001(api_client: AsyncClient) -> None:
    await _register(api_client)
    duplicate = await _register(api_client)

    assert duplicate["code"] == 40001
    assert duplicate["data"]["fields"][0]["field"] == "username"


async def test_register_requires_contact(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        f"{API}/register",
        json={"username": "no_contact", "password": PASSWORD, "verify_code": FIXED_CODE},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == 40001


# ---- A2 登录 ----
async def test_login_success(api_client: AsyncClient, registered: dict) -> None:
    body = await _login(api_client)

    assert body["code"] == 0
    data = body["data"]
    assert data["token_type"] == "Bearer"
    assert data["expires_in"] == 7200
    assert data["access_token"] and data["refresh_token"]
    assert data["user"]["username"] == USERNAME


async def test_login_wrong_password_returns_40100(
    api_client: AsyncClient, registered: dict
) -> None:
    body = await _login(api_client, password="WrongPass123")
    assert body["status"] == 401
    assert body["code"] == 40100


async def test_login_rate_limited_after_five_failures(
    api_client: AsyncClient, registered: dict
) -> None:
    for _ in range(5):
        body = await _login(api_client, password="WrongPass123")
        assert body["code"] == 40100

    blocked = await _login(api_client, password="WrongPass123")
    assert blocked["status"] == 429
    assert blocked["code"] == 42900


# ---- A5 当前用户 ----
async def test_me_requires_token(api_client: AsyncClient, registered: dict) -> None:
    unauthorized = await api_client.get(f"{API}/me")
    assert unauthorized.status_code == 401
    assert unauthorized.json()["code"] == 40100

    login = await _login(api_client)
    token = login["data"]["access_token"]
    resp = await api_client.get(f"{API}/me", headers={"Authorization": f"Bearer {token}"})

    assert resp.json()["code"] == 0
    data = resp.json()["data"]
    assert data["username"] == USERNAME
    # 统计口径为全部未软删报告（reports 暂无医生归属字段），故不固定为 0
    assert data["stats"]["total_reports"] >= 0
    assert data["stats"]["month_reports"] <= data["stats"]["total_reports"]


async def test_me_stats_counts_alive_reports(
    api_client: AsyncClient, registered: dict, db_session: AsyncSession
) -> None:
    """累计/本月报告数为真实统计：新增一份未软删报告后计数 +1（与 P7 列表同口径）。"""
    headers = await _auth_headers(api_client)
    before = (await api_client.get(f"{API}/me", headers=headers)).json()["data"]["stats"]

    db_session.add(
        Report(
            report_no=f"r_{uuid4().hex[:8]}",
            session_id="s_stats_probe",
            status=ReportStatus.FINAL,
            generated_at=datetime.now(timezone.utc),
        )
    )
    await db_session.commit()

    after = (await api_client.get(f"{API}/me", headers=headers)).json()["data"]["stats"]
    assert after["total_reports"] == before["total_reports"] + 1
    assert after["month_reports"] == before["month_reports"] + 1


# ---- A3/A4 刷新与登出 ----
async def test_refresh_rotates_token(api_client: AsyncClient, registered: dict) -> None:
    login = await _login(api_client)
    old_refresh = login["data"]["refresh_token"]

    refreshed = await api_client.post(f"{API}/refresh", json={"refresh_token": old_refresh})
    assert refreshed.json()["code"] == 0
    assert refreshed.json()["data"]["refresh_token"] != old_refresh

    # 旧令牌已旋转失效
    reused = await api_client.post(f"{API}/refresh", json={"refresh_token": old_refresh})
    assert reused.status_code == 401
    assert reused.json()["code"] == 40100


async def test_logout_revokes_refresh_token(
    api_client: AsyncClient, registered: dict
) -> None:
    login = await _login(api_client)
    refresh_token = login["data"]["refresh_token"]

    logout = await api_client.post(f"{API}/logout", json={"refresh_token": refresh_token})
    assert logout.json()["data"]["revoked"] is True

    reused = await api_client.post(f"{API}/refresh", json={"refresh_token": refresh_token})
    assert reused.status_code == 401


# ---- A7/A8 找回与重置 ----
async def test_reset_password_flow(api_client: AsyncClient, registered: dict) -> None:
    forgot = await api_client.post(
        f"{API}/password/forgot", json={"account": USERNAME, "channel": "email"}
    )
    assert forgot.json()["data"]["sent"] is True

    reset = await api_client.post(
        f"{API}/password/reset",
        json={"account": USERNAME, "verify_code": FIXED_CODE, "new_password": NEW_PASSWORD},
    )
    assert reset.json()["data"]["reset"] is True

    assert (await _login(api_client, password=PASSWORD))["code"] == 40100
    assert (await _login(api_client, password=NEW_PASSWORD))["code"] == 0


async def test_forgot_unknown_account_hides_existence(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        f"{API}/password/forgot", json={"account": "nobody", "channel": "email"}
    )
    assert resp.json()["code"] == 0
    assert resp.json()["data"]["sent"] is True


# ---- A9 修改密码 ----
async def test_change_password(api_client: AsyncClient, registered: dict) -> None:
    login = await _login(api_client)
    token = login["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    wrong = await api_client.post(
        f"{API}/password/change",
        json={"old_password": "WrongPass123", "new_password": NEW_PASSWORD},
        headers=headers,
    )
    assert wrong.json()["code"] == 40001

    ok = await api_client.post(
        f"{API}/password/change",
        json={"old_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=headers,
    )
    assert ok.json()["data"]["changed"] is True
    assert (await _login(api_client, password=NEW_PASSWORD))["code"] == 0


# ---- A10 更新个人资料 ----
def _avatar_bytes(fmt: str) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (64, 64), (200, 120, 90)).save(buf, format=fmt)
    return buf.getvalue()


async def _auth_headers(api_client: AsyncClient) -> dict[str, str]:
    login = await _login(api_client)
    return {"Authorization": f"Bearer {login['data']['access_token']}"}


async def test_update_profile(api_client: AsyncClient, registered: dict) -> None:
    headers = await _auth_headers(api_client)

    resp = await api_client.patch(
        f"{API}/me",
        json={"name": "王医师", "phone": "13800001111", "department": "针灸科"},
        headers=headers,
    )
    assert resp.json()["code"] == 0
    data = resp.json()["data"]
    assert data["name"] == "王医师"
    assert data["phone"] == "13800001111"
    assert data["department"] == "针灸科"
    # 账号与角色不因资料更新而变化
    assert data["username"] == USERNAME
    assert data["role"] == "doctor"

    # 重新查询仍生效（持久化）
    me = await api_client.get(f"{API}/me", headers=headers)
    assert me.json()["data"]["name"] == "王医师"

    # 空串表示清空；未提交的字段保持不变
    cleared = await api_client.patch(
        f"{API}/me", json={"department": ""}, headers=headers
    )
    assert cleared.json()["data"]["department"] is None
    assert cleared.json()["data"]["name"] == "王医师"


async def test_update_profile_requires_token(api_client: AsyncClient, registered: dict) -> None:
    resp = await api_client.patch(f"{API}/me", json={"name": "匿名"})
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


async def test_update_profile_rejects_invalid_phone(
    api_client: AsyncClient, registered: dict
) -> None:
    headers = await _auth_headers(api_client)
    resp = await api_client.patch(f"{API}/me", json={"phone": "not-a-phone"}, headers=headers)
    assert resp.json()["code"] == 40001


async def test_update_profile_rejects_taken_phone(
    api_client: AsyncClient, registered: dict
) -> None:
    other = await _register(
        api_client, username="doctor_b", email="doctor_b@example.com"
    )
    assert other["code"] == 0
    # 另一个账号先占用手机号
    other_login = await _login(api_client, account="doctor_b")
    other_headers = {"Authorization": f"Bearer {other_login['data']['access_token']}"}
    await api_client.patch(f"{API}/me", json={"phone": "13900002222"}, headers=other_headers)

    headers = await _auth_headers(api_client)
    resp = await api_client.patch(f"{API}/me", json={"phone": "13900002222"}, headers=headers)
    assert resp.json()["code"] == 40001
    assert resp.json()["data"]["fields"][0]["field"] == "phone"


# ---- A11 上传头像 ----
async def test_upload_avatar_and_read_media(api_client: AsyncClient, registered: dict) -> None:
    headers = await _auth_headers(api_client)

    resp = await api_client.post(
        f"{API}/avatar",
        files={"file": ("a.png", _avatar_bytes("PNG"), "image/png")},
        headers=headers,
    )
    assert resp.json()["code"] == 0
    url = resp.json()["data"]["avatar_url"]
    assert url.startswith("/auth/avatar/media/")
    assert url.split("?")[0].endswith("avatar.png")
    # 带文件版本参数：换图后 URL 必变，前端 <img> 才会重新请求（否则显示旧图）
    assert "?v=" in url

    media = await api_client.get(f"/api/v1{url}")
    assert media.status_code == 200
    assert media.headers["cache-control"] == "no-store"

    # 资料接口同步返回头像地址
    me = await api_client.get(f"{API}/me", headers=headers)
    assert me.json()["data"]["avatar_url"] == url

    # 换扩展名重复上传：引用指向新扩展名，旧文件被清理
    again = await api_client.post(
        f"{API}/avatar",
        files={"file": ("a.jpg", _avatar_bytes("JPEG"), "image/jpeg")},
        headers=headers,
    )
    new_url = again.json()["data"]["avatar_url"]
    assert new_url.split("?")[0].endswith("avatar.jpg")
    assert new_url != url
    assert (await api_client.get(f"/api/v1{url}")).status_code == 404


async def test_upload_avatar_rejects_unsupported_type(
    api_client: AsyncClient, registered: dict
) -> None:
    headers = await _auth_headers(api_client)
    resp = await api_client.post(
        f"{API}/avatar",
        files={"file": ("a.txt", b"not-an-image", "text/plain")},
        headers=headers,
    )
    assert resp.json()["code"] == 40001