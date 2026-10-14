"""三诊合一算法服务（独立进程，监听 :8100）。

契约（《开发任务文档》§4.10）：
- `GET /health`  健康检查
- `POST /llm/analyze`  入参 `{module, payload, language}`，出参 `{data: {...}}`
- `POST /vision/classify`  入参 `{module, image_base64, feature_names}`，
  调用视觉大模型（qwen-vl 系列）直接看图提取结构化特征，出参 `{data: {features, model_version}}`

行为：调用阿里云通义千问生成可读结论；失败（未配置密钥 / 网络 / 超时 / 解析失败）
一律返回 503，由后端 `*_ai_analysis.py` / F3 / T3 既有机制降级到规则 mock，链路不中断。

启动：`uvicorn main:app --port 8100`（在 algorithm-service 目录下执行）
日志：终端与 `logs/alg.log` 双写（滚动保留 5 份，含 uvicorn 访问日志），便于回溯大模型调用。
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from llm_client import LLMError, chat_json, chat_vision_json, settings
from parsing import normalize_features, normalize_output, parse_json_safely
from prompts import build_prompt, build_vision_prompt
from schemas import AnalyzeRequest, VisionClassifyRequest

LOG_DIR = Path(__file__).resolve().parent / "logs"


def _configure_logging() -> None:
    """终端 + 滚动文件双输出（含 uvicorn 访问日志）。"""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    handlers.append(
        RotatingFileHandler(
            LOG_DIR / "alg.log",
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
    )
    for handler in handlers:
        handler.setFormatter(formatter)
    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True)
    # uvicorn 自带 logger 默认不向 root 传播，显式挂同一组 handler 才能一并落盘
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = list(handlers)
        uvicorn_logger.propagate = False


_configure_logging()

app = FastAPI(title="三诊合一 算法服务", version="0.2.0")


@app.get("/health")
async def health() -> dict:
    """健康检查：暴露当前模型与密钥是否就绪。"""
    return {
        "status": "ok",
        "model": settings.LLM_MODEL,
        "vl_model": settings.VL_MODEL,
        "key_configured": bool(settings.DASHSCOPE_API_KEY),
    }


@app.post("/llm/analyze")
async def analyze(request: AnalyzeRequest) -> JSONResponse:
    """四模块共用的可读结论生成入口。"""
    if not settings.DASHSCOPE_API_KEY:
        raise HTTPException(status_code=503, detail="未配置 DASHSCOPE_API_KEY")

    system, user = build_prompt(request.module, request.payload, request.language)
    try:
        raw = await chat_json(system, user)
        data = parse_json_safely(raw)
    except (LLMError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    model_version = f"{request.module}_llm_v1_{settings.LLM_MODEL}"
    output = normalize_output(request.module, data, model_version=model_version)
    return JSONResponse({"data": output})


@app.post("/vision/classify")
async def vision_classify(request: VisionClassifyRequest) -> JSONResponse:
    """舌象 / 面象图片特征提取：视觉大模型直接看图输出结构化特征。"""
    if not settings.DASHSCOPE_API_KEY:
        raise HTTPException(status_code=503, detail="未配置 DASHSCOPE_API_KEY")

    system, user = build_vision_prompt(request.module)
    try:
        raw = await chat_vision_json(system, user, request.image_base64)
        data = parse_json_safely(raw)
        features = normalize_features(request.module, data, request.feature_names)
    except (LLMError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return JSONResponse(
        {
            "data": {
                "features": features,
                "model_version": f"{request.module}_vl_v1_{settings.VL_MODEL}",
            }
        }
    )
