"""阿里云百炼（DashScope）通义千问客户端 —— OpenAI 兼容接口。

- 端点：`POST {DASHSCOPE_BASE_URL}/chat/completions`，鉴权 `Authorization: Bearer <key>`；
- 强制 JSON 输出（`response_format={"type": "json_object"}`，prompt 内含 "JSON" 关键词）；
- 429 / 5xx 重试 1 次；其余异常统一抛 `LLMError`，由 `main.py` 映射 503 交后端降级。

配置通过环境变量 / `.env` 注入（密钥不落代码、不入库）。
"""

from __future__ import annotations

import asyncio

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """算法服务配置（字段名即环境变量名）。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DASHSCOPE_API_KEY: str = ""
    DASHSCOPE_BASE_URL: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    LLM_MODEL: str = "qwen-plus"
    #: 视觉模型（舌象 / 面象特征识别）；qwen3-vl-plus 为当前 Key 实测可用型号
    VL_MODEL: str = "qwen3-vl-plus"
    LLM_TIMEOUT_SECONDS: int = 60


settings = Settings()


class LLMError(RuntimeError):
    """调用大模型失败（网络 / 超时 / 非 2xx / 响应结构异常）。"""


async def chat_json(system: str, user: str, *, model: str | None = None) -> str:
    """调用通义千问并返回其 JSON 文本内容（不做解析）。"""
    payload = {
        "model": model or settings.LLM_MODEL,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {settings.DASHSCOPE_API_KEY}"}
    url = f"{settings.DASHSCOPE_BASE_URL}/chat/completions"

    for attempt in (0, 1):
        try:
            async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
                response = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:  # 网络异常 / 超时
            if attempt == 0:
                await asyncio.sleep(1)
                continue
            raise LLMError(f"调用大模型失败：{exc}") from exc

        if response.status_code == 200:
            try:
                return response.json()["choices"][0]["message"]["content"]
            except (KeyError, IndexError, ValueError, TypeError) as exc:
                raise LLMError(f"大模型响应结构异常：{exc}") from exc

        if (response.status_code == 429 or response.status_code >= 500) and attempt == 0:
            await asyncio.sleep(1)
            continue
        raise LLMError(f"DashScope 返回 {response.status_code}：{response.text[:200]}")

    raise LLMError("调用大模型失败")


async def chat_vision_json(system: str, user: str, image_base64: str, *, model: str | None = None) -> str:
    """调用视觉大模型（qwen-vl 系列）看图并返回其 JSON 文本内容（不做解析）。

    图片以 base64 data URL 内联传输；重试策略与 `chat_json` 一致。
    """
    payload = {
        "model": model or settings.VL_MODEL,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
                    },
                    {"type": "text", "text": user},
                ],
            },
        ],
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {settings.DASHSCOPE_API_KEY}"}
    url = f"{settings.DASHSCOPE_BASE_URL}/chat/completions"

    for attempt in (0, 1):
        try:
            async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
                response = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:  # 网络异常 / 超时
            if attempt == 0:
                await asyncio.sleep(1)
                continue
            raise LLMError(f"调用视觉大模型失败：{exc}") from exc

        if response.status_code == 200:
            try:
                return response.json()["choices"][0]["message"]["content"]
            except (KeyError, IndexError, ValueError, TypeError) as exc:
                raise LLMError(f"视觉大模型响应结构异常：{exc}") from exc

        if (response.status_code == 429 or response.status_code >= 500) and attempt == 0:
            await asyncio.sleep(1)
            continue
        raise LLMError(f"DashScope 返回 {response.status_code}：{response.text[:200]}")

    raise LLMError("调用视觉大模型失败")


__all__ = ["settings", "chat_json", "chat_vision_json", "LLMError"]
