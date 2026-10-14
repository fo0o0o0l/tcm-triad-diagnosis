import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import { PageShell } from '@/components/PageShell'
import { ROUTES } from '@/router/routes'
import { diagnosisApi, type FusionReadiness, type ModuleKey } from '@/services/api'
import { ApiError } from '@/utils/request'
import { resolveSessionId, withSession } from '@/utils/session'

import styles from './AnalysisLoading.module.css'

/**
 * P5 AI 分析中页面（PRD §6.4；UI/UX §5.4）。
 *
 * 进入本页只做前置校验，**不自动触发**合参（UI/UX §5.4.3）：
 * - 三诊未全部完成 → 阻断态，逐项列出缺哪一诊并给出直达入口；
 * - 三诊齐全 → 确认态，用户点「开始分析」后才调用 G1，再轮询 G2 展示进度；
 * - 已有 `completed` 结果或后台仍在 `analyzing` → 直接续接，无需重复确认。
 */

type Stage = 'checking' | 'confirm' | 'blocked' | 'running' | 'failed'

const STAGES = ['舌诊解构', '面诊解构', '一致性校验', '结论生成']
const MODULE_ORDER: ModuleKey[] = ['tongue', 'face', 'inquiry']
const MODULE_LABELS: Record<ModuleKey, string> = {
  tongue: '舌诊采集',
  face: '面诊采集',
  inquiry: '问诊录入',
}
const MODULE_ROUTES: Record<ModuleKey, string> = {
  tongue: ROUTES.TONGUE,
  face: ROUTES.FACE,
  inquiry: ROUTES.INQUIRY,
}
const POLL_INTERVAL_MS = 1000
const MAX_ATTEMPTS = 40

const sleep = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms))

export function AnalysisLoadingPage() {
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const sessionId = useMemo(() => resolveSessionId(searchParams.get('session_id')), [searchParams])

  const [stage, setStage] = useState<Stage>('checking')
  const [readiness, setReadiness] = useState<FusionReadiness | null>(null)
  const [progress, setProgress] = useState(4)
  const [stageIndex, setStageIndex] = useState(0)
  const [error, setError] = useState('')
  /** 上次分析未成功：确认态给出"重新分析"提示 */
  const [lastFailed, setLastFailed] = useState(false)
  const startedRef = useRef<string | null>(null)

  const goReport = useCallback(() => {
    navigate(withSession(ROUTES.REPORT, sessionId), { replace: true })
  }, [navigate, sessionId])

  const goModule = useCallback(
    (key: ModuleKey) => {
      navigate(withSession(MODULE_ROUTES[key], sessionId))
    },
    [navigate, sessionId],
  )

  // 轮询 G2 直至完成 / 失败；期间递增进度与阶段指示（进度为估算，仅用于感知）
  const poll = useCallback(async (): Promise<'completed' | 'failed'> => {
    let delay = POLL_INTERVAL_MS
    for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt += 1) {
      await sleep(delay)
      setProgress((prev) => (prev < 92 ? Math.min(92, prev + 5) : 92))
      setStageIndex(Math.min(STAGES.length - 1, Math.floor(attempt / 3)))
      const result = await diagnosisApi.getResult(sessionId)
      if (result.status === 'completed') return 'completed'
      if (result.status === 'failed') return 'failed'
      delay = Math.min(3000, delay + 300)
    }
    throw new Error('合参分析超时，请稍后重试')
  }, [sessionId])

  /** 完成/失败收尾：完成自动跳报告，失败切换到失败态 */
  const settle = useCallback(
    (outcome: 'completed' | 'failed') => {
      if (outcome === 'completed') {
        setProgress(100)
        goReport()
        return
      }
      setError('合参分析暂不可用，可重试')
      setStage('failed')
    },
    [goReport],
  )

  /** 用户点「开始分析」/「重试分析」时才真正触发 G1（UI/UX §5.4.3） */
  const startAnalysis = useCallback(async () => {
    setStage('running')
    setError('')
    setProgress(4)
    setStageIndex(0)
    try {
      await diagnosisApi.analyze(sessionId)
    } catch (err) {
      // 40901：后台已有进行中的任务，直接续接轮询即可
      if (!(err instanceof ApiError && err.code === 40901)) {
        setError(err instanceof Error ? err.message : '合参分析失败，请重试')
        setStage('failed')
        return
      }
    }
    try {
      settle(await poll())
    } catch (pollErr) {
      setError(pollErr instanceof Error ? pollErr.message : '合参分析失败')
      setStage('failed')
    }
  }, [poll, sessionId, settle])

  useEffect(() => {
    if (startedRef.current === sessionId) return
    startedRef.current = sessionId
    void (async () => {
      try {
        const readi = await diagnosisApi.getReadiness(sessionId)
        setReadiness(readi)
        // 前置校验：三诊未全部完成则阻断，点名缺诊并给出直达入口
        if (!readi.can_analyze) {
          setStage('blocked')
          return
        }

        // 页面刷新：已完成的合参直接跳报告；进行中则续接轮询；未开始 / 上次失败则等用户确认
        const current = await diagnosisApi
          .getResult(sessionId)
          .catch((err: unknown) =>
            err instanceof ApiError && err.code === 40400 ? null : Promise.reject(err),
          )

        if (current?.status === 'completed') {
          setProgress(100)
          goReport()
          return
        }
        if (current === null || current.status === 'failed') {
          setLastFailed(current !== null)
          setStage('confirm')
          return
        }

        setStage('running')
        settle(await poll())
      } catch (err) {
        setError(err instanceof Error ? err.message : '合参分析失败，请重试')
        setStage('failed')
      }
    })()
  }, [goReport, poll, sessionId, settle])

  const returnToInquiry = useCallback(() => goModule('inquiry'), [goModule])

  const fusionState: { dot: string; dotClass: string; tag: string } = useMemo(() => {
    switch (stage) {
      case 'running':
        return { dot: '◉', dotClass: styles.doing, tag: '进行中' }
      case 'confirm':
        return { dot: '○', dotClass: styles.todo, tag: '待开始' }
      case 'blocked':
        return { dot: '○', dotClass: styles.todo, tag: '未开始' }
      case 'failed':
        return { dot: '○', dotClass: styles.todo, tag: '未完成' }
      default:
        return { dot: '○', dotClass: styles.todo, tag: '校验中' }
    }
  }, [stage])

  const moduleRows = MODULE_ORDER.map((key) => ({
    key,
    label: MODULE_LABELS[key],
    state: readiness?.modules[key]?.done,
  }))

  return (
    <PageShell
      title="AI 智能分析"
      description="三诊合参 · 融合舌、面、问诊依据，生成综合结论与调理建议"
    >
      <div className={styles.wrap}>
        <section className={styles.main}>
          {stage === 'blocked' ? (
            <div className={styles.state} role="alert">
              <div className={styles.stateIcon}>!</div>
              <h2 className={styles.stateTitle}>还不能开始合参</h2>
              <p className={styles.stateText}>
                {readiness?.blocking_reason || '需三诊全部完成后方可合参'}
              </p>
              <ul className={styles.moduleList}>
                {moduleRows.map((row) => (
                  <li key={row.key} className={styles.moduleRow}>
                    <span className={`${styles.moduleDot} ${row.state ? styles.ok : styles.todo}`}>
                      {row.state ? '✓' : '○'}
                    </span>
                    <span className={styles.moduleLabel}>{row.label}</span>
                    <span className={styles.moduleTag}>{row.state ? '已完成' : '未完成'}</span>
                    {row.state ? null : (
                      <button
                        type="button"
                        className={styles.fixLink}
                        onClick={() => goModule(row.key)}
                      >
                        去完成
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ) : stage === 'failed' ? (
            <div className={styles.state} role="alert">
              <div className={`${styles.stateIcon} ${styles.stateIconError}`}>×</div>
              <h2 className={styles.stateTitle}>分析失败</h2>
              <p className={styles.stateText}>{error || '合参分析暂不可用'}</p>
              <div className={styles.actions}>
                <button type="button" className="btn btn--primary" onClick={startAnalysis}>
                  重试分析
                </button>
                <button type="button" className="btn btn--ghost" onClick={returnToInquiry}>
                  返回修改
                </button>
              </div>
            </div>
          ) : stage === 'confirm' ? (
            <div className={styles.state}>
              <div className={`${styles.stateIcon} ${styles.stateIconReady}`}>✓</div>
              <h2 className={styles.stateTitle}>三诊已齐全，可以开始合参</h2>
              <p className={styles.stateText}>
                系统将融合舌象、面象与问诊依据，做一致性校验与规则加权，生成综合结论与调理建议。
                {lastFailed ? '（上次分析未成功完成，点击下方按钮将重新分析）' : ''}
              </p>
              <ul className={styles.moduleList}>
                {moduleRows.map((row) => (
                  <li key={row.key} className={styles.moduleRow}>
                    <span className={`${styles.moduleDot} ${styles.ok}`}>✓</span>
                    <span className={styles.moduleLabel}>{row.label}</span>
                    <span className={styles.moduleTag}>已完成</span>
                  </li>
                ))}
              </ul>
              <div className={styles.actions}>
                <button type="button" className="btn btn--primary" onClick={startAnalysis}>
                  开始分析
                </button>
              </div>
            </div>
          ) : (
            <div className={styles.running}>
              <div className={styles.ring} aria-hidden="true">
                <svg viewBox="0 0 96 96" className={styles.ringSvg}>
                  <circle cx="48" cy="48" r="42" className={styles.ringTrack} />
                  <circle
                    cx="48"
                    cy="48"
                    r="42"
                    className={styles.ringArc}
                    style={{ strokeDashoffset: 264 - (264 * progress) / 100 }}
                  />
                </svg>
                <span className={styles.ringText}>AI</span>
              </div>

              <p className={styles.status} aria-live="polite">
                正在进行三诊合参分析…
              </p>

              <div
                className={styles.progress}
                role="progressbar"
                aria-valuenow={progress}
                aria-valuemin={0}
                aria-valuemax={100}
              >
                <div className={styles.track}>
                  <div className={styles.fill} style={{ width: `${progress}%` }} />
                </div>
                <span className={styles.percent}>{progress}%</span>
              </div>

              <ol className={styles.stages}>
                {STAGES.map((label, index) => {
                  const state = index < stageIndex ? 'done' : index === stageIndex ? 'doing' : 'todo'
                  return (
                    <li key={label} className={`${styles.stageItem} ${styles[state]}`}>
                      <span className={styles.stageDot}>
                        {state === 'done' ? '✓' : state === 'doing' ? '◉' : '○'}
                      </span>
                      {label}
                    </li>
                  )
                })}
              </ol>
            </div>
          )}
        </section>

        <aside className={styles.side}>
          <div className={styles.sideCard}>
            <h3 className={styles.sideTitle}>分析进度</h3>
            <ul className={styles.moduleList}>
              {moduleRows.map((row) => (
                <li key={row.key} className={styles.moduleRow}>
                  <span className={`${styles.moduleDot} ${row.state ? styles.ok : styles.todo}`}>
                    {row.state ? '✓' : '○'}
                  </span>
                  <span className={styles.moduleLabel}>{row.label}</span>
                  <span className={styles.moduleTag}>{row.state ? '已完成' : '未完成'}</span>
                </li>
              ))}
              <li className={styles.moduleRow}>
                <span className={`${styles.moduleDot} ${fusionState.dotClass}`}>
                  {fusionState.dot}
                </span>
                <span className={styles.moduleLabel}>合参分析</span>
                <span className={styles.moduleTag}>{fusionState.tag}</span>
              </li>
            </ul>
          </div>

          <div className={styles.sideCard}>
            <h3 className={styles.sideTitle}>小贴士</h3>
            <p className={styles.tip}>
              合参分析融合舌、面、问三类依据，通过一致性校验与规则加权，生成综合结论与调理建议。
            </p>
          </div>

          {stage === 'running' || stage === 'confirm' ? (
            <button type="button" className={styles.cancel} onClick={returnToInquiry}>
              取消并返回
            </button>
          ) : null}
          {stage === 'running' ? (
            <p className={styles.cancelHint}>返回后分析在后台继续进行，可再次进入本页查看。</p>
          ) : null}
        </aside>
      </div>
    </PageShell>
  )
}
