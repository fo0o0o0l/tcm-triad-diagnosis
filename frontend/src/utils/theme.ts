/**
 * 主题工具（UI/UX §3.7 主题系统）。
 *
 * 三套主题：白色（默认）/ 蓝紫 / 深色，通过 `html` 上的 `data-theme` 切换令牌覆盖；
 * 持久化于 `localStorage['ui_theme']`。首访不跟随系统深色，统一以白色主题为默认。
 */

export type ThemeName = 'light' | 'blue-purple' | 'dark'

export const THEME_STORAGE_KEY = 'ui_theme'
export const DEFAULT_THEME: ThemeName = 'light'

/** 主题选择卡片（§5.8.2 外观设置）展示顺序与文案。 */
export const THEME_OPTIONS: { value: ThemeName; label: string; description: string }[] = [
  { value: 'light', label: '白色主题', description: '纯白底 + 浅灰分隔（默认）' },
  { value: 'blue-purple', label: '蓝紫主题', description: '极淡紫底 + 紫色强调' },
  { value: 'dark', label: '深色主题', description: '深灰底 + 提亮蓝色强调' },
]

export function isThemeName(value: unknown): value is ThemeName {
  return value === 'light' || value === 'blue-purple' || value === 'dark'
}

export function readStoredTheme(): ThemeName {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY)
    return isThemeName(stored) ? stored : DEFAULT_THEME
  } catch {
    // 隐私模式等场景下 localStorage 不可用：退回默认主题，不阻断渲染
    return DEFAULT_THEME
  }
}

export function storeTheme(theme: ThemeName): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme)
  } catch {
    // 持久化失败不影响本次切换效果
  }
}

/**
 * 应用主题：白色主题为 `:root` 默认值，不设置属性以免多一层覆盖。
 * 在 React 渲染前调用可避免切换闪烁。
 */
export function applyTheme(theme: ThemeName): void {
  const root = document.documentElement
  if (theme === 'light') {
    root.removeAttribute('data-theme')
  } else {
    root.setAttribute('data-theme', theme)
  }
}
