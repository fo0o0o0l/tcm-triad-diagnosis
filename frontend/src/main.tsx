import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import App from '@/App'
import '@/styles/global.css'
import { applyTheme, readStoredTheme } from '@/utils/theme'

// 渲染前先应用本地主题（UI/UX §3.7），避免首帧闪烁
applyTheme(readStoredTheme())

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
