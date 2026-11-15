import { useState, type FormEvent } from 'react'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'operator'
  text: string
  recovered?: boolean
}

interface ConversationPanelProps {
  messages: ChatMessage[]
  isPending: boolean
  errorMessage?: string
  onSend: (message: string) => void
}

export function ConversationPanel({ messages, isPending, errorMessage, onSend }: ConversationPanelProps) {
  const [message, setMessage] = useState('')

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const text = message.trim()
    if (!text || isPending) return
    onSend(text)
    setMessage('')
  }

  return (
    <section className="conversation-panel" aria-labelledby="conversation-title">
      <div className="section-heading">
        <div>
          <p className="section-label">售后对话</p>
          <h2 id="conversation-title">告诉我需要处理什么</h2>
        </div>
        <span className="connection-dot">服务端已连接</span>
      </div>
      <div className="message-list" aria-live="polite" aria-relevant="additions">
        {messages.length === 0 ? (
          <div className="message-empty">
            <strong>可以从订单查询开始</strong>
            <p>例如：“查看订单 #W123”或“取消订单 #W123，因为下错单了”。</p>
          </div>
        ) : (
          messages.map((item) => (
            <article className={`message message-${item.role}`} key={item.id}>
              <span>{item.role === 'user' ? '你' : item.role === 'operator' ? '人工客服' : '智能客服'}</span>
              <p>{item.text}</p>
              {item.recovered ? <small>由服务端任务状态恢复</small> : null}
            </article>
          ))
        )}
        {isPending ? <div className="typing" role="status">正在处理并核对服务端状态…</div> : null}
      </div>
      {errorMessage ? <p className="inline-error" role="alert">{errorMessage}</p> : null}
      <form className="composer" onSubmit={submit}>
        <label className="sr-only" htmlFor="support-message">输入售后问题</label>
        <textarea
          id="support-message"
          rows={3}
          maxLength={2000}
          placeholder="描述问题，订单写操作会先展示具体方案…"
          value={message}
          onChange={(event) => setMessage(event.target.value)}
        />
        <button className="button button-primary" type="submit" disabled={isPending || !message.trim()}>
          发送消息
        </button>
      </form>
    </section>
  )
}
