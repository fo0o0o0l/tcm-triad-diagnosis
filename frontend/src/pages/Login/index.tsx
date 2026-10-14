import { useCallback, useEffect, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'

import { ROUTES } from '@/router/routes'
import { authApi } from '@/services/auth'
import { useAuthStore } from '@/stores/auth'
import { clearCredential, loadCredential, saveCredential } from '@/utils/credential'
import { ApiError } from '@/utils/request'

type Mode = 'login' | 'forgot'

const CODE_COOLDOWN = 60

const FEATURES = [
  { title: '三诊合参', desc: '舌 · 面 · 问 数据融合分析' },
  { title: '智能采集', desc: '质量校验，防重拍' },
  { title: 'AI 分析', desc: '特征项 + 置信度' },
  { title: '规范报告', desc: 'PDF 导出 / A4 打印' },
]

/** 统一把异常转成可展示文案（§7.3 错误码映射）。 */
function resolveError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === 42900) return '登录失败次数过多，请稍后再试'
    return err.message || '请求失败，请重试'
  }
  return '网络异常，请稍后重试'
}

/**
 * P1 登录页（UI/UX §5.1）：登录 / 找回密码两态，三栏布局。
 * 注册为独立路由 `/register`（§5.1 三态拆分，便于后续扩展）。
 */
export function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const setSession = useAuthStore((state) => state.setSession)
  const clearSession = useAuthStore((state) => state.clear)
  const rememberedAccount = useAuthStore((state) => state.rememberedAccount)

  const [mode, setMode] = useState<Mode>('login')
  const [account, setAccount] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [cooldown, setCooldown] = useState(0)

  const [code, setCode] = useState('')
  const [newPassword, setNewPassword] = useState('')

  const from = (location.state as { from?: string } | null)?.from ?? ROUTES.TONGUE

  // 回填已记住的账号（UI/UX §5.1.4）
  useEffect(() => {
    if (rememberedAccount) {
      setAccount(rememberedAccount)
      setRemember(true)
    }
  }, [rememberedAccount])

  // 回填本机加密保存的账号与密码（UI/UX §5.1.4 自实现方案）
  useEffect(() => {
    let cancelled = false
    void (async () => {
      const saved = await loadCredential()
      if (cancelled || !saved) return
      setAccount(saved.username)
      setPassword(saved.password)
      setRemember(true)
    })()
    return () => {
      cancelled = true
    }
  }, [])

  // 承接注册页跳转提示
  useEffect(() => {
    const state = location.state as { notice?: string } | null
    if (state?.notice) setNotice(state.notice)
  }, [location.state])

  useEffect(() => {
    if (cooldown <= 0) return
    const timer = window.setTimeout(() => setCooldown((v) => v - 1), 1000)
    return () => window.clearTimeout(timer)
  }, [cooldown])

  const handleLogin = useCallback(async () => {
    setError('')
    setNotice('')
    if (!account.trim()) {
      setError('请输入账号')
      return
    }
    if (password.length < 6) {
      setError('密码至少 6 位')
      return
    }
    setSubmitting(true)
    try {
      const data = await authApi.login({ account: account.trim(), password, remember })
      setSession({
        accessToken: data.access_token,
        refreshToken: data.refresh_token,
        user: data.user,
        remember,
      })
      // 仅在登录成功后写入 / 清除凭据（§5.1.4 保存时机）
      if (remember) {
        await saveCredential(account.trim(), password)
      } else {
        clearCredential()
      }
      navigate(from, { replace: true })
    } catch (err) {
      setError(resolveError(err))
    } finally {
      setSubmitting(false)
    }
  }, [account, from, navigate, password, remember, setSession])

  const handleSendCode = useCallback(async () => {
    setError('')
    setNotice('')
    if (!account.trim()) {
      setError('请先填写账号（用户名 / 邮箱 / 手机号）')
      return
    }
    try {
      await authApi.sendCode({ target: account.trim(), scene: 'reset_password', channel: 'email' })
      setCooldown(CODE_COOLDOWN)
      setNotice('验证码已发送，请查收（开发环境见 MailHog http://localhost:8025）')
    } catch (err) {
      setError(resolveError(err))
    }
  }, [account])

  const handleReset = useCallback(async () => {
    setError('')
    setNotice('')
    if (!account.trim()) {
      setError('请输入账号')
      return
    }
    if (code.trim().length < 4) {
      setError('请输入验证码')
      return
    }
    if (newPassword.length < 8) {
      setError('新密码至少 8 位且含字母与数字')
      return
    }
    setSubmitting(true)
    try {
      await authApi.resetPassword({
        account: account.trim(),
        verify_code: code.trim(),
        new_password: newPassword,
      })
      setMode('login')
      setPassword('')
      setCode('')
      setNewPassword('')
      // 密码已变更，清除本机已保存的凭据（§5.1.4 清除时机）
      clearCredential()
      setNotice('密码已重置，请使用新密码登录')
    } catch (err) {
      setError(resolveError(err))
    } finally {
      setSubmitting(false)
    }
  }, [account, code, newPassword])

  const handleClearSaved = useCallback(() => {
    clearCredential()
    clearSession({ keepAccount: false })
    setAccount('')
    setPassword('')
    setRemember(false)
    setError('')
    setNotice('已清除本机保存的登录信息')
  }, [clearSession])

  return (
    <div className="auth-shell">
      <section className="auth-brand">
        <div className="auth-brand__title">中医三诊合一分析系统</div>
        <p className="auth-brand__subtitle">舌诊 · 面诊 · 问诊 · 智能合参</p>
        <p className="auth-brand__subtitle">辅助中医诊疗的智能分析平台</p>
      </section>

      <section className="auth-card">
        <h1 className="auth-card__title">中医三诊合一</h1>

        {error ? <div className="form-error">{error}</div> : null}
        {notice ? <div className="form-hint">{notice}</div> : null}

        {mode === 'login' ? (
          <form
            onSubmit={(event) => {
              event.preventDefault()
              void handleLogin()
            }}
          >
            <div className="form-field">
              <label className="form-label" htmlFor="account">
                账号
              </label>
              <input
                id="account"
                className="form-input"
                autoComplete="username"
                placeholder="用户名 / 邮箱 / 手机号"
                value={account}
                onChange={(event) => setAccount(event.target.value)}
              />
            </div>

            <div className="form-field">
              <label className="form-label" htmlFor="password">
                密码
              </label>
              <div className="form-input-row">
                <input
                  id="password"
                  className="form-input"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  placeholder="请输入密码"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                />
                <button
                  type="button"
                  className="btn btn--ghost"
                  aria-label={showPassword ? '隐藏密码' : '显示密码'}
                  onClick={() => setShowPassword((v) => !v)}
                >
                  {showPassword ? '隐藏' : '显示'}
                </button>
              </div>
            </div>

            <div className="checkbox-row">
              <label>
                <input
                  type="checkbox"
                  checked={remember}
                  onChange={(event) => setRemember(event.target.checked)}
                />
                记住用户名和密码
              </label>
              <button
                type="button"
                className="form-link"
                onClick={() => {
                  setMode('forgot')
                  setError('')
                  setNotice('')
                }}
              >
                忘记密码？
              </button>
            </div>
            <p className="checkbox-note">请勿在公共设备上勾选</p>

            <button type="submit" className="btn btn--primary btn--block" disabled={submitting}>
              {submitting ? '登录中…' : '登录'}
            </button>

            <p className="auth-disclaimer">
              还没有账号？<Link to={ROUTES.REGISTER}>立即注册</Link>
            </p>
            <p className="auth-disclaimer">
              <button type="button" className="form-link" onClick={handleClearSaved}>
                清除已保存的登录信息
              </button>
            </p>
          </form>
        ) : (
          <form
            onSubmit={(event) => {
              event.preventDefault()
              void handleReset()
            }}
          >
            <div className="form-field">
              <label className="form-label" htmlFor="reset-account">
                账号
              </label>
              <input
                id="reset-account"
                className="form-input"
                autoComplete="username"
                placeholder="用户名 / 邮箱 / 手机号"
                value={account}
                onChange={(event) => setAccount(event.target.value)}
              />
            </div>

            <div className="form-field">
              <label className="form-label" htmlFor="reset-code">
                验证码
              </label>
              <div className="form-input-row">
                <input
                  id="reset-code"
                  className="form-input"
                  placeholder="请输入验证码"
                  value={code}
                  onChange={(event) => setCode(event.target.value)}
                />
                <button
                  type="button"
                  className="btn btn--ghost"
                  disabled={cooldown > 0}
                  onClick={() => void handleSendCode()}
                >
                  {cooldown > 0 ? `${cooldown}s` : '获取验证码'}
                </button>
              </div>
            </div>

            <div className="form-field">
              <label className="form-label" htmlFor="reset-password">
                新密码
              </label>
              <input
                id="reset-password"
                className="form-input"
                type="password"
                autoComplete="new-password"
                placeholder="至少 8 位，含字母与数字"
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
              />
            </div>

            <button type="submit" className="btn btn--primary btn--block" disabled={submitting}>
              {submitting ? '提交中…' : '重置密码'}
            </button>

            <p className="auth-disclaimer">
              <button
                type="button"
                className="form-link"
                onClick={() => {
                  setMode('login')
                  setError('')
                  setNotice('')
                }}
              >
                返回登录
              </button>
            </p>
          </form>
        )}

        <p className="auth-disclaimer">本系统为辅助参考，不构成最终医疗诊断</p>
      </section>

      <aside className="auth-features">
        {FEATURES.map((feature) => (
          <div className="auth-feature" key={feature.title}>
            <div className="auth-feature__title">{feature.title}</div>
            <div className="auth-feature__desc">{feature.desc}</div>
          </div>
        ))}
      </aside>
    </div>
  )
}