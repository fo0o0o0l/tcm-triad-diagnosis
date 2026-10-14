import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { PageShell } from '@/components/PageShell'
import { ROUTES } from '@/router/routes'
import {
  compareApi,
  reportApi,
  type ChangeDirection,
  type CompareFeatureDiffItem,
  type CompareResult,
  type CompareTrendPoint,
  type HealthLevel,
  type ReportHistoryItem,
} from '@/services/api'

import styles from './ComparePage.module.css'

/**
 * P8 数据对比页（PRD §6.5.4；UI/UX §5.7）。
 *
 * 选择两份**同一患者**的历史报告（基准 / 对比），对比三诊特征、健康状态、置信度趋势与
 * 综合结论的变化。数据由后端 R-CMP（`GET /reports/compare`）一次返回；
 * 入口：① 历史记录页勾选 2 条 →「对比」；② 报告页操作区「与上一次报告对比」。
 */

const HEALTH_META: Record<HealthLevel, { label: string; className: string }> = {
  good: { label: '健康', className: styles.healthGood },
  fair: { label: '一般', className: styles.healthFair },
  poor: { label: '较差', className: styles.healthPoor },
  bad: { label: '极差', className: styles.healthBad },
}

/** 变化方向 → 文案与着色 class（特征/健康通用）。 */
const DIRECTION_META: Record<ChangeDirection, { text: string; className: string }> = {
  improved: { text: '↑ 改善', className: styles.dirImproved },
  worsened: { text: '↓ 加重', className: styles.dirWorsened },
  same: { text: '→ 持平', className: styles.dirSame },
  unknown: { text: '有变化', className: styles.dirUnknown },
}

/** 对比维度开关。 */
interface Dims {
  tongue: boolean
  face: boolean
  inquiry: boolean
  confidence: boolean
  conclusion: boolean
}

const DEFAULT_DIMS: Dims = {
  tongue: true,
  face: true,
  inquiry: true,
  confidence: true,
  conclusion: true,
}

const DIM_ITEMS: { key: keyof Dims; label: string }[] = [
  { key: 'tongue', label: '舌象特征' },
  { key: 'face', label: '面象特征' },
  { key: 'inquiry', label: '问诊症状' },
  { key: 'confidence', label: '置信度' },
  { key: 'conclusion', label: '综合结论' },
]

function formatDate(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

function formatDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`
}

/** 报告归属患者键（匿名按会话号；跨患者禁止对比）。 */
function patientKey(item: ReportHistoryItem): string {
  return item.patient_name ?? item.session_id
}

function optionLabel(item: ReportHistoryItem): string {
  const patient = item.anonymous ? '匿名患者' : item.patient_name || '未登记姓名'
  return `${formatDate(item.generated_at)} ${item.summary || '暂无结论'} · ${patient}`
}

/** 特征值单元格：空值显示 `—`，变化项高亮。 */
function FeatureValue({ value, changed }: { value: string | null; changed: boolean }) {
  return <span className={changed ? styles.valueChanged : undefined}>{value ?? '—'}</span>
}

function FeatureRow({ item }: { item: CompareFeatureDiffItem }) {
  const direction = DIRECTION_META[item.direction]
  return (
    <tr className={item.changed ? styles.changedRow : undefined}>
      <td className={styles.featureCell}>{item.label}</td>
      <td>
        <FeatureValue value={item.base_value} changed={item.changed} />
      </td>
      <td>
        <FeatureValue value={item.target_value} changed={item.changed} />
      </td>
      <td>
        <span className={`${styles.direction} ${direction.className}`}>{direction.text}</span>
      </td>
    </tr>
  )
}

/** 置信度趋势：≥3 点画折线，否则退化为双柱对比（UI/UX §5.7.2）。 */
function ConfidenceTrend({ points }: { points: CompareTrendPoint[] }) {
  const values = points.map((p) => p.overall_confidence)

  if (points.length < 3) {
    return (
      <div className={styles.trendBars}>
        {points.map((point) => (
          <div className={styles.trendBarItem} key={point.report_id}>
            <div className={styles.trendBarValue}>
              {point.overall_confidence !== null
                ? `${Math.round(point.overall_confidence * 100)}%`
                : '—'}
            </div>
            <div className={styles.trendBarTrack}>
              <div
                className={`${styles.trendBarFill} ${
                  point.role === 'target' ? styles.trendBarTarget : ''
                }`}
                style={{ height: `${Math.round((point.overall_confidence ?? 0) * 100)}%` }}
              />
            </div>
            <div className={styles.trendBarLabel}>{formatDate(point.generated_at)}</div>
          </div>
        ))}
      </div>
    )
  }

  const width = 340
  const height = 130
  const padX = 24
  const padY = 16
  const step = points.length > 1 ? (width - padX * 2) / (points.length - 1) : 0
  const coords = points.map((point, index) => {
    const value = point.overall_confidence ?? 0
    return {
      x: padX + step * index,
      y: padY + (1 - value) * (height - padY * 2),
      value,
      low: value < 0.7,
      role: point.role,
    }
  })
  const line = coords.map((c) => `${c.x},${c.y}`).join(' ')

  return (
    <div className={styles.trendChart}>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="置信度趋势折线图">
        <line x1={padX} y1={height - padY} x2={width - padX} y2={height - padY} className={styles.axis} />
        <line x1={padX} y1={padY} x2={padX} y2={height - padY} className={styles.axis} />
        <polyline points={line} className={styles.trendLine} />
        {coords.map((c, index) => (
          <circle
            key={index}
            cx={c.x}
            cy={c.y}
            r={c.role === 'history' ? 3.5 : 5}
            className={c.low ? styles.trendDotLow : styles.trendDot}
          />
        ))}
      </svg>
      <div className={styles.trendLegend}>
        {points.map((point, index) => (
          <span className={styles.trendLegendItem} key={point.report_id}>
            {formatDate(point.generated_at)}
            <b>{values[index] !== null ? `${Math.round((values[index] ?? 0) * 100)}%` : '—'}</b>
            {point.role === 'base' ? '（基准）' : point.role === 'target' ? '（对比）' : ''}
          </span>
        ))}
      </div>
    </div>
  )
}

export function ComparePage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const baseId = searchParams.get('base') ?? ''
  const targetId = searchParams.get('target') ?? ''
  const range = searchParams.get('range') === '2' ? 2 : 5

  const [options, setOptions] = useState<ReportHistoryItem[]>([])
  const [optionsLoading, setOptionsLoading] = useState(true)
  const [result, setResult] = useState<CompareResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [dims, setDims] = useState<Dims>(DEFAULT_DIMS)

  // 报告选择器候选集：一次性拉取（P8 复用历史检索接口）
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const data = await reportApi.list({ page: 1, page_size: 100 })
        if (!cancelled) setOptions(data.items)
      } catch {
        if (!cancelled) setOptions([])
      } finally {
        if (!cancelled) setOptionsLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const ready = Boolean(baseId && targetId && baseId !== targetId)

  useEffect(() => {
    if (!ready) {
      setResult(null)
      return
    }
    let cancelled = false
    setLoading(true)
    setError('')
    void (async () => {
      try {
        const data = await compareApi.get(baseId, targetId, range)
        if (!cancelled) setResult(data)
      } catch (err) {
        if (!cancelled) {
          setResult(null)
          setError(err instanceof Error ? err.message : '对比数据加载失败，请稍后重试')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [ready, baseId, targetId, range])

  /** 候选下拉：限定为已选一侧的同一患者（禁止跨患者对比）。 */
  const { baseOptions, targetOptions } = useMemo(() => {
    const byId = (id: string) => options.find((item) => item.report_id === id)
    const target = byId(targetId)
    const base = byId(baseId)
    const baseList = target
      ? options.filter((item) => patientKey(item) === patientKey(target))
      : options
    const targetList = base
      ? options.filter((item) => patientKey(item) === patientKey(base))
      : options
    return { baseOptions: baseList, targetOptions: targetList }
  }, [baseId, options, targetId])

  const setParam = useCallback(
    (key: string, value: string) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev)
        if (value) next.set(key, value)
        else next.delete(key)
        return next
      })
    },
    [setSearchParams],
  )

  // 入口只带一侧（报告页「与历史对比」只传 target=当前报告）时，自动补齐同患者相邻的一份：
  // 有 target 则补上一次（更早）为基准，有 base 则补下一次（更晚）为对比。
  // 同一孤立选择只自动配对一次，避免用户手动清空后被反复回填。
  const autoPairedRef = useRef<string | null>(null)
  useEffect(() => {
    if (optionsLoading || options.length === 0) return
    const hasBase = Boolean(baseId)
    const hasTarget = Boolean(targetId)
    if (hasBase === hasTarget) return

    const selectedId = hasBase ? baseId : targetId
    if (autoPairedRef.current === selectedId) return
    const selected = options.find((item) => item.report_id === selectedId)
    if (!selected) return

    const others = options
      .filter((item) => item.report_id !== selectedId && patientKey(item) === patientKey(selected))
      .sort((a, b) => new Date(a.generated_at).getTime() - new Date(b.generated_at).getTime())
    if (!others.length) return

    const selectedTime = new Date(selected.generated_at).getTime()
    const pick = hasBase
      ? others.find((item) => new Date(item.generated_at).getTime() > selectedTime) ?? others[others.length - 1]
      : [...others].reverse().find((item) => new Date(item.generated_at).getTime() < selectedTime) ?? others[0]

    autoPairedRef.current = selectedId
    setParam(hasBase ? 'target' : 'base', pick.report_id)
  }, [baseId, options, optionsLoading, setParam, targetId])

  const swap = useCallback(() => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      const b = next.get('base') ?? ''
      const t = next.get('target') ?? ''
      if (t) next.set('base', t)
      else next.delete('base')
      if (b) next.set('target', b)
      else next.delete('target')
      return next
    })
  }, [setSearchParams])

  const toggleDim = useCallback((key: keyof Dims) => {
    setDims((prev) => ({ ...prev, [key]: !prev[key] }))
  }, [])

  // 数据不足（< 2 条可对比记录）：空状态 + 去诊断（§5.7.3）
  const insufficient = !optionsLoading && options.length < 2

  const trendPoints = useMemo<CompareTrendPoint[]>(() => {
    if (!result) return []
    if (result.trend.length >= 2) return result.trend
    return [
      {
        report_id: result.base.report_id,
        generated_at: result.base.generated_at,
        overall_confidence: result.base.overall_confidence,
        health_level: result.base.health_level,
        role: 'base',
      },
      {
        report_id: result.target.report_id,
        generated_at: result.target.generated_at,
        overall_confidence: result.target.overall_confidence,
        health_level: result.target.health_level,
        role: 'target',
      },
    ]
  }, [result])

  const visibleModules = useMemo(
    () => (result ? result.modules.filter((m) => dims[m.module]) : []),
    [dims, result],
  )

  const healthDirection = result ? DIRECTION_META[result.health.direction] : null

  return (
    <PageShell title="数据对比" description="对比同一患者两次诊断的三诊特征与结论变化">
      <div className={styles.layout}>
        <div className={styles.main}>
          {/* 报告选择器（§5.7.1） */}
          <section className={`${styles.card} ${styles.printHide}`}>
            <div className={styles.selectorRow}>
              <label className={styles.selectorField}>
                <span className={styles.selectorLabel}>基准（上次）</span>
                <select
                  className={styles.select}
                  value={baseId}
                  onChange={(event) => setParam('base', event.target.value)}
                >
                  <option value="">请选择报告</option>
                  {baseOptions.map((item) => (
                    <option key={item.report_id} value={item.report_id}>
                      {optionLabel(item)}
                    </option>
                  ))}
                </select>
              </label>

              <button
                type="button"
                className={`btn btn--ghost ${styles.swapBtn}`}
                onClick={swap}
                title="互换基准与对比"
                aria-label="互换基准与对比"
              >
                ⇅
              </button>

              <label className={styles.selectorField}>
                <span className={styles.selectorLabel}>对比（本次）</span>
                <select
                  className={styles.select}
                  value={targetId}
                  onChange={(event) => setParam('target', event.target.value)}
                >
                  <option value="">请选择报告</option>
                  {targetOptions.map((item) => (
                    <option key={item.report_id} value={item.report_id}>
                      {optionLabel(item)}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {(baseId || targetId) && !ready && !insufficient ? (
              <div className={styles.hint}>请分别选择同一患者的两份报告（基准与对比）</div>
            ) : null}
          </section>

          {/* 内容区 */}
          {optionsLoading ? (
            <div className={styles.card}>
              <div className={styles.skeleton} />
            </div>
          ) : insufficient ? (
            <div className={`${styles.card} ${styles.empty}`}>
              <div>暂无可对比的历史记录，完成第二次诊断后即可对比</div>
              <button
                type="button"
                className="btn btn--primary"
                style={{ marginTop: 'var(--space-2)' }}
                onClick={() => navigate(ROUTES.TONGUE)}
              >
                去诊断
              </button>
            </div>
          ) : !ready ? (
            <div className={`${styles.card} ${styles.empty}`}>
              <div>请选择两份同一患者的报告开始对比</div>
            </div>
          ) : loading ? (
            <div className={styles.card}>
              <div className={styles.skeleton} />
            </div>
          ) : error ? (
            <div className={`${styles.card} ${styles.error}`}>
              <div>{error}</div>
            </div>
          ) : result ? (
            <>
              {/* 健康状态变化 */}
              <section className={`${styles.card} ${styles.patientBar}`}>
                <span className={styles.patientName}>
                  {result.base.anonymous
                    ? '匿名患者'
                    : result.base.patient_name || '未登记姓名'}
                </span>
                <span className={styles.patientMeta}>
                  {formatDateTime(result.base.generated_at)} → {formatDateTime(result.target.generated_at)}
                </span>
              </section>

              <section className={styles.card}>
                <h3 className={styles.sectionTitle}>健康状态变化</h3>
                <div className={styles.healthRow}>
                  {result.health.base_level ? (
                    <span className={`${styles.healthBadge} ${HEALTH_META[result.health.base_level].className}`}>
                      {HEALTH_META[result.health.base_level].label}
                    </span>
                  ) : (
                    <span className={styles.healthBadge}>—</span>
                  )}
                  <span className={styles.arrow}>→</span>
                  {result.health.target_level ? (
                    <span className={`${styles.healthBadge} ${HEALTH_META[result.health.target_level].className}`}>
                      {HEALTH_META[result.health.target_level].label}
                    </span>
                  ) : (
                    <span className={styles.healthBadge}>—</span>
                  )}
                  {healthDirection ? (
                    <span className={`${styles.direction} ${healthDirection.className}`}>
                      {healthDirection.text}
                    </span>
                  ) : null}
                </div>
              </section>

              {/* 特征对比表（按维度勾选） */}
              {dims.tongue || dims.face || dims.inquiry ? (
                visibleModules.length && visibleModules.some((m) => m.items.length) ? (
                  visibleModules.map((module) => (
                    <section className={styles.card} key={module.module}>
                      <h3 className={styles.sectionTitle}>{module.label}对比</h3>
                      {module.items.length ? (
                        <table className={styles.table}>
                          <thead>
                            <tr>
                              <th className={styles.featureCell}>特征</th>
                              <th>上次</th>
                              <th>本次</th>
                              <th>变化</th>
                            </tr>
                          </thead>
                          <tbody>
                            {module.items.map((item) => (
                              <FeatureRow key={item.name} item={item} />
                            ))}
                          </tbody>
                        </table>
                      ) : (
                        <p className={styles.muted}>暂无可比项</p>
                      )}
                    </section>
                  ))
                ) : (
                  <section className={styles.card}>
                    <p className={styles.muted}>所选维度暂无可比项</p>
                  </section>
                )
              ) : null}

              {/* 置信度趋势 */}
              {dims.confidence ? (
                <section className={styles.card}>
                  <h3 className={styles.sectionTitle}>
                    置信度趋势{trendPoints.length >= 3 ? `（近 ${trendPoints.length} 次）` : ''}
                  </h3>
                  <ConfidenceTrend points={trendPoints} />
                </section>
              ) : null}

              {/* 综合结论对比 */}
              {dims.conclusion ? (
                <section className={styles.card}>
                  <h3 className={styles.sectionTitle}>综合结论对比</h3>
                  <div className={styles.conclusionGrid}>
                    <div className={styles.conclusionCol}>
                      <h4 className={styles.conclusionHead}>上次</h4>
                      {result.conclusions.base_texts.length ? (
                        result.conclusions.base_texts.map((text) => (
                          <p className={styles.conclusionText} key={text}>
                            {text}
                            {result.conclusions.removed.includes(text) ? (
                              <span className={styles.diffTagRemoved}>已变化</span>
                            ) : null}
                          </p>
                        ))
                      ) : (
                        <p className={styles.muted}>暂无结论</p>
                      )}
                    </div>
                    <div className={styles.conclusionCol}>
                      <h4 className={styles.conclusionHead}>本次</h4>
                      {result.conclusions.target_texts.length ? (
                        result.conclusions.target_texts.map((text) => (
                          <p className={styles.conclusionText} key={text}>
                            {text}
                            {result.conclusions.added.includes(text) ? (
                              <span className={styles.diffTagAdded}>新增</span>
                            ) : null}
                          </p>
                        ))
                      ) : (
                        <p className={styles.muted}>暂无结论</p>
                      )}
                    </div>
                  </div>
                </section>
              ) : null}
            </>
          ) : null}
        </div>

        {/* 右侧对比设置（§5.7.1） */}
        <aside className={`${styles.aside} ${styles.printHide}`}>
          <div className={styles.settingCard}>
            <h3 className={styles.asideTitle}>对比维度</h3>
            <div className={styles.settingList}>
              {DIM_ITEMS.map((item) => (
                <label className={styles.settingItem} key={item.key}>
                  <input
                    type="checkbox"
                    checked={dims[item.key]}
                    onChange={() => toggleDim(item.key)}
                  />
                  {item.label}
                </label>
              ))}
            </div>
          </div>

          <div className={styles.settingCard}>
            <h3 className={styles.asideTitle}>趋势范围</h3>
            <div className={styles.settingList}>
              <label className={styles.settingItem}>
                <input
                  type="radio"
                  name="trend-range"
                  checked={range === 2}
                  onChange={() => setParam('range', '2')}
                />
                仅两次
              </label>
              <label className={styles.settingItem}>
                <input
                  type="radio"
                  name="trend-range"
                  checked={range === 5}
                  onChange={() => setParam('range', '5')}
                />
                近 5 次
              </label>
            </div>
          </div>
        </aside>
      </div>
    </PageShell>
  )
}
