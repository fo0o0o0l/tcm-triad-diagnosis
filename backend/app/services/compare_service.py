"""报告对比服务（P8 数据对比页；UI/UX §5.7）。

输入两份**同一患者**的历史报告，输出对比所需的渲染数据：
- 健康状态变化（`HealthLevel` → 改善 / 持平 / 恶化）；
- 三诊特征对比（舌象 / 面象 / 问诊症状，按特征名对齐，产出变化方向）；
- 综合结论对比（两侧结论并排 + 新增 / 移除差异）；
- 置信度趋势（同患者近 N 次报告按生成时间升序）。

方向映射依赖「特征标签 → 偏离度」的启发式排序表：数值越小越平和。
该表为 §5.7.3 标注的 `[TBD]`（待特征字典落地）的临时实现，字典上线后替换为查表；
未覆盖的标签一律返回 `unknown`，前端按“有变化”中性展示，不做医学判定。
"""

from __future__ import annotations

from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ErrorCode
from app.core.response import BusinessError
from app.models.diagnosis import HealthLevel, Report
from app.schemas.compare import (
    ChangeDirection,
    ConclusionDiff,
    CompareReportSummary,
    CompareResult,
    ConfidencePoint,
    FeatureDiffItem,
    HealthChange,
    ModuleFeatureDiff,
)
from app.schemas.diagnosis import ModuleKey

#: 三诊模块中文名
_MODULE_LABELS: dict[str, str] = {"tongue": "舌象特征", "face": "面象特征", "inquiry": "问诊症状"}

#: 图像诊特征字段中文名（与前端 FEATURE_LABELS 保持一致）
_FEATURE_LABELS: dict[str, str] = {
    "tongue_color": "舌色",
    "coating_color": "苔色",
    "coating_texture": "苔质",
    "tongue_shape": "舌形",
    "face_color": "面色",
    "luster": "光泽",
    "acne": "痘痘",
    "spots": "斑点",
}

#: 问诊关键症状字段与中文名（用于症状对比）
_INQUIRY_QIDS: dict[str, str] = {
    "cold_heat": "寒热",
    "sweating": "汗出",
    "sleep": "睡眠",
    "appetite": "食欲",
    "taste": "口味",
    "thirst": "口渴",
    "stool": "大便",
    "urine": "小便",
    "chest_abdomen": "胸腹",
    "other_symptoms": "其他",
    "chief_complaint": "主诉",
}

#: 健康等级排序（越大越健康）
_HEALTH_RANK: dict[HealthLevel, int] = {
    HealthLevel.BAD: 0,
    HealthLevel.POOR: 1,
    HealthLevel.FAIR: 2,
    HealthLevel.GOOD: 3,
}

#: 特征标签偏离度（越小越平和）；未命中即视为无法判定（`unknown`）
_FEATURE_RANK: dict[str, dict[str, int]] = {
    "tongue_color": {"淡红": 0, "淡白": 1, "红": 1, "绛红": 2, "青紫": 2},
    "coating_color": {"白": 0, "黄": 1},
    "coating_texture": {"薄": 0, "腻": 1, "厚": 2},
    "tongue_shape": {"正常": 0, "齿痕": 1, "胖大": 1},
    "face_color": {"红润": 0, "萎黄": 1, "苍白": 1, "晦暗": 1, "潮红": 2, "青紫": 2},
    "luster": {"有光泽": 0, "少光泽": 1, "油光": 1},
    "acne": {"无": 0, "轻微": 1, "较少": 1, "少量": 1, "中等": 2, "较多": 3},
    "spots": {"无": 0, "轻微": 1, "较少": 1, "少量": 1, "中等": 2, "较多": 3},
}


def patient_key(report: Report) -> str:
    """患者分组键：具名患者按姓名，匿名记录按会话标识（跨患者禁止对比）。"""
    snapshot = report.patient_snapshot or {}
    raw_name = snapshot.get("name")
    name = str(raw_name).strip() if isinstance(raw_name, str) else ""
    if name and not snapshot.get("anonymous"):
        return f"name:{name}"
    return f"session:{report.session_id}"


def _to_summary(report: Report) -> CompareReportSummary:
    snapshot = report.patient_snapshot or {}
    raw_name = snapshot.get("name")
    name = str(raw_name).strip() if isinstance(raw_name, str) else ""
    is_anonymous = bool(snapshot.get("anonymous")) or not name
    return CompareReportSummary(
        report_id=report.report_no,
        session_id=report.session_id,
        patient_name=None if is_anonymous else name,
        anonymous=is_anonymous,
        generated_at=report.generated_at,
        health_level=report.health_level,
        overall_confidence=float(report.overall_confidence)
        if report.overall_confidence is not None
        else None,
        status=report.status,
        summary=report.summary,
    )


def _health_direction(base: HealthLevel | None, target: HealthLevel | None) -> ChangeDirection:
    if base is None or target is None:
        return "unknown"
    if base == target:
        return "same"
    return "improved" if _HEALTH_RANK[target] > _HEALTH_RANK[base] else "worsened"


def _rank(feature_name: str, label: str | None) -> int | None:
    """特征标签的偏离度；支持“胖大+齿痕”这类复合标签的关键词回退匹配。"""
    table = _FEATURE_RANK.get(feature_name)
    if not table or not label:
        return None
    if label in table:
        return table[label]
    for key, value in table.items():
        if key and key in label:
            return value
    return None


def _feature_direction(
    feature_name: str, base_label: str | None, target_label: str | None
) -> ChangeDirection:
    if base_label is None or target_label is None:
        return "unknown"
    if base_label == target_label:
        return "same"
    base_rank = _rank(feature_name, base_label)
    target_rank = _rank(feature_name, target_label)
    if base_rank is None or target_rank is None or base_rank == target_rank:
        return "unknown"
    return "improved" if target_rank < base_rank else "worsened"


def _image_features(report_data: dict[str, Any], module: str) -> dict[str, dict]:
    """取出图像诊特征（按字段名索引）。"""
    details = (report_data or {}).get("details") or {}
    detail = details.get(module) or {}
    features = detail.get("features") or []
    return {
        str(item.get("name")): item
        for item in features
        if isinstance(item, dict) and item.get("name")
    }


def _image_module_diff(
    module: ModuleKey, base_data: dict[str, Any], target_data: dict[str, Any]
) -> ModuleFeatureDiff:
    base_features = _image_features(base_data, module)
    target_features = _image_features(target_data, module)
    # 基准特征顺序优先，再补对比侧新增的特征
    names = list(base_features) + [n for n in target_features if n not in base_features]

    items: list[FeatureDiffItem] = []
    for name in names:
        base_item = base_features.get(name) or {}
        target_item = target_features.get(name) or {}
        base_value = _clean(base_item.get("label"))
        target_value = _clean(target_item.get("label"))
        items.append(
            FeatureDiffItem(
                name=name,
                label=_FEATURE_LABELS.get(name, name),
                base_value=base_value,
                target_value=target_value,
                changed=base_value != target_value,
                direction=_feature_direction(name, base_value, target_value),
                base_confidence=_confidence(base_item.get("confidence")),
                target_confidence=_confidence(target_item.get("confidence")),
            )
        )
    return ModuleFeatureDiff(module=module, label=_MODULE_LABELS[module], items=items)


def _inquiry_module_diff(
    base_data: dict[str, Any], target_data: dict[str, Any]
) -> ModuleFeatureDiff:
    base_answers = _inquiry_answers(base_data)
    target_answers = _inquiry_answers(target_data)
    # 仅对比存在作答项的症状（两侧皆空则跳过）
    qids = [qid for qid in _INQUIRY_QIDS if base_answers.get(qid) or target_answers.get(qid)]

    items: list[FeatureDiffItem] = []
    for qid in qids:
        base_value = _answer_text(base_answers.get(qid))
        target_value = _answer_text(target_answers.get(qid))
        changed = base_value != target_value
        items.append(
            FeatureDiffItem(
                name=qid,
                label=_INQUIRY_QIDS[qid],
                base_value=base_value,
                target_value=target_value,
                changed=changed,
                # 症状方向不臆断改善/加重，仅标注是否有变化
                direction="unknown" if changed else "same",
            )
        )
    return ModuleFeatureDiff(module="inquiry", label=_MODULE_LABELS["inquiry"], items=items)


def _inquiry_answers(report_data: dict[str, Any]) -> dict[str, Any]:
    details = (report_data or {}).get("details") or {}
    inquiry = details.get("inquiry") or {}
    return dict(inquiry.get("answers") or {})


def _conclusions(report_data: dict[str, Any]) -> list[str]:
    overview = (report_data or {}).get("overview") or {}
    return [
        str(item.get("text"))
        for item in (overview.get("conclusions") or [])
        if isinstance(item, dict) and item.get("text")
    ]


def _conclusion_diff(base_data: dict[str, Any], target_data: dict[str, Any]) -> ConclusionDiff:
    base_texts = _conclusions(base_data)
    target_texts = _conclusions(target_data)
    return ConclusionDiff(
        base_texts=base_texts,
        target_texts=target_texts,
        added=[text for text in target_texts if text not in base_texts],
        removed=[text for text in base_texts if text not in target_texts],
    )


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _confidence(value: Any) -> float | None:
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _answer_text(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, list):
        return "、".join(str(item) for item in value) if value else "—"
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


async def _trend_points(
    db: AsyncSession, base_report: Report, target_report: Report, limit: int
) -> list[ConfidencePoint]:
    """同患者近 N 次报告（按生成时间升序）的置信度序列。"""
    snapshot = base_report.patient_snapshot or {}
    raw_name = snapshot.get("name")
    name = str(raw_name).strip() if isinstance(raw_name, str) else ""

    stmt = select(Report).where(Report.deleted_at.is_(None))
    if name and not snapshot.get("anonymous"):
        stmt = stmt.where(Report.patient_snapshot["name"].astext == name)
    else:
        # 匿名记录只能在同会话内成序列（跨会话无法判定为同一患者）
        stmt = stmt.where(Report.session_id == base_report.session_id)
    stmt = stmt.order_by(Report.generated_at.asc(), Report.id.asc())

    rows = list((await db.scalars(stmt)).all())
    rows = rows[-limit:] if len(rows) > limit else rows

    roles: dict[str, Literal["base", "target", "history"]] = {
        base_report.report_no: "base",
        target_report.report_no: "target",
    }
    return [
        ConfidencePoint(
            report_id=row.report_no,
            generated_at=row.generated_at,
            overall_confidence=float(row.overall_confidence)
            if row.overall_confidence is not None
            else None,
            health_level=row.health_level,
            role=roles.get(row.report_no, "history"),
        )
        for row in rows
    ]


async def build_compare(
    db: AsyncSession, base_report: Report, target_report: Report, *, trend_limit: int = 5
) -> CompareResult:
    """组装两份报告的对比结果；跨患者对比直接阻断（§5.7.3）。"""
    if patient_key(base_report) != patient_key(target_report):
        raise BusinessError(ErrorCode.PARAM_INVALID, "仅支持同一患者的多条报告对比")

    base_data = base_report.report_data or {}
    target_data = target_report.report_data or {}

    modules = [
        _image_module_diff("tongue", base_data, target_data),
        _image_module_diff("face", base_data, target_data),
        _inquiry_module_diff(base_data, target_data),
    ]

    return CompareResult(
        base=_to_summary(base_report),
        target=_to_summary(target_report),
        health=HealthChange(
            base_level=base_report.health_level,
            target_level=target_report.health_level,
            direction=_health_direction(base_report.health_level, target_report.health_level),
        ),
        modules=modules,
        conclusions=_conclusion_diff(base_data, target_data),
        trend=await _trend_points(db, base_report, target_report, trend_limit),
    )
