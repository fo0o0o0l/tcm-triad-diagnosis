"""面象 AI 分析（M3-5，F4/F5）。

- F4：创建 `face_analyses` 版本化记录（`is_current=true`）并入队后台任务，立即返回 `task_id`；
- 后台任务：调用算法/LLM 服务（`POST {ALGO_BASE_URL}/llm/analyze`），失败或超时则降级到
  `face_mock_analysis`，保证链路不中断；结果写回分析记录（PRD §6.2.4）。
- F5：返回当前有效版本；`failed` 时给出 `retryable`。
"""

from __future__ import annotations

import uuid

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.errors import ErrorCode
from app.core.logging import get_logger
from app.models.diagnosis import AnalysisStatus, FaceAnalysis, FaceRecord
from app.services import face_mock_analysis

logger = get_logger(__name__)


async def create_analysis_task(db: AsyncSession, record: FaceRecord) -> FaceAnalysis:
    """归档旧版本并创建新的 `analyzing` 分析记录，返回带 `task_id` 的版本。"""
    await db.execute(
        update(FaceAnalysis)
        .where(
            FaceAnalysis.record_id == record.id,
            FaceAnalysis.is_current.is_(True),
        )
        .values(is_current=False)
    )
    row = FaceAnalysis(
        analysis_no=f"tmp_{uuid.uuid4().hex[:24]}",
        record_id=record.id,
        status=AnalysisStatus.ANALYZING,
        is_current=True,
    )
    db.add(row)
    await db.flush()
    row.analysis_no = f"fa_{row.id}"
    row.task_id = f"task_{row.id}"
    await db.commit()
    await db.refresh(row)
    return row


async def get_current_analysis(db: AsyncSession, record_id: int) -> FaceAnalysis | None:
    """查询某记录当前有效版本的分析结果。"""
    stmt = select(FaceAnalysis).where(
        FaceAnalysis.record_id == record_id,
        FaceAnalysis.is_current.is_(True),
    )
    return await db.scalar(stmt)


async def execute_analysis(analysis_id: int) -> None:
    """后台任务入口：独立会话执行分析并写回结果（供 BackgroundTasks 调用）。"""
    async with AsyncSessionLocal() as db:
        row = await db.get(FaceAnalysis, analysis_id)
        if row is None:
            return
        record = await db.get(FaceRecord, row.record_id)
        features = (record.features if record else None) or []
        try:
            result = await analyze_features(features, language="zh-CN")
            row.face_summary = result["face_summary"]
            row.main_syndrome = result["main_syndrome"]
            row.secondary_syndromes = result["secondary_syndromes"]
            row.treatment_principles = result["treatment_principles"]
            row.recommendations = result["recommendations"]
            row.model_version = result["model_version"]
            row.status = AnalysisStatus.COMPLETED
            row.error_code = None
        except Exception as exc:  # noqa: BLE001 - 兜底：任何异常均置 failed 且可重试
            logger.warning("face_analysis_failed", analysis_no=row.analysis_no, error=str(exc))
            row.status = AnalysisStatus.FAILED
            row.error_code = str(int(ErrorCode.ALGO_UNAVAILABLE))
            row.retryable = True
        await db.commit()


async def analyze_features(features: list[dict], *, language: str = "zh-CN") -> dict:
    """优先调用算法服务，不可用时降级到规则 Mock。"""
    try:
        result = await _call_algo(features, language=language)
        if result is not None:
            return result
    except Exception as exc:  # noqa: BLE001 - 网络/超时/解析失败统一降级
        logger.warning("face_algo_unavailable", error=str(exc))
    return face_mock_analysis.analyze(features, language=language)


async def _call_algo(features: list[dict], *, language: str) -> dict | None:
    """调用算法服务 `/llm/analyze`；返回规范化后的结果，未就绪时返回 None。"""
    url = f"{settings.ALGO_BASE_URL}/llm/analyze"
    payload = {
        "module": "face",
        "payload": {"features": features},
        "language": language,
    }
    async with httpx.AsyncClient(timeout=settings.ALGO_TIMEOUT_SECONDS) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        body = response.json()

    data = body.get("data", body) if isinstance(body, dict) else {}
    if not data:
        return None
    return {
        "face_summary": data.get("face_summary") or "暂无",
        "main_syndrome": data.get("main_syndrome"),
        "secondary_syndromes": data.get("secondary_syndromes") or [],
        "treatment_principles": data.get("treatment_principles") or [],
        "recommendations": data.get("recommendations") or [],
        "model_version": data.get("model_version") or "face_llm_v1",
    }