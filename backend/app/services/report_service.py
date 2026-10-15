"""报告生成服务（M5-7 / 报告主体，PRD §6.4 / §6.5）。

合参完成后由 G2 按需组装报告 `report_data`：一次性包含 P6 报告页 8 个 Tab
（综合概览 / 三诊详情 / 基础指数 / 理疗参数 / 体质辨证 / 治未病 / 调理建议 / 情绪分析）
的渲染数据（UI/UX §5.5.3）。扩展维度（基础指数 / 理疗参数 / 治未病 / 情绪分析）由规则与
知识层模板驱动，缺失时以空结构返回，前端展示空状态，不隐藏 Tab。

> M6 报告管理模块（PDF / 归档 / 历史 / 分享）在 `reports` 表落地后再接入；本服务只负责
> 组装渲染数据，`report_data` 结构保持不变即可复用同一模板。
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, cast

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    Image as RLImage,
    Paragraph,
    SimpleDocTemplate,
    Table,
    TableStyle,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.diagnosis import FusionResult, Report, ReportStatus
from app.schemas.diagnosis import (
    AdviceTab,
    Conclusion,
    ConstitutionTab,
    DetailsTab,
    EmotionDimension,
    EmotionTab,
    FeatureItem,
    IndexItem,
    IndicesTab,
    InquiryDetail,
    ModuleDetail,
    OverviewTab,
    PatientSnapshot,
    PreventionGroup,
    PreventionTab,
    ReportData,
    ReportHeader,
    Suggestion as SchemaSuggestion,
    Syndrome,
    TherapyTab,
)
from app.services import image_storage, integrated_analysis

logger = get_logger(__name__)

#: 模块中文名
_MODULE_LABELS = {"tongue": "舌诊", "face": "面诊", "inquiry": "问诊"}

#: 报告健康等级中文标签
_HEALTH_LABELS = {"good": "健康", "fair": "一般", "poor": "较差", "bad": "极差"}

_REPORT_DISCLAIMER = "本报告由系统生成，仅供临床辅助参考，不构成最终医疗诊断，须由医师确认签署。"

#: 会话 id 解析（`s_YYYYMMDD_NNNN`，用于推导会话编号中的创建日期与当天序号）
_SESSION_ID_PATTERN = re.compile(r"^s_(\d{4})(\d{2})(\d{2})_(\d+)$")

#: 注册中文字体（reportlab 内置 Adobe CID 字体，无需外部字体文件）
_CJK_FONT = "STSong-Light"
_font_registered = False


def _ensure_font() -> None:
    global _font_registered
    if not _font_registered:
        pdfmetrics.registerFont(UnicodeCIDFont(_CJK_FONT))
        _font_registered = True


def _to_patient_snapshot(raw: dict | None) -> PatientSnapshot | None:
    if not raw:
        return None
    return PatientSnapshot.model_validate(raw)


def _module_detail(module: integrated_analysis.ModuleInput) -> ModuleDetail:
    return ModuleDetail(
        module=cast(Any, module.key),
        record_id=module.record_no,
        image_ref=module.image_ref or "",
        features=[FeatureItem.model_validate(item) for item in module.features],
        summary=module.summary,
        main_syndrome=Syndrome.model_validate(module.main_syndrome)
        if module.main_syndrome
        else None,
        secondary_syndromes=[
            Syndrome.model_validate(item) for item in module.secondary_syndromes
        ],
        treatment_principles=module.treatment_principles,
        model_version=module.model_version,
    )


def _inquiry_detail(module: integrated_analysis.ModuleInput) -> InquiryDetail:
    return InquiryDetail(
        record_id=module.record_no,
        patient_snapshot=_to_patient_snapshot(module.patient_snapshot),
        answers=module.answers,
        missing_items=module.missing_items,
        summary=module.summary,
        main_syndrome=Syndrome.model_validate(module.main_syndrome)
        if module.main_syndrome
        else None,
        secondary_syndromes=[
            Syndrome.model_validate(item) for item in module.secondary_syndromes
        ],
        treatment_principles=module.treatment_principles,
        model_version=module.model_version,
    )


def _indices(inputs: integrated_analysis.FusionInputs) -> IndicesTab:
    """基础指数：由问诊基础信息与三诊置信度派生的展示指标。"""
    items: list[IndexItem] = []
    inquiry = inputs.modules.get("inquiry")
    snapshot = (inquiry.patient_snapshot if inquiry else {}) or {}
    height = snapshot.get("height")
    weight = snapshot.get("weight")
    try:
        height_m = float(height) / 100.0 if height else None
        weight_kg = float(weight) if weight else None
    except (TypeError, ValueError):
        height_m = weight_kg = None
    if height_m and weight_kg and height_m > 0:
        bmi = round(weight_kg / (height_m * height_m), 1)
        if bmi < 18.5:
            level, reference = "low", "参考区间 18.5 ~ 23.9"
        elif bmi < 24:
            level, reference = "good", "参考区间 18.5 ~ 23.9"
        elif bmi < 28:
            level, reference = "fair", "参考区间 18.5 ~ 23.9"
        else:
            level, reference = "poor", "参考区间 18.5 ~ 23.9"
        items.append(IndexItem(name="体质指数（BMI）", value=str(bmi), reference=reference, level=level))

    for key, module in inputs.modules.items():
        if key == "inquiry" or module.overall_confidence is None:
            continue
        confidence = module.overall_confidence
        level = "good" if confidence >= 0.85 else "fair" if confidence >= 0.7 else "low"
        items.append(
            IndexItem(
                name=f"{_MODULE_LABELS.get(key, key)}整体置信度",
                value=f"{round(confidence * 100)}%",
                reference="越高表示特征识别越稳定",
                level=level,
            )
        )
    return IndicesTab(items=items)


def _prevention(inputs: integrated_analysis.FusionInputs, main_name: str | None) -> PreventionTab:
    """治未病：未病先防 / 既病防变类通用建议（规则驱动）。"""
    groups = [
        PreventionGroup(
            title="未病先防",
            items=[
                "顺应四时起居，规律作息，避免长期熬夜耗伤正气。",
                "适度运动（如八段锦、快走），以微汗为度，增强体质。",
                "饮食有节、五味不偏，少食生冷油腻与辛辣煎炸。",
            ],
        )
    ]
    if main_name:
        groups.append(
            PreventionGroup(
                title="既病防变",
                items=[
                    f"围绕「{main_name}」持续调理，避免诱因反复。",
                    "定期复诊，动态对比舌象与症状变化，及时调整方案。",
                ],
            )
        )
    return PreventionTab(groups=groups)


def _emotion(inputs: integrated_analysis.FusionInputs) -> EmotionTab:
    """情绪分析：依问诊睡眠/胸腹/口味等情志相关项派生维度。"""
    inquiry = inputs.modules.get("inquiry")
    if inquiry is None:
        return EmotionTab()
    answers = inquiry.answers or {}
    sleep = {str(item) for item in (answers.get("sleep") or [])}
    chest = {str(item) for item in (answers.get("chest_abdomen") or [])}
    taste = {str(item) for item in (answers.get("taste") or [])}

    def score(penalties: int) -> float:
        return round(max(0.2, 1.0 - 0.2 * penalties), 2)

    sleep_flags = sleep - {"正常", "嗜睡"}
    chest_flags = chest & {"胸闷", "胁痛", "心悸"}
    mood_flags = taste & {"口苦"}

    dimensions = [
        EmotionDimension(
            name="睡眠质量",
            score=score(len(sleep_flags)),
            note="、" .join(sorted(sleep_flags)) if sleep_flags else "睡眠尚可",
        ),
        EmotionDimension(
            name="情志平稳度",
            score=score(len(chest_flags) + len(mood_flags)),
            note="、" .join(sorted(chest_flags | mood_flags)) if (chest_flags or mood_flags) else "情绪较为平稳",
        ),
    ]
    summary = (
        "情志相关表现较为平稳，建议保持规律作息与情绪舒畅。"
        if not (sleep_flags or chest_flags or mood_flags)
        else "存在情志相关不适表现，建议疏解压力、规律作息，必要时结合心理调适。"
    )
    return EmotionTab(dimensions=dimensions, summary=summary)


async def build_report(db: AsyncSession, fusion: FusionResult) -> ReportData:
    """组装 P6 报告 8 Tab 渲染数据。"""
    inputs = await integrated_analysis.collect_inputs(db, fusion.session_id)
    ranked = integrated_analysis.ranked_syndromes(inputs)

    inquiry = inputs.modules.get("inquiry")
    patient_snapshot = _to_patient_snapshot(inquiry.patient_snapshot if inquiry else None)

    header = ReportHeader(
        session_id=fusion.session_id,
        patient_snapshot=patient_snapshot,
        generated_at=fusion.updated_at,
        overall_confidence=float(fusion.overall_confidence)
        if fusion.overall_confidence is not None
        else None,
        health_level=fusion.health_level,
        rule_version=fusion.rule_version,
        model_version=fusion.model_version,
        status="final",
    )

    conclusions = [Conclusion.model_validate(item) for item in (fusion.conclusions or [])]
    syndrome_points = list(fusion.syndrome_points or [])
    overview = OverviewTab(
        conclusions=conclusions,
        syndrome_points=syndrome_points,
        overall_confidence=header.overall_confidence,
        evidence_summary=syndrome_points,
    )

    tongue = inputs.modules.get("tongue")
    face = inputs.modules.get("face")
    details = DetailsTab(
        tongue=_module_detail(tongue) if tongue else None,
        face=_module_detail(face) if face else None,
        inquiry=_inquiry_detail(inquiry) if inquiry else None,
    )

    main_syndrome = Syndrome.model_validate(ranked[0]) if ranked else None
    constitution = ConstitutionTab(
        main_syndrome=main_syndrome,
        secondary_syndromes=[Syndrome.model_validate(item) for item in ranked[1:4]],
        description=_constitution_description(ranked),
    )

    suggestions = [SchemaSuggestion.model_validate(item) for item in (fusion.suggestions or [])]

    return ReportData(
        header=header,
        overview=overview,
        details=details,
        indices=_indices(inputs),
        therapy=TherapyTab(),  # 理疗参数 [TBD]：以规则集为准，暂返回空结构（前端空状态）
        constitution=constitution,
        prevention=_prevention(inputs, main_syndrome.name if main_syndrome else None),
        advice=AdviceTab(suggestions=suggestions),
        emotion=_emotion(inputs),
    )


def _constitution_description(ranked: list[dict[str, Any]]) -> str:
    if not ranked:
        return "三诊未见明显偏颇，体质大致平和。"
    names = "、".join(f"{item['name']}（{round(item['confidence'] * 100)}%）" for item in ranked[:3])
    return f"三诊汇总证候倾向：{names}。"


# ---- 报告落库（M6 R1）----
async def create_report(db: AsyncSession, fusion: FusionResult) -> Report:
    """按合参结果生成并落库一份报告（同一合参结果对应一份，重复调用前应查重）。"""
    data = await build_report(db, fusion)
    payload = data.model_dump(mode="json")
    conclusions = data.overview.conclusions
    summary = conclusions[0].text[:255] if conclusions else None
    snapshot = (
        data.header.patient_snapshot.model_dump(mode="json") if data.header.patient_snapshot else {}
    )
    row = Report(
        report_no=f"tmp_{uuid.uuid4().hex[:24]}",
        session_id=fusion.session_id,
        fusion_id=fusion.id,
        status=ReportStatus.FINAL,
        patient_snapshot=snapshot,
        overall_confidence=fusion.overall_confidence,
        health_level=fusion.health_level,
        summary=summary,
        report_data=payload,
        rule_version=fusion.rule_version,
        model_version=fusion.model_version,
    )
    db.add(row)
    await db.flush()
    row.report_no = f"r_{row.id}"
    await db.commit()
    await db.refresh(row)
    return row


async def get_or_create_report(db: AsyncSession, fusion: FusionResult) -> Report:
    """取该合参结果对应的报告；不存在则生成（幂等，供合参完成 / G2 查询共用）。"""
    existing = await db.scalar(
        select(Report)
        .where(Report.fusion_id == fusion.id, Report.deleted_at.is_(None))
        .order_by(Report.id.desc())
    )
    if existing is not None:
        return existing
    return await create_report(db, fusion)


async def get_report(db: AsyncSession, report_no: str) -> Report | None:
    """按报告号查询未删除报告。"""
    return await db.scalar(
        select(Report).where(Report.report_no == report_no, Report.deleted_at.is_(None))
    )


async def archive_report(db: AsyncSession, report: Report) -> Report:
    """归档报告（幂等）：状态置 `archived` 并记录归档时间（PRD §6.5 归档后只读）。"""
    if report.status != ReportStatus.ARCHIVED:
        report.status = ReportStatus.ARCHIVED
        report.archived_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(report)
    return report


async def delete_report(
    db: AsyncSession, report: Report, *, actor_no: str | None = None
) -> None:
    """软删报告（R6）：置 `deleted_at`，此后列表/详情/PDF 均不再返回。

    二次确认由前端完成（PRD §9.6），后端写结构化审计日志（PRD §7.4）。
    """
    report.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    logger.info(
        "report.delete",
        report_no=report.report_no,
        session_id=report.session_id,
        actor_no=actor_no,
    )


# ---- PDF 生成（M6 R3）----
def reports_dir() -> Path:
    """报告 PDF 目录（`{MEDIA_ROOT}/reports`，必要时创建）。"""
    root = Path(settings.MEDIA_ROOT) / "reports"
    root.mkdir(parents=True, exist_ok=True)
    return root


def pdf_path(report_no: str) -> Path:
    return reports_dir() / f"{report_no}.pdf"


def pdf_ref(report_no: str) -> str:
    return f"pdf://reports/{report_no}.pdf"


def pdf_filename(report: Report) -> str:
    """文件名规则：`报告_{姓名}_{会话号}_{yyyyMMdd}.pdf`（PRD §6.5）。"""
    name = (report.patient_snapshot or {}).get("name") or "用户"
    name = re.sub(r"[\\/:*?\"<>|\s]+", "", str(name)) or "用户"
    session = re.sub(r"[\\/:*?\"<>|\s]+", "", report.session_id) or "session"
    date = report.generated_at.strftime("%Y%m%d")
    return f"报告_{name}_{session}_{date}.pdf"


async def ensure_pdf(db: AsyncSession, report: Report) -> Path:
    """确保 PDF 已生成：缺失则渲染并落盘，回写 `pdf_ref`。"""
    path = pdf_path(report.report_no)
    if not path.is_file():
        path.write_bytes(render_pdf(report.report_data or {}))
        report.pdf_ref = pdf_ref(report.report_no)
        await db.commit()
    return path


def _styles() -> dict[str, ParagraphStyle]:
    _ensure_font()
    return {
        "title": ParagraphStyle("title", fontName=_CJK_FONT, fontSize=18, leading=24, spaceAfter=4),
        "h2": ParagraphStyle(
            "h2", fontName=_CJK_FONT, fontSize=13, leading=18, spaceBefore=10, spaceAfter=4,
            textColor=colors.HexColor("#1890ff"),
        ),
        "h3": ParagraphStyle("h3", fontName=_CJK_FONT, fontSize=11, leading=16, spaceBefore=6),
        "body": ParagraphStyle("body", fontName=_CJK_FONT, fontSize=10, leading=16),
        "small": ParagraphStyle(
            "small", fontName=_CJK_FONT, fontSize=9, leading=13, textColor=colors.HexColor("#5a6472")
        ),
    }


def _pct(value: Any) -> str:
    try:
        return f"{round(float(value) * 100)}%"
    except (TypeError, ValueError):
        return "—"


def _table(rows: list[list[str]], widths: list[float]) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), _CJK_FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e0e4eb")),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f7f9fc")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def _module_image(module_detail: dict | None) -> RLImage | None:
    """读取单诊原图并缩放嵌入 PDF；文件缺失时返回 None（不阻断文本）。"""
    if not module_detail:
        return None
    ref = module_detail.get("image_ref")
    if not ref:
        return None
    try:
        content = image_storage.read_ref(ref)
    except ValueError:
        return None
    try:
        image = RLImage(BytesIO(content))
    except Exception:  # noqa: BLE001 - 图像损坏时跳过
        return None
    max_w, max_h = 70 * mm, 70 * mm
    ratio = min(max_w / image.imageWidth, max_h / image.imageHeight, 1.0)
    image.drawWidth = image.imageWidth * ratio
    image.drawHeight = image.imageHeight * ratio
    return image


def _session_display_no(session_id: str, snapshot: dict | None) -> str:
    """会话编号展示（对齐前端 `sessionDisplayNo`）：`{姓名|待补姓名|匿名患者}_{M月D日}[ #序号]`。

    - 日期取会话 id 中的创建日期（无法解析时退回当前日期）；
    - 当天第 2 个及以后的会话追加 `#序号`，避免同一患者同天重号。
    """
    snapshot = snapshot or {}
    matched = _SESSION_ID_PATTERN.match(session_id or "")
    if matched:
        month, day, sequence = int(matched.group(2)), int(matched.group(3)), int(matched.group(4))
    else:
        now = datetime.now()
        month, day, sequence = now.month, now.day, 0
    if snapshot.get("anonymous"):
        who = "匿名用户"
    else:
        who = str(snapshot.get("name") or "").strip() or "待补姓名"
    suffix = f" #{sequence}" if sequence > 1 else ""
    return f"{who}_{month}月{day}日{suffix}"


def render_pdf(report_data: dict[str, Any]) -> bytes:
    """由报告数据渲染 PDF（与在线预览同源，保证版式一致）。"""
    styles = _styles()
    header = report_data.get("header", {})
    overview = report_data.get("overview", {})
    details = report_data.get("details", {})
    constitution = report_data.get("constitution", {})

    story: list[Any] = []
    story.append(Paragraph("三诊合参综合报告", styles["title"]))
    snapshot = header.get("patient_snapshot") or {}
    patient = "匿名用户" if snapshot.get("anonymous") else (snapshot.get("name") or "未登记姓名")
    meta_parts = [
        f"会话编号：{_session_display_no(header.get('session_id', ''), snapshot)}",
        f"用户：{patient}",
    ]
    if snapshot.get("gender"):
        meta_parts.append(f"性别：{snapshot['gender']}")
    if snapshot.get("age"):
        meta_parts.append(f"年龄：{snapshot['age']}")
    if header.get("generated_at"):
        meta_parts.append(f"生成时间：{str(header['generated_at'])[:19].replace('T', ' ')}")
    if header.get("health_level"):
        meta_parts.append(f"健康等级：{_HEALTH_LABELS.get(header['health_level'], header['health_level'])}")
    meta_parts.append(f"整体置信度：{_pct(header.get('overall_confidence'))}")
    story.append(Paragraph("　".join(meta_parts), styles["small"]))

    # 综合概览
    story.append(Paragraph("一、综合概览", styles["h2"]))
    for item in overview.get("conclusions", []):
        story.append(
            Paragraph(f"· {item.get('text', '')}（置信度 {_pct(item.get('confidence'))}）", styles["body"])
        )
    points = overview.get("syndrome_points", [])
    if points:
        story.append(Paragraph("辨证要点：" + "；".join(points), styles["small"]))

    # 三诊详情
    story.append(Paragraph("二、三诊详情", styles["h2"]))
    for key in ("tongue", "face"):
        module = details.get(key)
        if not module:
            continue
        story.append(Paragraph(f"{_MODULE_LABELS[key]}依据", styles["h3"]))
        image = _module_image(module)
        if image is not None:
            story.append(image)
        features = module.get("features", [])
        if features:
            rows = [["特征项", "判读结果", "置信度"]]
            for feature in features:
                area = feature.get("area")
                label = feature.get("label", "")
                if area:
                    label = f"{label}（{'、'.join(area)}）"
                rows.append([feature.get("name", ""), label, _pct(feature.get("confidence"))])
            story.append(_table(rows, [45 * mm, 80 * mm, 25 * mm]))
        if module.get("summary"):
            story.append(Paragraph(module["summary"], styles["small"]))
    inquiry = details.get("inquiry")
    if inquiry:
        story.append(Paragraph("问诊依据", styles["h3"]))
        rows = [["项目", "内容"]]
        for qid, value in (inquiry.get("answers") or {}).items():
            if qid == "anonymous":
                continue
            rows.append([qid, _answer_text(value)])
        if len(rows) > 1:
            story.append(_table(rows, [45 * mm, 105 * mm]))

    # 基础指数
    story.append(Paragraph("三、基础指数", styles["h2"]))
    items = report_data.get("indices", {}).get("items", [])
    if items:
        rows = [["指标", "取值", "参考"]]
        for item in items:
            rows.append([item.get("name", ""), item.get("value", ""), item.get("reference") or "—"])
        story.append(_table(rows, [55 * mm, 35 * mm, 60 * mm]))
    else:
        story.append(Paragraph("暂无可展示内容。", styles["small"]))

    # 体质辨证
    story.append(Paragraph("四、体质辨证", styles["h2"]))
    main = constitution.get("main_syndrome")
    if main:
        story.append(
            Paragraph(f"主证：{main.get('name', '')}（置信度 {_pct(main.get('confidence'))}）", styles["body"])
        )
        secondary = constitution.get("secondary_syndromes", [])
        if secondary:
            story.append(
                Paragraph(
                    "次证：" + "；".join(f"{s.get('name')}（{_pct(s.get('confidence'))}）" for s in secondary),
                    styles["small"],
                )
            )
        if constitution.get("description"):
            story.append(Paragraph(constitution["description"], styles["small"]))
    else:
        story.append(Paragraph("暂无可展示内容。", styles["small"]))

    # 治未病
    story.append(Paragraph("五、治未病", styles["h2"]))
    groups = report_data.get("prevention", {}).get("groups", [])
    if groups:
        for group in groups:
            story.append(Paragraph(group.get("title", ""), styles["h3"]))
            for text in group.get("items", []):
                story.append(Paragraph(f"· {text}", styles["small"]))
    else:
        story.append(Paragraph("暂无可展示内容。", styles["small"]))

    # 调理建议
    story.append(Paragraph("六、调理建议", styles["h2"]))
    suggestions = report_data.get("advice", {}).get("suggestions", [])
    if suggestions:
        rows = [["类别", "建议"]]
        for item in suggestions:
            rows.append([item.get("category", ""), item.get("text", "")])
        story.append(_table(rows, [30 * mm, 120 * mm]))
    else:
        story.append(Paragraph("暂无可展示内容。", styles["small"]))

    # 情绪分析
    story.append(Paragraph("七、情绪分析", styles["h2"]))
    emotion = report_data.get("emotion", {})
    dimensions = emotion.get("dimensions", [])
    if dimensions:
        rows = [["维度", "评分", "说明"]]
        for dim in dimensions:
            rows.append([dim.get("name", ""), _pct(dim.get("score")), dim.get("note") or "—"])
        story.append(_table(rows, [35 * mm, 25 * mm, 90 * mm]))
        if emotion.get("summary"):
            story.append(Paragraph(emotion["summary"], styles["small"]))
    else:
        story.append(Paragraph("暂无可展示内容。", styles["small"]))

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        title="三诊合参综合报告",
    )
    doc.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
    return buffer.getvalue()


def _answer_text(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, list):
        return "、".join(str(item) for item in value) if value else "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


def _draw_footer(canvas: Any, doc: Any) -> None:
    canvas.saveState()
    canvas.setFont(_CJK_FONT, 8)
    canvas.setFillColor(colors.HexColor("#98a2b3"))
    canvas.drawString(16 * mm, 10 * mm, _REPORT_DISCLAIMER)
    canvas.drawRightString(A4[0] - 16 * mm, 10 * mm, f"第 {doc.page} 页")
    canvas.restoreState()