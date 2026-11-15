import type { FormEvent } from 'react'

import type {
  TicketCategory,
  TicketListResponse,
  TicketStatus,
} from '../../api/adminTypes'
import { StateNotice } from '../StateNotice'
import {
  CATEGORY_LABELS,
  formatTimestamp,
  STATUS_LABELS,
  TICKET_CATEGORIES,
  TICKET_STATUSES,
} from './presentation'

export interface TicketFilterDraft {
  status: '' | TicketStatus
  category: '' | TicketCategory
  assignee: string
  createdFrom: string
  createdTo: string
}

interface TicketLedgerProps {
  result: TicketListResponse | undefined
  selectedTicketId: string | null
  draft: TicketFilterDraft
  isLoading: boolean
  errorMessage?: string
  onDraftChange: (draft: TicketFilterDraft) => void
  onFilter: () => void
  onSelect: (ticketId: string) => void
  onPage: (direction: 'previous' | 'next') => void
}

function Tag({ kind, children }: { kind: string; children: string }) {
  return <span className={`admin-tag tag-${kind}`}>{children}</span>
}

export function TicketLedger({
  result,
  selectedTicketId,
  draft,
  isLoading,
  errorMessage,
  onDraftChange,
  onFilter,
  onSelect,
  onPage,
}: TicketLedgerProps) {
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    onFilter()
  }

  const hasPrevious = Boolean(result && result.offset > 0)
  const hasNext = Boolean(result && result.offset + result.items.length < result.total)

  return (
    <section className="ticket-ledger" aria-labelledby="ticket-ledger-title">
      <div className="section-heading">
        <div>
          <p className="section-label">派工账本</p>
          <h2 id="ticket-ledger-title">工单列表</h2>
        </div>
        {result ? <span>{result.total} 条</span> : null}
      </div>
      <form className="ticket-filters" onSubmit={submit}>
        <label>
          状态
          <select
            value={draft.status}
            onChange={(event) => onDraftChange({ ...draft, status: event.target.value as TicketFilterDraft['status'] })}
          >
            <option value="">全部</option>
            {TICKET_STATUSES.map((status) => <option key={status} value={status}>{STATUS_LABELS[status]}</option>)}
          </select>
        </label>
        <label>
          类别
          <select
            value={draft.category}
            onChange={(event) => onDraftChange({ ...draft, category: event.target.value as TicketFilterDraft['category'] })}
          >
            <option value="">全部</option>
            {TICKET_CATEGORIES.map((category) => <option key={category} value={category}>{CATEGORY_LABELS[category]}</option>)}
          </select>
        </label>
        <label>
          客服
          <input
            value={draft.assignee}
            onChange={(event) => onDraftChange({ ...draft, assignee: event.target.value })}
            placeholder="operator-demo"
          />
        </label>
        <label>
          创建时间从
          <input
            type="datetime-local"
            value={draft.createdFrom}
            onChange={(event) => onDraftChange({ ...draft, createdFrom: event.target.value })}
          />
        </label>
        <label>
          创建时间至
          <input
            type="datetime-local"
            value={draft.createdTo}
            onChange={(event) => onDraftChange({ ...draft, createdTo: event.target.value })}
          />
        </label>
        <button className="button button-secondary" type="submit">应用过滤</button>
      </form>
      {isLoading ? <StateNotice kind="loading" title="正在读取工单" /> : null}
      {errorMessage ? <StateNotice kind="error" title="工单列表加载失败">{errorMessage}</StateNotice> : null}
      {!isLoading && !errorMessage && result?.items.length === 0 ? (
        <StateNotice title="没有匹配的工单">调整过滤条件或等待新的人工接管请求。</StateNotice>
      ) : null}
      {result?.items.length ? (
        <div className="ticket-table-wrap">
          <table className="ticket-table">
            <thead>
              <tr><th>工单</th><th>订单</th><th>状态</th><th>级别</th><th>客服</th><th>创建时间</th></tr>
            </thead>
            <tbody>
              {result.items.map((ticket) => (
                <tr className={selectedTicketId === ticket.id ? 'is-selected' : ''} key={ticket.id}>
                  <td>
                    <button type="button" onClick={() => onSelect(ticket.id)}>
                      <strong>{ticket.ticket_no}</strong>
                      <small>{CATEGORY_LABELS[ticket.category]}</small>
                    </button>
                  </td>
                  <td>
                    <span className="order-reference">
                      {ticket.order_id ? `订单 ${ticket.order_id}` : '通用咨询'}
                    </span>
                  </td>
                  <td><Tag kind={`status-${ticket.status}`}>{STATUS_LABELS[ticket.status]}</Tag></td>
                  <td>
                    <span className="tag-stack">
                      <Tag kind={`priority-${ticket.priority}`}>{`P${ticket.priority}`}</Tag>
                      <Tag kind={`severity-${ticket.severity}`}>{ticket.severity}</Tag>
                    </span>
                  </td>
                  <td>{ticket.assignee ?? '未分配'}</td>
                  <td>{formatTimestamp(ticket.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
      {result && result.total > 0 ? (
        <nav className="pagination" aria-label="工单分页">
          <button className="button button-secondary" type="button" disabled={!hasPrevious} onClick={() => onPage('previous')}>上一页</button>
          <span>{result.offset + 1}–{Math.min(result.offset + result.limit, result.total)} / {result.total}</span>
          <button className="button button-secondary" type="button" disabled={!hasNext} onClick={() => onPage('next')}>下一页</button>
        </nav>
      ) : null}
    </section>
  )
}
