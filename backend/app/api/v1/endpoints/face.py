"""面诊接口（《开发任务文档》§4.6 F1~F5；PRD §9.3）。

路径严格对齐 PRD：`/sessions/{session_id}/face/...`；所有接口需登录态。
附带 `GET /face/media/{record_no}/{filename}` 用于开发期读取原始图像
（生产环境改为签发临时 URL，PRD §7.4）。

与舌诊差异：F1 额外校验正脸/单脸/遮挡；F2 为面部区域检测（非单脸 42201 阻断）；
F3 痘痘/斑点额外输出分布区域 `area`。
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
from app.models.diagnosis import (
    AnalysisStatus,
    FaceAnalysis,
    FaceRecord,
    ImageSource,
    ModuleStatus,
)
from app.schemas.face import (
    AiAnalysisRequest,
    AiAnalysisResponse,
    AnalysisQueryResponse,
    AnalysisResult,
    AnalyzeRequest,
    AnalyzeResponse,
    DEFAULT_FACE_FEATURES,
    DetectRequest,
    DetectResponse,
    FaceImageResponse,
    FeatureItem,
    QualityResult,
    Recommendation,
    RecordStateResponse,
    Region,
    Syndrome,
)
from app.services import (
    algo_vision,
    face_ai_analysis,
    face_detection,
    face_mock_analysis,
    image_storage,
)

router = APIRouter(tags=["face"])

RULE_VERSION = "face_weight_v1"


# ---- 内部工具 ----
async def _get_record(db: DbSession, session_id: str, record_no: str) -> FaceRecord:
    stmt = select(FaceRecord).where(
        FaceRecord.session_id == session_id,
        FaceRecord.record_no == record_no,
        FaceRecord.deleted_at.is_(None),
    )
    record = await db.scalar(stmt)
    if record is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "面诊记录不存在")
    return record


async def _get_session_record(db: DbSession, session_id: str) -> FaceRecord:
    stmt = select(FaceRecord).where(
        FaceRecord.session_id == session_id,
        FaceRecord.deleted_at.is_(None),
    )
    record = await db.scalar(stmt)
    if record is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "该会话尚未采集面象")
    return record


def _read_image(record: FaceRecord) -> bytes:
    try:
        return image_storage.read_ref(record.image_ref)
    except ValueError as exc:
        raise BusinessError(ErrorCode.NOT_FOUND, "原始图像不存在") from exc


def _to_analysis_query(analysis: FaceAnalysis, record: FaceRecord) -> AnalysisQueryResponse:
    """把分析记录映射为 F5 / F0 共用的响应体（未完成时 `result` 为 None）。"""
    result = None
    if analysis.status == AnalysisStatus.COMPLETED:
        result = AnalysisResult(
            face_summary=analysis.face_summary or "暂无",
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
        face_id=analysis.analysis_no,
        record_id=record.record_no,
        status=analysis.status,
        result=result,
        model_version=analysis.model_version,
        retryable=analysis.retryable,
    )


# ---- F1 上传面象（含质量校验）----
@router.post("/sessions/{session_id}/face/image", summary="F1 上传面象（含质量校验）")
async def upload_face_image(
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
    quality = face_detection.assess_quality(content)
    if not quality["passed"]:
        raise BusinessError(
            ErrorCode.IMAGE_QUALITY,
            data={
                "passed": False,
                "clearness": quality["clearness"],
                "lighting": quality["lighting"],
                "composition": quality["composition"],
                "face_detected": quality["face_detected"],
                "single_face": quality["single_face"],
                "suggestions": quality["suggestions"],
            },
        )

    # 重新采集覆盖当前记录；否则新建（PRD §6.2.5 处理规则）
    existing = await db.scalar(
        select(FaceRecord).where(
            FaceRecord.session_id == session_id, FaceRecord.deleted_at.is_(None)
        )
    )
    record = existing or FaceRecord(
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
            update(FaceAnalysis)
            .where(FaceAnalysis.record_id == record.id, FaceAnalysis.is_current.is_(True))
            .values(is_current=False)
        )

    record.record_no = f"f_{record.id}" if record.record_no.startswith("tmp_") else record.record_no
    record.source = source
    # 重复采集固定覆盖同一路径（raw.{ext}），先删旧文件以处理扩展名变化
    if record.image_ref:
        image_storage.delete_ref(record.image_ref)
    record.image_ref = image_storage.save_raw_image(
        record.record_no, content, file.filename or "raw", content_type, module="face"
    )
    record.quality_passed = True
    record.quality_score = quality["score"]
    record.quality_detail = {
        "clearness": quality["clearness"],
        "lighting": quality["lighting"],
        "composition": quality["composition"],
        "face_detected": quality["face_detected"],
        "single_face": quality["single_face"],
        "suggestions": quality["suggestions"],
    }
    record.face_count = None
    record.regions = []
    record.detect_confidence = None
    record.detect_status = ModuleStatus.PENDING
    record.features = []
    record.overall_confidence = None
    await db.commit()
    await db.refresh(record)

    return success(
        FaceImageResponse(
            record_id=record.record_no,
            image_ref=record.image_ref,
            quality=QualityResult(
                passed=True,
                clearness=quality["clearness"],
                lighting=quality["lighting"],
                composition=quality["composition"],
                face_detected=quality["face_detected"],
                single_face=quality["single_face"],
                suggestions=quality["suggestions"],
            ),
        ).model_dump(mode="json")
    )


# ---- F2 面部区域检测 ----
@router.post("/sessions/{session_id}/face/detect", summary="F2 面部区域检测")
async def detect_face_regions(
    session_id: str, payload: DetectRequest, db: DbSession, current_user: CurrentUser
) -> dict:
    record = await _get_record(db, session_id, payload.record_id)
    face_count, regions, confidence = face_detection.detect_regions(_read_image(record))

    threshold = settings.DEFAULT_CONFIDENCE_THRESHOLD
    record.face_count = face_count
    record.regions = regions
    record.detect_confidence = confidence
    record.detect_status = (
        ModuleStatus.ANALYZED if confidence >= threshold else ModuleStatus.EXTRACTING
    )
    await db.commit()

    return success(
        DetectResponse(
            record_id=record.record_no,
            face_count=face_count,
            regions=[Region.model_validate(item) for item in regions],
            detect_confidence=confidence,
            status=record.detect_status,
        ).model_dump(mode="json")
    )


# ---- F3 面象特征识别 ----
@router.post("/sessions/{session_id}/face/analyze", summary="F3 面象特征识别")
async def analyze_face_features(
    session_id: str, payload: AnalyzeRequest, db: DbSession, current_user: CurrentUser
) -> dict:
    record = await _get_record(db, session_id, payload.record_id)
    names = payload.features or list(DEFAULT_FACE_FEATURES)
    image = _read_image(record)
    # 优先走视觉大模型（算法服务）；不可用时降级本地启发式，链路不中断
    vision = await algo_vision.classify_features("face", image, names)
    if vision is not None:
        features, rule_version = vision
    else:
        features = face_detection.classify_features(image, names)
        rule_version = RULE_VERSION
    overall = face_mock_analysis.weighted_confidence(features)

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


# ---- F4 面象 AI 分析（异步）----
@router.post("/sessions/{session_id}/face/ai-analysis", summary="F4 面象 AI 分析（异步）")
async def create_face_ai_analysis(
    session_id: str,
    payload: AiAnalysisRequest,
    db: DbSession,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
) -> dict:
    record = await _get_record(db, session_id, payload.record_id)
    analysis = await face_ai_analysis.create_analysis_task(db, record)
    background_tasks.add_task(face_ai_analysis.execute_analysis, analysis.id)

    return success(
        AiAnalysisResponse(
            task_id=analysis.task_id or "",
            analysis_status=analysis.status,
        ).model_dump(mode="json")
    )


# ---- F5 查询面象分析结果 ----
@router.get("/sessions/{session_id}/face/analysis", summary="F5 查询面象分析结果")
async def get_face_analysis(
    session_id: str, db: DbSession, current_user: CurrentUser, record_id: str | None = None
) -> dict:
    record = (
        await _get_record(db, session_id, record_id)
        if record_id
        else await _get_session_record(db, session_id)
    )
    analysis = await face_ai_analysis.get_current_analysis(db, record.id)
    if analysis is None:
        raise BusinessError(ErrorCode.NOT_FOUND, "尚未发起面象 AI 分析")

    return success(_to_analysis_query(analysis, record).model_dump(mode="json"))


# ---- F0 查询会话当前采集状态（页面重新挂载时恢复进度）----
@router.get("/sessions/{session_id}/face/record", summary="F0 查询会话当前面诊采集状态")
async def get_face_record(
    session_id: str, db: DbSession, current_user: CurrentUser
) -> dict:
    record = await db.scalar(
        select(FaceRecord).where(
            FaceRecord.session_id == session_id,
            FaceRecord.deleted_at.is_(None),
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
        face_detected=bool(detail.get("face_detected", False)),
        single_face=bool(detail.get("single_face", False)),
        suggestions=list(detail.get("suggestions", [])),
    )
    detect = (
        DetectResponse(
            record_id=record.record_no,
            face_count=record.face_count or 0,
            regions=record.regions or [],
            detect_confidence=float(record.detect_confidence),
            status=record.detect_status,
        )
        if record.detect_confidence is not None
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
    analysis = await face_ai_analysis.get_current_analysis(db, record.id)

    return success(
        RecordStateResponse(
            record_id=record.record_no,
            image_ref=record.image_ref,
            quality=quality,
            detect=detect,
            analyze=analyze,
            analysis=_to_analysis_query(analysis, record) if analysis else None,
        ).model_dump(mode="json")
    )


# ---- F6 清空会话面诊采集（软删；供「重新采集」后刷新不恢复旧数据）----
@router.delete("/sessions/{session_id}/face/record", summary="F6 清空会话面诊采集记录")
async def clear_face_record(
    session_id: str, db: DbSession, current_user: CurrentUser
) -> dict:
    record = await db.scalar(
        select(FaceRecord).where(
            FaceRecord.session_id == session_id,
            FaceRecord.deleted_at.is_(None),
        )
    )
    deleted = record is not None
    if record is not None:
        record.deleted_at = datetime.now(timezone.utc)
        await db.commit()
    return success({"session_id": session_id, "deleted": deleted})


# ---- 图像读取（开发期免签；生产改为临时签名 URL）----
@router.get("/face/media/{record_no}/{filename}", summary="读取面象原图")
async def get_face_media(record_no: str, filename: str) -> FileResponse:
    try:
        path = image_storage.resolve(record_no, filename, module="face")
    except ValueError as exc:
        raise BusinessError(ErrorCode.NOT_FOUND, "资源不存在") from exc
    if not path.is_file():
        raise BusinessError(ErrorCode.NOT_FOUND, "资源不存在")
    # 同一会话重复采集会复用同一路径（raw.{ext}），必须禁用缓存，
    # 否则浏览器会命中旧图，导致「返回时看到上一次的采集图」。
    return FileResponse(path, headers={"Cache-Control": "no-store"})