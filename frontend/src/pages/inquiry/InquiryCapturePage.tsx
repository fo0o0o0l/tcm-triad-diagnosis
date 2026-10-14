import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { ModelBadge } from '@/components/ModelBadge'
import { PageShell } from '@/components/PageShell'
import { SessionNo } from '@/components/SessionNo'
import {
  inquiryApi,
  type AnswerItem,
  type AnswersMap,
  type AnswerValue,
  type InquiryAnalysisQueryResult,
  type InquiryTemplate,
  type Question,
  type QuestionGroup,
} from '@/services/api'
import { ApiError } from '@/utils/request'
import { resolveSessionId } from '@/utils/session'

import styles from './InquiryCapturePage.module.css'

/**
 * P4 问诊录入页（PRD §6.3 / UI/UX §5.3）。
 *
 * 模板驱动动态渲染：进页面拉取 I1 模板 → 按分组渲染题目 → 草稿防抖双写（localStorage + 服务端）
 * → 提交校验（定位首个缺失项）→ 提交成功后轮询 I5 展示 AI 证候判读。
 */

type Stage = 'loading' | 'form' | 'submitting' | 'ai' | 'done'

const LOCAL_DRAFT_PREFIX = 'inquiry_draft_'
const DEBOUNCE_MS = 800
const cardId = (qid: string) => `q-${qid}`

const sleep = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms))

/** 空值判定：null/undefined、空串、空数组均视为未作答。 */
function isBlank(value: AnswerValue): boolean {
  if (value === null || value === undefined) return true
  if (typeof value === 'string') return value.trim() === ''
  if (Array.isArray(value)) return value.length === 0
  return false
}

/** 「其他」补充值前缀（用于与模板固定选项区分）。 */
const OTHER_PREFIX = '其他：'

/** 读取「其他」补充文本；未填写其他时返回 null。 */
function otherText(value: AnswerValue): string | null {
  const prefixItem = (item: unknown): string | null =>
    typeof item === 'string' && item.startsWith(OTHER_PREFIX)
      ? item.slice(OTHER_PREFIX.length)
      : null
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = prefixItem(item)
      if (found !== null) return found
    }
    return null
  }
  return prefixItem(value)
}

function isOtherItem(value: unknown): boolean {
  return typeof value === 'string' && value.startsWith(OTHER_PREFIX)
}

/** 写入「其他」文本：单选→字符串值；多选→替换其它项，保留其余已选。 */
function withOtherText(value: AnswerValue, text: string): AnswerValue {
  const item = `${OTHER_PREFIX}${text}`
  if (Array.isArray(value)) return [...value.filter((v) => !isOtherItem(v)), item]
  return item
}

/** 移除「其他」补充项。 */
function withoutOther(value: AnswerValue): AnswerValue {
  if (Array.isArray(value)) return value.filter((v) => !isOtherItem(v))
  return ''
}

/** 多选切换：命中互斥项（如「正常」）时独占；命中其它项时先清掉互斥项。 */
function toggleMultiOption(
  selected: string[],
  option: string,
  exclusive: string[],
): string[] {
  if (selected.includes(option)) return selected.filter((item) => item !== option)
  if (exclusive.includes(option)) return [option]
  return [...selected.filter((item) => !exclusive.includes(item)), option]
}

/** 分组显示条件判定：无 `showWhen` 恒显示；否则需 `answers[qid] === equals`。 */
function groupVisible(group: QuestionGroup, answers: AnswersMap): boolean {
  const cond = group.showWhen
  if (!cond || !cond.qid) return true
  return answers[cond.qid] === cond.equals
}

function confidenceLevel(value: number): 'high' | 'medium' | 'low' {
  if (value >= 0.85) return 'high'
  if (value >= 0.7) return 'medium'
  return 'low'
}

interface LocalDraft {
  template_version: string
  answers: AnswersMap
  updated_at: string
}

function readLocalDraft(sessionId: string): LocalDraft | null {
  try {
    const raw = window.localStorage.getItem(LOCAL_DRAFT_PREFIX + sessionId)
    if (!raw) return null
    const parsed = JSON.parse(raw) as LocalDraft
    if (!parsed || typeof parsed !== 'object' || !parsed.answers) return null
    return parsed
  } catch {
    return null
  }
}

function writeLocalDraft(sessionId: string, draft: LocalDraft): void {
  try {
    window.localStorage.setItem(LOCAL_DRAFT_PREFIX + sessionId, JSON.stringify(draft))
  } catch {
    /* 隐私模式等写入失败时静默降级 */
  }
}

function clearLocalDraft(sessionId: string): void {
  try {
    window.localStorage.removeItem(LOCAL_DRAFT_PREFIX + sessionId)
  } catch {
    /* 忽略 */
  }
}

/** 按模板生成初始答案（multi→[]、switch→默认布尔、其余→默认值或空串）。 */
function buildDefaults(template: InquiryTemplate): AnswersMap {
  const map: AnswersMap = {}
  for (const group of template.groups) {
    for (const question of group.questions) {
      if (question.type === 'multi') map[question.qid] = []
      else if (question.type === 'switch') map[question.qid] = Boolean(question.default)
      else if (question.default !== undefined && question.default !== null)
        map[question.qid] = String(question.default)
      else map[question.qid] = ''
    }
  }
  return map
}

function toAnswerItems(answers: AnswersMap): AnswerItem[] {
  return Object.entries(answers).map(([qid, value]) => ({ qid, value }))
}

export function InquiryCapturePage() {
  const [searchParams] = useSearchParams()
  const sessionId = useMemo(() => resolveSessionId(searchParams.get('session_id')), [searchParams])

  const [stage, setStage] = useState<Stage>('loading')
  const [template, setTemplate] = useState<InquiryTemplate | null>(null)
  const [answers, setAnswers] = useState<AnswersMap>({})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [notice, setNotice] = useState('')
  const [globalError, setGlobalError] = useState('')
  const [recordId, setRecordId] = useState<string | null>(null)
  const [analysis, setAnalysis] = useState<InquiryAnalysisQueryResult | null>(null)

  const hydratedRef = useRef<string | null>(null)
  const dirtyRef = useRef(false)

  const pollAnalysis = useCallback(async (): Promise<InquiryAnalysisQueryResult> => {
    let delay = 1000
    for (let attempt = 0; attempt < 40; attempt += 1) {
      await sleep(delay)
      const result = await inquiryApi.getAnalysis(sessionId)
      if (result.status === 'completed' || result.status === 'failed') return result
      delay = Math.min(3000, delay + 500)
    }
    throw new Error('问诊分析超时，请稍后重试')
  }, [sessionId])

  // 挂载时拉取模板与状态：已提交记录优先展示；否则取较新的草稿（服务端 / 本地）恢复。
  useEffect(() => {
    if (hydratedRef.current === sessionId) return
    hydratedRef.current = sessionId
    void (async () => {
      try {
        const [tpl, state] = await Promise.all([
          inquiryApi.getTemplate(),
          inquiryApi.getRecord(sessionId),
        ])
        setTemplate(tpl)

        if (state.record) {
          setAnswers({ ...buildDefaults(tpl), ...state.record.answers })
          setRecordId(state.record.record_id)
          setStage('form')
          if (state.record.analysis) {
            setAnalysis(state.record.analysis)
            if (['pending', 'analyzing'].includes(state.record.analysis.status)) {
              setStage('ai')
              setAnalysis(await pollAnalysis().catch(() => state.record?.analysis ?? null))
            }
          }
          return
        }

        const local = readLocalDraft(sessionId)
        const localValid = Boolean(local && local.template_version === tpl.template_version)
        const serverDraft =
          state.draft && state.draft.template_version === tpl.template_version ? state.draft : null

        // 服务端草稿与本地草稿取较新者（服务端为准，但避免丢失未同步的本地输入）
        let source: { answers: AnswersMap; updated_at: string } | null = serverDraft
        if (localValid && local) {
          const newer =
            !source || new Date(local.updated_at).getTime() > new Date(source.updated_at).getTime()
          if (newer) source = { answers: local.answers, updated_at: local.updated_at }
        }

        if (source) {
          setAnswers({ ...buildDefaults(tpl), ...source.answers })
          const time = new Date(source.updated_at).toLocaleTimeString('zh-CN', {
            hour: '2-digit',
            minute: '2-digit',
          })
          setNotice(`已恢复上次填写内容（${time}）`)
        } else {
          setAnswers(buildDefaults(tpl))
        }
        setStage('form')
      } catch (err) {
        setGlobalError(err instanceof Error ? err.message : '模板加载失败，请稍后重试')
        setStage('form')
      }
    })()
  }, [pollAnalysis, sessionId])

  const flushDraft = useCallback(() => {
    if (!template || !dirtyRef.current) return
    dirtyRef.current = false
    writeLocalDraft(sessionId, {
      template_version: template.template_version,
      answers,
      updated_at: new Date().toISOString(),
    })
    void inquiryApi.saveDraft(sessionId, template.template_version, toAnswerItems(answers)).catch(
      () => undefined,
    )
  }, [answers, sessionId, template])

  // 草稿防抖保存（字段变更 800ms 后写入本地 + 服务端）
  useEffect(() => {
    if (!template || !dirtyRef.current) return
    const timer = window.setTimeout(flushDraft, DEBOUNCE_MS)
    return () => window.clearTimeout(timer)
  }, [answers, flushDraft, template])

  // 页面隐藏时立即落草稿，避免中途离开丢失
  useEffect(() => {
    const onHide = () => {
      if (document.visibilityState === 'hidden') flushDraft()
    }
    document.addEventListener('visibilitychange', onHide)
    return () => document.removeEventListener('visibilitychange', onHide)
  }, [flushDraft])

  // 依 `showWhen` 过滤可见分组（如性别=女才显示月经专项）；隐藏分组不参与进度与校验
  const visibleGroups = useMemo(
    () => (template ? template.groups.filter((group) => groupVisible(group, answers)) : []),
    [answers, template],
  )

  // 分组折叠态：缺省 P2（补充）分组折叠、其余展开；用户可手动切换
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const isCollapsed = useCallback(
    (group: QuestionGroup) => collapsed[group.group_id] ?? group.priority === 'P2',
    [collapsed],
  )

  const handleChange = useCallback(
    (question: Question, value: AnswerValue) => {
      dirtyRef.current = true
      setAnswers((prev) => {
        const next: AnswersMap = { ...prev, [question.qid]: value }
        // 联动：开启「匿名」等 clearFields 效果时清空目标字段
        if (question.effect === 'clearFields' && value === true) {
          for (const target of question.targets ?? []) {
            next[target] = Array.isArray(prev[target]) ? [] : ''
          }
        }
        return next
      })
      setErrors((prev) => {
        if (!prev[question.qid]) return prev
        const next = { ...prev }
        delete next[question.qid]
        return next
      })
    },
    [],
  )

  const validate = useCallback((): boolean => {
    if (!template) return false
    const nextErrors: Record<string, string> = {}
    let firstMissing: string | null = null
    for (const group of visibleGroups) {
      for (const question of group.questions) {
        const value = answers[question.qid]
        let message = ''
        if (question.required && isBlank(value)) {
          message = '该项为必填'
        } else if (question.type === 'number' && !isBlank(value)) {
          const num = Number(value)
          if (Number.isNaN(num)) message = '请输入数值'
          else if (question.range && (num < question.range[0] || num > question.range[1]))
            message = `请输入 ${question.range[0]}-${question.range[1]} 之间的数值`
        } else if (
          question.type === 'text' &&
          typeof value === 'string' &&
          question.maxLength &&
          value.length > question.maxLength
        ) {
          message = `最多 ${question.maxLength} 字`
        }
        if (message) {
          nextErrors[question.qid] = message
          if (!firstMissing) firstMissing = question.qid
        }
      }
    }
    setErrors(nextErrors)
    if (firstMissing) {
      document
        .getElementById(cardId(firstMissing))
        ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
      setGlobalError('存在未完成的必填项，请检查红色提示项')
      return false
    }
    setGlobalError('')
    return true
  }, [answers, template, visibleGroups])

  const submit = useCallback(async () => {
    if (!template || !validate()) return
    setGlobalError('')
    setStage('submitting')
    try {
      const result = await inquiryApi.submit(
        sessionId,
        template.template_version,
        toAnswerItems(answers),
      )
      setRecordId(result.record_id)
      dirtyRef.current = false
      clearLocalDraft(sessionId)
      setStage('ai')
      setAnalysis(await pollAnalysis())
      setStage('done')
    } catch (err) {
      if (err instanceof ApiError && err.code === 40001) {
        const data = err.data as { missing?: string[]; first_missing?: string } | null
        const missing = data?.missing ?? []
        const nextErrors: Record<string, string> = {}
        for (const qid of missing) nextErrors[qid] = '该项为必填'
        setErrors(nextErrors)
        const first = data?.first_missing ?? missing[0]
        if (first) {
          document.getElementById(cardId(first))?.scrollIntoView({ behavior: 'smooth', block: 'center' })
        }
        setGlobalError(err.message || '存在未完成的必填项')
      } else {
        setGlobalError(err instanceof Error ? err.message : '提交失败，请重试')
      }
      setStage('form')
    }
  }, [answers, pollAnalysis, sessionId, template, validate])

  const reanalyze = useCallback(async () => {
    if (!recordId) return
    setGlobalError('')
    setAnalysis(null)
    try {
      setStage('ai')
      await inquiryApi.startAiAnalysis(sessionId, recordId)
      setAnalysis(await pollAnalysis())
      setStage('done')
    } catch (err) {
      setGlobalError(err instanceof Error ? err.message : '分析失败，请重试')
      setStage('form')
    }
  }, [pollAnalysis, recordId, sessionId])

  const [clearing, setClearing] = useState(false)

  const reset = useCallback(async () => {
    if (!template || clearing) return
    if (!window.confirm('将清空所有已填内容并删除草稿，是否继续？')) return
    setGlobalError('')
    setClearing(true)
    try {
      // 同步清空服务端记录与草稿，否则刷新后 I0 会回填已提交 / 已填内容
      await inquiryApi.clearRecord(sessionId)
    } catch (err) {
      setGlobalError(err instanceof Error ? err.message : '清空失败，请稍后重试')
      setClearing(false)
      return
    }
    clearLocalDraft(sessionId)
    dirtyRef.current = false
    setAnswers(buildDefaults(template))
    setErrors({})
    setNotice('')
    setAnalysis(null)
    setRecordId(null)
    setStage('form')
    setClearing(false)
  }, [clearing, sessionId, template])

  const requiredQuestions = useMemo(
    () => visibleGroups.flatMap((g) => g.questions).filter((q) => q.required),
    [visibleGroups],
  )
  const allQuestions = useMemo(() => visibleGroups.flatMap((g) => g.questions), [visibleGroups])

  // 分组导航点击：先展开该分组再滚动定位（折叠时内容不在可视区）
  const jumpToGroup = useCallback((group: QuestionGroup) => {
    setCollapsed((prev) => ({ ...prev, [group.group_id]: false }))
    window.requestAnimationFrame(() => {
      document
        .getElementById(`group-${group.group_id}`)
        ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    })
  }, [])

  const expandAll = useCallback(() => {
    setCollapsed(Object.fromEntries(visibleGroups.map((g) => [g.group_id, false])))
  }, [visibleGroups])

  const collapseAll = useCallback(() => {
    setCollapsed(Object.fromEntries(visibleGroups.map((g) => [g.group_id, true])))
  }, [visibleGroups])
  const answeredRequired = requiredQuestions.filter((q) => !isBlank(answers[q.qid])).length
  const answeredTotal = allQuestions.filter((q) => !isBlank(answers[q.qid])).length
  const progressPct = allQuestions.length
    ? Math.round((answeredTotal / allQuestions.length) * 100)
    : 0

  const busy = stage === 'submitting' || stage === 'ai'

  const groupStatus = useCallback(
    (group: QuestionGroup): 'done' | 'doing' | 'empty' => {
      const required = group.questions.filter((q) => q.required)
      if (required.length > 0 && required.every((q) => !isBlank(answers[q.qid]))) return 'done'
      if (group.questions.some((q) => !isBlank(answers[q.qid]))) return 'doing'
      return 'empty'
    },
    [answers],
  )

  return (
    <PageShell
      title="问诊录入"
      description="问诊 · 结构化表单：基础信息 → 主诉 → 症状（寒热/汗/眠/食/二便/胸腹）→ AI 证候判读"
    >
      <div className={styles.sessionBar}>
        <span className={styles.sessionLabel}>当前会话</span>
        <SessionNo sessionId={sessionId} className={styles.sessionId} />
      </div>

      {/* 顶部进度 */}
      <div className={styles.progressBar}>
        <span className={styles.progressText}>
          必填 {answeredRequired}/{requiredQuestions.length}
        </span>
        <div className={styles.track}>
          <div className={styles.fill} style={{ width: `${progressPct}%` }} />
        </div>
        <span className={styles.progressText}>{progressPct}%</span>
      </div>

      {notice ? (
        <div className={styles.notice}>
          <span>{notice}</span>
          <button type="button" className={styles.noticeClose} onClick={() => setNotice('')}>
            放弃恢复
          </button>
        </div>
      ) : null}

      {globalError ? <div className={styles.error}>{globalError}</div> : null}

      {stage === 'loading' ? (
        <div className={styles.empty}>正在加载问诊模板…</div>
      ) : (
        <div className={styles.layout}>
          {/* 分组导航 */}
          <nav className={styles.groupNav} aria-label="问诊分组">
            <ol className={styles.groupList}>
              {visibleGroups.map((group) => {
                const status = groupStatus(group)
                return (
                  <li key={group.group_id}>
                    <button
                      type="button"
                      className={`${styles.groupItem} ${styles[status]}`}
                      onClick={() => jumpToGroup(group)}
                    >
                      <span className={styles.groupDot}>
                        {status === 'done' ? '✓' : status === 'doing' ? '◉' : '○'}
                      </span>
                      <span className={styles.groupTitle}>{group.title}</span>
                      <span className={`${styles.priorityBadge} ${styles[group.priority]}`}>
                        {group.priority === 'P0' ? '必填' : group.priority === 'P1' ? '选填' : '补充'}
                      </span>
                    </button>
                  </li>
                )
              })}
            </ol>
            <div className={styles.navActions}>
              <button type="button" className={styles.navAction} onClick={expandAll}>
                全部展开
              </button>
              <button type="button" className={styles.navAction} onClick={collapseAll}>
                全部收起
              </button>
            </div>
          </nav>

          {/* 题目区（分组折叠：P2 缺省收起，可手动切换） */}
          <div className={styles.main}>
            {visibleGroups.map((group) => {
              const collapsedNow = isCollapsed(group)
              return (
                <section
                  key={group.group_id}
                  id={`group-${group.group_id}`}
                  className={styles.groupSection}
                >
                  <button
                    type="button"
                    className={styles.groupHeader}
                    aria-expanded={!collapsedNow}
                    onClick={() =>
                      setCollapsed((prev) => ({ ...prev, [group.group_id]: !collapsedNow }))
                    }
                  >
                    <span className={`${styles.caret} ${collapsedNow ? '' : styles.caretOpen}`}>
                      ▾
                    </span>
                    <span className={styles.groupHeaderTitle}>{group.title}</span>
                    <span className={`${styles.priorityBadge} ${styles[group.priority]}`}>
                      {group.priority}
                    </span>
                  </button>

                  {!collapsedNow ? (
                    <div className={styles.questions}>
                      {group.questions
                        // 匿名开启时隐藏姓名输入（PRD §6.3.1）
                        .filter((q) => !(q.qid === 'name' && answers.anonymous === true))
                        .map((question) => (
                          <QuestionField
                            key={question.qid}
                            question={question}
                            value={answers[question.qid]}
                            error={errors[question.qid]}
                            disabled={busy}
                            onChange={(value) => handleChange(question, value)}
                          />
                        ))}
                    </div>
                  ) : null}
                </section>
              )
            })}

            <div className={styles.actions}>
              <button
                type="button"
                className="btn btn--primary"
                disabled={busy}
                onClick={() => void submit()}
              >
                {stage === 'submitting' ? '提交中…' : '提交并分析'}
              </button>
              <button
                type="button"
                className="btn btn--ghost"
                disabled={busy}
                onClick={() => {
                  flushDraft()
                  setNotice('草稿已保存')
                }}
              >
                保存草稿
              </button>
              <button
                type="button"
                className="btn btn--ghost"
                disabled={busy || clearing}
                onClick={() => void reset()}
              >
                {clearing ? '清空中…' : '重置表单'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* AI 结果区 */}
      {stage === 'ai' ? <div className={styles.status}>AI 正在分析问诊信息…</div> : null}

      {analysis ? (
        <section className={styles.result}>
          <h2 className={styles.groupHeading}>
            AI 问诊分析
            <ModelBadge modelVersion={analysis.model_version} />
          </h2>

          {analysis.status === 'completed' && analysis.result ? (
            <>
              <p className={styles.summary}>{analysis.result.symptoms_summary}</p>

              {analysis.result.main_syndrome ? (
                <div className={styles.inline}>
                  <span>主要证候</span>
                  <strong>{analysis.result.main_syndrome.name}</strong>
                  <span
                    className={`${styles.confBadge} ${styles[confidenceLevel(analysis.result.main_syndrome.confidence)]}`}
                  >
                    {Math.round(analysis.result.main_syndrome.confidence * 100)}%
                  </span>
                </div>
              ) : null}

              {analysis.result.secondary_syndromes.length > 0 ? (
                <div className={styles.tagRow}>
                  {analysis.result.secondary_syndromes.map((item) => (
                    <span className={styles.tag} key={item.name}>
                      {item.name} {Math.round(item.confidence * 100)}%
                    </span>
                  ))}
                </div>
              ) : null}

              {analysis.result.treatment_principles.length > 0 ? (
                <div className={styles.tagRow}>
                  {analysis.result.treatment_principles.map((item) => (
                    <span className={styles.tagPrimary} key={item}>
                      {item}
                    </span>
                  ))}
                </div>
              ) : null}

              <ul className={styles.recommendations}>
                {analysis.result.recommendations.map((item) => (
                  <li key={`${item.category}-${item.text}`}>
                    <strong>{item.category}：</strong>
                    {item.text}
                  </li>
                ))}
              </ul>

              {analysis.missing_items.length > 0 ? (
                <p className={styles.muted}>
                  未答选填项：{analysis.missing_items.join('、')}（供置信度参考）
                </p>
              ) : null}
            </>
          ) : analysis.status === 'failed' ? (
            <div className={styles.error}>
              <div>问诊分析暂不可用，可重试（已提交的问诊记录不受影响）。</div>
              {analysis.retryable ? (
                <button type="button" className="btn btn--ghost" onClick={() => void reanalyze()}>
                  重新分析
                </button>
              ) : null}
            </div>
          ) : (
            <div className={styles.status}>AI 分析中…</div>
          )}
        </section>
      ) : null}
    </PageShell>
  )
}

interface QuestionFieldProps {
  question: Question
  value: AnswerValue
  error?: string
  disabled: boolean
  onChange: (value: AnswerValue) => void
}

/** 单题渲染：按题型映射到对应控件（PRD §6.3.4 / UI/UX §5.3.3）。 */
function QuestionField({ question, value, error, disabled, onChange }: QuestionFieldProps) {
  const { qid, type, label, required, options, placeholder, range, unit, maxLength, hint } = question
  const exclusive = question.exclusiveOptions ?? []
  const selectedList = Array.isArray(value) ? value : []
  const textValue = typeof value === 'string' ? value : value === null ? '' : String(value ?? '')
  const allowOther = Boolean(question.allowOther)
  const other = allowOther ? otherText(value) : null

  return (
    <div className={`${styles.questionCard} ${error ? styles.hasError : ''}`} id={cardId(qid)}>
      <div className={styles.questionLabel}>
        <span className={styles.labelText}>
          {label}
          {required ? <span className={styles.requiredMark}>*</span> : null}
          {hint ? (
            <span className={styles.tip}>
              <button type="button" className={styles.tipTrigger} aria-label={`${label} 术语说明`}>
                ?
              </button>
              <span className={styles.tipBubble} role="tooltip">
                {hint}
              </span>
            </span>
          ) : null}
        </span>
        {question.priority !== 'P0' ? (
          <span className={styles.muted}>{question.priority === 'P1' ? '选填' : '补充'}</span>
        ) : null}
      </div>

      {type === 'single' ? (
        <div className={styles.chips} role="radiogroup" aria-label={label}>
          {(options ?? []).map((option) => (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={value === option}
              disabled={disabled}
              className={`${styles.chip} ${styles.chipSingle} ${
                value === option ? styles.chipActive : ''
              }`}
              onClick={() => onChange(option)}
            >
              {value === option ? '✓ ' : ''}
              {option}
            </button>
          ))}
          {allowOther ? (
            <button
              type="button"
              role="radio"
              aria-checked={other !== null}
              disabled={disabled}
              className={`${styles.chip} ${styles.chipSingle} ${
                other !== null ? styles.chipActive : ''
              }`}
              onClick={() => onChange(other !== null ? '' : OTHER_PREFIX)}
            >
              {other !== null ? '✓ ' : ''}其他
            </button>
          ) : null}
        </div>
      ) : null}

      {type === 'multi' ? (
        <div className={styles.chips} role="group" aria-label={label}>
          {(options ?? []).map((option) => {
            const active = selectedList.includes(option)
            const isExclusive = exclusive.includes(option)
            return (
              <button
                key={option}
                type="button"
                aria-pressed={active}
                disabled={disabled}
                className={`${styles.chip} ${styles.chipMulti} ${active ? styles.chipActive : ''} ${
                  isExclusive ? styles.chipExclusive : ''
                }`}
                onClick={() => onChange(toggleMultiOption(selectedList, option, exclusive))}
              >
                {active ? '✓ ' : ''}
                {option}
              </button>
            )
          })}
          {allowOther ? (
            <button
              type="button"
              aria-pressed={other !== null}
              disabled={disabled}
              className={`${styles.chip} ${styles.chipMulti} ${
                other !== null ? styles.chipActive : ''
              }`}
              onClick={() => onChange(other !== null ? withoutOther(value) : withOtherText(value, ''))}
            >
              {other !== null ? '✓ ' : ''}其他
            </button>
          ) : null}
        </div>
      ) : null}

      {allowOther && other !== null ? (
        <input
          className={styles.otherInput}
          type="text"
          value={other}
          placeholder="请补充「其他」具体情况"
          disabled={disabled}
          onChange={(event) => onChange(withOtherText(value, event.target.value))}
        />
      ) : null}

      {type === 'text' ? (
        <textarea
          className={styles.textarea}
          value={textValue}
          rows={maxLength && maxLength > 200 ? 4 : 2}
          maxLength={maxLength ?? undefined}
          placeholder={placeholder ?? '请输入'}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
        />
      ) : null}

      {type === 'number' && (
        <div className={styles.numberRow}>
          <input
            className={styles.input}
            type="number"
            inputMode="decimal"
            value={textValue}
            min={range?.[0]}
            max={range?.[1]}
            step={question.decimals ? 0.1 : 1}
            placeholder={range ? `${range[0]}-${range[1]}` : '请输入'}
            disabled={disabled}
            onChange={(event) => onChange(event.target.value)}
          />
          {unit ? <span className={styles.unit}>{unit}</span> : null}
        </div>
      )}

      {type === 'scale' ? (
        <div className={styles.scaleRow}>
          <input
            className={styles.scale}
            type="range"
            min={0}
            max={10}
            step={1}
            value={typeof value === 'number' ? value : 0}
            disabled={disabled}
            onChange={(event) => onChange(Number(event.target.value))}
          />
          <span className={styles.scaleValue}>{typeof value === 'number' ? value : 0}</span>
        </div>
      ) : null}

      {type === 'switch' ? (
        <label className={styles.switch}>
          <input
            type="checkbox"
            checked={value === true}
            disabled={disabled}
            onChange={(event) => onChange(event.target.checked)}
          />
          <span className={styles.switchTrack} aria-hidden="true" />
          <span className={styles.switchText}>{value === true ? '已开启' : '未开启'}</span>
        </label>
      ) : null}

      {maxLength && type === 'text' ? (
        <div className={styles.counter}>
          {textValue.length}/{maxLength}
        </div>
      ) : null}

      {error ? <div className={styles.fieldError}>{error}</div> : null}
    </div>
  )
}