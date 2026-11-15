import { type ReactNode, useEffect, useRef } from 'react'

interface SupportDialogProps {
  open: boolean
  orderId: string | null
  onClose: () => void
  children: ReactNode
}

export function SupportDialog({ open, orderId, onClose, children }: SupportDialogProps) {
  const closeButton = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return undefined
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    closeButton.current?.focus()
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      window.removeEventListener('keydown', onKeyDown)
    }
  }, [onClose, open])

  if (!open) return null

  return (
    <div className="support-dialog-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose()
    }}>
      <section
        className="support-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="support-dialog-title"
      >
        <header>
          <div>
            <span>ServiceFlow 智能客服</span>
            <h2 id="support-dialog-title">
              {orderId ? `正在咨询订单 ${orderId}` : '售前与售后咨询'}
            </h2>
          </div>
          <button ref={closeButton} className="dialog-close" type="button" onClick={onClose}>
            关闭
          </button>
        </header>
        <p className="support-context-note">
          {orderId
            ? '发送消息时会明确附带这笔订单号；服务端仍会重新核验订单归属。'
            : '可以咨询商品、政策或订单问题。涉及订单时仍需核验身份。'}
        </p>
        <div className="support-dialog-body">{children}</div>
      </section>
    </div>
  )
}
