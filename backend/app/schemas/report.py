"""报告请求 / 响应模型（《开发任务文档》§4.9 R1~R5；PRD §6.5 / §9.6）。

本模块覆盖「生成 / 详情 / 导出 PDF / 归档」；历史检索、删除、分享（R4/R6~R8）后续接入。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.models.diagnosis import HealthLevel, ReportStatus
from app.schemas.diagnosis import PatientSnapshot, ReportData


class GenerateReportResponse(BaseModel):
    """R1 响应 `data`。"""

    report_id: str
    status: ReportStatus


class ReportDetailData(BaseModel):
    """R2 响应 `data`：报告头 + 8 Tab 渲染数据 + PDF 地址。"""

    report_id: str
    session_id: str
    status: ReportStatus
    generated_at: datetime
    archived_at: datetime | None = None
    patient_snapshot: PatientSnapshot | None = None
    overall_confidence: float | None = None
    health_level: HealthLevel | None = None
    summary: str | None = None
    rule_version: str | None = None
    model_version: str | None = None
    pdf_url: str | None = None
    report: ReportData


class ArchiveReportResponse(BaseModel):
    """R5 响应 `data`。"""

    report_id: str
    status: ReportStatus
    archived_at: datetime | None = None


class DeleteReportResponse(BaseModel):
    """R6 响应 `data`。"""

    report_id: str
    deleted: bool = True