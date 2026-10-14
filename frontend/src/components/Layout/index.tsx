/**
 * 应用布局（UI/UX §4.1 布局 / §4.2 顶部导航栏 / §4.3 左侧诊断流程步骤指示器）。
 *
 * 顶部导航：系统名称 + 会话信息（占位）+ 用户头像下拉（个人中心/我的报告/退出登录）。
 * 左侧边栏：诊断流程常驻步骤条（舌诊/面诊/问诊），登录后全站固定展示，
 * 供随时切换模块查看同一会话的数据；<1024px 折叠为顶部横向步骤条。
 */

import type { ReactNode } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useCallback, useMemo, useState } from 'react'

import { authApi } from '@/services/auth'
import { useAuthStore } from '@/stores/auth'
import { ROUTES } from '@/router/routes'
import { resolveSessionId, startNewSession, withSession } from '@/utils/session'

interface LayoutProps {
  /** 直接传入子节点时用于非路由场景；默认渲染路由出口 `<Outlet />` */
  children?: ReactNode
}

interface FlowStep {
  key: string
  label: string
  to: string
  /** 模块尚未上线时置灰展示、不可点击 */
  offline?: boolean
}

/** 诊断流程步骤（M2 舌诊 → M3 面诊 → M4 问诊 → M5 合参分析）。 */
const FLOW_STEPS: FlowStep[] = [
  { key: 'tongue', label: '舌象采集', to: ROUTES.TONGUE },
  { key: 'face', label: '面诊采集', to: ROUTES.FACE },
  { key: 'inquiry', label: '问诊', to: ROUTES.INQUIRY },
  { key: 'analysis', label: '分析报告', to: ROUTES.ANALYSIS },
]

export function Layout({ children }: LayoutProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const { user, accessToken, refreshToken, clear } = useAuthStore()
  const [menuOpen, setMenuOpen] = useState(false)
  const [loggingOut, setLoggingOut] = useState(false)

  const displayName = user?.name || user?.username || '未登录'
  const avatarSrc = authApi.avatarUrl(user?.avatar_url)

  // 会话标识：以当前 URL 的 ?session_id= 为准（与采集页解析规则一致），
  // 保证左侧步骤条切换模块时沿用同一会话；URL 未携带时回退缓存 / 新建。
  const sessionId = useMemo(() => {
    if (!accessToken) return ''
    const fromUrl = new URLSearchParams(location.search).get('session_id')
    return resolveSessionId(fromUrl)
  }, [accessToken, location.search])

  // P6 报告页由「分析报告」步骤进入，步骤条高亮保持一致
  const isReportView = location.pathname === ROUTES.REPORT

  const handleLogout = useCallback(async () => {
    if (loggingOut) return
    setLoggingOut(true)
    try {
      if (refreshToken) {
        await authApi.logout(refreshToken)
      }
    } catch {
      // 登出失败不阻断本地清理
    } finally {
      clear({ keepAccount: true })
      setMenuOpen(false)
      navigate(ROUTES.LOGIN, { replace: true })
    }
  }, [clear, loggingOut, navigate, refreshToken])

  // 新建会话：清除当前会话标识后回到舌诊采集页，resolveSessionId 会自动生成新会话，
  // 无需退出登录即可开始下一位患者的诊断（旧会话报告仍保留在「我的报告」）。
  const handleNewSession = useCallback(() => {
    if (
      !window.confirm('开始下一位患者？将清空当前会话的采集数据，已生成的报告仍可在「我的报告」中查看。')
    ) {
      return
    }
    navigate(withSession(ROUTES.TONGUE, startNewSession()))
  }, [navigate])

  return (
    <div className="app-layout">
      <header className="app-layout__nav">
        <div className="app-layout__brand">
          <span className="app-layout__logo" aria-hidden="true">
            诊
          </span>
          <span className="app-layout__title">中医三诊合一分析系统</span>
          {accessToken ? (
            <button
              type="button"
              className="app-layout__session"
              onClick={handleNewSession}
              title="开始下一位患者，清空当前会话数据"
            >
              ＋ 新建会话
            </button>
          ) : null}
        </div>

        {accessToken ? (
          <div className="app-layout__user">
            <button
              type="button"
              className="app-layout__user-trigger"
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((v) => !v)}
            >
              {avatarSrc ? (
                <img className="app-layout__avatar" src={avatarSrc} alt="" />
              ) : (
                <span className="app-layout__avatar" aria-hidden="true">
                  {displayName.slice(0, 1)}
                </span>
              )}
              <span className="app-layout__username">{displayName}</span>
              <span className={`app-layout__caret${menuOpen ? ' is-open' : ''}`}>▾</span>
            </button>

            {menuOpen ? (
              <div className="app-layout__menu" role="menu">
                <button
                  type="button"
                  className="app-layout__menu-item"
                  role="menuitem"
                  onClick={() => {
                    setMenuOpen(false)
                    navigate(ROUTES.PROFILE)
                  }}
                >
                  个人中心
                </button>
                <button
                  type="button"
                  className="app-layout__menu-item"
                  role="menuitem"
                  onClick={() => {
                    setMenuOpen(false)
                    navigate(ROUTES.REPORTS)
                  }}
                >
                  我的报告
                </button>
                <div className="app-layout__menu-sep" />
                <button
                  type="button"
                  className="app-layout__menu-item app-layout__menu-item--danger"
                  role="menuitem"
                  disabled={loggingOut}
                  onClick={handleLogout}
                >
                  {loggingOut ? '正在退出…' : '退出登录'}
                </button>
              </div>
            ) : null}
          </div>
        ) : (
          <div className="app-layout__guest">未登录</div>
        )}
      </header>

      <div className="app-layout__body">
        {accessToken ? (
          <aside className="app-layout__sidebar" aria-label="诊断流程">
            <nav>
              <ol className="app-layout__steps">
                {FLOW_STEPS.map((step, index) => {
                  const disabled = Boolean(step.offline)
                  return (
                    <li key={step.key}>
                      {disabled ? (
                        <span
                          className="app-layout__step is-disabled"
                          aria-disabled="true"
                          title="即将上线"
                        >
                          <span className="app-layout__step-index">{index + 1}</span>
                          <span className="app-layout__step-label">{step.label}</span>
                          {step.offline ? (
                            <span className="app-layout__step-tag">即将上线</span>
                          ) : null}
                        </span>
                      ) : (
                        <NavLink
                          to={withSession(step.to, sessionId)}
                          className={({ isActive }) =>
                            `app-layout__step${
                              isActive || (step.key === 'analysis' && isReportView)
                                ? ' is-active'
                                : ''
                            }`
                          }
                        >
                          <span className="app-layout__step-index">{index + 1}</span>
                          <span className="app-layout__step-label">{step.label}</span>
                        </NavLink>
                      )}
                    </li>
                  )
                })}
              </ol>
            </nav>
          </aside>
        ) : null}

        <main className="app-layout__content">{children ?? <Outlet />}</main>
      </div>
    </div>
  )
}