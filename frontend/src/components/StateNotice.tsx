import type { ReactNode } from 'react'

interface StateNoticeProps {
  kind?: 'neutral' | 'loading' | 'warning' | 'error' | 'success'
  title: string
  children?: ReactNode
  action?: ReactNode
  role?: 'status' | 'alert'
}

export function StateNotice({
  kind = 'neutral',
  title,
  children,
  action,
  role = kind === 'error' ? 'alert' : 'status',
}: StateNoticeProps) {
  return (
    <section className={`state-notice state-notice-${kind}`} role={role} aria-live="polite">
      {kind === 'loading' ? <span className="spinner" aria-hidden="true" /> : null}
      <div>
        <strong>{title}</strong>
        {children ? <div className="state-notice-body">{children}</div> : null}
      </div>
      {action ? <div className="state-notice-action">{action}</div> : null}
    </section>
  )
}
