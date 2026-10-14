"""面诊模块端到端用例（《开发任务文档》M3-7 / §4.6 F1~F5）。

覆盖：质量校验通过/多脸/无脸阻断、格式与鉴权校验、检测→特征→AI 全链路、
错误码 40001/40100/40400/42201。
"""

from __future__ import annotations

from io import BytesIO

import pytest
import pytest_asyncio
from httpx import AsyncClient
from PIL import Image, ImageDraw

from app.core.errors import ErrorCode
from app.core.response import BusinessError
from app.services import algo_vision
from app.services import auth as auth_service
from app.services import face_ai_analysis, face_detection

API = "/api/v1"
FIXED_CODE = "123456"
PASSWORD = "Abc@123456"
USERNAME = "face_doc"
EMAIL = "face_doc@example.com"


def _draw_face(draw: ImageDraw.ImageDraw, box: list[int]) -> None:
    """在 box 内绘制带纹理的肤色椭圆（保证清晰度与肤色连通域）。"""
    x0, y0, x1, y1 = box
    draw.ellipse(box, fill=(232, 168, 150))
    for x in range(x0, x1, 16):
        draw.line([(x, y0), (x, y1)], fill=(200, 140, 126), width=2)
    for y in range(y0, y1, 16):
        draw.line([(x0, y), (x1, y)], fill=(200, 140, 126), width=2)


def _good_face_image() -> bytes:
    """清晰、光照均匀、单张正脸占比充足的合成图像（保证质量校验通过）。"""
    img = Image.new("RGB", (640, 480), (110, 112, 122))
    _draw_face(ImageDraw.Draw(img), [150, 90, 490, 400])
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()


def _two_face_image() -> bytes:
    """含两张分离人脸轮廓的图像（触发单脸校验失败）。"""
    img = Image.new("RGB", (640, 480), (110, 112, 122))
    draw = ImageDraw.Draw(img)
    _draw_face(draw, [40, 120, 240, 360])
    _draw_face(draw, [400, 120, 600, 360])
    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()


def _no_face_image() -> bytes:
    """暗且模糊、无肤色区域的图像（质量校验应阻断）。"""
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
    monkeypatch.setattr(face_ai_analysis, "_call_algo", _no_algo)

    async def _no_vision(*_args: object, **_kwargs: object) -> None:
        return None

    # 默认算法服务视觉识别不可用 → F3 降级本地启发式，保证用例不依赖外部进程
    monkeypatch.setattr(algo_vision, "classify_features", _no_vision)


@pytest_asyncio.fixture
async def use_test_session(monkeypatch: pytest.MonkeyPatch, db_session: object) -> None:
    """让后台 AI 任务复用用例事务会话，保证未提交数据可见。"""

    class _Ctx:
        async def __aenter__(self) -> object:
            return db_session

        async def __aexit__(self, *_exc: object) -> bool:
            return False

    monkeypatch.setattr(face_ai_analysis, "AsyncSessionLocal", lambda: _Ctx())


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
            "name": "面诊医师",
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
    session_id: str = "s_face_0001",
    content_type: str = "image/jpeg",
) -> dict:
    return (
        await client.post(
            f"{API}/sessions/{session_id}/face/image",
            headers=headers,
            files={"file": ("face.jpg", content, content_type)},
            data={"source": "upload"},
        )
    ).json()


# ---- F1 上传与质量校验 ----
async def test_upload_requires_auth(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        f"{API}/sessions/s_x/face/image",
        files={"file": ("f.jpg", _good_face_image(), "image/jpeg")},
        data={"source": "upload"},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


async def test_upload_quality_pass(api_client: AsyncClient, headers: dict[str, str]) -> None:
    body = await _upload(api_client, headers, _good_face_image())
    assert body["code"] == 0
    data = body["data"]
    assert data["record_id"].startswith("f_")
    assert data["image_ref"].startswith("img://face/")
    assert data["quality"]["passed"] is True
    assert data["quality"]["face_detected"] is True
    assert data["quality"]["single_face"] is True


async def test_upload_multi_face_returns_42201(
    api_client: AsyncClient, headers: dict[str, str]
) -> None:
    resp = await api_client.post(
        f"{API}/sessions/s_face_multi/face/image",
        headers=headers,
        files={"file": ("multi.jpg", _two_face_image(), "image/jpeg")},
        data={"source": "upload"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == 42201
    assert body["data"]["single_face"] is False


async def test_upload_no_face_returns_42201(
    api_client: AsyncClient, headers: dict[str, str]
) -> None:
    resp = await api_client.post(
        f"{API}/sessions/s_face_none/face/image",
        headers=headers,
        files={"file": ("none.jpg", _no_face_image(), "image/jpeg")},
        data={"source": "upload"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == 42201
    assert body["data"]["face_detected"] is False
    assert len(body["data"]["suggestions"]) >= 1


async def test_upload_rejects_unsupported_type(
    api_client: AsyncClient, headers: dict[str, str]
) -> None:
    body = await _upload(api_client, headers, b"hello", content_type="text/plain")
    assert body["code"] == 40001


# ---- F2/F3/F4/F5 全链路 ----
async def test_full_face_flow(
    api_client: AsyncClient, headers: dict[str, str], use_test_session: None
) -> None:
    session_id = "s_flow_face_0001"
    uploaded = await _upload(api_client, headers, _good_face_image(), session_id=session_id)
    record_id = uploaded["data"]["record_id"]

    # F2 面部区域检测
    detect = (
        await api_client.post(
            f"{API}/sessions/{session_id}/face/detect",
            headers=headers,
            json={"record_id": record_id},
        )
    ).json()
    assert detect["code"] == 0
    assert detect["data"]["face_count"] == 1
    assert len(detect["data"]["regions"]) == 5
    assert detect["data"]["status"] in {"analyzed", "extracting"}

    # 原图可通过媒体接口读取（文件名从 image_ref 推导）
    raw_name = uploaded["data"]["image_ref"].split("/")[-1]
    media = await api_client.get(f"{API}/face/media/{record_id}/{raw_name}")
    assert media.status_code == 200
    assert media.content[:2] == b"\xff\xd8"

    # F3 面象特征识别
    analyze = (
        await api_client.post(
            f"{API}/sessions/{session_id}/face/analyze",
            headers=headers,
            json={"record_id": record_id},
        )
    ).json()
    assert analyze["code"] == 0
    assert 0 < analyze["data"]["overall_confidence"] <= 1
    assert len(analyze["data"]["features"]) == 4
    names = {feature["name"] for feature in analyze["data"]["features"]}
    assert names == {"face_color", "luster", "acne", "spots"}

    # F4 AI 分析（异步）→ F5 查询
    started = (
        await api_client.post(
            f"{API}/sessions/{session_id}/face/ai-analysis",
            headers=headers,
            json={"record_id": record_id, "language": "zh-CN"},
        )
    ).json()
    assert started["code"] == 0
    assert started["data"]["task_id"].startswith("task_")

    result = (
        await api_client.get(f"{API}/sessions/{session_id}/face/analysis", headers=headers)
    ).json()
    assert result["code"] == 0
    assert result["data"]["status"] == "completed"
    assert result["data"]["result"]["face_summary"]
    assert result["data"]["result"]["main_syndrome"]["name"]


async def test_analyze_uses_algo_vision_when_available(
    api_client: AsyncClient, headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """算法服务视觉识别可用时，F3 返回其特征（含痘痘分布区域）。"""
    vision_features = [
        {"name": "face_color", "label": "潮红", "confidence": 0.81},
        {"name": "luster", "label": "油光", "confidence": 0.77},
        {"name": "acne", "label": "中等", "confidence": 0.88, "area": ["nose", "chin"]},
        {"name": "spots", "label": "无", "confidence": 0.9},
    ]

    async def _vision_ok(module: str, image: bytes, names: list[str]) -> tuple[list[dict], str]:
        assert module == "face"
        return [f for f in vision_features if f["name"] in names], "face_vl_v1_qwen3-vl-plus"

    monkeypatch.setattr(algo_vision, "classify_features", _vision_ok)

    session_id = "s_vision_face_0001"
    uploaded = await _upload(api_client, headers, _good_face_image(), session_id=session_id)
    record_id = uploaded["data"]["record_id"]

    body = (
        await api_client.post(
            f"{API}/sessions/{session_id}/face/analyze",
            headers=headers,
            json={"record_id": record_id},
        )
    ).json()
    assert body["code"] == 0
    features = {f["name"]: f for f in body["data"]["features"]}
    assert features["acne"]["label"] == "中等"
    assert features["acne"]["area"] == ["nose", "chin"]
    assert features["face_color"]["label"] == "潮红"
    assert 0 < body["data"]["overall_confidence"] <= 1


async def test_detect_missing_record_returns_40400(
    api_client: AsyncClient, headers: dict[str, str]
) -> None:
    body = (
        await api_client.post(
            f"{API}/sessions/s_none/face/detect",
            headers=headers,
            json={"record_id": "f_9999"},
        )
    ).json()
    assert body["code"] == 40400


async def test_analysis_before_start_returns_40400(
    api_client: AsyncClient, headers: dict[str, str]
) -> None:
    session_id = "s_nostart_face_0001"
    await _upload(api_client, headers, _good_face_image(), session_id=session_id)

    resp = await api_client.get(f"{API}/sessions/{session_id}/face/analysis", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["code"] == 40400


# ---- F0 查询采集状态（切换模块后返回时恢复进度）----
async def test_record_state_requires_auth(api_client: AsyncClient) -> None:
    resp = await api_client.get(f"{API}/sessions/s_x/face/record")
    assert resp.status_code == 401
    assert resp.json()["code"] == 40100


async def test_record_state_null_without_capture(
    api_client: AsyncClient, headers: dict[str, str]
) -> None:
    body = (
        await api_client.get(f"{API}/sessions/s_empty_rec/face/record", headers=headers)
    ).json()
    assert body["code"] == 0
    assert body["data"] is None


async def test_record_state_restores_progress(
    api_client: AsyncClient, headers: dict[str, str], use_test_session: None
) -> None:
    session_id = "s_restore_face_0001"
    uploaded = await _upload(api_client, headers, _good_face_image(), session_id=session_id)
    record_id = uploaded["data"]["record_id"]

    await api_client.post(
        f"{API}/sessions/{session_id}/face/detect",
        headers=headers,
        json={"record_id": record_id},
    )
    await api_client.post(
        f"{API}/sessions/{session_id}/face/analyze",
        headers=headers,
        json={"record_id": record_id},
    )
    await api_client.post(
        f"{API}/sessions/{session_id}/face/ai-analysis",
        headers=headers,
        json={"record_id": record_id, "language": "zh-CN"},
    )

    body = (
        await api_client.get(f"{API}/sessions/{session_id}/face/record", headers=headers)
    ).json()
    assert body["code"] == 0
    data = body["data"]
    assert data["record_id"] == record_id
    assert data["image_ref"].startswith("img://face/")
    assert data["quality"]["passed"] is True
    assert data["detect"]["face_count"] == 1
    assert len(data["detect"]["regions"]) == 5
    assert len(data["analyze"]["features"]) == 4
    assert data["analysis"]["status"] == "completed"
    assert data["analysis"]["result"]["face_summary"]


# ---- 服务层：非单脸 → 42201 ----
def test_detect_regions_multi_face_raises() -> None:
    with pytest.raises(BusinessError) as exc:
        face_detection.detect_regions(_two_face_image())
    assert exc.value.code == int(ErrorCode.IMAGE_QUALITY)