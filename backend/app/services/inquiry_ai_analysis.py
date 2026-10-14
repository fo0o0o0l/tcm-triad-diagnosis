"""问诊 AI 分析（M4-5，I4/I5）。

- I4：创建 `inquiry_analyses` 版本化记录（`is_current=true`）并入队后台任务，立即返回 `task_id`；
- 后台任务：调用算法/LLM 服务（`POST {ALGO_BASE_URL}/llm/analyze`），失败或超时则降级到
  `inquiry_mock_analysis`，保证链路不中断；结果写回分析记录（PRD §6.3.5）。
- I5：返回当前有效版本；`failed` 时给出 `retryable`，且不阻断后续合参。
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.errors import ErrorCode
from app.core.logging import get_logger
from app.models.diagnosis import AnalysisStatus, InquiryAnalysis, InquiryRecord
from app.services import inquiry_mock_analysis

logger = get_logger(__name__)


async def create_analysis_task(db: AsyncSession, record: InquiryRecord) -> InquiryAnalysis:
    """归档旧版本并创建新的 `analyzing` 分析记录，返回带 `task_id` 的版本。"""
    await db.execute(
        update(InquiryAnalysis)
        .where(
            InquiryAnalysis.record_id == record.id,
            InquiryAnalysis.is_current.is_(True),
        )
        .values(is_current=False)
    )
    row = InquiryAnalysis(
        analysis_no=f"tmp_{uuid.uuid4().hex[:24]}",
        record_id=record.id,
        status=AnalysisStatus.ANALYZING,
        is_current=True,
    )
    db.add(row)
    await db.flush()
    row.analysis_no = f"ia_{row.id}"
    row.task_id = f"task_{row.id}"
    await db.commit()
    await db.refresh(row)
    return row


async def get_current_analysis(db: AsyncSession, record_id: int) -> InquiryAnalysis | None:
    """查询某记录当前有效版本的分析结果。"""
    stmt = select(InquiryAnalysis).where(
        InquiryAnalysis.record_id == record_id,
        InquiryAnalysis.is_current.is_(True),
    )
    return await db.scalar(stmt)


async def execute_analysis(analysis_id: int) -> None:
    """后台任务入口：独立会话执行分析并写回结果（供 BackgroundTasks 调用）。"""
    async with AsyncSessionLocal() as db:
        row = await db.get(InquiryAnalysis, analysis_id)
        if row is None:
            return
        record = await db.get(InquiryRecord, row.record_id)
        answers: dict[str, Any] = (record.answers if record else None) or {}
        missing: list[str] = list((record.missing_items if record else None) or [])
        try:
            result = await analyze_answers(answers, missing, language="zh-CN")
            row.symptoms_summary = result["symptoms_summary"]
            row.main_syndrome = result["main_syndrome"]
            row.secondary_syndromes = result["secondary_syndromes"]
            row.treatment_principles = result["treatment_principles"]
            row.recommendations = result["recommendations"]
            row.model_version = result["model_version"]
            row.status = AnalysisStatus.COMPLETED
            row.error_code = None
        except Exception as exc:  # noqa: BLE001 - 兜底：任何异常均置 failed 且可重试
            logger.warning("inquiry_analysis_failed", analysis_no=row.analysis_no, error=str(exc))
            row.status = AnalysisStatus.FAILED
            row.error_code = str(int(ErrorCode.ALGO_UNAVAILABLE))
            row.retryable = True
        await db.commit()


async def analyze_answers(
    answers: dict[str, Any], missing_items: list[str], *, language: str = "zh-CN"
) -> dict:
    """优先调用算法服务，不可用时降级到规则 Mock。"""
    try:
        result = await _call_algo(answers, missing_items, language=language)
        if result is not None:
            return result
    except Exception as exc:  # noqa: BLE001 - 网络/超时/解析失败统一降级
        logger.warning("inquiry_algo_unavailable", error=str(exc))
    return inquiry_mock_analysis.analyze(answers, missing_items=missing_items, language=language)


async def _call_algo(
    answers: dict[str, Any], missing_items: list[str], *, language: str
) -> dict | None:
    """调用算法服务 `/llm/analyze`；返回规范化后的结果，未就绪时返回 None。"""
    url = f"{settings.ALGO_BASE_URL}/llm/analyze"
    payload = {
        "module": "inquiry",
        "payload": {"answers": answers, "missing_items": missing_items},
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
        "symptoms_summary": data.get("symptoms_summary") or "暂无",
        "main_syndrome": data.get("main_syndrome"),
        "secondary_syndromes": data.get("secondary_syndromes") or [],
        "treatment_principles": data.get("treatment_principles") or [],
        "recommendations": data.get("recommendations") or [],
        "model_version": data.get("model_version") or "inquiry_llm_v1",
    }