"""问诊接口（《开发任务文档》§4.7 I1~I5；PRD §6.3 / §9.4）。

路径严格对齐 PRD：模板 `GET /inquiry/template`，其余 `/sessions/{session_id}/inquiry/...`；
所有接口需登录态。与舌诊/面诊差异：无图像，核心是「模板下发 → 草稿/提交 → AI 证候判读」。

I3 提交成功后自动触发 I4（PRD §6.3.5）；I4 亦可单独调用用于「重新分析」。
附带 `GET .../inquiry/record`（I0）供切换模块返回时恢复草稿与已提交结果。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks
from sqlalchemy import delete, select

from app.api.deps import CurrentUser, DbSession
from app.core.errors import ErrorCode
from app.core.response import BusinessError, success
from app.models.diagnosis import (
    AnalysisStatus,
    InquiryAnalysis,
    InquiryDraft,
    InquiryRecord,
    InquiryTemplate,
    ModuleStatus,
)
from app.schemas.inquiry import (
    AnswerItem,
    AiAnalysisRequest,
    AiAnalysisResponse,
    AnalysisQueryResponse,
    AnalysisResult,
    DraftRequest,
    DraftResponse,
    DraftState,
    INQUIRY_TEMPLATE_V2,
    INQUIRY_TEMPLATE_VERSION,
    PatientSnapshot,
    Recommendation,
    RecordState,
    RecordStateResponse,
    SubmitRequest,
    SubmitResponse,
    Syndrome,
    TemplateResponse,
)
from app.services import inquiry_ai_analysis

router = APIRouter(tags=["inquiry"])


# ---- 内部工具 ----
async def _load_template(db: DbSession, version: str | None = None) -> InquiryTemplate:
    """读取指定 / 当前 active 模板；active 版本落后于代码内置版本时**自愈升级**。

    - `version` 指定且非 `latest`：按版本号精确读取，不存在即 404；
    - 否则取 active 模板；若其版本 ≠ `INQUIRY_TEMPLATE_VERSION`（表为空 / 版本升级），
      停用旧 active 并写入当前版本（`INQUIRY_TEMPLATE_V2`）。旧版本行保留为历史。
    """
    if version and version != "latest":
        row = await db.scalar(select(InquiryTemplate).where(InquiryTemplate.version == version))
        if row is None:
            raise BusinessError(ErrorCode.NOT_FOUND, "问诊模板不存在")
        return row

    rows = list((await db.scalars(select(InquiryTemplate).order_by(InquiryTemplate.id))).all())
    current = next((r for r in rows if r.version == INQUIRY_TEMPLATE_VERSION), None)
    active = next((r for r in reversed(rows) if r.status == "active"), None)
    if active is not None and active.version == INQUIRY_TEMPLATE_VERSION:
        return active

    # 自愈升级：停用旧的 active 版本，写入并启用当前版本
    for row in rows:
        if row.status == "active" and row.version != INQUIRY_TEMPLATE_VERSION:
            row.status = "inactive"
    if current is None:
        current = InquiryTemplate(
            version=INQUIRY_TEMPLATE_VERSION,
            template_schema=INQUIRY_TEMPLATE_V2,
            status="active",
        )
        db.add(current)
    else:
        current.template_schema = INQUIRY_TEMPLATE_V2
        current.status = "active"
    await db.commit()
    await db.refresh(current)
    return current


def _to_answer_dict(items: list[AnswerItem]) -> dict[str, Any]:
    """`[{qid, value}]` → `{qid: value}`（后者覆盖前者）。"""
    return {item.qid: item.value for item in items}


def _is_blank(value: Any) -> bool:
    return value is None or value == "" or (isinstance(value, list) and len(value) == 0)


def _group_shown(group: dict, answers: dict[str, Any]) -> bool:
    """分组显示条件判定：无 `showWhen` 恒显示；否则需 `answers[qid] == equals`。"""
    show = group.get("showWhen")
    if not show:
        return True
    return answers.get(show.get("qid")) == show.get("equals")


def _split_missing(template_schema: dict, answers: dict[str, Any]) -> tuple[list[str], list[str]]:
    """返回 `(P0 必填缺失, P1/P2 未答项)`，均按模板顺序；隐藏分组不计入缺失。"""
    required_missing: list[str] = []
    optional_missing: list[str] = []
    for group in template_schema.get("groups", []):
        if not _group_shown(group, answers):
            continue
        for question in group.get("questions", []):
            qid = question["qid"]
            if not _is_blank(answers.get(qid)):
                continue
            if question.get("required"):
                required_missing.append(qid)
            else:
                optional_missing.append(qid)
    return required_missing, optional_missing


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _patient_snapshot(answers: dict[str, Any]) -> PatientSnapshot:
    anonymous = bool(answers.get("anonymous"))
    return PatientSnapshot(
        name=None if anonymous else (answers.get("name") or None),
        gender=answers.get("gender") if isinstance(answers.get("gender"), str) else None,
        age=_to_float(answers.get("age")),
        height=_to_float(answers.get("height")),
        weight=_to_float(answers.get("weight")),
        anonymous=anonymous,
    )


async def _get_record(db: DbSession, session_id: str, record_no: str) -> InquiryRecord:
    stmt = select(InquiryRecord).where(
        InquiryRecord.session_id == session_id,
        InquiryRecord.record_no == record_no,
        InquiryRecord.deleted_at.is_(None),
    )
    record = await db.scalar(stmt)
    if record is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "问诊记录不存在")
    return record


async def _get_session_record(db: DbSession, session_id: str) -> InquiryRecord:
    stmt = select(InquiryRecord).where(
        InquiryRecord.session_id == session_id,
        InquiryRecord.deleted_at.is_(None),
    )
    record = await db.scalar(stmt)
    if record is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "该会话尚未提交问诊")
    return record


async def _resolve_record(
    db: DbSession, session_id: str, record_no: str | None
) -> InquiryRecord:
    if record_no:
        return await _get_record(db, session_id, record_no)
    return await _get_session_record(db, session_id)


def _to_analysis_query(
    analysis: InquiryAnalysis, record: InquiryRecord
) -> AnalysisQueryResponse:
    """把分析记录映射为 I5 / I0 共用的响应体（未完成时 `result` 为 None）。"""
    result = None
    if analysis.status == AnalysisStatus.COMPLETED:
        result = AnalysisResult(
            symptoms_summary=analysis.symptoms_summary or "暂无",
            main_syndrome=Syndrome.model_validate(analysis.main_syndrome)
            if analysis.main_syndrome
            else None,
            secondary_syndromes=[
                Syndrome.model_validate(item) for item in (analysis.secondary_syndromes or [])
            ],
            treatment_principles=analysis.treatment_principles or [],
            recommendations=[
                Recommendation.model_validate(item) for item in (analysis.recommendations or [])
            ],
        )
    return AnalysisQueryResponse(
        inquiry_id=analysis.analysis_no,
        record_id=record.record_no,
        status=analysis.status,
        missing_items=list(record.missing_items or []),
        result=result,
        model_version=analysis.model_version,
        retryable=analysis.retryable,
    )


# ---- I1 获取问诊模板 ----
@router.get("/inquiry/template", summary="I1 获取问诊模板")
async def get_inquiry_template(
    db: DbSession, current_user: CurrentUser, version: str | None = None
) -> dict:
    row = await _load_template(db, version)
    return success(TemplateResponse.model_validate(row.template_schema).model_dump(mode="json"))


# ---- I2 保存服务端草稿 ----
@router.put("/sessions/{session_id}/inquiry/draft", summary="I2 保存问诊草稿")
async def save_inquiry_draft(
    session_id: str, payload: DraftRequest, db: DbSession, current_user: CurrentUser
) -> dict:
    answers = _to_answer_dict(payload.answers)
    draft = await db.scalar(select(InquiryDraft).where(InquiryDraft.session_id == session_id))
    if draft is None:
        draft = InquiryDraft(
            session_id=session_id,
            template_version=payload.template_version,
            answers=answers,
        )
        db.add(draft)
    else:
        draft.template_version = payload.template_version
        draft.answers = answers
    await db.commit()
    await db.refresh(draft)

    return success(
        DraftResponse(saved=True, updated_at=draft.updated_at).model_dump(mode="json")
    )


# ---- I3 提交问诊（并触发 I4）----
@router.post("/sessions/{session_id}/inquiry/submit", summary="I3 提交问诊")
async def submit_inquiry(
    session_id: str,
    payload: SubmitRequest,
    db: DbSession,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
) -> dict:
    template = await _load_template(db)
    answers = _to_answer_dict(payload.answers)
    # 匿名开启时姓名置空（PRD §6.3.1 联动校验）
    if answers.get("anonymous"):
        answers["name"] = ""

    # 服务端二次校验 P0 必填（前端不可信）；缺失返回 40001 + missing[] + first_missing
    required_missing, optional_missing = _split_missing(template.template_schema, answers)
    if required_missing:
        raise BusinessError(
            ErrorCode.PARAM_INVALID,
            "存在未完成的必填项",
            data={"missing": required_missing, "first_missing": required_missing[0]},
        )

    record = await db.scalar(
        select(InquiryRecord).where(
            InquiryRecord.session_id == session_id, InquiryRecord.deleted_at.is_(None)
        )
    )
    if record is None:
        record = InquiryRecord(
            record_no=f"tmp_{uuid.uuid4().hex[:24]}",
            session_id=session_id,
            template_version=payload.template_version,
        )
        db.add(record)
        await db.flush()
        record.record_no = f"q_{record.id}"

    record.template_version = payload.template_version
    record.patient_snapshot = _patient_snapshot(answers).model_dump(mode="json")
    record.answers = answers
    record.missing_items = optional_missing
    record.status = ModuleStatus.ANALYZED
    record.submitted_at = datetime.now(timezone.utc)

    # 提交成功后清空服务端草稿（PRD §6.3.3）
    await db.execute(delete(InquiryDraft).where(InquiryDraft.session_id == session_id))
    await db.commit()
    await db.refresh(record)

    # 自动触发问诊 AI 分析（PRD §6.3.5）
    analysis = await inquiry_ai_analysis.create_analysis_task(db, record)
    background_tasks.add_task(inquiry_ai_analysis.execute_analysis, analysis.id)

    return success(SubmitResponse(record_id=record.record_no, completed=True).model_dump(mode="json"))


# ---- I4 问诊 AI 分析（异步）----
@router.post("/sessions/{session_id}/inquiry/ai-analysis", summary="I4 问诊 AI 分析（异步）")
async def create_inquiry_ai_analysis(
    session_id: str,
    payload: AiAnalysisRequest,
    db: DbSession,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
) -> dict:
    record = await _resolve_record(db, session_id, payload.record_id)
    analysis = await inquiry_ai_analysis.create_analysis_task(db, record)
    background_tasks.add_task(inquiry_ai_analysis.execute_analysis, analysis.id)

    return success(
        AiAnalysisResponse(
            task_id=analysis.task_id or "",
            analysis_status=analysis.status,
        ).model_dump(mode="json")
    )


# ---- I5 查询问诊分析结果 ----
@router.get("/sessions/{session_id}/inquiry/analysis", summary="I5 查询问诊分析结果")
async def get_inquiry_analysis(
    session_id: str, db: DbSession, current_user: CurrentUser, record_id: str | None = None
) -> dict:
    record = await _resolve_record(db, session_id, record_id)
    analysis = await inquiry_ai_analysis.get_current_analysis(db, record.id)
    if analysis is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "尚未发起问诊 AI 分析")

    return success(_to_analysis_query(analysis, record).model_dump(mode="json"))


# ---- I0 查询会话问诊状态（页面重新挂载时恢复草稿 / 结果，无记录返回 null）----
@router.get("/sessions/{session_id}/inquiry/record", summary="I0 查询会话问诊状态")
async def get_inquiry_record(
    session_id: str, db: DbSession, current_user: CurrentUser
) -> dict:
    draft = await db.scalar(select(InquiryDraft).where(InquiryDraft.session_id == session_id))
    record = await db.scalar(
        select(InquiryRecord).where(
            InquiryRecord.session_id == session_id, InquiryRecord.deleted_at.is_(None)
        )
    )

    draft_state = (
        DraftState(
            template_version=draft.template_version,
            answers=draft.answers or {},
            updated_at=draft.updated_at,
        )
        if draft
        else None
    )

    record_state = None
    if record is not None:
        analysis = await inquiry_ai_analysis.get_current_analysis(db, record.id)
        record_state = RecordState(
            record_id=record.record_no,
            template_version=record.template_version,
            patient_snapshot=PatientSnapshot.model_validate(record.patient_snapshot or {}),
            answers=record.answers or {},
            missing_items=list(record.missing_items or []),
            status=record.status,
            completed=record.status == ModuleStatus.ANALYZED,
            submitted_at=record.submitted_at,
            analysis=_to_analysis_query(analysis, record) if analysis else None,
        )

    return success(
        RecordStateResponse(draft=draft_state, record=record_state).model_dump(mode="json")
    )


# ---- I6 清空会话问诊（软删记录 + 删除草稿；供「重置表单」后刷新不恢复旧数据）----
@router.delete("/sessions/{session_id}/inquiry/record", summary="I6 清空会话问诊记录与草稿")
async def clear_inquiry_record(
    session_id: str, db: DbSession, current_user: CurrentUser
) -> dict:
    record = await db.scalar(
        select(InquiryRecord).where(
            InquiryRecord.session_id == session_id,
            InquiryRecord.deleted_at.is_(None),
        )
    )
    deleted = record is not None
    if record is not None:
        record.deleted_at = datetime.now(timezone.utc)
    # 草稿一并删除（否则刷新后仍会回填已填答案）
    await db.execute(delete(InquiryDraft).where(InquiryDraft.session_id == session_id))
    await db.commit()
    return success({"session_id": session_id, "deleted": deleted})