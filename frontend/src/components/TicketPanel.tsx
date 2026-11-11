import type { Ticket } from '../api/types'
import { StateNotice } from './StateNotice'

interface TicketPanelProps {
  ticket: Ticket | null
  isPending: boolean
  errorMessage?: string
  onCreate: () => void
}

export function TicketPanel({ ticket, isPending, errorMessage, onCreate }: TicketPanelProps) {
  return (
    <section className="ticket-panel" aria-labelledby="ticket-title">
      <div>
        <p className="section-label">需要更多帮助？</p>
        <h2 id="ticket-title">转人工处理</h2>
        <p>创建工单后进入人工队列，不代表问题已经处理完成。</p>
      </div>
      {ticket ? (
        <StateNotice kind="warning" title={`已创建工单 ${ticket.ticket_no}`}>
          等待人工处理。当前状态：{ticket.status}。
        </StateNotice>
      ) : (
        <button className="button button-secondary" type="button" disabled={isPending} onClick={onCreate}>
          {isPending ? '正在创建…' : '创建人工工单'}
        </button>
      )}
      {errorMessage ? <StateNotice kind="error" title="工单创建失败">{errorMessage}</StateNotice> : null}
    </section>
  )
}
