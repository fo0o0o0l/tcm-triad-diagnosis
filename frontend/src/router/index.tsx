/* eslint-disable react-refresh/only-export-components -- 路由文件同时导出守卫组件与路由实例 */
import type { ReactNode } from 'react'
import { createBrowserRouter, Navigate, useLocation } from 'react-router-dom'

import { Layout } from '@/components/Layout'
import { LoginPage } from '@/pages/Login'
import { RegisterPage } from '@/pages/Register'
import { ComparePage } from '@/pages/compare/ComparePage'
import { AnalysisLoadingPage } from '@/pages/diagnosis/AnalysisLoadingPage'
import { ReportPage } from '@/pages/diagnosis/ReportPage'
import { FaceCapturePage } from '@/pages/face/FaceCapturePage'
import { HistoryPage } from '@/pages/history/HistoryPage'
import { InquiryCapturePage } from '@/pages/inquiry/InquiryCapturePage'
import { ProfilePage } from '@/pages/profile/ProfilePage'
import { TongueCapturePage } from '@/pages/tongue/TongueCapturePage'
import { ROUTES } from '@/router/routes'
import { selectIsAuthenticated, useAuthStore } from '@/stores/auth'

/**
 * 路由表（UI/UX §7.4 导航与守卫）。
 *
 * - `RequireAuth`：未登录访问受保护路由 → 重定向 `/login`（携带来源，登录后回跳）；
 * - `GuestOnly`：已登录访问登录/注册页 → 重定向舌诊采集页。
 * M2~M6 的采集/问诊/报告路由后续在此追加。
 */

function RequireAuth({ children }: { children: ReactNode }) {
  const isAuthenticated = useAuthStore(selectIsAuthenticated)
  const location = useLocation()

  if (!isAuthenticated) {
    return <Navigate to={ROUTES.LOGIN} replace state={{ from: location.pathname }} />
  }
  return <>{children}</>
}

function GuestOnly({ children }: { children: ReactNode }) {
  const isAuthenticated = useAuthStore(selectIsAuthenticated)

  if (isAuthenticated) {
    return <Navigate to={ROUTES.TONGUE} replace />
  }
  return <>{children}</>
}

export const router = createBrowserRouter([
  {
    path: ROUTES.LOGIN,
    element: (
      <GuestOnly>
        <LoginPage />
      </GuestOnly>
    ),
  },
  {
    path: ROUTES.REGISTER,
    element: (
      <GuestOnly>
        <RegisterPage />
      </GuestOnly>
    ),
  },
  {
    path: ROUTES.HOME,
    element: (
      <RequireAuth>
        <Layout />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Navigate to={ROUTES.TONGUE} replace /> },
      { path: ROUTES.TONGUE, element: <TongueCapturePage /> },
      { path: ROUTES.FACE, element: <FaceCapturePage /> },
      { path: ROUTES.INQUIRY, element: <InquiryCapturePage /> },
      { path: ROUTES.ANALYSIS, element: <AnalysisLoadingPage /> },
      { path: ROUTES.REPORT, element: <ReportPage /> },
      { path: ROUTES.REPORTS, element: <HistoryPage /> },
      { path: ROUTES.COMPARE, element: <ComparePage /> },
      { path: ROUTES.PROFILE, element: <ProfilePage /> },
    ],
  },
  { path: '*', element: <Navigate to={ROUTES.TONGUE} replace /> },
])