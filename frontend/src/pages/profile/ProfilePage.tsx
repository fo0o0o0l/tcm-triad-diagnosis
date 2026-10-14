/**
 * P9 个人中心页（UI/UX §5.8）。
 *
 * 单页 + 左侧分组导航（移动端折叠为顶部 Tab），右侧常驻账号状态与退出登录：
 * - 基本信息：姓名 / 手机 / 科室可改（A10），账号只读；头像上传（A11）；
 * - 外观设置：主题卡片单选，即时生效并持久化于 `localStorage['ui_theme']`（§3.7）；
 * - 账号安全：修改密码（A9，需原密码 + 二次确认）、清除本地数据；
 * - 我的报告：最近报告列表，复用 P7 的报告打开方式（§5.6.3）。
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import type { ChangeEvent, FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { PageShell } from '@/components/PageShell'
import { Toast } from '@/components/Toast'
import type { ToastTone } from '@/components/Toast'
import { ROUTES } from '@/router/routes'
import { reportApi } from '@/services/api'
import type { ReportHistoryItem } from '@/services/api'
import { authApi } from '@/services/auth'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'
import type { UpdateProfileRequest, UserProfile } from '@/types/auth'
import { clearCredential } from '@/utils/credential'
import { getFieldErrors } from '@/utils/request'
import { withSession } from '@/utils/session'
import { DEFAULT_THEME, THEME_OPTIONS } from '@/utils/theme'

import styles from './ProfilePage.module.css'

type GroupKey = 'basic' | 'appearance' | 'security' | 'reports'

const GROUPS: { key: GroupKey; label: string }[] = [
  { key: 'basic', label: '基本信息' },
  { key: 'appearance', label: '外观设置' },
  { key: 'security', label: '账号安全' },
  { key: 'reports', label: '我的报告' },
]

const ROLE_LABELS: Record<string, string> = {
  doctor: '医师',
  patient: '患者',
  admin: '管理员',
}

const STATUS_LABELS: Record<string, string> = {
  active: '已认证',
  pending: '待激活',
  disabled: '已禁用',
}

const HEALTH_LABELS: Record<string, string> = {
  good: '健康',
  fair: '一般',
  poor: '较差',
  bad: '极差',
}

const AVATAR_MAX_BYTES = 5 * 1024 * 1024

function toGroupKey(value: string | null): GroupKey {
  return GROUPS.some((group) => group.key === value) ? (value as GroupKey) : 'basic'
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

function formatDateTime(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

export function ProfilePage() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const group = toGroupKey(searchParams.get('tab'))

  const { user, refreshToken, clear, setUser } = useAuthStore()
  const { theme, setTheme } = useUiStore()

  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')

  const [form, setForm] = useState({ name: '', phone: '', department: '' })
  const [saving, setSaving] = useState(false)
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})

  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [password, setPassword] = useState({
    old_password: '',
    new_password: '',
    confirm_password: '',
  })
  const [passwordError, setPasswordError] = useState('')
  const [changing, setChanging] = useState(false)

  const [reports, setReports] = useState<ReportHistoryItem[]>([])
  const [reportsLoading, setReportsLoading] = useState(true)

  const [loggingOut, setLoggingOut] = useState(false)
  const [toast, setToast] = useState<{ message: string; tone: ToastTone } | null>(null)

  const showToast = useCallback((message: string, tone: ToastTone = 'success') => {
    setToast({ message, tone })
  }, [])

  // 资料同步到会话（Layout 的昵称 / 头像随之更新）
  const syncSession = useCallback(
    (next: UserProfile) => {
      setUser({
        user_no: next.user_no,
        username: next.username,
        name: next.name,
        role: next.role,
        avatar_url: next.avatar_url,
      })
    },
    [setUser],
  )

  // 首次进入拉取资料（A5）；表单仅在首次赋值，避免后续刷新覆盖未保存的编辑
  const formSyncedRef = useRef(false)
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    authApi
      .me()
      .then((data) => {
        if (cancelled) return
        setProfile(data)
        syncSession(data)
        if (!formSyncedRef.current) {
          formSyncedRef.current = true
          setForm({
            name: data.name ?? '',
            phone: data.phone ?? '',
            department: data.department ?? '',
          })
        }
        setLoadError('')
      })
      .catch((error: unknown) => {
        if (!cancelled) setLoadError(errorMessage(error, '资料加载失败，请稍后重试'))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [syncSession])

  // 最近报告（§5.8.2 我的报告，复用 P7 列表数据源）
  useEffect(() => {
    let cancelled = false
    reportApi
      .list({ page: 1, page_size: 5 })
      .then((page) => {
        if (!cancelled) setReports(page.items)
      })
      .catch(() => {
        if (!cancelled) setReports([])
      })
      .finally(() => {
        if (!cancelled) setReportsLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const selectGroup = (key: GroupKey) => {
    setSearchParams(key === 'basic' ? {} : { tab: key }, { replace: true })
  }

  const handleSave = async (event: FormEvent) => {
    event.preventDefault()
    if (saving) return
    setSaving(true)
    setFieldErrors({})
    const payload: UpdateProfileRequest = {
      name: form.name.trim(),
      phone: form.phone.trim(),
      department: form.department.trim(),
    }
    try {
      const updated = await authApi.updateProfile(payload)
      setProfile(updated)
      syncSession(updated)
      setForm({
        name: updated.name ?? '',
        phone: updated.phone ?? '',
        department: updated.department ?? '',
      })
      showToast('已保存')
    } catch (error) {
      const fields = getFieldErrors(error)
      if (fields.length) {
        setFieldErrors(
          fields.reduce<Record<string, string>>((acc, item) => {
            acc[item.field] = item.error
            return acc
          }, {}),
        )
      } else {
        showToast(errorMessage(error, '保存失败，请稍后重试'), 'error')
      }
    } finally {
      setSaving(false)
    }
  }

  const handleAvatarChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    // 清空取值，允许连续选择同一文件
    event.target.value = ''
    if (!file || uploading) return
    if (!file.type.startsWith('image/')) {
      showToast('请选择 JPG / PNG / WebP 格式的图片', 'error')
      return
    }
    if (file.size > AVATAR_MAX_BYTES) {
      showToast('头像大小不能超过 5MB', 'error')
      return
    }
    setUploading(true)
    try {
      const updated = await authApi.uploadAvatar(file)
      setProfile(updated)
      syncSession(updated)
      showToast('头像已更新')
    } catch (error) {
      showToast(errorMessage(error, '头像上传失败，请稍后重试'), 'error')
    } finally {
      setUploading(false)
    }
  }

  const handleChangePassword = async (event: FormEvent) => {
    event.preventDefault()
    if (changing) return
    if (password.new_password.length < 8 || !/[A-Za-z]/.test(password.new_password) || !/\d/.test(password.new_password)) {
      setPasswordError('新密码至少 8 位，且需同时包含字母与数字')
      return
    }
    if (password.new_password !== password.confirm_password) {
      setPasswordError('两次输入的新密码不一致')
      return
    }
    if (!window.confirm('确定要修改密码吗？修改成功后其它设备将需要重新登录。')) return

    setChanging(true)
    setPasswordError('')
    try {
      await authApi.changePassword({
        old_password: password.old_password,
        new_password: password.new_password,
      })
      setPassword({ old_password: '', new_password: '', confirm_password: '' })
      showToast('密码修改成功')
    } catch (error) {
      setPasswordError(errorMessage(error, '密码修改失败，请稍后重试'))
    } finally {
      setChanging(false)
    }
  }

  const handleClearLocalData = () => {
    if (
      !window.confirm('确定要清除本地数据吗？将重置外观偏好与已保存的账号密码，云端报告不受影响。')
    ) {
      return
    }
    clearCredential()
    setTheme(DEFAULT_THEME)
    showToast('清理成功')
  }

  const handleLogout = async () => {
    if (loggingOut) return
    if (!window.confirm('确定要退出登录吗？')) return
    setLoggingOut(true)
    try {
      if (refreshToken) await authApi.logout(refreshToken)
    } catch {
      // 登出失败不阻断本地清理（§5.8.3）
    } finally {
      clearCredential()
      clear({ keepAccount: false })
      navigate(ROUTES.LOGIN, { replace: true })
    }
  }

  const displayName = profile?.name || profile?.username || user?.name || user?.username || '未登录'
  const avatarSrc = authApi.avatarUrl(profile?.avatar_url ?? user?.avatar_url ?? null)

  const avatarNode = avatarSrc ? (
    <img className={styles.avatar} src={avatarSrc} alt="用户头像" />
  ) : (
    <span className={`${styles.avatar} ${styles.avatarFallback}`} aria-hidden="true">
      {displayName.slice(0, 1)}
    </span>
  )

  return (
    <PageShell title="个人中心" description="管理账号资料、外观与账号安全">
      <div className={styles.layout}>
        <nav className={styles.nav} aria-label="个人中心分组">
          {GROUPS.map((item) => (
            <button
              key={item.key}
              type="button"
              className={`${styles.navItem}${item.key === group ? ' ' + styles.navItemActive : ''}`}
              aria-current={item.key === group ? 'page' : undefined}
              onClick={() => selectGroup(item.key)}
            >
              {item.label}
            </button>
          ))}
        </nav>

        <section className={styles.content}>
          {loading ? (
            <p className={styles.hint}>加载中…</p>
          ) : loadError ? (
            <p className={styles.error}>{loadError}</p>
          ) : (
            <>
              {group === 'basic' ? (
                <form className={styles.card} onSubmit={handleSave}>
                  <div className={styles.avatarRow}>
                    {avatarNode}
                    <div>
                      <button
                        type="button"
                        className={styles.secondaryButton}
                        disabled={uploading}
                        onClick={() => fileInputRef.current?.click()}
                      >
                        {uploading ? '上传中…' : '更换头像'}
                      </button>
                      <p className={styles.hint}>
                        支持 JPG / PNG / WebP，不超过 5MB，仅本人可见
                      </p>
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept="image/jpeg,image/png,image/webp"
                        className={styles.fileInput}
                        onChange={handleAvatarChange}
                      />
                    </div>
                  </div>

                  <label className={styles.field}>
                    <span className={styles.fieldLabel}>账号</span>
                    <input className={styles.input} value={profile?.username ?? ''} readOnly />
                  </label>

                  <label className={styles.field}>
                    <span className={styles.fieldLabel}>姓名</span>
                    <input
                      className={styles.input}
                      value={form.name}
                      maxLength={64}
                      placeholder="请输入姓名"
                      onChange={(event) => setForm({ ...form, name: event.target.value })}
                    />
                  </label>

                  <label className={styles.field}>
                    <span className={styles.fieldLabel}>手机号</span>
                    <input
                      className={styles.input}
                      value={form.phone}
                      maxLength={20}
                      placeholder="请输入手机号"
                      onChange={(event) => setForm({ ...form, phone: event.target.value })}
                    />
                    {fieldErrors.phone ? (
                      <span className={styles.error}>{fieldErrors.phone}</span>
                    ) : null}
                  </label>

                  <label className={styles.field}>
                    <span className={styles.fieldLabel}>科室</span>
                    <input
                      className={styles.input}
                      value={form.department}
                      maxLength={64}
                      placeholder="请输入科室"
                      onChange={(event) => setForm({ ...form, department: event.target.value })}
                    />
                  </label>

                  <div className={styles.actions}>
                    <button type="submit" className={styles.primaryButton} disabled={saving}>
                      {saving ? '保存中…' : '保存修改'}
                    </button>
                  </div>
                </form>
              ) : null}

              {group === 'appearance' ? (
                <div className={styles.card}>
                  <h2 className={styles.cardTitle}>外观设置</h2>
                  <p className={styles.hint}>切换即时生效并保存在本机，无需额外保存（§3.7）。</p>
                  <div className={styles.themeGrid} role="radiogroup" aria-label="主题">
                    {THEME_OPTIONS.map((option) => (
                      <button
                        key={option.value}
                        type="button"
                        role="radio"
                        aria-checked={theme === option.value}
                        className={`${styles.themeCard} ${
                          styles[`preview_${option.value.replace('-', '_')}`]
                        }${theme === option.value ? ' ' + styles.themeCardActive : ''}`}
                        onClick={() => setTheme(option.value)}
                      >
                        <span className={styles.themeSwatch} aria-hidden="true" />
                        <span className={styles.themeName}>{option.label}</span>
                        <span className={styles.hint}>{option.description}</span>
                        {theme === option.value ? (
                          <span className={styles.themeCheck} aria-hidden="true">
                            ✓
                          </span>
                        ) : null}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}

              {group === 'security' ? (
                <>
                  <form className={styles.card} onSubmit={handleChangePassword}>
                    <h2 className={styles.cardTitle}>修改密码</h2>
                    <label className={styles.field}>
                      <span className={styles.fieldLabel}>原密码</span>
                      <input
                        className={styles.input}
                        type="password"
                        autoComplete="current-password"
                        value={password.old_password}
                        onChange={(event) =>
                          setPassword({ ...password, old_password: event.target.value })
                        }
                      />
                    </label>
                    <label className={styles.field}>
                      <span className={styles.fieldLabel}>新密码</span>
                      <input
                        className={styles.input}
                        type="password"
                        autoComplete="new-password"
                        value={password.new_password}
                        onChange={(event) =>
                          setPassword({ ...password, new_password: event.target.value })
                        }
                      />
                    </label>
                    <label className={styles.field}>
                      <span className={styles.fieldLabel}>确认新密码</span>
                      <input
                        className={styles.input}
                        type="password"
                        autoComplete="new-password"
                        value={password.confirm_password}
                        onChange={(event) =>
                          setPassword({ ...password, confirm_password: event.target.value })
                        }
                      />
                    </label>
                    <p className={styles.hint}>新密码至少 8 位，且需同时包含字母与数字。</p>
                    {passwordError ? <p className={styles.error}>{passwordError}</p> : null}
                    <div className={styles.actions}>
                      <button type="submit" className={styles.primaryButton} disabled={changing}>
                        {changing ? '提交中…' : '确认修改'}
                      </button>
                    </div>
                  </form>

                  <div className={styles.card}>
                    <h2 className={styles.cardTitle}>本地数据</h2>
                    <p className={styles.hint}>
                      清除本机保存的外观偏好与「记住用户名和密码」，不影响云端的报告数据。
                    </p>
                    <div className={styles.actions}>
                      <button
                        type="button"
                        className={styles.secondaryButton}
                        onClick={handleClearLocalData}
                      >
                        清除本地数据
                      </button>
                    </div>
                  </div>
                </>
              ) : null}

              {group === 'reports' ? (
                <div className={styles.card}>
                  <h2 className={styles.cardTitle}>我的报告</h2>
                  {reportsLoading ? (
                    <p className={styles.hint}>加载中…</p>
                  ) : reports.length === 0 ? (
                    <p className={styles.hint}>暂无报告，完成一次三诊分析后即可在此查看。</p>
                  ) : (
                    <ul className={styles.reportList}>
                      {reports.map((item) => (
                        <li key={item.report_id}>
                          <button
                            type="button"
                            className={styles.reportItem}
                            onClick={() => navigate(withSession(ROUTES.REPORT, item.session_id))}
                          >
                            <span className={styles.reportPatient}>
                              {item.anonymous ? '匿名患者' : item.patient_name || '未填写'}
                            </span>
                            <span className={styles.hint}>{formatDateTime(item.generated_at)}</span>
                            {item.health_level ? (
                              <span className={`${styles.tag} ${styles[`health_${item.health_level}`]}`}>
                                {HEALTH_LABELS[item.health_level] ?? item.health_level}
                              </span>
                            ) : null}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                  <div className={styles.actions}>
                    <Link className={styles.linkButton} to={ROUTES.REPORTS}>
                      查看全部报告
                    </Link>
                  </div>
                </div>
              ) : null}
            </>
          )}
        </section>

        <aside className={styles.aside}>
          <div className={styles.card}>
            <div className={styles.asideUser}>
              {avatarNode}
              <div>
                <p className={styles.asideName}>{displayName}</p>
                <p className={styles.hint}>
                  {ROLE_LABELS[profile?.role ?? user?.role ?? ''] ?? '医师'} ·{' '}
                  {STATUS_LABELS[profile?.status ?? ''] ?? '正常'}
                </p>
              </div>
            </div>
          </div>

          <div className={styles.card}>
            <h2 className={styles.cardTitle}>数据统计</h2>
            <dl className={styles.stats}>
              <div>
                <dt className={styles.hint}>累计报告</dt>
                <dd className={styles.statValue}>{profile?.stats.total_reports ?? 0}</dd>
              </div>
              <div>
                <dt className={styles.hint}>本月报告</dt>
                <dd className={styles.statValue}>{profile?.stats.month_reports ?? 0}</dd>
              </div>
            </dl>
          </div>

          <div className={styles.card}>
            <h2 className={styles.cardTitle}>关于项目</h2>
            <p className={styles.hint}>
              中医三诊合一分析系统 v1.0.0
              <br />
              舌诊 / 面诊 / 问诊融合分析，基于 FastAPI + React + TypeScript 构建，仅供辅助参考。
            </p>
          </div>

          <button
            type="button"
            className={styles.dangerButton}
            disabled={loggingOut}
            onClick={handleLogout}
          >
            {loggingOut ? '正在退出…' : '退出登录'}
          </button>
        </aside>
      </div>

      {toast ? (
        <Toast message={toast.message} tone={toast.tone} onClose={() => setToast(null)} />
      ) : null}
    </PageShell>
  )
}
