/**
 * UI 偏好状态（《开发任务文档》§5.1：Zustand `ui(theme)`）。
 *
 * 目前仅承载外观主题（UI/UX §3.7）；切换即时生效并写入 `localStorage['ui_theme']`，
 * 刷新后由 main.tsx 在渲染前读回并应用，保证无闪烁。
 */

import { create } from 'zustand'

import { applyTheme, readStoredTheme, storeTheme, type ThemeName } from '@/utils/theme'

interface UiState {
  theme: ThemeName
  setTheme: (theme: ThemeName) => void
}

export const useUiStore = create<UiState>()((set) => ({
  theme: readStoredTheme(),

  setTheme: (theme) => {
    applyTheme(theme)
    storeTheme(theme)
    set({ theme })
  },
}))
