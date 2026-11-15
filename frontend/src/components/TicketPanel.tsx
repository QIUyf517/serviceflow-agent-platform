import type { Ticket } from '../api/types'
import { StateNotice } from './StateNotice'

const STATUS_LABELS: Record<string, string> = {
  open: '待分配', assigned: '已分配', in_progress: '处理中', waiting_customer: '等待顾客回复',
  resolved: '已解决', closed: '已关闭', cancelled: '已取消',
}

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
          人工处理进度：{STATUS_LABELS[ticket.status] ?? '状态待更新'}。继续发送的消息会直接进入人工工单，人工回复会显示在左侧对话中。
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
