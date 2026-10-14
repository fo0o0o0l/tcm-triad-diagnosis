/**
 * 舌诊 / 面诊 API 封装（舌诊对齐后端 §4.5 T1~T5、面诊对齐 §4.6 F1~F5；PRD §9.2 / §9.3）。
 *
 * 统一走 `utils/request` 的 `http` 助手：自动携带 Bearer 令牌、解包统一响应体、
 * 401 静默续期。`code !== 0` 时抛 `ApiError`（含 42201 质量/检测失败等）。
 */

import { API_BASE_URL, ApiError, http } from '@/utils/request'
import { useAuthStore } from '@/stores/auth'
import type { PageResult } from '@/types/api'

// ---- 类型（与后端 app/schemas/tongue.py 一一对应）----
export type ImageSource = 'upload' | 'camera'
export type ModuleStatus = 'pending' | 'collecting' | 'extracting' | 'analyzed' | 'failed'
export type AnalysisStatus = 'pending' | 'analyzing' | 'completed' | 'failed'

/** 四类舌象特征字段名（PRD §6.1.3）。 */
export type TongueFeatureName =
  | 'tongue_color'
  | 'coating_color'
  | 'coating_texture'
  | 'tongue_shape'

export const DEFAULT_TONGUE_FEATURES: TongueFeatureName[] = [
  'tongue_color',
  'coating_color',
  'coating_texture',
  'tongue_shape',
]

/** 特征项中文名（用于特征卡标题）。 */
export const FEATURE_LABELS: Record<TongueFeatureName, string> = {
  tongue_color: '舌色',
  coating_color: '苔色',
  coating_texture: '苔质',
  tongue_shape: '舌形',
}

export interface QualityResult {
  passed: boolean
  clearness: number
  lighting: number
  composition: number
  suggestions: string[]
}

export interface TongueImageResult {
  record_id: string
  image_ref: string
  quality: QualityResult
}

export interface ExtractResult {
  record_id: string
  mask_ref: string
  confidence: number
  status: ModuleStatus
}

export interface FeatureItem {
  name: string
  label: string
  confidence: number
  /** 分布区域（面诊的痘痘/斑点输出；舌诊不返回） */
  area?: string[] | null
}

export interface AnalyzeResult {
  record_id: string
  overall_confidence: number
  features: FeatureItem[]
}

export interface AiAnalysisStart {
  task_id: string
  analysis_status: AnalysisStatus
}

export interface Syndrome {
  name: string
  confidence: number
}

export interface Recommendation {
  category: string
  text: string
}

export interface AnalysisResult {
  tongue_summary: string
  main_syndrome: Syndrome | null
  secondary_syndromes: Syndrome[]
  treatment_principles: string[]
  recommendations: Recommendation[]
}

export interface AnalysisQueryResult {
  tongue_id: string
  record_id: string
  status: AnalysisStatus
  result: AnalysisResult | null
  model_version: string | null
  retryable: boolean
}

/** 会话当前舌诊采集状态快照（T0）；无记录时接口返回 null。 */
export interface TongueRecordState {
  record_id: string
  image_ref: string
  quality: QualityResult
  extract: ExtractResult | null
  analyze: AnalyzeResult | null
  analysis: AnalysisQueryResult | null
}

/** 清空采集记录（软删）的响应。 */
export interface ClearRecordResult {
  session_id: string
  deleted: boolean
}

// ---- 接口 ----
export const tongueApi = {
  /** T1 上传舌象（含质量校验）；FormData 交由浏览器自动设置 multipart 边界 */
  uploadImage: (sessionId: string, file: File, source: ImageSource) => {
    const form = new FormData()
    form.append('file', file)
    form.append('source', source)
    return http.post<TongueImageResult>(`/sessions/${sessionId}/tongue/image`, form)
  },

  /** T2 舌体区域提取 */
  extract: (sessionId: string, recordId: string) =>
    http.post<ExtractResult>(`/sessions/${sessionId}/tongue/extract`, { record_id: recordId }),

  /** T3 舌象特征识别 */
  analyze: (sessionId: string, recordId: string, features: TongueFeatureName[]) =>
    http.post<AnalyzeResult>(`/sessions/${sessionId}/tongue/analyze`, {
      record_id: recordId,
      features,
    }),

  /** T4 舌象 AI 分析（异步，返回 task_id） */
  startAiAnalysis: (sessionId: string, recordId: string, language = 'zh-CN') =>
    http.post<AiAnalysisStart>(`/sessions/${sessionId}/tongue/ai-analysis`, {
      record_id: recordId,
      language,
    }),

  /** T5 查询舌象分析结果 */
  getAnalysis: (sessionId: string) =>
    http.get<AnalysisQueryResult>(`/sessions/${sessionId}/tongue/analysis`),

  /** T0 查询会话当前采集状态（页面重新挂载时恢复进度；无记录返回 null） */
  getRecord: (sessionId: string) =>
    http.get<TongueRecordState | null>(`/sessions/${sessionId}/tongue/record`),

  /** T6 清空会话舌诊采集（软删；「重新采集」时调用，避免刷新后回填旧数据） */
  removeRecord: (sessionId: string) =>
    http.delete<ClearRecordResult>(`/sessions/${sessionId}/tongue/record`),

  /** 掩膜 / 原图访问地址（开发期免签） */
  mediaUrl: (recordNo: string, filename: string) =>
    `${API_BASE_URL}/tongue/media/${recordNo}/${filename}`,
}

// ===== 面诊（M3，F1~F5；PRD §9.3）=====

/** 四类面象特征字段名（PRD §6.2.3）。 */
export type FaceFeatureName = 'face_color' | 'luster' | 'acne' | 'spots'

export const DEFAULT_FACE_FEATURES: FaceFeatureName[] = [
  'face_color',
  'luster',
  'acne',
  'spots',
]

/** 特征项中文名（用于特征卡标题）。 */
export const FACE_FEATURE_LABELS: Record<FaceFeatureName, string> = {
  face_color: '面色',
  luster: '光泽',
  acne: '痘痘',
  spots: '斑点',
}

/** 面部区域中文名（用于区域标注/分布展示）。 */
export const FACE_REGION_LABELS: Record<string, string> = {
  forehead: '额头',
  left_cheek: '左颊',
  right_cheek: '右颊',
  nose: '鼻部',
  chin: '下颌',
}

/** 面诊质量校验结果：在通用维度上额外含面部维度。 */
export interface FaceQualityResult extends QualityResult {
  face_detected: boolean
  single_face: boolean
}

export interface FaceImageResult {
  record_id: string
  image_ref: string
  quality: FaceQualityResult
}

export interface FaceRegion {
  name: string
  bbox: number[]
}

export interface DetectResult {
  record_id: string
  face_count: number
  regions: FaceRegion[]
  detect_confidence: number
  status: ModuleStatus
}

export interface FaceAnalysisResult {
  face_summary: string
  main_syndrome: Syndrome | null
  secondary_syndromes: Syndrome[]
  treatment_principles: string[]
  recommendations: Recommendation[]
}

export interface FaceAnalysisQueryResult {
  face_id: string
  record_id: string
  status: AnalysisStatus
  result: FaceAnalysisResult | null
  model_version: string | null
  retryable: boolean
}

/** 会话当前面诊采集状态快照（F0）；无记录时接口返回 null。 */
export interface FaceRecordState {
  record_id: string
  image_ref: string
  quality: FaceQualityResult
  detect: DetectResult | null
  analyze: AnalyzeResult | null
  analysis: FaceAnalysisQueryResult | null
}

export const faceApi = {
  /** F1 上传面象（含质量校验）；FormData 交由浏览器自动设置 multipart 边界 */
  uploadImage: (sessionId: string, file: File, source: ImageSource) => {
    const form = new FormData()
    form.append('file', file)
    form.append('source', source)
    return http.post<FaceImageResult>(`/sessions/${sessionId}/face/image`, form)
  },

  /** F2 面部区域检测 */
  detect: (sessionId: string, recordId: string) =>
    http.post<DetectResult>(`/sessions/${sessionId}/face/detect`, { record_id: recordId }),

  /** F3 面象特征识别 */
  analyze: (sessionId: string, recordId: string, features: FaceFeatureName[]) =>
    http.post<AnalyzeResult>(`/sessions/${sessionId}/face/analyze`, {
      record_id: recordId,
      features,
    }),

  /** F4 面象 AI 分析（异步，返回 task_id） */
  startAiAnalysis: (sessionId: string, recordId: string, language = 'zh-CN') =>
    http.post<AiAnalysisStart>(`/sessions/${sessionId}/face/ai-analysis`, {
      record_id: recordId,
      language,
    }),

  /** F5 查询面象分析结果 */
  getAnalysis: (sessionId: string) =>
    http.get<FaceAnalysisQueryResult>(`/sessions/${sessionId}/face/analysis`),

  /** F0 查询会话当前采集状态（页面重新挂载时恢复进度；无记录返回 null） */
  getRecord: (sessionId: string) =>
    http.get<FaceRecordState | null>(`/sessions/${sessionId}/face/record`),

  /** F6 清空会话面诊采集（软删；「重新采集」时调用，避免刷新后回填旧数据） */
  removeRecord: (sessionId: string) =>
    http.delete<ClearRecordResult>(`/sessions/${sessionId}/face/record`),

  /** 原图访问地址（开发期免签） */
  mediaUrl: (recordNo: string, filename: string) =>
    `${API_BASE_URL}/face/media/${recordNo}/${filename}`,
}

// ===== 问诊（M4，I1~I5；PRD §6.3 / §9.4）=====

/** 题目类型（PRD §6.3.4）。 */
export type QuestionType = 'single' | 'multi' | 'text' | 'number' | 'scale' | 'switch'
/** 题目/分组优先级（P0 必填阻断）。 */
export type Priority = 'P0' | 'P1' | 'P2'

export interface Question {
  qid: string
  type: QuestionType
  priority: Priority
  required: boolean
  label: string
  placeholder?: string | null
  options?: string[] | null
  default?: unknown
  range?: number[] | null
  unit?: string | null
  decimals?: number | null
  maxLength?: number | null
  /** 联动效果（如 `clearFields`）与目标字段 */
  effect?: string | null
  targets?: string[] | null
  /** 术语白话解释（前端 Tooltip） */
  hint?: string | null
  /** 选择题是否在选项末尾提供「其他」文本输入 */
  allowOther?: boolean | null
  /** 互斥选项标签（如「正常」）：选中即清空其它，选其它即取消该项 */
  exclusiveOptions?: string[] | null
}

export interface QuestionGroup {
  group_id: string
  title: string
  priority: Priority
  questions: Question[]
  /** 分组显示条件（如 `{qid:'gender', equals:'女'}`：性别为女时才展示） */
  showWhen?: { qid: string; equals?: unknown } | null
}

export interface InquiryTemplate {
  template_version: string
  groups: QuestionGroup[]
}

/** 单题作答值。 */
export type AnswerValue = string | number | boolean | string[] | null
export interface AnswerItem {
  qid: string
  value: AnswerValue
}
export type AnswersMap = Record<string, AnswerValue>

export interface DraftResult {
  saved: boolean
  updated_at: string
}

export interface SubmitResult {
  record_id: string
  completed: boolean
}

export interface InquiryAnalysisResult {
  symptoms_summary: string
  main_syndrome: Syndrome | null
  secondary_syndromes: Syndrome[]
  treatment_principles: string[]
  recommendations: Recommendation[]
}

export interface InquiryAnalysisQueryResult {
  inquiry_id: string
  record_id: string
  status: AnalysisStatus
  missing_items: string[]
  result: InquiryAnalysisResult | null
  model_version: string | null
  retryable: boolean
}

export interface InquiryPatientSnapshot {
  name: string | null
  gender: string | null
  age: number | null
  height: number | null
  weight: number | null
  anonymous: boolean
}

export interface InquiryDraftState {
  template_version: string
  answers: AnswersMap
  updated_at: string
}

export interface InquiryRecordState {
  record_id: string
  template_version: string
  patient_snapshot: InquiryPatientSnapshot
  answers: AnswersMap
  missing_items: string[]
  status: ModuleStatus
  completed: boolean
  submitted_at: string | null
  analysis: InquiryAnalysisQueryResult | null
}

/** 会话问诊状态快照（I0）：草稿与已提交记录均可能为空。 */
export interface InquiryState {
  draft: InquiryDraftState | null
  record: InquiryRecordState | null
}

export const inquiryApi = {
  /** I1 获取问诊模板（模板驱动渲染） */
  getTemplate: () => http.get<InquiryTemplate>('/inquiry/template'),

  /** I2 保存服务端草稿（与 localStorage 双写，服务端为准） */
  saveDraft: (sessionId: string, templateVersion: string, answers: AnswerItem[]) =>
    http.put<DraftResult>(`/sessions/${sessionId}/inquiry/draft`, {
      template_version: templateVersion,
      answers,
    }),

  /** I3 提交问诊（服务端二次校验 P0；成功即自动触发 AI 分析） */
  submit: (sessionId: string, templateVersion: string, answers: AnswerItem[]) =>
    http.post<SubmitResult>(`/sessions/${sessionId}/inquiry/submit`, {
      template_version: templateVersion,
      answers,
    }),

  /** I4 问诊 AI 分析（异步，返回 task_id；用于「重新分析」） */
  startAiAnalysis: (sessionId: string, recordId: string, language = 'zh-CN') =>
    http.post<AiAnalysisStart>(`/sessions/${sessionId}/inquiry/ai-analysis`, {
      record_id: recordId,
      language,
    }),

  /** I5 查询问诊分析结果 */
  getAnalysis: (sessionId: string) =>
    http.get<InquiryAnalysisQueryResult>(`/sessions/${sessionId}/inquiry/analysis`),

  /** I0 查询会话问诊状态（页面重新挂载时恢复草稿 / 结果） */
  getRecord: (sessionId: string) =>
    http.get<InquiryState>(`/sessions/${sessionId}/inquiry/record`),

  /** I6 清空会话问诊（软删记录 + 删除草稿；「重置表单」时调用，避免刷新后回填） */
  clearRecord: (sessionId: string) =>
    http.delete<ClearRecordResult>(`/sessions/${sessionId}/inquiry/record`),
}

// ===== 三诊合参（M5，G0~G2；PRD §6.4 / §9.5）=====

/** 报告综合评估健康等级（UI/UX §3.1 色板）。 */
export type HealthLevel = 'good' | 'fair' | 'poor' | 'bad'
/** 三诊模块键。 */
export type ModuleKey = 'tongue' | 'face' | 'inquiry'

/** 报告 Tab 键（UI/UX §5.5.3，顺序即打印串行顺序）。 */
export type ReportTabKey =
  | 'overview'
  | 'details'
  | 'indices'
  | 'therapy'
  | 'constitution'
  | 'prevention'
  | 'advice'
  | 'emotion'

export interface FusionModuleState {
  done: boolean
  overall_confidence: number | null
  summary: string | null
}

/** G0 前置校验：三诊完成态 + 缺诊判定。 */
export interface FusionReadiness {
  session_id: string
  modules: Record<ModuleKey, FusionModuleState>
  missing_modules: ModuleKey[]
  can_analyze: boolean
  blocking_reason: string | null
}

export interface FusionConflict {
  modules: ModuleKey[]
  description: string
}

export interface FusionConclusion {
  text: string
  confidence: number
}

export interface FusionSuggestion {
  category: string
  text: string
}

export interface FusionAnalyzeResult {
  fusion_status: AnalysisStatus
  task_id: string
}

// ---- 报告数据（P6 8 Tab）----
export interface ReportPatientSnapshot {
  name: string | null
  gender: string | null
  age: number | null
  height: number | null
  weight: number | null
  anonymous: boolean
}

export interface ReportHeader {
  session_id: string
  patient_snapshot: ReportPatientSnapshot | null
  generated_at: string | null
  overall_confidence: number | null
  health_level: HealthLevel | null
  rule_version: string | null
  model_version: string | null
  status: string
}

export interface ReportModuleDetail {
  module: ModuleKey
  record_id: string
  image_ref: string
  features: FeatureItem[]
  summary: string | null
  main_syndrome: Syndrome | null
  secondary_syndromes: Syndrome[]
  treatment_principles: string[]
  model_version: string | null
}

export interface ReportInquiryDetail {
  record_id: string
  patient_snapshot: ReportPatientSnapshot | null
  answers: Record<string, unknown>
  missing_items: string[]
  summary: string | null
  main_syndrome: Syndrome | null
  secondary_syndromes: Syndrome[]
  treatment_principles: string[]
  model_version: string | null
}

export interface ReportOverview {
  conclusions: FusionConclusion[]
  syndrome_points: string[]
  overall_confidence: number | null
  evidence_summary: string[]
}

export interface ReportDetails {
  tongue: ReportModuleDetail | null
  face: ReportModuleDetail | null
  inquiry: ReportInquiryDetail | null
}

export interface ReportIndexItem {
  name: string
  value: string
  reference: string | null
  level: string
}

export interface ReportTherapyItem {
  name: string
  value: string
  note: string | null
}

export interface ReportConstitution {
  main_syndrome: Syndrome | null
  secondary_syndromes: Syndrome[]
  description: string | null
}

export interface ReportPreventionGroup {
  title: string
  items: string[]
}

export interface ReportEmotionDimension {
  name: string
  score: number
  note: string | null
}

export interface ReportEmotion {
  dimensions: ReportEmotionDimension[]
  summary: string | null
}

/** 报告 8 Tab 渲染数据。 */
export interface ReportData {
  header: ReportHeader
  overview: ReportOverview
  details: ReportDetails
  indices: { items: ReportIndexItem[] }
  therapy: { items: ReportTherapyItem[] }
  constitution: ReportConstitution
  prevention: { groups: ReportPreventionGroup[] }
  advice: { suggestions: FusionSuggestion[] }
  emotion: ReportEmotion
}

/** G2 合参结果（含报告数据）。 */
export interface FusionResultData {
  fusion_id: string
  session_id: string
  status: AnalysisStatus
  overall_confidence: number | null
  health_level: HealthLevel | null
  missing_modules: ModuleKey[]
  conflicts: FusionConflict[]
  conclusions: FusionConclusion[]
  syndrome_points: string[]
  suggestions: FusionSuggestion[]
  rule_version: string | null
  model_version: string | null
  retryable: boolean
  /** 报告记录标识与状态（合参完成后自动生成；供导出 PDF / 归档使用） */
  report_id: string | null
  report_status: ReportStatus | null
  report: ReportData | null
}

/** 报告状态（PRD §6.5）：草稿 / 定稿 / 已归档。 */
export type ReportStatus = 'draft' | 'final' | 'archived'

export interface ArchiveReportResult {
  report_id: string
  status: ReportStatus
  archived_at: string | null
}

export interface DeleteReportResult {
  report_id: string
  deleted: boolean
}

export const diagnosisApi = {
  /** G0 前置校验（三诊就绪 / 缺诊阻断） */
  getReadiness: (sessionId: string) =>
    http.get<FusionReadiness>(`/sessions/${sessionId}/fusion/readiness`),

  /** G1 触发三诊合参分析（异步，返回 task_id） */
  analyze: (sessionId: string, includeInquiry = true, language = 'zh-CN') =>
    http.post<FusionAnalyzeResult>(`/sessions/${sessionId}/fusion/analyze`, {
      options: { include_inquiry: includeInquiry, language },
    }),

  /** G2 查询合参结果（完成后附带报告 8 Tab 数据） */
  getResult: (sessionId: string) =>
    http.get<FusionResultData>(`/sessions/${sessionId}/fusion/result`),
}

/** 报告图像访问地址（原图；开发期免签，对齐单诊媒体接口）。 */
export function reportImageUrl(module: ModuleKey, recordId: string, imageRef: string): string {
  const filename = imageRef.split('/').filter(Boolean).pop() ?? 'raw.png'
  if (module === 'face') return faceApi.mediaUrl(recordId, filename)
  return tongueApi.mediaUrl(recordId, filename)
}

// ===== 报告管理（M6，R3 / R5；PRD §6.5 / §9.6）=====

/** 从 `Content-Disposition` 解析文件名（优先 RFC 5987 的 `filename*`）。 */
function parseFilename(disposition: string | null): string | null {
  if (!disposition) return null
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  if (utf8 && utf8[1]) {
    try {
      return decodeURIComponent(utf8[1])
    } catch {
      /* 解码失败则回退 */
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(disposition)
  return plain && plain[1] ? plain[1] : null
}

// ---- 报告历史（M6 R4；PRD §6.5.4 / §9.6）----

/** 历史列表项（对齐后端 `ReportHistoryItem`）。 */
export interface ReportHistoryItem {
  report_id: string
  session_id: string
  patient_name: string | null
  anonymous: boolean
  generated_at: string
  overall_confidence: number | null
  health_level: HealthLevel | null
  status: ReportStatus
  summary: string | null
}

/** R4 查询参数（对齐后端 `GET /reports`）。 */
export interface ReportHistoryQuery {
  patient_name?: string
  /** 结论关键词，可多词（AND 关系），以重复同名参数提交 */
  keyword?: string[]
  anonymous?: boolean
  status?: ReportStatus
  /** 生成时间范围（`yyyy-MM-dd`） */
  from?: string
  to?: string
  page?: number
  page_size?: number
}

export const reportApi = {
  /**
   * R4 历史记录查询（`GET /reports`，PRD §6.5.4 / §9.6）。
   * 手工拼查询串以支持多词 `keyword` 重复参数（后端按 AND 处理）。
   */
  list: (params: ReportHistoryQuery) => {
    const search = new URLSearchParams()
    if (params.patient_name) search.append('patient_name', params.patient_name)
    for (const term of params.keyword ?? []) {
      if (term) search.append('keyword', term)
    }
    if (params.anonymous !== undefined) search.append('anonymous', String(params.anonymous))
    if (params.status) search.append('status', params.status)
    if (params.from) search.append('from', params.from)
    if (params.to) search.append('to', params.to)
    search.append('page', String(params.page ?? 1))
    search.append('page_size', String(params.page_size ?? 20))
    return http.get<PageResult<ReportHistoryItem>>(`/reports?${search.toString()}`)
  },

  /** R5 归档报告（二态流转，幂等） */
  archive: (reportId: string) =>
    http.post<ArchiveReportResult>(`/reports/${reportId}/archive`),

  /** R6 删除报告（软删；二次确认由前端完成） */
  remove: (reportId: string) => http.delete<DeleteReportResult>(`/reports/${reportId}`),

  /**
   * R3 导出报告 PDF：以 Blob 下载（需携带 Bearer，故不走 `window.open`）。
   * 文件名优先取响应头 `Content-Disposition`，回退 `报告_{reportId}.pdf`。
   */
  downloadPdf: async (reportId: string): Promise<void> => {
    const token = useAuthStore.getState().accessToken
    const response = await fetch(`${API_BASE_URL}/reports/${reportId}/pdf`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
    if (!response.ok) {
      throw new ApiError({
        code: response.status,
        message: '报告导出失败，请稍后重试',
        httpStatus: response.status,
      })
    }
    const blob = await response.blob()
    const filename = parseFilename(response.headers.get('content-disposition')) ?? `报告_${reportId}.pdf`
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = filename
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    URL.revokeObjectURL(url)
  },
}

// ===== 报告对比（P8 数据对比页；UI/UX §5.7）=====

/** 变化方向语义：改善 / 加重 / 持平 / 无法判定。 */
export type ChangeDirection = 'improved' | 'worsened' | 'same' | 'unknown'

/** 参与对比的一份报告元信息。 */
export interface CompareReportSummary {
  report_id: string
  session_id: string
  patient_name: string | null
  anonymous: boolean
  generated_at: string
  health_level: HealthLevel | null
  overall_confidence: number | null
  status: ReportStatus
  summary: string | null
}

export interface CompareHealthChange {
  base_level: HealthLevel | null
  target_level: HealthLevel | null
  direction: ChangeDirection
}

export interface CompareFeatureDiffItem {
  name: string
  label: string
  base_value: string | null
  target_value: string | null
  changed: boolean
  direction: ChangeDirection
  base_confidence: number | null
  target_confidence: number | null
}

export interface CompareModuleFeatureDiff {
  module: ModuleKey
  label: string
  items: CompareFeatureDiffItem[]
}

export interface CompareConclusionDiff {
  base_texts: string[]
  target_texts: string[]
  added: string[]
  removed: string[]
}

export interface CompareTrendPoint {
  report_id: string
  generated_at: string
  overall_confidence: number | null
  health_level: HealthLevel | null
  role: 'base' | 'target' | 'history'
}

export interface CompareResult {
  base: CompareReportSummary
  target: CompareReportSummary
  health: CompareHealthChange
  modules: CompareModuleFeatureDiff[]
  conclusions: CompareConclusionDiff
  trend: CompareTrendPoint[]
}

export const compareApi = {
  /**
   * R-CMP 报告对比（`GET /reports/compare`，UI/UX §5.7）。
   * `base` 为基准（较早）报告，`target` 为对比（最近）报告；仅支持同一患者。
   */
  get: (base: string, target: string, trend = 5) =>
    http.get<CompareResult>(
      `/reports/compare?base=${encodeURIComponent(base)}&target=${encodeURIComponent(
        target,
      )}&trend=${trend}`,
    ),
}
