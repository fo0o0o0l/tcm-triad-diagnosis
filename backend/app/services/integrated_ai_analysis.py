"""三诊合参 AI 分析（M5-4 / M5-5，G1/G2）。

- G1：归档旧版本并创建新的 `analyzing` 合参记录（`is_current=true`），入队后台任务，
  立即返回 `task_id`；归一快照、跨诊矛盾、整体置信度与健康等级在创建时即写入，
  供 P5 分析中页轮询展示；
- 后台任务：调用算法/大模型服务（`POST {ALGO_BASE_URL}/llm/analyze`，`module=fusion`），
  失败或超时降级到 `integrated_mock_analysis`，保证链路不中断；结果写回合参记录；
- G2：返回当前有效版本；`failed` 时给出 `retryable`。

并发与幂等（PRD §7.3）：`analyzing` 期间重复触发由接口层拦截（返回 40901）。
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
from app.models.diagnosis import AnalysisStatus, FusionResult
from app.services import integrated_analysis, integrated_mock_analysis, report_service

logger = get_logger(__name__)


async def get_current_fusion(db: AsyncSession, session_id: str) -> FusionResult | None:
    """查询会话当前有效版本的合参结果。"""
    stmt = select(FusionResult).where(
        FusionResult.session_id == session_id,
        FusionResult.is_current.is_(True),
    )
    return await db.scalar(stmt)


async def create_analysis_task(
    db: AsyncSession, session_id: str, inputs: integrated_analysis.FusionInputs
) -> FusionResult:
    """归档旧版本并创建新的 `analyzing` 合参记录，返回带 `task_id` 的版本。"""
    await db.execute(
        update(FusionResult)
        .where(FusionResult.session_id == session_id, FusionResult.is_current.is_(True))
        .values(is_current=False)
    )
    summary = integrated_analysis.summarize(inputs)
    row = FusionResult(
        fusion_no=f"tmp_{uuid.uuid4().hex[:24]}",
        session_id=session_id,
        status=AnalysisStatus.ANALYZING,
        overall_confidence=summary["overall_confidence"],
        health_level=summary["health_level"],
        missing_modules=summary["missing_modules"],
        conflicts=summary["conflicts"],
        conclusions=[],
        syndrome_points=[],
        suggestions=[],
        inputs_snapshot=summary["snapshot"],
        rule_version=summary["rule_version"],
        is_current=True,
    )
    db.add(row)
    await db.flush()
    row.fusion_no = f"fu_{row.id}"
    row.task_id = f"task_{row.id}"
    await db.commit()
    await db.refresh(row)
    return row


async def execute_analysis(fusion_id: int) -> None:
    """后台任务入口：独立会话执行合参并写回结果（供 BackgroundTasks 调用）。"""
    completed = False
    async with AsyncSessionLocal() as db:
        row = await db.get(FusionResult, fusion_id)
        if row is None:
            return
        try:
            inputs = await integrated_analysis.collect_inputs(db, row.session_id)
            summary = integrated_analysis.summarize(inputs)
            result = await analyze_fusion(
                summary["snapshot"],
                conflicts=summary["conflicts"],
                missing_modules=summary["missing_modules"],
                overall_confidence=summary["overall_confidence"],
                language="zh-CN",
            )
            row.inputs_snapshot = summary["snapshot"]
            row.conflicts = summary["conflicts"]
            row.missing_modules = summary["missing_modules"]
            row.overall_confidence = summary["overall_confidence"]
            row.health_level = summary["health_level"]
            row.rule_version = summary["rule_version"]
            row.conclusions = result["conclusions"]
            row.syndrome_points = result["syndrome_points"]
            row.suggestions = result["suggestions"]
            row.model_version = result["model_version"]
            row.status = AnalysisStatus.COMPLETED
            row.error_code = None
            completed = True
        except Exception as exc:  # noqa: BLE001 - 兜底：任何异常均置 failed 且可重试
            logger.warning("fusion_analysis_failed", fusion_no=row.fusion_no, error=str(exc))
            row.status = AnalysisStatus.FAILED
            row.error_code = str(int(ErrorCode.ALGO_UNAVAILABLE))
            row.retryable = True
        await db.commit()

    # 合参完成后自动生成报告记录（M5-7）；失败不影响合参结果本身，可经 G2 惰性补建
    if not completed:
        return
    try:
        async with AsyncSessionLocal() as report_db:
            fusion = await report_db.get(FusionResult, fusion_id)
            if fusion is not None:
                await report_service.get_or_create_report(report_db, fusion)
    except Exception as exc:  # noqa: BLE001 - 报告生成失败仅记录
        logger.warning("report_generation_failed", fusion_id=fusion_id, error=str(exc))


async def analyze_fusion(
    snapshot: dict[str, Any],
    *,
    conflicts: list[dict],
    missing_modules: list[str],
    overall_confidence: float,
    language: str = "zh-CN",
) -> dict:
    """优先调用算法/大模型服务，不可用时降级到规则 Mock。"""
    try:
        result = await _call_algo(
            snapshot, conflicts, missing_modules, overall_confidence, language=language
        )
        if result is not None:
            return result
    except Exception as exc:  # noqa: BLE001 - 网络/超时/解析失败统一降级
        logger.warning("fusion_algo_unavailable", error=str(exc))
    return integrated_mock_analysis.analyze(
        snapshot,
        conflicts=conflicts,
        missing_modules=missing_modules,
        overall_confidence=overall_confidence,
        language=language,
    )


async def _call_algo(
    snapshot: dict[str, Any],
    conflicts: list[dict],
    missing_modules: list[str],
    overall_confidence: float,
    *,
    language: str,
) -> dict | None:
    """调用算法服务 `/llm/analyze`；返回规范化后的结果，未就绪时返回 None。"""
    url = f"{settings.ALGO_BASE_URL}/llm/analyze"
    payload = {
        "module": "fusion",
        "payload": {
            "snapshot": snapshot,
            "conflicts": conflicts,
            "missing_modules": missing_modules,
            "overall_confidence": overall_confidence,
        },
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
        "conclusions": data.get("conclusions") or [],
        "syndrome_points": data.get("syndrome_points") or [],
        "suggestions": data.get("suggestions") or [],
        "model_version": data.get("model_version") or "fusion_llm_v1",
    }