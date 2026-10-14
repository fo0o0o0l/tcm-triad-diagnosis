import type { ReactNode } from 'react'

interface PageShellProps {
  /** 页面主标题 */
  title: string
  /** 标题下方说明（可选） */
  description?: string
  children?: ReactNode
}

/**
 * 页面骨架：统一标题区与内容区。
 * P1~P10 页面复用，避免各页重复布局代码。
 */
export function PageShell({ title, description, children }: PageShellProps) {
  return (
    <main className="page-shell">
      <header>
        <h1 className="page-shell__title">{title}</h1>
        {description ? <p className="page-shell__desc">{description}</p> : null}
      </header>
      <section className="page-shell__body">{children}</section>
    </main>
  )
}
