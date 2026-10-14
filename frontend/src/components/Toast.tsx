/**
 * 轻提示（UI/UX §6 组件规范 / §5.8.3 反馈）。
 *
 * 用于「保存成功」「密码修改成功」等瞬时反馈，到时自动消失；调用方通过 `onClose` 清除状态。
 */

import { useEffect } from 'react'

import styles from './Toast.module.css'

export type ToastTone = 'success' | 'info' | 'error'

interface ToastProps {
  message: string
  tone?: ToastTone
  onClose: () => void
  /** 自动关闭延时（毫秒） */
  duration?: number
}

export function Toast({ message, tone = 'success', onClose, duration = 2400 }: ToastProps) {
  useEffect(() => {
    const timer = window.setTimeout(onClose, duration)
    return () => window.clearTimeout(timer)
  }, [duration, message, onClose])

  const toneClass = tone === 'error' ? styles.error : tone === 'info' ? styles.info : styles.success

  return (
    <div className={`${styles.toast} ${toneClass}`} role="status" aria-live="polite">
      {message}
    </div>
  )
}
