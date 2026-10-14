"""报告接口（《开发任务文档》§4.9 M6；PRD §6.5 / §9.6）。

本模块覆盖「导出 PDF（R3）/ 归档（R5）/ 删除（R6）」与「报告对比（R-CMP，P8）」；报告记录在
合参完成时自动生成（M5-7），历史检索（R4）落在 `diagnosis.py` 的报告历史接口，分享（R7~R8）后续接入。所有接口需登录态。
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from app.api.deps import CurrentUser, DbSession
from app.core.errors import ErrorCode
from app.core.response import BusinessError, success
from app.models.diagnosis import Report
from app.schemas.report import ArchiveReportResponse, DeleteReportResponse
from app.services import compare_service, report_service

router = APIRouter(tags=["reports"])


async def _get_report_or_404(db: DbSession, report_id: str) -> Report:
    report = await report_service.get_report(db, report_id)
    if report is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "报告不存在")
    return report


# ---- R-CMP 报告对比（P8 数据对比页；UI/UX §5.7）----
@router.get("/reports/compare", summary="R-CMP 报告对比")
async def compare_reports(
    db: DbSession,
    current_user: CurrentUser,
    base: str = Query(..., description="基准报告号"),
    target: str = Query(..., description="对比报告号"),
    trend: int = Query(5, description="置信度趋势范围（近 N 次，2 ≤ N ≤ 20）"),
) -> dict:
    if base == target:
        raise BusinessError(ErrorCode.PARAM_INVALID, "请选择两条不同的报告进行对比")
    if trend < 2 or trend > 20:
        raise BusinessError(ErrorCode.PARAM_INVALID, "趋势范围需在 2~20 之间")

    base_report = await _get_report_or_404(db, base)
    target_report = await _get_report_or_404(db, target)
    result = await compare_service.build_compare(
        db, base_report, target_report, trend_limit=trend
    )
    return success(result.model_dump(mode="json"))


# ---- R3 导出 PDF ----
@router.get("/reports/{report_id}/pdf", summary="R3 导出报告 PDF")
async def export_report_pdf(
    report_id: str, db: DbSession, current_user: CurrentUser
) -> FileResponse:
    report = await _get_report_or_404(db, report_id)
    path = await report_service.ensure_pdf(db, report)
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=report_service.pdf_filename(report),
    )


# ---- R5 归档报告 ----
@router.post("/reports/{report_id}/archive", summary="R5 归档报告")
async def archive_report(
    report_id: str, db: DbSession, current_user: CurrentUser
) -> dict:
    report = await _get_report_or_404(db, report_id)
    report = await report_service.archive_report(db, report)
    return success(
        ArchiveReportResponse(
            report_id=report.report_no,
            status=report.status,
            archived_at=report.archived_at,
        ).model_dump(mode="json")
    )


# ---- R6 删除报告 ----
@router.delete("/reports/{report_id}", summary="R6 删除报告")
async def delete_report(
    report_id: str, db: DbSession, current_user: CurrentUser
) -> dict:
    report = await _get_report_or_404(db, report_id)
    await report_service.delete_report(db, report, actor_no=current_user.user_no)
    return success(
        DeleteReportResponse(report_id=report.report_no).model_dump(mode="json")
    )