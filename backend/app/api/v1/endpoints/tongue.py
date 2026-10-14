"""舌诊接口（《开发任务文档》§4.5 T1~T5；PRD §9.2）。

路径严格对齐 PRD：`/sessions/{session_id}/tongue/...`；所有接口需登录态。
附带 `GET /tongue/media/{record_no}/{filename}` 用于开发期读取原始图像 / 掩膜
（生产环境改为签发临时 URL，PRD §7.4）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, File, Form, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select, update

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.errors import ErrorCode
from app.core.response import BusinessError, success
from app.models.diagnosis import AnalysisStatus, ImageSource, ModuleStatus, TongueAnalysis, TongueRecord
from app.schemas.tongue import (
    AiAnalysisRequest,
    AiAnalysisResponse,
    AnalysisQueryResponse,
    AnalysisResult,
    AnalyzeRequest,
    AnalyzeResponse,
    DEFAULT_TONGUE_FEATURES,
    ExtractRequest,
    ExtractResponse,
    FeatureItem,
    QualityResult,
    Recommendation,
    RecordStateResponse,
    Syndrome,
    TongueImageResponse,
)
from app.services import (
    algo_vision,
    image_storage,
    tongue_ai_analysis,
    tongue_detection,
    tongue_mock_analysis,
)

router = APIRouter(tags=["tongue"])

RULE_VERSION = "weight_v1"


# ---- 内部工具 ----
async def _get_record(db: DbSession, session_id: str, record_no: str) -> TongueRecord:
    stmt = select(TongueRecord).where(
        TongueRecord.session_id == session_id,
        TongueRecord.record_no == record_no,
        TongueRecord.deleted_at.is_(None),
    )
    record = await db.scalar(stmt)
    if record is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "舌诊记录不存在")
    return record


async def _get_session_record(db: DbSession, session_id: str) -> TongueRecord:
    stmt = select(TongueRecord).where(
        TongueRecord.session_id == session_id,
        TongueRecord.deleted_at.is_(None),
    )
    record = await db.scalar(stmt)
    if record is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "该会话尚未采集舌象")
    return record


def _read_image(record: TongueRecord) -> bytes:
    try:
        return image_storage.read_ref(record.image_ref)
    except ValueError as exc:
        raise BusinessError(ErrorCode.NOT_FOUND, "原始图像不存在") from exc


def _to_analysis_query(analysis: TongueAnalysis, record: TongueRecord) -> AnalysisQueryResponse:
    """把分析记录映射为 T5 / T0 共用的响应体（未完成时 `result` 为 None）。"""
    result = None
    if analysis.status == AnalysisStatus.COMPLETED:
        result = AnalysisResult(
            tongue_summary=analysis.tongue_summary or "暂无",
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
        tongue_id=analysis.analysis_no,
        record_id=record.record_no,
        status=analysis.status,
        result=result,
        model_version=analysis.model_version,
        retryable=analysis.retryable,
    )


# ---- T1 上传舌象（含质量校验）----
@router.post("/sessions/{session_id}/tongue/image", summary="T1 上传舌象（含质量校验）")
async def upload_tongue_image(
    session_id: str,
    db: DbSession,
    current_user: CurrentUser,
    file: UploadFile = File(..., description="jpg/jpeg/png/webp，≤10MB"),
    source: ImageSource = Form(...),
) -> dict:
    content_type = file.content_type or ""
    if content_type not in settings.ALLOWED_IMAGE_TYPES:
        raise BusinessError(ErrorCode.PARAM_INVALID, "仅支持 jpg/jpeg/png/webp 格式")

    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_BYTES:
        limit_mb = settings.MAX_UPLOAD_BYTES // (1024 * 1024)
        raise BusinessError(ErrorCode.PARAM_INVALID, f"文件超过大小上限（{limit_mb}MB）")

    # 质量校验先于落库：不通过则阻断且不写记录（PRD §7.1）
    quality = tongue_detection.assess_quality(content)
    if not quality["passed"]:
        raise BusinessError(
            ErrorCode.IMAGE_QUALITY,
            data={
                "passed": False,
                "clearness": quality["clearness"],
                "lighting": quality["lighting"],
                "composition": quality["composition"],
                "suggestions": quality["suggestions"],
            },
        )

    # 重新采集覆盖当前记录；否则新建（PRD §6.1 处理规则 6）
    existing = await db.scalar(
        select(TongueRecord).where(
            TongueRecord.session_id == session_id, TongueRecord.deleted_at.is_(None)
        )
    )
    record = existing or TongueRecord(
        record_no=f"tmp_{uuid.uuid4().hex[:24]}",
        session_id=session_id,
        source=source,
        image_ref="",
    )
    if existing is None:
        db.add(record)
        await db.flush()
    else:
        await db.execute(
            update(TongueAnalysis)
            .where(TongueAnalysis.record_id == record.id, TongueAnalysis.is_current.is_(True))
            .values(is_current=False)
        )

    record.record_no = f"t_{record.id}" if record.record_no.startswith("tmp_") else record.record_no
    record.source = source
    # 重复采集固定覆盖同一路径（raw.{ext}），先删旧文件以处理扩展名变化
    if record.image_ref:
        image_storage.delete_ref(record.image_ref)
    record.image_ref = image_storage.save_raw_image(
        record.record_no, content, file.filename or "raw", content_type
    )
    record.quality_passed = True
    record.quality_score = quality["score"]
    record.quality_detail = {
        "clearness": quality["clearness"],
        "lighting": quality["lighting"],
        "composition": quality["composition"],
        "suggestions": quality["suggestions"],
    }
    record.mask_ref = None
    record.extract_confidence = None
    record.extract_status = ModuleStatus.PENDING
    record.features = []
    record.overall_confidence = None
    await db.commit()
    await db.refresh(record)

    return success(
        TongueImageResponse(
            record_id=record.record_no,
            image_ref=record.image_ref,
            quality=QualityResult(
                passed=True,
                clearness=quality["clearness"],
                lighting=quality["lighting"],
                composition=quality["composition"],
                suggestions=quality["suggestions"],
            ),
        ).model_dump(mode="json")
    )


# ---- T2 舌体区域提取 ----
@router.post("/sessions/{session_id}/tongue/extract", summary="T2 舌体区域提取")
async def extract_tongue_region(
    session_id: str, payload: ExtractRequest, db: DbSession, current_user: CurrentUser
) -> dict:
    record = await _get_record(db, session_id, payload.record_id)
    mask_bytes, confidence = tongue_detection.extract_region(_read_image(record))

    threshold = settings.DEFAULT_CONFIDENCE_THRESHOLD
    mask_ref = image_storage.save_mask(record.record_no, mask_bytes)
    record.mask_ref = mask_ref
    record.extract_confidence = confidence
    record.extract_status = (
        ModuleStatus.ANALYZED if confidence >= threshold else ModuleStatus.EXTRACTING
    )
    await db.commit()

    return success(
        ExtractResponse(
            record_id=record.record_no,
            mask_ref=mask_ref,
            confidence=confidence,
            status=record.extract_status,
        ).model_dump(mode="json")
    )


# ---- T3 舌象特征识别 ----
@router.post("/sessions/{session_id}/tongue/analyze", summary="T3 舌象特征识别")
async def analyze_tongue_features(
    session_id: str, payload: AnalyzeRequest, db: DbSession, current_user: CurrentUser
) -> dict:
    record = await _get_record(db, session_id, payload.record_id)
    names = payload.features or list(DEFAULT_TONGUE_FEATURES)
    image = _read_image(record)
    # 优先走视觉大模型（算法服务）；不可用时降级本地启发式，链路不中断
    vision = await algo_vision.classify_features("tongue", image, names)
    if vision is not None:
        features, rule_version = vision
    else:
        features = tongue_detection.classify_features(image, names)
        rule_version = RULE_VERSION
    overall = tongue_mock_analysis.weighted_confidence(features)

    record.features = features
    record.overall_confidence = overall
    record.rule_version = rule_version
    await db.commit()

    return success(
        AnalyzeResponse(
            record_id=record.record_no,
            overall_confidence=overall,
            features=[FeatureItem.model_validate(item) for item in features],
        ).model_dump(mode="json")
    )


# ---- T4 舌象 AI 分析（异步）----
@router.post("/sessions/{session_id}/tongue/ai-analysis", summary="T4 舌象 AI 分析（异步）")
async def create_tongue_ai_analysis(
    session_id: str,
    payload: AiAnalysisRequest,
    db: DbSession,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
) -> dict:
    record = await _get_record(db, session_id, payload.record_id)
    analysis = await tongue_ai_analysis.create_analysis_task(db, record)
    background_tasks.add_task(tongue_ai_analysis.execute_analysis, analysis.id)

    return success(
        AiAnalysisResponse(
            task_id=analysis.task_id or "",
            analysis_status=analysis.status,
        ).model_dump(mode="json")
    )


# ---- T5 查询舌象分析结果 ----
@router.get("/sessions/{session_id}/tongue/analysis", summary="T5 查询舌象分析结果")
async def get_tongue_analysis(
    session_id: str, db: DbSession, current_user: CurrentUser, record_id: str | None = None
) -> dict:
    record = (
        await _get_record(db, session_id, record_id)
        if record_id
        else await _get_session_record(db, session_id)
    )
    analysis = await tongue_ai_analysis.get_current_analysis(db, record.id)
    if analysis is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "尚未发起舌象 AI 分析")

    return success(_to_analysis_query(analysis, record).model_dump(mode="json"))


# ---- T0 查询会话当前采集状态（页面重新挂载时恢复进度）----
@router.get("/sessions/{session_id}/tongue/record", summary="T0 查询会话当前舌诊采集状态")
async def get_tongue_record(
    session_id: str, db: DbSession, current_user: CurrentUser
) -> dict:
    record = await db.scalar(
        select(TongueRecord).where(
            TongueRecord.session_id == session_id,
            TongueRecord.deleted_at.is_(None),
        )
    )
    if record is None:
        # 无采集记录：返回空数据而非错误，前端保持未采集态
        return success(None)

    detail = record.quality_detail or {}
    quality = QualityResult(
        passed=record.quality_passed,
        clearness=float(detail.get("clearness", 0.0)),
        lighting=float(detail.get("lighting", 0.0)),
        composition=float(detail.get("composition", 0.0)),
        suggestions=list(detail.get("suggestions", [])),
    )
    extract = (
        ExtractResponse(
            record_id=record.record_no,
            mask_ref=record.mask_ref or "",
            confidence=float(record.extract_confidence),
            status=record.extract_status,
        )
        if record.mask_ref and record.extract_confidence is not None
        else None
    )
    analyze = (
        AnalyzeResponse(
            record_id=record.record_no,
            overall_confidence=float(record.overall_confidence),
            features=record.features or [],
        )
        if record.overall_confidence is not None
        else None
    )
    analysis = await tongue_ai_analysis.get_current_analysis(db, record.id)

    return success(
        RecordStateResponse(
            record_id=record.record_no,
            image_ref=record.image_ref,
            quality=quality,
            extract=extract,
            analyze=analyze,
            analysis=_to_analysis_query(analysis, record) if analysis else None,
        ).model_dump(mode="json")
    )


# ---- T6 清空会话舌诊采集（软删；供「重新采集」后刷新不恢复旧数据）----
@router.delete("/sessions/{session_id}/tongue/record", summary="T6 清空会话舌诊采集记录")
async def clear_tongue_record(
    session_id: str, db: DbSession, current_user: CurrentUser
) -> dict:
    record = await db.scalar(
        select(TongueRecord).where(
            TongueRecord.session_id == session_id,
            TongueRecord.deleted_at.is_(None),
        )
    )
    deleted = record is not None
    if record is not None:
        record.deleted_at = datetime.now(timezone.utc)
        await db.commit()
    return success({"session_id": session_id, "deleted": deleted})


# ---- 图像读取（开发期免签；生产改为临时签名 URL）----
@router.get("/tongue/media/{record_no}/{filename}", summary="读取舌象原图 / 掩膜")
async def get_tongue_media(record_no: str, filename: str) -> FileResponse:
    try:
        path = image_storage.resolve(record_no, filename)
    except ValueError as exc:
        raise BusinessError(ErrorCode.NOT_FOUND, "资源不存在") from exc
    if not path.is_file():
        raise BusinessError(ErrorCode.NOT_FOUND, "资源不存在")
    # 同一会话重复采集会复用同一路径（raw.{ext}），必须禁用缓存，
    # 否则浏览器会命中旧图，导致「返回时看到上一次的采集图」。
    return FileResponse(path, headers={"Cache-Control": "no-store"})