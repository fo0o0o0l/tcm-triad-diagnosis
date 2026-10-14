"""视觉特征识别客户端（F3 / T3）：调用算法服务 `POST /vision/classify`。

视觉大模型直接对舌象 / 面象原图提取结构化特征，替代本地启发式规则；
服务未就绪 / 超时 / 返回异常时返回 None，由调用方降级到
`face_detection` / `tongue_detection` 本地启发式，链路不中断。
"""

from __future__ import annotations

import base64

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


async def classify_features(
    module: str, image: bytes, feature_names: list[str]
) -> tuple[list[dict], str] | None:
    """返回 `(features, model_version)`；任何失败均返回 None（由调用方降级）。"""
    url = f"{settings.ALGO_BASE_URL}/vision/classify"
    payload = {
        "module": module,
        "image_base64": base64.b64encode(image).decode(),
        "feature_names": feature_names,
    }
    try:
        async with httpx.AsyncClient(timeout=settings.ALGO_TIMEOUT_SECONDS) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            body = response.json()
    except Exception as exc:  # noqa: BLE001 - 网络/超时/解析失败统一降级
        logger.warning("algo_vision_unavailable", module=module, error=str(exc))
        return None

    data = body.get("data", body) if isinstance(body, dict) else {}
    features = data.get("features") if isinstance(data, dict) else None
    if not isinstance(features, list) or not features:
        logger.warning("algo_vision_invalid_response", module=module)
        return None
    return features, str(data.get("model_version") or f"{module}_vl_v1")
