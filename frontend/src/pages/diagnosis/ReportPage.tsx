import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { PageShell } from '@/components/PageShell'
import { ROUTES } from '@/router/routes'
import {
  diagnosisApi,
  reportApi,
  reportImageUrl,
  type FusionResultData,
  type HealthLevel,
  type ReportData,
  type ReportModuleDetail,
  type ReportStatus,
  type ReportTabKey,
  type Syndrome,
} from '@/services/api'
import { describeModel } from '@/utils/model'
import { ApiError } from '@/utils/request'
import { resolveSessionId, sessionDisplayNo, startNewSession, withSession } from '@/utils/session'

import styles from './ReportPage.module.css'

/**
 * P6 综合诊断报告页（PRD §6.5；UI/UX §5.5）。
 *
 * 渲染合参结论与三诊依据，8 个 Tab 覆盖概览/详情/指数/理疗/体质/治未病/建议/情绪；
 * Tab 状态写入 URL query（`?tab=`）以支持刷新定位；打印态串行展开全部 Tab（§5.5.6）。
 * 报告管理（PDF 导出 / 归档 / 分享）属 M6，此处保留入口占位。
 */

const TAB_KEYS: ReportTabKey[] = [
  'overview',
  'details',
  'indices',
  'therapy',
  'constitution',
  'prevention',
  'advice',
  'emotion',
]

const TAB_LABELS: Record<ReportTabKey, string> = {
  overview: '综合概览',
  details: '三诊详情',
  indices: '基础指数',
  therapy: '理疗参数',
  constitution: '体质辨证',
  prevention: '治未病',
  advice: '调理建议',
  emotion: '情绪分析',
}

const HEALTH_META: Record<HealthLevel, { label: string; className: string }> = {
  good: { label: '健康', className: styles.healthGood },
  fair: { label: '一般', className: styles.healthFair },
  poor: { label: '较差', className: styles.healthPoor },
  bad: { label: '极差', className: styles.healthBad },
}

const MODULE_LABELS: Record<string, string> = { tongue: '舌诊', face: '面诊', inquiry: '问诊' }
const FEATURE_LABELS: Record<string, string> = {
  tongue_color: '舌色',
  coating_color: '苔色',
  coating_texture: '苔质',
  tongue_shape: '舌形',
  face_color: '面色',
  luster: '光泽',
  acne: '痘痘',
  spots: '斑点',
}
const QID_LABELS: Record<string, string> = {
  gender: '性别',
  age: '年龄',
  height: '身高',
  weight: '体重',
  name: '姓名',
  chief_complaint: '主诉',
  cold_heat: '寒热',
  sweating: '汗出',
  sleep: '睡眠',
  appetite: '食欲',
  taste: '口味',
  thirst: '口渴',
  stool: '大便',
  urine: '小便',
  chest_abdomen: '胸腹',
  other_symptoms: '其他',
}

function confidenceLevel(value: number): 'high' | 'medium' | 'low' {
  if (value >= 0.8) return 'high'
  if (value >= 0.7) return 'medium'
  return 'low'
}

function formatAnswer(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (Array.isArray(value)) return value.length ? value.join('、') : '—'
  if (typeof value === 'boolean') return value ? '是' : '否'
  return String(value)
}

function SyndromeBadge({ syndrome }: { syndrome: Syndrome }) {
  const level = confidenceLevel(syndrome.confidence)
  return (
    <span className={`${styles.confBadge} ${styles[`conf_${level}`]}`}>
      {syndrome.name} {Math.round(syndrome.confidence * 100)}%
    </span>
  )
}

function ModuleImage({ detail }: { detail: ReportModuleDetail }) {
  const [failed, setFailed] = useState(false)
  if (failed) {
    return <div className={styles.imageFallback}>图像加载失败</div>
  }
  return (
    <img
      className={styles.image}
      src={reportImageUrl(detail.module, detail.record_id, detail.image_ref)}
      alt={`${MODULE_LABELS[detail.module] ?? detail.module}图像`}
      onError={() => setFailed(true)}
    />
  )
}

export function ReportPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const navigate = useNavigate()
  const sessionId = useMemo(() => resolveSessionId(searchParams.get('session_id')), [searchParams])
  const tabParam = searchParams.get('tab') as ReportTabKey | null
  const activeTab: ReportTabKey = tabParam && TAB_KEYS.includes(tabParam) ? tabParam : 'overview'

  const [result, setResult] = useState<FusionResultData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [reportStatus, setReportStatus] = useState<ReportStatus | null>(null)
  const [pdfLoading, setPdfLoading] = useState(false)
  const [archiveLoading, setArchiveLoading] = useState(false)
  const [actionError, setActionError] = useState('')
  const loadedRef = useRef<string | null>(null)

  useEffect(() => {
    if (loadedRef.current === sessionId) return
    loadedRef.current = sessionId
    void (async () => {
      try {
        const data = await diagnosisApi.getResult(sessionId)
        if (data.status === 'completed') {
          setResult(data)
          setReportStatus(data.report_status)
        } else {
          // 分析中 / 失败 → 回到 P5 分析中页查看进度或重试
          navigate(withSession(ROUTES.ANALYSIS, sessionId), { replace: true })
          return
        }
      } catch (err) {
        if (err instanceof ApiError && err.code === 40400) {
          navigate(withSession(ROUTES.ANALYSIS, sessionId), { replace: true })
          return
        }
        setError(err instanceof Error ? err.message : '报告加载失败，请稍后重试')
      } finally {
        setLoading(false)
      }
    })()
  }, [navigate, sessionId])

  const reportId = result?.report_id ?? null
  const archived = reportStatus === 'archived'

  const exportPdf = useCallback(async () => {
    if (!reportId || pdfLoading) return
    setActionError('')
    setPdfLoading(true)
    try {
      await reportApi.downloadPdf(reportId)
    } catch (err) {
      setActionError(err instanceof Error ? err.message : '报告导出失败，请稍后重试')
    } finally {
      setPdfLoading(false)
    }
  }, [pdfLoading, reportId])

  const archive = useCallback(async () => {
    if (!reportId || archived || archiveLoading) return
    if (!window.confirm('归档后报告将进入只读状态，是否继续？')) return
    setActionError('')
    setArchiveLoading(true)
    try {
      const res = await reportApi.archive(reportId)
      setReportStatus(res.status)
    } catch (err) {
      setActionError(err instanceof Error ? err.message : '归档失败，请稍后重试')
    } finally {
      setArchiveLoading(false)
    }
  }, [archiveLoading, archived, reportId])

  // 与上一次报告对比：本报告作为「本次/对比」侧（target）进入 P8 数据对比页，
  // 对比页会自动补齐同患者上一次报告作为「基准/上次」侧（UI/UX §5.7 入口②）
  const compareWithHistory = useCallback(() => {
    if (!reportId) return
    navigate(`${ROUTES.COMPARE}?target=${reportId}`)
  }, [navigate, reportId])

  const selectTab = useCallback(
    (key: ReportTabKey) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev)
        next.set('tab', key)
        return next
      })
    },
    [setSearchParams],
  )

  const onTabKeyDown = useCallback(
    (event: KeyboardEvent) => {
      const index = TAB_KEYS.indexOf(activeTab)
      if (event.key === 'ArrowRight') selectTab(TAB_KEYS[(index + 1) % TAB_KEYS.length])
      else if (event.key === 'ArrowLeft')
        selectTab(TAB_KEYS[(index - 1 + TAB_KEYS.length) % TAB_KEYS.length])
      else if (event.key === 'Home') selectTab(TAB_KEYS[0])
      else if (event.key === 'End') selectTab(TAB_KEYS[TAB_KEYS.length - 1])
    },
    [activeTab, selectTab],
  )

  const report: ReportData | null = result?.report ?? null
  const modelLabel = describeModel(report?.header.model_version)
  const lowConfidence =
    report !== null &&
    ((report.header.overall_confidence ?? 1) < 0.7 ||
      (result?.missing_modules.length ?? 0) > 0 ||
      (result?.conflicts.length ?? 0) > 0)

  // 开始下一位患者：生成全新会话标识并跳转舌诊采集页（本报告保留在「我的报告」）
  const startNextPatient = useCallback(() => {
    if (!window.confirm('开始下一位患者？将清空当前会话标识，本报告仍可在「我的报告」中查看。')) {
      return
    }
    navigate(withSession(ROUTES.TONGUE, startNewSession()))
  }, [navigate])

  return (
    <PageShell
      title="综合诊断报告"
      description={`会话编号 ${sessionDisplayNo(sessionId, report?.header.patient_snapshot)}`}
    >
      {loading ? (
        <div className={styles.loading}>报告生成中…</div>
      ) : error || !report ? (
        <div className={styles.error}>
          <div>{error || '报告暂不可用'}</div>
          <button
            type="button"
            className="btn btn--ghost"
            onClick={() => navigate(withSession(ROUTES.ANALYSIS, sessionId))}
          >
            返回分析页
          </button>
        </div>
      ) : (
        <div className={styles.report} id="report-root">
          {/* 报告头与操作区 */}
          <header className={styles.header}>
            <div className={styles.headerMain}>
              <h2 className={styles.reportTitle}>
                三诊合参综合报告
                {report.header.health_level ? (
                  <span className={`${styles.healthBadge} ${HEALTH_META[report.header.health_level].className}`}>
                    {HEALTH_META[report.header.health_level].label}
                  </span>
                ) : null}
                {archived ? <span className={styles.archivedBadge}>已归档</span> : null}
              </h2>
              <p className={styles.reportMeta}>
                {report.header.patient_snapshot?.anonymous
                  ? '匿名患者'
                  : report.header.patient_snapshot?.name || '未登记姓名'}
                {report.header.patient_snapshot?.gender ? ` · ${report.header.patient_snapshot.gender}` : ''}
                {report.header.patient_snapshot?.age ? ` · ${report.header.patient_snapshot.age} 岁` : ''}
                {report.header.generated_at
                  ? ` · 生成于 ${new Date(report.header.generated_at).toLocaleString('zh-CN')}`
                  : ''}
              </p>
            </div>
            <div className={styles.headerActions}>
              <button
                type="button"
                className="btn btn--ghost"
                disabled={!reportId}
                onClick={compareWithHistory}
              >
                与上一次报告对比
              </button>
              <button type="button" className="btn btn--ghost" onClick={() => window.print()}>
                打印 A4
              </button>
              <button
                type="button"
                className="btn btn--ghost"
                disabled={!reportId || pdfLoading}
                onClick={() => void exportPdf()}
              >
                {pdfLoading ? '导出中…' : '导出 PDF'}
              </button>
              <button
                type="button"
                className="btn btn--ghost"
                disabled={!reportId || archived || archiveLoading}
                onClick={() => void archive()}
              >
                {archived ? '已归档' : archiveLoading ? '归档中…' : '归档'}
              </button>
              <button type="button" className="btn btn--primary" onClick={startNextPatient}>
                开始下一位
              </button>
            </div>
          </header>

          {actionError ? <div className={styles.actionError}>{actionError}</div> : null}

          {lowConfidence ? (
            <div className={styles.warning} role="status">
              ⚠ 参考强度有限：存在缺诊 / 跨诊矛盾或低可信项，请结合临床综合判断。
            </div>
          ) : null}

          {/* Tab 导航 */}
          <nav className={styles.tabs} aria-label="报告分区" onKeyDown={onTabKeyDown}>
            {TAB_KEYS.map((key) => (
              <button
                key={key}
                type="button"
                className={`${styles.tab} ${activeTab === key ? styles.tabActive : ''}`}
                aria-current={activeTab === key}
                onClick={() => selectTab(key)}
              >
                {TAB_LABELS[key]}
              </button>
            ))}
          </nav>

          {/* Tab 内容（打印态全部展开） */}
          <div className={styles.panels}>
            <section className={`${styles.panel} ${activeTab === 'overview' ? '' : styles.hidden}`}>
              <h3 className={styles.panelTitle}>综合概览</h3>
              <div className={styles.conclusions}>
                {report.overview.conclusions.length ? (
                  report.overview.conclusions.map((item, index) => (
                    <div className={styles.conclusionCard} key={`${index}-${item.text}`}>
                      <span
                        className={`${styles.confBadge} ${styles[`conf_${confidenceLevel(item.confidence)}`]}`}
                      >
                        {Math.round(item.confidence * 100)}%
                      </span>
                      <p className={styles.conclusionText}>{item.text}</p>
                    </div>
                  ))
                ) : (
                  <p className={styles.muted}>暂无综合结论</p>
                )}
              </div>

              {report.overview.syndrome_points.length ? (
                <>
                  <h4 className={styles.subTitle}>辨证要点</h4>
                  <ul className={styles.points}>
                    {report.overview.syndrome_points.map((point) => (
                      <li key={point}>{point}</li>
                    ))}
                  </ul>
                </>
              ) : null}

              {result?.conflicts.length ? (
                <>
                  <h4 className={styles.subTitle}>跨诊矛盾项</h4>
                  <ul className={styles.conflicts}>
                    {result.conflicts.map((conflict) => (
                      <li key={conflict.description}>
                        <span className={styles.conflictModules}>
                          {conflict.modules.map((m) => MODULE_LABELS[m] ?? m).join(' × ')}
                        </span>
                        {conflict.description}
                      </li>
                    ))}
                  </ul>
                </>
              ) : null}
            </section>

            <section className={`${styles.panel} ${activeTab === 'details' ? '' : styles.hidden}`}>
              <h3 className={styles.panelTitle}>三诊详情</h3>
              <div className={styles.detailGrid}>
                {[report.details.tongue, report.details.face].map((detail) =>
                  detail ? (
                    <article className={styles.detailCard} key={detail.module}>
                      <h4 className={styles.subTitle}>{MODULE_LABELS[detail.module]}依据</h4>
                      <ModuleImage detail={detail} />
                      <table className={styles.table}>
                        <thead>
                          <tr>
                            <th>特征项</th>
                            <th>判读结果</th>
                            <th>置信度</th>
                          </tr>
                        </thead>
                        <tbody>
                          {detail.features.map((feature) => {
                            const level = confidenceLevel(feature.confidence)
                            return (
                              <tr key={feature.name} className={level === 'low' ? styles.lowRow : ''}>
                                <td>{FEATURE_LABELS[feature.name] ?? feature.name}</td>
                                <td>
                                  {feature.label}
                                  {feature.area?.length ? `（${feature.area.join('、')}）` : ''}
                                </td>
                                <td>{Math.round(feature.confidence * 100)}%</td>
                              </tr>
                            )
                          })}
                        </tbody>
                      </table>
                      {detail.summary ? <p className={styles.summary}>{detail.summary}</p> : null}
                    </article>
                  ) : null,
                )}

                {report.details.inquiry ? (
                  <article className={styles.detailCard}>
                    <h4 className={styles.subTitle}>问诊依据</h4>
                    <table className={styles.table}>
                      <tbody>
                        {Object.entries(report.details.inquiry.answers)
                          .filter(([qid]) => ['other_symptoms', 'anonymous'].includes(qid) === false)
                          .map(([qid, value]) => (
                            <tr key={qid}>
                              <td className={styles.qidCell}>{QID_LABELS[qid] ?? qid}</td>
                              <td>{formatAnswer(value)}</td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                    {report.details.inquiry.summary ? (
                      <p className={styles.summary}>{report.details.inquiry.summary}</p>
                    ) : null}
                  </article>
                ) : null}
              </div>
            </section>

            <section className={`${styles.panel} ${activeTab === 'indices' ? '' : styles.hidden}`}>
              <h3 className={styles.panelTitle}>基础指数</h3>
              {report.indices.items.length ? (
                <div className={styles.indexGrid}>
                  {report.indices.items.map((item) => (
                    <div className={styles.indexCard} key={item.name}>
                      <div className={styles.indexName}>{item.name}</div>
                      <div className={styles.indexValue}>{item.value}</div>
                      {item.reference ? (
                        <div className={styles.indexRef}>{item.reference}</div>
                      ) : null}
                    </div>
                  ))}
                </div>
              ) : (
                <p className={styles.empty}>暂无可展示内容</p>
              )}
            </section>

            <section className={`${styles.panel} ${activeTab === 'therapy' ? '' : styles.hidden}`}>
              <h3 className={styles.panelTitle}>理疗参数</h3>
              {report.therapy.items.length ? (
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>参数</th>
                      <th>取值</th>
                      <th>说明</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.therapy.items.map((item) => (
                      <tr key={item.name}>
                        <td>{item.name}</td>
                        <td>{item.value}</td>
                        <td>{item.note ?? '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className={styles.empty}>暂无可展示内容</p>
              )}
            </section>

            <section className={`${styles.panel} ${activeTab === 'constitution' ? '' : styles.hidden}`}>
              <h3 className={styles.panelTitle}>体质辨证</h3>
              {report.constitution.main_syndrome ? (
                <>
                  <div className={styles.mainSyndrome}>
                    <span className={styles.mainSyndromeName}>
                      {report.constitution.main_syndrome.name}
                    </span>
                    <span
                      className={`${styles.confBadge} ${styles[`conf_${confidenceLevel(report.constitution.main_syndrome.confidence)}`]}`}
                    >
                      {Math.round(report.constitution.main_syndrome.confidence * 100)}%
                    </span>
                  </div>
                  {report.constitution.secondary_syndromes.length ? (
                    <div className={styles.tagRow}>
                      {report.constitution.secondary_syndromes.map((item) => (
                        <SyndromeBadge key={item.name} syndrome={item} />
                      ))}
                    </div>
                  ) : null}
                  {report.constitution.description ? (
                    <p className={styles.summary}>{report.constitution.description}</p>
                  ) : null}
                </>
              ) : (
                <p className={styles.empty}>暂无可展示内容</p>
              )}
            </section>

            <section className={`${styles.panel} ${activeTab === 'prevention' ? '' : styles.hidden}`}>
              <h3 className={styles.panelTitle}>治未病</h3>
              {report.prevention.groups.length ? (
                <div className={styles.preventionGrid}>
                  {report.prevention.groups.map((group) => (
                    <div className={styles.preventionCard} key={group.title}>
                      <h4 className={styles.subTitle}>{group.title}</h4>
                      <ul className={styles.points}>
                        {group.items.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
              ) : (
                <p className={styles.empty}>暂无可展示内容</p>
              )}
            </section>

            <section className={`${styles.panel} ${activeTab === 'advice' ? '' : styles.hidden}`}>
              <h3 className={styles.panelTitle}>调理建议</h3>
              {report.advice.suggestions.length ? (
                <div className={styles.adviceList}>
                  {report.advice.suggestions.map((item, index) => (
                    <div className={styles.adviceCard} key={`${item.category}-${index}`}>
                      <span className={styles.adviceCategory}>{item.category}</span>
                      <span className={styles.adviceText}>{item.text}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className={styles.empty}>暂无可展示内容</p>
              )}
            </section>

            <section className={`${styles.panel} ${activeTab === 'emotion' ? '' : styles.hidden}`}>
              <h3 className={styles.panelTitle}>情绪分析</h3>
              {report.emotion.dimensions.length ? (
                <div className={styles.emotionList}>
                  {report.emotion.dimensions.map((dim) => (
                    <div className={styles.emotionRow} key={dim.name}>
                      <span className={styles.emotionName}>{dim.name}</span>
                      <div className={styles.emotionTrack}>
                        <div
                          className={styles.emotionFill}
                          style={{ width: `${Math.round(dim.score * 100)}%` }}
                        />
                      </div>
                      <span className={styles.emotionNote}>{dim.note ?? '—'}</span>
                    </div>
                  ))}
                  {report.emotion.summary ? (
                    <p className={styles.summary}>{report.emotion.summary}</p>
                  ) : null}
                </div>
              ) : (
                <p className={styles.empty}>暂无可展示内容</p>
              )}
            </section>
          </div>

          <footer className={styles.footer}>
            本报告由系统生成，仅供临床辅助参考，不构成最终医疗诊断，须由医师确认签署。
            {report.header.rule_version ? ` 规则版本 ${report.header.rule_version}。` : ''}
            {modelLabel ? ` 分析模型 ${modelLabel.text}。` : ''}
          </footer>
        </div>
      )}
    </PageShell>
  )
}