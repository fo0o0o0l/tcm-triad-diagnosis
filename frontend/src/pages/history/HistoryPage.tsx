import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent, KeyboardEvent } from 'react'
import { useNavigate } from 'react-router-dom'

import { PageShell } from '@/components/PageShell'
import { ROUTES } from '@/router/routes'
import {
  reportApi,
  type HealthLevel,
  type ReportHistoryItem,
  type ReportHistoryQuery,
} from '@/services/api'
import { sessionDisplayNo, withSession } from '@/utils/session'

import styles from './HistoryPage.module.css'

/**
 * P7 历史记录页（PRD §6.5.4 / §9.6；UI/UX §5.6）。
 *
 * 按患者 / 会话号 / 结论关键词、时间范围与快捷筛选检索历史报告（后端 R4），
 * 列表支持无限滚动分页与「重新打开报告」；多选对比仅作占位（P8 后续接入）。
 */

const PAGE_SIZE = 10

/** 快捷筛选（§5.6.1）。`mine` 依赖归属字段，暂置灰。 */
type QuickFilter = 'all' | 'mine' | 'anonymous' | 'archived'

const QUICK_FILTERS: { key: QuickFilter; label: string; disabled?: boolean; hint?: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'mine', label: '我的报告', disabled: true, hint: '报告暂无归属字段，暂不可用' },
  { key: 'anonymous', label: '匿名用户' },
  { key: 'archived', label: '已归档' },
]

const HEALTH_META: Record<HealthLevel, { label: string; className: string }> = {
  good: { label: '健康', className: styles.healthGood },
  fair: { label: '一般', className: styles.healthFair },
  poor: { label: '较差', className: styles.healthPoor },
  bad: { label: '极差', className: styles.healthBad },
}

function confidenceClass(value: number): string {
  if (value >= 0.8) return styles.confHigh
  if (value >= 0.7) return styles.confMedium
  return styles.confLow
}

/** `yyyy-MM-dd HH:mm`（本地时区）。 */
function formatDateTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(
    date.getHours(),
  )}:${pad(date.getMinutes())}`
}

function toDateInput(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

/** 对比分组键：匿名记录以会话号标识（跨患者禁止对比）。 */
function patientKey(item: ReportHistoryItem): string {
  return item.patient_name ?? item.session_id
}

interface HistoryCardProps {
  item: ReportHistoryItem
  selected: boolean
  deleting: boolean
  onToggle: (item: ReportHistoryItem) => void
  onOpen: (item: ReportHistoryItem) => void
  onDelete: (item: ReportHistoryItem) => void
}

function HistoryCard({ item, selected, deleting, onToggle, onOpen, onDelete }: HistoryCardProps) {
  const health = item.health_level ? HEALTH_META[item.health_level] : null
  const patient = item.anonymous ? '匿名用户' : item.patient_name || '未登记姓名'

  const onKeyDown = (event: KeyboardEvent<HTMLLIElement>) => {
    if (event.key === 'Enter') {
      event.preventDefault()
      onOpen(item)
    }
  }

  return (
    <li
      className={`${styles.card} ${selected ? styles.cardSelected : ''}`}
      tabIndex={0}
      aria-label={`打开 ${patient} 的报告`}
      onClick={() => onOpen(item)}
      onKeyDown={onKeyDown}
    >
      <input
        type="checkbox"
        className={styles.cardCheckbox}
        aria-label="选择用于对比"
        checked={selected}
        onClick={(event) => event.stopPropagation()}
        onChange={() => onToggle(item)}
      />
      <div className={styles.cardMain}>
        <div className={styles.cardTop}>
          <span className={styles.patient}>{patient}</span>
          <span className={styles.session}>
            {sessionDisplayNo(item.session_id, {
              name: item.patient_name,
              anonymous: item.anonymous,
            })}
          </span>
          <span className={styles.time}>{formatDateTime(item.generated_at)}</span>
          {item.status === 'archived' ? <span className={styles.archivedBadge}>已归档</span> : null}
        </div>
        <div className={styles.cardBody}>
          {health ? (
            <span className={`${styles.healthBadge} ${health.className}`}>{health.label}</span>
          ) : null}
          {item.overall_confidence !== null ? (
            <span className={`${styles.confBadge} ${confidenceClass(item.overall_confidence)}`}>
              {Math.round(item.overall_confidence * 100)}%
            </span>
          ) : null}
          <span className={styles.summary} title={item.summary ?? ''}>
            {item.summary || '暂无结论摘要'}
          </span>
          <button
            type="button"
            className={`btn btn--ghost ${styles.openBtn}`}
            onClick={(event) => {
              event.stopPropagation()
              onOpen(item)
            }}
          >
            打开
          </button>
          <button
            type="button"
            className={`btn btn--ghost ${styles.deleteBtn}`}
            disabled={deleting}
            onClick={(event) => {
              event.stopPropagation()
              onDelete(item)
            }}
          >
            {deleting ? '删除中…' : '删除'}
          </button>
        </div>
      </div>
    </li>
  )
}

export function HistoryPage() {
  const navigate = useNavigate()

  const [keywordInput, setKeywordInput] = useState('')
  const [liveKeyword, setLiveKeyword] = useState('')
  const [chips, setChips] = useState<string[]>([])
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [quick, setQuick] = useState<QuickFilter>('all')

  const [items, setItems] = useState<ReportHistoryItem[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(false)
  const [initialLoading, setInitialLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState('')

  const [selected, setSelected] = useState<string[]>([])
  const [compareHint, setCompareHint] = useState('')
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const sentinelRef = useRef<HTMLDivElement | null>(null)

  // 关键词输入防抖 300ms（§5.6.2 即时筛选）
  useEffect(() => {
    const timer = window.setTimeout(() => setLiveKeyword(keywordInput.trim()), 300)
    return () => window.clearTimeout(timer)
  }, [keywordInput])

  const buildQuery = useCallback(
    (targetPage: number): ReportHistoryQuery => {
      const keywords = [liveKeyword, ...chips].filter(Boolean)
      const query: ReportHistoryQuery = { page: targetPage, page_size: PAGE_SIZE }
      if (keywords.length) query.keyword = keywords
      if (from) query.from = from
      if (to) query.to = to
      if (quick === 'anonymous') query.anonymous = true
      if (quick === 'archived') query.status = 'archived'
      return query
    },
    [chips, from, liveKeyword, quick, to],
  )

  const load = useCallback(
    async (targetPage: number, append: boolean) => {
      setError('')
      if (append) setLoadingMore(true)
      else {
        setInitialLoading(true)
        setSelected([])
        setCompareHint('')
      }
      try {
        const data = await reportApi.list(buildQuery(targetPage))
        setTotal(data.total)
        setPage(data.page)
        setItems((prev) => (append ? [...prev, ...data.items] : data.items))
        setHasMore(data.page * data.page_size < data.total)
      } catch (err) {
        setError(err instanceof Error ? err.message : '历史记录加载失败，请稍后重试')
        if (!append) {
          setItems([])
          setTotal(0)
          setHasMore(false)
        }
      } finally {
        setInitialLoading(false)
        setLoadingMore(false)
      }
    },
    [buildQuery],
  )

  // 筛选条件变化 → 回到第 1 页重新查询
  useEffect(() => {
    void load(1, false)
  }, [load])

  // 无限滚动：触底自动加载下一页
  useEffect(() => {
    const node = sentinelRef.current
    if (!node) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && hasMore && !loadingMore && !initialLoading) {
          void load(page + 1, true)
        }
      },
      { rootMargin: '120px' },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [hasMore, initialLoading, load, loadingMore, page])

  const resetFilters = useCallback(() => {
    setKeywordInput('')
    setLiveKeyword('')
    setChips([])
    setFrom('')
    setTo('')
    setQuick('all')
  }, [])

  const applyPreset = useCallback((days: number | null) => {
    if (days === null) {
      setFrom('')
      setTo('')
      return
    }
    const end = new Date()
    const start = new Date()
    start.setDate(end.getDate() - (days - 1))
    setFrom(toDateInput(start))
    setTo(toDateInput(end))
  }, [])

  const addChip = useCallback(
    (event: FormEvent) => {
      event.preventDefault()
      const term = keywordInput.trim()
      if (term && !chips.includes(term)) setChips((prev) => [...prev, term])
      setKeywordInput('')
      setLiveKeyword('')
    },
    [chips, keywordInput],
  )

  const removeChip = useCallback((term: string) => {
    setChips((prev) => prev.filter((item) => item !== term))
  }, [])

  const openReport = useCallback(
    (item: ReportHistoryItem) => {
      navigate(withSession(ROUTES.REPORT, item.session_id))
    },
    [navigate],
  )

  const removeReport = useCallback(
    async (item: ReportHistoryItem) => {
      if (deletingId) return
      if (!window.confirm('删除后该报告将从历史记录中移除（不可恢复），是否继续？')) return
      setCompareHint('')
      setDeletingId(item.report_id)
      try {
        await reportApi.remove(item.report_id)
        setItems((prev) => prev.filter((row) => row.report_id !== item.report_id))
        setSelected((prev) => prev.filter((id) => id !== item.report_id))
        setTotal((prev) => Math.max(0, prev - 1))
      } catch (err) {
        setCompareHint(err instanceof Error ? err.message : '删除失败，请稍后重试')
      } finally {
        setDeletingId(null)
      }
    },
    [deletingId],
  )

  const toggleSelect = useCallback(
    (item: ReportHistoryItem) => {
      setCompareHint('')
      if (selected.includes(item.report_id)) {
        setSelected(selected.filter((id) => id !== item.report_id))
        return
      }
      const chosen = selected
        .map((id) => items.find((row) => row.report_id === id))
        .filter((row): row is ReportHistoryItem => Boolean(row))
      if (chosen.some((row) => patientKey(row) !== patientKey(item))) {
        setCompareHint('仅支持同一用户的多条记录对比')
        return
      }
      if (selected.length >= 2) {
        setCompareHint('最多选择 2 条记录进行对比')
        return
      }
      setSelected([...selected, item.report_id])
    },
    [items, selected],
  )

  const compareReady = selected.length === 2

  // 进入 P8 数据对比页：以生成时间较早者为基准，较近者为对比（UI/UX §5.7）
  const startCompare = useCallback(() => {
    if (selected.length !== 2) return
    const rows = selected
      .map((id) => items.find((row) => row.report_id === id))
      .filter((row): row is ReportHistoryItem => Boolean(row))
    if (rows.length !== 2) return
    rows.sort((a, b) => new Date(a.generated_at).getTime() - new Date(b.generated_at).getTime())
    const [older, newer] = rows
    navigate(`${ROUTES.COMPARE}?base=${older.report_id}&target=${newer.report_id}`)
  }, [items, navigate, selected])

  const skeleton = useMemo(
    () => (
      <div className={styles.skeletonList} aria-hidden="true">
        {[0, 1, 2].map((key) => (
          <div className={styles.skeletonCard} key={key} />
        ))}
      </div>
    ),
    [],
  )

  return (
    <PageShell title="历史记录">
      <div className={styles.layout}>
        <div className={styles.main}>
          {/* 搜索筛选栏（§5.6.2） */}
          <form className={styles.searchBar} onSubmit={addChip}>
            <div className={styles.searchRow}>
              <input
                className={styles.searchInput}
                type="text"
                value={keywordInput}
                placeholder="用户姓名 / 会话编号 / 结论关键词"
                onChange={(event) => setKeywordInput(event.target.value)}
              />
              <button type="submit" className="btn btn--primary">
                搜索
              </button>
            </div>

            {chips.length ? (
              <div className={styles.chips}>
                {chips.map((term) => (
                  <span className={styles.chip} key={term}>
                    {term}
                    <button
                      type="button"
                      className={styles.chipRemove}
                      aria-label={`移除关键词 ${term}`}
                      onClick={() => removeChip(term)}
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
            ) : null}

            <div className={styles.dateRange}>
              <span className={styles.dateLabel}>时间范围</span>
              <input
                className={styles.dateInput}
                type="date"
                value={from}
                max={to || undefined}
                onChange={(event) => setFrom(event.target.value)}
              />
              <span className={styles.dateLabel}>~</span>
              <input
                className={styles.dateInput}
                type="date"
                value={to}
                min={from || undefined}
                onChange={(event) => setTo(event.target.value)}
              />
              <div className={styles.presets}>
                <button type="button" className={styles.presetBtn} onClick={() => applyPreset(7)}>
                  近 7 天
                </button>
                <button type="button" className={styles.presetBtn} onClick={() => applyPreset(30)}>
                  近 30 天
                </button>
                <button type="button" className={styles.presetBtn} onClick={() => applyPreset(null)}>
                  自定义
                </button>
              </div>
            </div>

            <div className={styles.searchActions}>
              <span className={styles.count}>共 {total} 份报告</span>
              <button type="button" className={styles.resetBtn} onClick={resetFilters}>
                重置
              </button>
            </div>
          </form>

          {/* 列表 */}
          {initialLoading ? (
            skeleton
          ) : error ? (
            <div className={styles.error}>
              <div>{error}</div>
              <button
                type="button"
                className="btn btn--ghost"
                style={{ marginTop: 'var(--space-2)' }}
                onClick={() => void load(1, false)}
              >
                重试
              </button>
            </div>
          ) : items.length === 0 ? (
            <div className={styles.empty}>
              <div>未找到符合条件的诊断记录</div>
              <button
                type="button"
                className="btn btn--ghost"
                style={{ marginTop: 'var(--space-2)' }}
                onClick={resetFilters}
              >
                重置筛选
              </button>
            </div>
          ) : (
            <ul className={styles.list}>
              {items.map((item) => (
                <HistoryCard
                  key={item.report_id}
                  item={item}
                  selected={selected.includes(item.report_id)}
                  deleting={deletingId === item.report_id}
                  onToggle={toggleSelect}
                  onOpen={openReport}
                  onDelete={removeReport}
                />
              ))}
            </ul>
          )}

          {loadingMore ? <div className={styles.loadingMore}>加载中…</div> : null}

          {!initialLoading && hasMore && !loadingMore ? (
            <button
              type="button"
              className={`btn btn--ghost ${styles.loadMore}`}
              onClick={() => void load(page + 1, true)}
            >
              加载更多
            </button>
          ) : null}

          <div className={styles.sentinel} ref={sentinelRef} />

          {compareHint ? <div className={styles.compareHint}>{compareHint}</div> : null}

          {/* 多选对比操作条（P8 数据对比页入口） */}
          {selected.length > 0 ? (
            <div className={styles.compareBar}>
              <span className={styles.compareBarText}>
                已选 {selected.length} 条
                {compareReady ? ' · 可对比' : ' · 再选 1 条同用户记录'}
              </span>
              <button
                type="button"
                className="btn btn--primary"
                disabled={!compareReady}
                onClick={startCompare}
              >
                对比
              </button>
              <button type="button" className="btn btn--ghost" onClick={() => setSelected([])}>
                取消
              </button>
            </div>
          ) : null}
        </div>

        {/* 右侧栏（§5.6.1） */}
        <aside className={styles.aside}>
          <div className={styles.statCard}>
            <div className={styles.statValue}>{total}</div>
            <div className={styles.statLabel}>共 {total} 份报告</div>
          </div>
          <div className={styles.quickCard}>
            <h3 className={styles.asideTitle}>快捷筛选</h3>
            <div className={styles.quickList}>
              {QUICK_FILTERS.map((option) => (
                <label
                  key={option.key}
                  className={`${styles.quickItem} ${
                    option.disabled ? styles.quickItemDisabled : ''
                  }`}
                  title={option.hint}
                >
                  <input
                    type="radio"
                    name="quick-filter"
                    value={option.key}
                    checked={quick === option.key}
                    disabled={option.disabled}
                    onChange={() => setQuick(option.key)}
                  />
                  {option.label}
                </label>
              ))}
            </div>
          </div>
        </aside>
      </div>
    </PageShell>
  )
}