"""舌诊模块端到端用例（《开发任务文档》M2-10 / §4.5 T1~T5）。

覆盖：质量校验通过/阻断、格式与鉴权校验、提取→特征→AI 全链路、错误码 40001/40100/40400/42201。
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import AsyncClient
from PIL import Image, ImageDraw

from app.core.config import settings
from app.core.errors import ErrorCode
from app.core.response import BusinessError
from app.services import algo_vision
from app.services import auth as auth_service
from app.services import tongue_ai_analysis, tongue_detection

API = "/api/v1"
FIXED_CODE = "123456"
PASSWORD = "Abc@123456"
USERNAME = "tongue_doc"
EMAIL = "tongue_doc@example.com"


def _good_tongue_image() -> bytes:
    """构造一张清晰、光照均匀、舌体占比充足的合成图像（保证质量校验通过）。"""
    img = Image.new("RGB", (640, 480), (110, 112, 122))
    draw = ImageDraw.Draw(img)
    draw.ellipse([150, 90, 490, 400], fill=(232, 152, 142))
    for x in range(150, 490, 16):
        draw.line([(x, 90), (x, 400)], fill=(196, 108, 100), width=2)
    for y in range(90, 400, 16):
        draw.line([(150, y), (490, y)], fill=(196, 108, 100), width=2)
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()


def _bad_image() -> bytes:
    """暗且模糊、无舌体色域的图像（质量校验应阻断）。"""
    img = Image.new("RGB", (640, 480), (20, 20, 24))
    buffer = BytesIO()
    img.save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def _stub_side_effects(monkeypatch: pytest.MonkeyPatch) -> None:
    """固定验证码、屏蔽邮件；算法服务不可用 → 走降级 Mock。"""
    monkeypatch.setattr(auth_service, "generate_numeric_code", lambda length=6: FIXED_CODE)

    async def _noop(*_args: object, **_kwargs: object) -> None:
        return None

    async def _no_algo(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(auth_service, "_dispatch_code", _noop)
    monkeypatch.setattr(tongue_ai_analysis, "_call_algo", _no_algo)

    async def _no_vision(*_args: object, **_kwargs: object) -> None:
        return None

    # 默认算法服务视觉识别不可用 → T3 降级本地启发式，保证用例不依赖外部进程
    monkeypatch.setattr(algo_vision, "classify_features", _no_vision)


@pytest_asyncio.fixture
async def use_test_session(monkeypatch: pytest.MonkeyPatch, db_session: object) -> None:
    """让后台 AI 任务复用用例事务会话，保证未提交数据可见。"""

    class _Ctx:
        async def __aenter__(self) -> object:
            return db_session

        async def __aexit__(self, *_exc: object) -> bool:
            return False

    monkeypatch.setattr(tongue_ai_analysis, "AsyncSessionLocal", lambda: _Ctx())


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
            "name": "舌诊医师",
            "email": EMAIL,
            "verify_code": FIXED_CODE,
        },
    )
    resp = await api_client.post(
        f"{API}/auth/login",
        json={"account": USERNAME, "password": PASSWORD, "remember": False},
    )
    return {"Authorization": f"Bearer {resp.json()['data']['access_token']}"}


async def _upload(
    client: AsyncClient,
    headers: dict[str, str],
    content: bytes,
    *,
    session_id: str = "s_tongue_0001",
    content_type: str = "image/jpeg",
) -> dict:
    return (
        await client.post(
            f"{API}/sessions/{session_id}/tongue/image",
            headers=headers,
            files={"file": ("tongue.jpg", content, content_type)},
            data={"source": "upload"},
        )
    ).json()


# ---- T1 上传与质量校验 ----
async def test_upload_requires_auth(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        f"{API}/sessions/s_x/tongue/image",
        files={"file": ("t.jpg", _good_tongue_image(), "image/jpeg")},
        data={"source": "upload"},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


async def test_upload_quality_pass(api_client: AsyncClient, headers: dict[str, str]) -> None:
    body = await _upload(api_client, headers, _good_tongue_image())
    assert body["code"] == 0
    data = body["data"]
    assert data["record_id"].startswith("t_")
    assert data["image_ref"].startswith("img://tongue/")
    assert data["quality"]["passed"] is True
    assert data["quality"]["composition"] >= 0.7


async def test_upload_quality_fail_returns_42201(
    api_client: AsyncClient, headers: dict[str, str]
) -> None:
    resp = await api_client.post(
        f"{API}/sessions/s_tongue_bad/tongue/image",
        headers=headers,
        files={"file": ("bad.jpg", _bad_image(), "image/jpeg")},
        data={"source": "upload"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == 42201
    assert body["data"]["passed"] is False
    assert len(body["data"]["suggestions"]) >= 1


async def test_upload_rejects_unsupported_type(
    api_client: AsyncClient, headers: dict[str, str]
) -> None:
    body = await _upload(api_client, headers, b"hello", content_type="text/plain")
    assert body["code"] == 40001


# ---- T2/T3/T4/T5 全链路 ----
async def test_full_tongue_flow(
    api_client: AsyncClient, headers: dict[str, str], use_test_session: None
) -> None:
    session_id = "s_flow_0001"
    uploaded = await _upload(api_client, headers, _good_tongue_image(), session_id=session_id)
    record_id = uploaded["data"]["record_id"]

    # T2 舌体区域提取
    extract = (
        await api_client.post(
            f"{API}/sessions/{session_id}/tongue/extract",
            headers=headers,
            json={"record_id": record_id},
        )
    ).json()
    assert extract["code"] == 0
    assert extract["data"]["mask_ref"].endswith("mask.png")
    assert extract["data"]["status"] in {"analyzed", "extracting"}

    # 掩膜可通过媒体接口读取
    media = await api_client.get(f"{API}/tongue/media/{record_id}/mask.png")
    assert media.status_code == 200
    assert media.content[:8] == b"\x89PNG\r\n\x1a\n"

    # T3 舌象特征识别
    analyze = (
        await api_client.post(
            f"{API}/sessions/{session_id}/tongue/analyze",
            headers=headers,
            json={"record_id": record_id},
        )
    ).json()
    assert analyze["code"] == 0
    assert 0 < analyze["data"]["overall_confidence"] <= 1
    assert len(analyze["data"]["features"]) == 4

    # T4 AI 分析（异步）→ T5 查询
    started = (
        await api_client.post(
            f"{API}/sessions/{session_id}/tongue/ai-analysis",
            headers=headers,
            json={"record_id": record_id, "language": "zh-CN"},
        )
    ).json()
    assert started["code"] == 0
    assert started["data"]["task_id"].startswith("task_")

    result = (
        await api_client.get(f"{API}/sessions/{session_id}/tongue/analysis", headers=headers)
    ).json()
    assert result["code"] == 0
    assert result["data"]["status"] == "completed"
    assert result["data"]["result"]["tongue_summary"]
    assert result["data"]["result"]["main_syndrome"]["name"]


async def test_analyze_uses_algo_vision_when_available(
    api_client: AsyncClient, headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """算法服务视觉识别可用时，T3 返回其特征。"""
    vision_features = [
        {"name": "tongue_color", "label": "红", "confidence": 0.83},
        {"name": "coating_color", "label": "黄", "confidence": 0.79},
        {"name": "coating_texture", "label": "腻", "confidence": 0.72},
        {"name": "tongue_shape", "label": "齿痕", "confidence": 0.81},
    ]

    async def _vision_ok(module: str, image: bytes, names: list[str]) -> tuple[list[dict], str]:
        assert module == "tongue"
        return [f for f in vision_features if f["name"] in names], "tongue_vl_v1_qwen3-vl-plus"

    monkeypatch.setattr(algo_vision, "classify_features", _vision_ok)

    session_id = "s_vision_tongue_01"
    uploaded = await _upload(api_client, headers, _good_tongue_image(), session_id=session_id)
    record_id = uploaded["data"]["record_id"]

    body = (
        await api_client.post(
            f"{API}/sessions/{session_id}/tongue/analyze",
            headers=headers,
            json={"record_id": record_id},
        )
    ).json()
    assert body["code"] == 0
    features = {f["name"]: f for f in body["data"]["features"]}
    assert features["tongue_color"]["label"] == "红"
    assert features["tongue_shape"]["label"] == "齿痕"
    assert 0 < body["data"]["overall_confidence"] <= 1


async def test_extract_missing_record_returns_40400(
    api_client: AsyncClient, headers: dict[str, str]
) -> None:
    body = (
        await api_client.post(
            f"{API}/sessions/s_none/tongue/extract",
            headers=headers,
            json={"record_id": "t_9999"},
        )
    ).json()
    assert body["code"] == 40400


async def test_analysis_before_start_returns_40400(
    api_client: AsyncClient, headers: dict[str, str]
) -> None:
    session_id = "s_nostart_0001"
    await _upload(api_client, headers, _good_tongue_image(), session_id=session_id)

    resp = await api_client.get(f"{API}/sessions/{session_id}/tongue/analysis", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["code"] == 40400


# ---- T0 查询采集状态（切换模块后返回时恢复进度）----
async def test_record_state_requires_auth(api_client: AsyncClient) -> None:
    resp = await api_client.get(f"{API}/sessions/s_x/tongue/record")
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


async def test_record_state_null_without_capture(
    api_client: AsyncClient, headers: dict[str, str]
) -> None:
    body = (
        await api_client.get(f"{API}/sessions/s_empty_rec/tongue/record", headers=headers)
    ).json()
    assert body["code"] == 0
    assert body["data"] is None


async def test_record_state_restores_progress(
    api_client: AsyncClient, headers: dict[str, str], use_test_session: None
) -> None:
    session_id = "s_restore_0001"
    uploaded = await _upload(api_client, headers, _good_tongue_image(), session_id=session_id)
    record_id = uploaded["data"]["record_id"]

    await api_client.post(
        f"{API}/sessions/{session_id}/tongue/extract",
        headers=headers,
        json={"record_id": record_id},
    )
    await api_client.post(
        f"{API}/sessions/{session_id}/tongue/analyze",
        headers=headers,
        json={"record_id": record_id},
    )
    await api_client.post(
        f"{API}/sessions/{session_id}/tongue/ai-analysis",
        headers=headers,
        json={"record_id": record_id, "language": "zh-CN"},
    )

    body = (
        await api_client.get(f"{API}/sessions/{session_id}/tongue/record", headers=headers)
    ).json()
    assert body["code"] == 0
    data = body["data"]
    assert data["record_id"] == record_id
    assert data["image_ref"].startswith("img://tongue/")
    assert data["quality"]["passed"] is True
    assert data["extract"]["mask_ref"].endswith("mask.png")
    assert len(data["analyze"]["features"]) == 4
    assert data["analysis"]["status"] == "completed"
    assert data["analysis"]["result"]["tongue_summary"]


# ---- 重复采集：同一会话复用同一条记录，原图覆盖在同一路径（不产生重复文件）----
async def test_recapture_overwrites_image_in_place(
    api_client: AsyncClient, headers: dict[str, str], use_test_session: None
) -> None:
    session_id = "s_recapture_0001"
    first = await _upload(api_client, headers, _good_tongue_image(), session_id=session_id)
    second = await _upload(api_client, headers, _good_tongue_image(), session_id=session_id)

    # 会话内仍只有一条记录，且原图路径不变（覆盖而非另存一份）
    assert first["data"]["record_id"] == second["data"]["record_id"]
    assert first["data"]["image_ref"] == second["data"]["image_ref"]

    record_id = second["data"]["record_id"]
    name = second["data"]["image_ref"].split("/")[-1]
    media = await api_client.get(f"{API}/tongue/media/{record_id}/{name}")
    assert media.status_code == 200
    assert media.headers["cache-control"] == "no-store"

    # 记录目录内只有这一张原图，重复采集不留多余文件
    record_dir = Path(settings.MEDIA_ROOT) / "tongue" / record_id
    assert [p.name for p in record_dir.iterdir() if p.name.startswith("raw.")] == [name]


# ---- 服务层：未检出舌体 → 42201 ----
def test_extract_region_without_tongue_raises() -> None:
    img = Image.new("RGB", (320, 240), (10, 10, 10))
    buffer = BytesIO()
    img.save(buffer, format="JPEG")
    with pytest.raises(BusinessError) as exc:
        tongue_detection.extract_region(buffer.getvalue())
    assert exc.value.code == int(ErrorCode.IMAGE_QUALITY)