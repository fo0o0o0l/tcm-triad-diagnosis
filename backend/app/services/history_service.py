"""报告历史查询服务（M6-4 / R4；PRD §6.5.4 / §9.6）。

按患者姓名、关键词（患者 / 会话号 / 结论）、时间范围、匿名与状态快捷筛选，
对 `reports` 表做分页检索，返回 `{total, page, page_size, items[]}`（开发任务文档 §4.1）。

> 说明：`reports` 表当前**无 owner/doctor 外键**，会话以不透明 `session_id` 存储，
> 故本服务不含「按医生/我的报告」过滤；仅按报告元信息维度检索，且只返回未软删记录。
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.diagnosis import Report, ReportStatus
from app.schemas.diagnosis import ReportHistoryItem


def _name_expr() -> ColumnElement[str]:
    """`patient_snapshot->>'name'` 的文本表达式（供 ILIKE 使用）。"""
    return Report.patient_snapshot["name"].astext


async def count_reports(db: AsyncSession, *, generated_from: datetime | None = None) -> int:
    """统计报告数（未软删，含已归档）。

    口径与列表检索一致：`reports` 无医生归属字段，故为全库范围统计；
    传入 `generated_from` 可做时间范围统计（如「本月报告数」，UTC 下界）。
    """
    stmt = select(func.count()).select_from(Report).where(Report.deleted_at.is_(None))
    if generated_from is not None:
        stmt = stmt.where(Report.generated_at >= generated_from)
    return int(await db.scalar(stmt) or 0)


def _build_filters(
    *,
    patient_name: str | None,
    keywords: list[str] | None,
    anonymous: bool | None,
    status: ReportStatus | None,
    date_from: date | None,
    date_to: date | None,
) -> list[Any]:
    """按检索条件拼装过滤子句（均与软删条件并存）。"""
    filters: list[Any] = [Report.deleted_at.is_(None)]

    if patient_name and patient_name.strip():
        filters.append(_name_expr().ilike(f"%{patient_name.strip()}%"))

    # 关键词：每个词都要命中「结论摘要 / 会话号 / 患者姓名」之一（多词 AND）
    for term in keywords or []:
        cleaned = term.strip()
        if not cleaned:
            continue
        pattern = f"%{cleaned}%"
        filters.append(
            or_(
                Report.summary.ilike(pattern),
                Report.session_id.ilike(pattern),
                _name_expr().ilike(pattern),
            )
        )

    if anonymous is not None:
        flag = Report.patient_snapshot["anonymous"].as_boolean().is_(True)
        filters.append(flag if anonymous else ~flag)

    if status is not None:
        filters.append(Report.status == status)

    if date_from is not None:
        filters.append(
            Report.generated_at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc)
        )
    if date_to is not None:
        filters.append(
            Report.generated_at <= datetime.combine(date_to, time.max, tzinfo=timezone.utc)
        )

    return filters


async def list_reports(
    db: AsyncSession,
    *,
    patient_name: str | None = None,
    keywords: list[str] | None = None,
    anonymous: bool | None = None,
    status: ReportStatus | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Report], int]:
    """按条件分页查询报告，返回 `(当页记录, 命中总数)`（按生成时间倒序）。"""
    filters = _build_filters(
        patient_name=patient_name,
        keywords=keywords,
        anonymous=anonymous,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )

    total = await db.scalar(select(func.count()).select_from(Report).where(*filters))
    stmt = (
        select(Report)
        .where(*filters)
        .order_by(Report.generated_at.desc(), Report.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = list((await db.scalars(stmt)).all())
    return rows, int(total or 0)


def to_history_item(report: Report) -> ReportHistoryItem:
    """把报告记录映射为历史列表项；匿名（开关开启或姓名空）时姓名置空。"""
    snapshot = report.patient_snapshot or {}
    raw_name = snapshot.get("name")
    name = str(raw_name).strip() if isinstance(raw_name, str) else ""
    is_anonymous = bool(snapshot.get("anonymous")) or not name
    return ReportHistoryItem(
        report_id=report.report_no,
        session_id=report.session_id,
        patient_name=None if is_anonymous else name,
        anonymous=is_anonymous,
        generated_at=report.generated_at,
        overall_confidence=float(report.overall_confidence)
        if report.overall_confidence is not None
        else None,
        health_level=report.health_level,
        status=report.status,
        summary=report.summary,
    )