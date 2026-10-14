import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import { ROUTES } from '@/router/routes'
import { authApi } from '@/services/auth'
import { ApiError, getFieldErrors } from '@/utils/request'

const CODE_COOLDOWN = 60

function resolveError(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === 42900) return '操作过于频繁，请稍后再试'
    const fields = getFieldErrors(err)
    if (fields.length > 0) return fields.map((f) => f.error).join('；')
    return err.message || '请求失败，请重试'
  }
  return '网络异常，请稍后重试'
}

/** P1 注册页（《开发任务文档》§4.3 A1/A6）。 */
export function RegisterPage() {
  const navigate = useNavigate()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [department, setDepartment] = useState('')
  const [verifyCode, setVerifyCode] = useState('')

  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [cooldown, setCooldown] = useState(0)

  useEffect(() => {
    if (cooldown <= 0) return
    const timer = window.setTimeout(() => setCooldown((v) => v - 1), 1000)
    return () => window.clearTimeout(timer)
  }, [cooldown])

  const codeTarget = email.trim() || phone.trim()

  const handleSendCode = useCallback(async () => {
    setError('')
    setNotice('')
    if (!codeTarget) {
      setError('请先填写邮箱或手机号')
      return
    }
    try {
      const channel = email.trim() ? 'email' : 'sms'
      await authApi.sendCode({ target: codeTarget, scene: 'register', channel })
      setCooldown(CODE_COOLDOWN)
      setNotice('验证码已发送（开发环境请到 MailHog http://localhost:8025 查看）')
    } catch (err) {
      setError(resolveError(err))
    }
  }, [codeTarget, email])

  const handleSubmit = useCallback(async () => {
    setError('')
    setNotice('')
    if (!username.trim()) {
      setError('请输入用户名')
      return
    }
    if (password.length < 8) {
      setError('密码至少 8 位且需含字母与数字')
      return
    }
    if (!codeTarget) {
      setError('邮箱与手机号至少填写一个')
      return
    }
    if (!verifyCode.trim()) {
      setError('请输入验证码')
      return
    }
    setSubmitting(true)
    try {
      await authApi.register({
        username: username.trim(),
        password,
        name: name.trim() || undefined,
        email: email.trim() || undefined,
        phone: phone.trim() || undefined,
        department: department.trim() || undefined,
        verify_code: verifyCode.trim(),
      })
      navigate(ROUTES.LOGIN, { replace: true, state: { notice: '注册成功，请登录' } })
    } catch (err) {
      setError(resolveError(err))
    } finally {
      setSubmitting(false)
    }
  }, [codeTarget, department, email, name, navigate, password, phone, username, verifyCode])

  return (
    <div className="auth-shell">
      <section className="auth-brand">
        <div className="auth-brand__title">中医三诊合一分析系统</div>
        <p className="auth-brand__subtitle">创建医师账号，开启三诊合参分析</p>
        <p className="auth-brand__subtitle">账号将用于诊疗会话、报告与历史记录</p>
      </section>

      <section className="auth-card">
        <h1 className="auth-card__title">注册账号</h1>

        {error ? <div className="form-error">{error}</div> : null}
        {notice ? <div className="form-hint">{notice}</div> : null}

        <form
          onSubmit={(event) => {
            event.preventDefault()
            void handleSubmit()
          }}
        >
          <div className="form-field">
            <label className="form-label" htmlFor="reg-username">
              用户名
            </label>
            <input
              id="reg-username"
              className="form-input"
              autoComplete="username"
              placeholder="4-32 位字母、数字或下划线"
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
          </div>

          <div className="form-field">
            <label className="form-label" htmlFor="reg-password">
              密码
            </label>
            <input
              id="reg-password"
              className="form-input"
              type="password"
              autoComplete="new-password"
              placeholder="至少 8 位，含字母与数字"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </div>

          <div className="form-field">
            <label className="form-label" htmlFor="reg-name">
              姓名
            </label>
            <input
              id="reg-name"
              className="form-input"
              placeholder="选填"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </div>

          <div className="form-field">
            <label className="form-label" htmlFor="reg-email">
              邮箱
            </label>
            <input
              id="reg-email"
              className="form-input"
              autoComplete="email"
              placeholder="doctor@example.com"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </div>

          <div className="form-field">
            <label className="form-label" htmlFor="reg-phone">
              手机号
            </label>
            <input
              id="reg-phone"
              className="form-input"
              placeholder="选填（与邮箱至少填一个）"
              value={phone}
              onChange={(event) => setPhone(event.target.value)}
            />
          </div>

          <div className="form-field">
            <label className="form-label" htmlFor="reg-department">
              科室
            </label>
            <input
              id="reg-department"
              className="form-input"
              placeholder="选填，如：中医内科"
              value={department}
              onChange={(event) => setDepartment(event.target.value)}
            />
          </div>

          <div className="form-field">
            <label className="form-label" htmlFor="reg-code">
              验证码
            </label>
            <div className="form-input-row">
              <input
                id="reg-code"
                className="form-input"
                placeholder="请输入验证码"
                value={verifyCode}
                onChange={(event) => setVerifyCode(event.target.value)}
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

          <button type="submit" className="btn btn--primary btn--block" disabled={submitting}>
            {submitting ? '注册中…' : '注册'}
          </button>

          <p className="auth-disclaimer">
            已有账号？<Link to={ROUTES.LOGIN}>返回登录</Link>
          </p>
        </form>
      </section>

      <aside className="auth-features">
        <div className="auth-feature">
          <div className="auth-feature__title">辅助参考</div>
          <div className="auth-feature__desc">分析结果不构成最终医疗诊断</div>
        </div>
        <div className="auth-feature">
          <div className="auth-feature__title">数据安全</div>
          <div className="auth-feature__desc">图像加密存储，仅用于本次诊断</div>
        </div>
      </aside>
    </div>
  )
}