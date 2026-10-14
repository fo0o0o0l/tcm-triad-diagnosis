"""问诊请求 / 响应模型（《开发任务文档》§4.7 I1~I5；PRD §6.3 / §9.4）。

字段与响应示例严格对齐 PRD §9.4，供前端按模板动态渲染。与舌诊/面诊差异：
- 无图像，核心是「模板 → 答案（`{qid: value}`）→ AI 证候判读」；
- 模板由后端下发（`INQUIRY_TEMPLATE_V2`，落 `inquiry_templates` 表），前端不硬编码；
- 必填校验在服务端二次执行（前端不可信），缺失返回 40001 + `missing[]` + `first_missing`。
"""

from __future__ import annotations

import copy
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.diagnosis import AnalysisStatus, ModuleStatus

#: 当前模板版本（与 `inquiry_templates.version` 一致）
INQUIRY_TEMPLATE_VERSION = "inquiry_v2"

#: 题目类型（PRD §6.3.4：single/multi/text/number/scale/switch）
QuestionType = Literal["single", "multi", "text", "number", "scale", "switch"]
#: 优先级（P0 必填阻断；P1/P2 可选）
Priority = Literal["P0", "P1", "P2"]


# ---- 通用结构 ----
class Syndrome(BaseModel):
    """证候倾向 `{name, confidence}`。"""

    name: str
    confidence: float = Field(ge=0, le=1)


class Recommendation(BaseModel):
    """调理建议 `{category, text}`。"""

    category: str
    text: str


# ---- I1 问诊模板 ----
class Question(BaseModel):
    """单个题目定义（模板驱动前端渲染）。"""

    qid: str
    type: QuestionType
    priority: Priority
    required: bool = False
    label: str
    placeholder: str | None = None
    options: list[str] | None = None
    default: Any = None
    range: list[float] | None = None
    unit: str | None = None
    decimals: int | None = None
    maxLength: int | None = None
    # 条件/联动：`effect=clearFields` + `targets[]`（如匿名开关清空姓名）
    effect: str | None = None
    targets: list[str] | None = None
    # 术语白话解释（前端 Tooltip 展示）
    hint: str | None = None
    # 选择题是否在选项末尾提供「其他」文本输入
    allowOther: bool = False
    # 互斥选项标签（如「正常」「无明显寒热」）：选中即清空其它，选其它即取消该项
    exclusiveOptions: list[str] | None = None


class ShowWhen(BaseModel):
    """分组显示条件：`answers[qid] == equals` 时才展示该分组（如性别=女）。"""

    qid: str
    equals: Any = None


class QuestionGroup(BaseModel):
    """题目分组 `{group_id, title, priority, questions[]}`。"""

    group_id: str
    title: str
    priority: Priority
    questions: list[Question]
    # 分组级显示条件（缺省表示始终显示）
    showWhen: ShowWhen | None = None


class TemplateResponse(BaseModel):
    """I1 响应 `data`。"""

    template_version: str
    groups: list[QuestionGroup]


# ---- I2/I3 请求 ----
class AnswerItem(BaseModel):
    """单题作答 `{qid, value}`；`value` 支持字符串 / 数组 / 数值 / 布尔 / 空。"""

    qid: str = Field(min_length=1)
    value: Any = None


class DraftRequest(BaseModel):
    """I2 保存草稿请求（PRD §9.4.2）。"""

    template_version: str = Field(min_length=1)
    answers: list[AnswerItem] = Field(default_factory=list)


class SubmitRequest(BaseModel):
    """I3 提交问诊请求（结构同草稿）。"""

    template_version: str = Field(min_length=1)
    answers: list[AnswerItem] = Field(default_factory=list)


class DraftResponse(BaseModel):
    """I2 响应 `data`。"""

    saved: bool
    updated_at: datetime


class SubmitResponse(BaseModel):
    """I3 响应 `data`。"""

    record_id: str
    completed: bool


# ---- I4 问诊 AI 分析（异步）----
class AiAnalysisRequest(BaseModel):
    """I4 请求；`record_id` 缺省时取会话当前记录。"""

    record_id: str | None = None
    language: str = "zh-CN"


class AiAnalysisResponse(BaseModel):
    """I4 响应 `data`（返回任务，前端轮询 I5）。"""

    task_id: str
    analysis_status: AnalysisStatus


# ---- I5 查询分析结果 ----
class AnalysisResult(BaseModel):
    """AI 问诊解读结果（PRD §6.3.5 输出字段）。"""

    symptoms_summary: str
    main_syndrome: Syndrome | None = None
    secondary_syndromes: list[Syndrome] = []
    treatment_principles: list[str] = []
    recommendations: list[Recommendation] = []


class AnalysisQueryResponse(BaseModel):
    """I5 响应 `data`。"""

    model_config = ConfigDict(from_attributes=True)

    inquiry_id: str
    record_id: str
    status: AnalysisStatus
    missing_items: list[str] = []
    result: AnalysisResult | None = None
    model_version: str | None = None
    retryable: bool = True


# ---- I0 会话问诊状态（页面重新挂载时恢复进度 / 草稿）----
class PatientSnapshot(BaseModel):
    """患者快照（由答案归一而来；匿名时姓名置空）。"""

    name: str | None = None
    gender: str | None = None
    age: float | None = None
    height: float | None = None
    weight: float | None = None
    anonymous: bool = False


class DraftState(BaseModel):
    """服务端草稿快照。"""

    template_version: str
    answers: dict[str, Any]
    updated_at: datetime


class RecordState(BaseModel):
    """已提交问诊记录快照（含最近一次分析）。"""

    record_id: str
    template_version: str
    patient_snapshot: PatientSnapshot
    answers: dict[str, Any]
    missing_items: list[str]
    status: ModuleStatus
    completed: bool
    submitted_at: datetime | None = None
    analysis: AnalysisQueryResponse | None = None


class RecordStateResponse(BaseModel):
    """I0 响应 `data`：草稿 + 已提交记录（均可能为 null）。"""

    draft: DraftState | None = None
    record: RecordState | None = None


#: 问诊模板 v1（PRD §9.4.1 结构 + 展示用 `label`/`placeholder`）。
#: **历史版本**，作为 v2 的构造基线保留；落库版本见文件末尾 `INQUIRY_TEMPLATE_V2`。
INQUIRY_TEMPLATE_V1: dict[str, Any] = {
    "template_version": "inquiry_v1",
    "groups": [
        {
            "group_id": "basic",
            "title": "基础信息收集",
            "priority": "P0",
            "questions": [
                {
                    "qid": "gender",
                    "type": "single",
                    "priority": "P0",
                    "required": True,
                    "label": "性别",
                    "options": ["男", "女", "未知"],
                    "default": "未知",
                },
                {
                    "qid": "age",
                    "type": "number",
                    "priority": "P0",
                    "required": True,
                    "label": "年龄",
                    "range": [1, 120],
                    "unit": "岁",
                },
                {
                    "qid": "height",
                    "type": "number",
                    "priority": "P0",
                    "required": True,
                    "label": "身高",
                    "range": [50, 250],
                    "unit": "cm",
                    "decimals": 1,
                },
                {
                    "qid": "weight",
                    "type": "number",
                    "priority": "P0",
                    "required": True,
                    "label": "体重",
                    "range": [10, 300],
                    "unit": "kg",
                    "decimals": 1,
                },
                {
                    "qid": "name",
                    "type": "text",
                    "priority": "P1",
                    "required": False,
                    "label": "姓名",
                    "placeholder": "请输入姓名（选填）",
                    "maxLength": 20,
                },
                {
                    "qid": "anonymous",
                    "type": "switch",
                    "priority": "P1",
                    "required": False,
                    "label": "匿名填写",
                    "default": False,
                    "effect": "clearFields",
                    "targets": ["name"],
                },
            ],
        },
        {
            "group_id": "chief_symptom",
            "title": "主诉",
            "priority": "P0",
            "questions": [
                {
                    "qid": "chief_complaint",
                    "type": "text",
                    "priority": "P0",
                    "required": True,
                    "label": "主要不适描述",
                    "placeholder": "请简要描述本次主要不适",
                    "maxLength": 500,
                }
            ],
        },
        {
            "group_id": "cold_heat",
            "title": "寒热症状收集",
            "priority": "P0",
            "questions": [
                {
                    "qid": "cold_heat",
                    "type": "multi",
                    "priority": "P0",
                    "required": True,
                    "label": "寒热表现",
                    "options": ["怕冷畏寒", "怕热喜凉", "寒热交替", "手足不温", "手足心热", "无明显寒热"],
                }
            ],
        },
        {
            "group_id": "sweating",
            "title": "汗出情况收集",
            "priority": "P1",
            "questions": [
                {
                    "qid": "sweating",
                    "type": "multi",
                    "priority": "P1",
                    "required": False,
                    "label": "汗出情况",
                    "options": ["自汗", "盗汗", "无汗", "汗出过多", "正常"],
                }
            ],
        },
        {
            "group_id": "sleep",
            "title": "睡眠情况收集",
            "priority": "P1",
            "questions": [
                {
                    "qid": "sleep",
                    "type": "multi",
                    "priority": "P1",
                    "required": False,
                    "label": "睡眠情况",
                    "options": ["入睡困难", "易醒", "多梦", "早醒", "嗜睡", "正常"],
                }
            ],
        },
        {
            "group_id": "diet_taste",
            "title": "饮食口味收集",
            "priority": "P1",
            "questions": [
                {
                    "qid": "appetite",
                    "type": "single",
                    "priority": "P1",
                    "required": False,
                    "label": "食欲",
                    "options": ["正常", "食欲不振", "食欲亢进"],
                },
                {
                    "qid": "taste",
                    "type": "multi",
                    "priority": "P1",
                    "required": False,
                    "label": "口味",
                    "options": ["正常", "口苦", "口甜", "口酸", "口咸", "口淡"],
                },
                {
                    "qid": "thirst",
                    "type": "single",
                    "priority": "P1",
                    "required": False,
                    "label": "口渴情况",
                    "options": ["不渴", "口渴喜冷饮", "口渴喜热饮", "口干不欲饮"],
                },
            ],
        },
        {
            "group_id": "excretion",
            "title": "二便情况收集",
            "priority": "P1",
            "questions": [
                {
                    "qid": "stool",
                    "type": "single",
                    "priority": "P1",
                    "required": False,
                    "label": "大便",
                    "options": ["正常", "便溏", "便秘", "先干后溏"],
                },
                {
                    "qid": "urine",
                    "type": "single",
                    "priority": "P1",
                    "required": False,
                    "label": "小便",
                    "options": ["正常", "清长", "黄赤", "频数", "癃闭"],
                },
            ],
        },
        {
            "group_id": "chest_abdomen",
            "title": "胸腹不适收集",
            "priority": "P1",
            "questions": [
                {
                    "qid": "chest_abdomen",
                    "type": "multi",
                    "priority": "P1",
                    "required": False,
                    "label": "胸腹不适",
                    "options": ["胸闷", "心悸", "腹胀", "腹痛", "胁痛", "无明显不适"],
                }
            ],
        },
        {
            "group_id": "other",
            "title": "其他症状补充",
            "priority": "P2",
            "questions": [
                {
                    "qid": "other_symptoms",
                    "type": "text",
                    "priority": "P2",
                    "required": False,
                    "label": "其他症状补充",
                    "placeholder": "可补充其他不适（选填）",
                    "maxLength": 1000,
                }
            ],
        },
    ],
}


# ---- 问诊模板 v2（术语提示 / 「其他」输入 / 正常-异常互斥 / 女性生理期专项）----

#: 术语白话解释（qid → 提示文案；未列出的题目不显示提示）
_QUESTION_HINTS: dict[str, str] = {
    "cold_heat": "寒热指怕冷、怕热等体感：畏寒多提示寒证，怕热喜凉多提示热证。",
    "sweating": "自汗指白天稍动即汗出；盗汗指睡时出汗、醒后汗止。",
    "sleep": "入睡困难指难以入睡；易醒 / 早醒指睡眠中断；多梦指梦境繁多。",
    "appetite": "食欲不振指不愿进食；食欲亢进指容易饥饿、食量明显增大。",
    "taste": "口中异常味觉（苦 / 甜 / 酸 / 咸 / 淡）多与脏腑功能失调相关，如实记录即可。",
    "thirst": "口渴喜冷饮多提示内热；喜热饮多提示寒证；口干不欲饮多提示湿或痰饮。",
    "stool": "便溏指大便稀软不成形；先干后溏指先硬后稀；便秘指排便困难或次数减少。",
    "urine": "清长指小便清亮量多；黄赤指色黄而深；频数指次数多；癃闭指排尿困难或闭塞。",
    "chest_abdomen": "胸腹不适含胸闷、心悸、腹胀、腹痛、胁痛等；无则勾选「无明显不适」。",
    "menstruation_cycle": "指月经来潮的间隔天数是否规律。",
    "menstruation_volume": "指单次月经的总出血量，正常约 20~60ml。",
    "menstruation_color": "经色淡红质稀多提示血虚；色深红有血块多提示血瘀或血热。",
    "menstruation_pain": "经期伴随症状，如痛经、腰酸、乳房胀痛、情绪波动等。",
}

#: 互斥选项标签（选中即清空其它选项，如「正常」与异常项互斥）
_EXCLUSIVE_OPTIONS: dict[str, list[str]] = {
    "cold_heat": ["无明显寒热"],
    "sweating": ["正常"],
    "sleep": ["正常"],
    "taste": ["正常"],
    "chest_abdomen": ["无明显不适"],
    "menstruation_volume": ["正常"],
    "menstruation_color": ["正常"],
    "menstruation_pain": ["无明显不适"],
}

#: 女性生理期专项（`showWhen` 性别=女 时展示；全部选填，不阻断提交）
_MENSTRUATION_GROUP: dict[str, Any] = {
    "group_id": "menstruation",
    "title": "月经情况（女性专项）",
    "priority": "P1",
    "showWhen": {"qid": "gender", "equals": "女"},
    "questions": [
        {
            "qid": "menstruation_cycle",
            "type": "single",
            "priority": "P1",
            "required": False,
            "label": "月经周期",
            "options": ["规律", "提前", "推迟", "先后不定", "已绝经"],
        },
        {
            "qid": "menstruation_volume",
            "type": "single",
            "priority": "P1",
            "required": False,
            "label": "经量",
            "options": ["正常", "偏多", "偏少", "时多时少"],
        },
        {
            "qid": "menstruation_color",
            "type": "single",
            "priority": "P1",
            "required": False,
            "label": "经色 / 经质",
            "options": ["正常", "色淡", "色深红", "有血块", "质稀"],
        },
        {
            "qid": "menstruation_pain",
            "type": "multi",
            "priority": "P1",
            "required": False,
            "label": "经期伴随",
            "options": ["痛经", "腰酸", "乳房胀痛", "情绪波动", "无明显不适"],
        },
    ],
}


def _enrich_question(question: dict[str, Any]) -> None:
    """按 qid 补充提示 / 「其他」输入 / 互斥标签（就地修改）。"""
    qid = question["qid"]
    if hint := _QUESTION_HINTS.get(qid):
        question["hint"] = hint
    # 除性别外，所有选择题均在选项末尾提供「其他」输入
    if question.get("options") and qid != "gender":
        question["allowOther"] = True
    if exclusive := _EXCLUSIVE_OPTIONS.get(qid):
        question["exclusiveOptions"] = exclusive


def _build_template_v2() -> dict[str, Any]:
    """在 v1 结构上补充提示 / 「其他」输入 / 互斥标签，并追加女性生理期专项。"""
    schema = copy.deepcopy(INQUIRY_TEMPLATE_V1)
    schema["template_version"] = INQUIRY_TEMPLATE_VERSION
    # 女性生理期专项插在「基础信息」之后（顺序影响前端分组导航）
    schema["groups"].insert(1, copy.deepcopy(_MENSTRUATION_GROUP))
    for group in schema["groups"]:
        for question in group["questions"]:
            _enrich_question(question)
    return schema


#: 问诊模板 v2（当前生效版本；落 `inquiry_templates`，`status=active`）
INQUIRY_TEMPLATE_V2: dict[str, Any] = _build_template_v2()