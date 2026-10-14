"""三诊合参接口（《开发任务文档》§4.8 G0~G2；PRD §6.4 / §9.5）与报告历史查询（R4）。

路径严格对齐 PRD：`/sessions/{session_id}/fusion/...`；所有接口需登录态。
- G0 `GET .../fusion/readiness`：三诊完成态 + 缺诊判定（供 P5 页面缺诊阻断）；
- G1 `POST .../fusion/analyze`：缺诊 ≥2 阻断、`analyzing` 期间幂等拦截（40901），否则入队；
- G2 `GET .../fusion/result`：返回综合结论并附报告 8 Tab 数据（`report`）。

R4 `GET /reports`（报告历史检索）无 session 维度，按《开发任务文档》§4.9 / 模块清单归入
本文件的「诊断报告历史接口」，查询逻辑复用 `history_service`。
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, BackgroundTasks, Query

from app.api.deps import CurrentUser, DbSession
from app.core.errors import ErrorCode
from app.core.response import BusinessError, success
from app.models.diagnosis import AnalysisStatus, FusionResult, ReportStatus
from app.schemas.diagnosis import (
    Conclusion,
    Conflict,
    FusionAnalyzeRequest,
    FusionAnalyzeResponse,
    FusionResultData,
    ModuleState,
    ReadinessResponse,
    ReportData,
    ReportHistoryList,
    Suggestion,
)
from app.services import (
    history_service,
    integrated_ai_analysis,
    integrated_analysis,
    report_service,
)

router = APIRouter(tags=["diagnosis"])

#: 视为「进行中」的合参状态（幂等拦截）
_IN_PROGRESS = {AnalysisStatus.PENDING, AnalysisStatus.ANALYZING}


async def _to_fusion_data(
    db: DbSession, fusion: FusionResult, *, with_report: bool
) -> FusionResultData:
    """把合参记录映射为 G2 响应体；完成后取（或补建）报告记录并回填 8 Tab 数据。"""
    report_row = await report_service.get_or_create_report(db, fusion) if with_report else None
    report = ReportData.model_validate(report_row.report_data) if report_row else None
    return FusionResultData(
        fusion_id=fusion.fusion_no,
        session_id=fusion.session_id,
        status=fusion.status,
        overall_confidence=float(fusion.overall_confidence)
        if fusion.overall_confidence is not None
        else None,
        health_level=fusion.health_level,
        missing_modules=list(fusion.missing_modules or []),
        conflicts=[Conflict.model_validate(item) for item in (fusion.conflicts or [])],
        conclusions=[Conclusion.model_validate(item) for item in (fusion.conclusions or [])],
        syndrome_points=list(fusion.syndrome_points or []),
        suggestions=[Suggestion.model_validate(item) for item in (fusion.suggestions or [])],
        rule_version=fusion.rule_version,
        model_version=fusion.model_version,
        retryable=fusion.retryable,
        report_id=report_row.report_no if report_row else None,
        report_status=report_row.status if report_row else None,
        report=report,
    )


# ---- G0 前置校验（三诊就绪 / 缺诊阻断）----
@router.get("/sessions/{session_id}/fusion/readiness", summary="G0 三诊合参前置校验")
async def get_fusion_readiness(
    session_id: str, db: DbSession, current_user: CurrentUser
) -> dict:
    inputs = await integrated_analysis.collect_inputs(db, session_id)
    states = integrated_analysis.module_states(inputs)
    can, reason = integrated_analysis.can_analyze(inputs)
    return success(
        ReadinessResponse(
            session_id=session_id,
            modules={key: ModuleState.model_validate(value) for key, value in states.items()},
            missing_modules=inputs.missing_modules,
            can_analyze=can,
            blocking_reason=reason,
        ).model_dump(mode="json")
    )


# ---- G1 触发合参分析 ----
@router.post("/sessions/{session_id}/fusion/analyze", summary="G1 触发三诊合参分析")
async def trigger_fusion_analysis(
    session_id: str,
    db: DbSession,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
    payload: FusionAnalyzeRequest | None = None,
) -> dict:
    inputs = await integrated_analysis.collect_inputs(db, session_id)
    can, reason = integrated_analysis.can_analyze(inputs)
    if not can:
        raise BusinessError(
            ErrorCode.PARAM_INVALID,
            reason or "需三诊全部完成后方可合参",
            data={"missing_modules": inputs.missing_modules, "can_analyze": False},
        )

    existing = await integrated_ai_analysis.get_current_fusion(db, session_id)
    if existing is not None and existing.status in _IN_PROGRESS:
        raise BusinessError(
            ErrorCode.CONFLICT,
            "分析进行中，请稍后查看",
            data={"fusion_status": existing.status.value, "task_id": existing.task_id},
        )

    row = await integrated_ai_analysis.create_analysis_task(db, session_id, inputs)
    background_tasks.add_task(integrated_ai_analysis.execute_analysis, row.id)

    return success(
        FusionAnalyzeResponse(
            fusion_status=row.status, task_id=row.task_id or ""
        ).model_dump(mode="json")
    )


# ---- G2 查询合参结果 ----
@router.get("/sessions/{session_id}/fusion/result", summary="G2 查询三诊合参结果")
async def get_fusion_result(session_id: str, db: DbSession, current_user: CurrentUser) -> dict:
    fusion = await integrated_ai_analysis.get_current_fusion(db, session_id)
    if fusion is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "尚未发起三诊合参分析")

    data = await _to_fusion_data(db, fusion, with_report=fusion.status == AnalysisStatus.COMPLETED)
    return success(data.model_dump(mode="json"))


# ---- R4 报告历史查询（PRD §6.5.4 / §9.6；分页 {total, page, page_size, items[]}）----
@router.get("/reports", summary="R4 报告历史记录查询")
async def list_report_history(
    db: DbSession,
    current_user: CurrentUser,
    patient_name: str | None = None,
    keyword: list[str] | None = Query(None, description="可重复传入，多词 AND"),
    anonymous: bool | None = None,
    status: ReportStatus | None = None,
    date_from: date | None = Query(None, alias="from"),
    date_to: date | None = Query(None, alias="to"),
    page: int = 1,
    page_size: int = 20,
) -> dict:
    if page < 1 or page_size < 1 or page_size > 100:
        raise BusinessError(
            ErrorCode.PARAM_INVALID, "分页参数不合法（page ≥ 1，1 ≤ page_size ≤ 100）"
        )

    rows, total = await history_service.list_reports(
        db,
        patient_name=patient_name,
        keywords=keyword,
        anonymous=anonymous,
        status=status,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )
    payload = ReportHistoryList(
        total=total,
        page=page,
        page_size=page_size,
        items=[history_service.to_history_item(row) for row in rows],
    )
    return success(payload.model_dump(mode="json"))