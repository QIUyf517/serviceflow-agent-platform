import { useState, type FormEvent } from 'react'

import type {
  ApprovalRecord,
  CloseReason,
  OperatorExecutionResult,
  TicketAuditEvent,
  TicketDetail,
  TicketStatus,
} from '../../api/adminTypes'
import { redactDisplayText, safeJson } from '../../utils/safeDisplay'
import { StateNotice } from '../StateNotice'
import {
  allowedTransitions,
  CATEGORY_LABELS,
  CLOSE_REASON_LABELS,
  CLOSE_REASONS,
  formatTimestamp,
  STATUS_LABELS,
} from './presentation'

interface TicketCaseFileProps {
  detail: TicketDetail | undefined
  audit: TicketAuditEvent[] | undefined
  isLoading: boolean
  isMutating: boolean
  errorMessage?: string
  actionError?: string
  approval: ApprovalRecord | null
  executionResult: OperatorExecutionResult | null
  onAssign: (assignee: string) => void
  onStatus: (status: TicketStatus, closeReason?: CloseReason) => void
  onCreateApproval: () => void
  onDecideApproval: (decision: 'approved' | 'rejected', reason: string) => void
  onExecute: () => void
}

function IdRow({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value || '—'}</dd>
    </div>
  )
}

export function TicketCaseFile({
  detail,
  audit,
  isLoading,
  isMutating,
  errorMessage,
  actionError,
  approval,
  executionResult,
  onAssign,
  onStatus,
  onCreateApproval,
  onDecideApproval,
  onExecute,
}: TicketCaseFileProps) {
  const [assignee, setAssignee] = useState(detail?.assignee ?? '')
  const transitions = detail ? allowedTransitions(detail.status) : []
  const [nextStatus, setNextStatus] = useState<TicketStatus | ''>(transitions[0] ?? '')
  const [closeReason, setCloseReason] = useState<CloseReason | ''>('')
  const [statusError, setStatusError] = useState<string>()
  const [decisionReason, setDecisionReason] = useState('')

  if (isLoading) return <StateNotice kind="loading" title="正在打开案件卷宗" />
  if (errorMessage) return <StateNotice kind="error" title="工单详情加载失败">{errorMessage}</StateNotice>
  if (!detail) {
    return (
      <section className="case-file-empty">
        <p className="section-label">案件卷宗</p>
        <h2>选择一张工单</h2>
        <p>这里会显示脱敏会话、关联请求、审计记录和允许的操作。</p>
      </section>
    )
  }

  const terminalTarget = nextStatus === 'closed' || nextStatus === 'cancelled'
  const visibleConversation = detail.conversation.filter((message) => message.role !== 'system')

  function submitAssignment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (assignee.trim()) onAssign(assignee.trim())
  }

  function submitStatus(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!nextStatus) return
    if (terminalTarget && !closeReason) {
      setStatusError('关闭或取消工单必须选择合法 close_reason。')
      return
    }
    setStatusError(undefined)
    onStatus(nextStatus, terminalTarget ? closeReason || undefined : undefined)
  }

  return (
    <article className="case-file" aria-labelledby="case-file-title">
      <header className="case-file-header">
        <div>
          <p className="section-label">案件卷宗</p>
          <h2 id="case-file-title">{detail.ticket_no}</h2>
        </div>
        <span className={`admin-tag tag-status-${detail.status}`}>{STATUS_LABELS[detail.status]}</span>
      </header>

      <section className="case-section" aria-labelledby="case-summary-title">
        <h3 id="case-summary-title">脱敏摘要</h3>
        <p className="case-summary">{redactDisplayText(detail.summary)}</p>
        <dl className="case-ids">
          <IdRow label="ticket_id" value={detail.id} />
          <IdRow label="session_id" value={detail.session.session_id} />
          <IdRow label="request_id" value={detail.request_id} />
          <IdRow label="order_id" value={detail.order_id} />
          <IdRow label="assignee" value={detail.assignee} />
          <IdRow label="category" value={CATEGORY_LABELS[detail.category]} />
        </dl>
        <details className="safe-object">
          <summary>查看脱敏请求参数</summary>
          <pre>{safeJson(detail.requested_action)}</pre>
        </details>
      </section>

      <section className="case-section" aria-labelledby="conversation-title-admin">
        <div className="case-section-title">
          <h3 id="conversation-title-admin">脱敏会话</h3>
          <span>{visibleConversation.length} 条</span>
        </div>
        {visibleConversation.length ? (
          <ol className="admin-conversation">
            {visibleConversation.map((message) => (
              <li key={message.sequence}>
                <div><strong>{message.role}</strong><time>{formatTimestamp(message.created_at)}</time></div>
                <p>{redactDisplayText(message.content)}</p>
              </li>
            ))}
          </ol>
        ) : <p className="empty-copy">没有可显示的客户或客服会话。系统消息和完整 Prompt 不在此页面展示。</p>}
      </section>

      <section className="case-section" aria-labelledby="audit-title">
        <div className="case-section-title">
          <h3 id="audit-title">审计时间线</h3>
          <span>{audit?.length ?? detail.audit_summary.event_count} 个事件</span>
        </div>
        {audit?.length ? (
          <ol className="audit-timeline">
            {audit.map((event) => (
              <li key={event.id}>
                <span className="audit-marker" aria-hidden="true" />
                <div>
                  <strong>{event.event_type}</strong>
                  <small>{event.actor} · {formatTimestamp(event.created_at)}</small>
                  <pre>{safeJson(event.payload)}</pre>
                </div>
              </li>
            ))}
          </ol>
        ) : <p className="empty-copy">没有审计事件。</p>}
      </section>

      <section className="case-section case-actions" aria-labelledby="case-actions-title">
        <h3 id="case-actions-title">操作员动作</h3>
        <p className="boundary-note">审批是内部治理决定，不能替代客户对具体方案的明确确认。</p>

        <form onSubmit={submitAssignment}>
          <label>
            分配客服
            <input value={assignee} onChange={(event) => setAssignee(event.target.value)} maxLength={128} />
          </label>
          <button className="button button-secondary" type="submit" disabled={isMutating || !assignee.trim()}>保存分配</button>
        </form>

        {transitions.length ? (
          <form onSubmit={submitStatus}>
            <label>
              合法状态流转
              <select value={nextStatus} onChange={(event) => {
                setNextStatus(event.target.value as TicketStatus)
                setCloseReason('')
                setStatusError(undefined)
              }}>
                {transitions.map((status) => <option key={status} value={status}>{STATUS_LABELS[status]}</option>)}
              </select>
            </label>
            {terminalTarget ? (
              <label>
                close_reason
                <select value={closeReason} onChange={(event) => setCloseReason(event.target.value as CloseReason | '')}>
                  <option value="">请选择关闭原因</option>
                  {CLOSE_REASONS.map((reason) => <option key={reason} value={reason}>{CLOSE_REASON_LABELS[reason]}</option>)}
                </select>
              </label>
            ) : null}
            <button className="button button-secondary" type="submit" disabled={isMutating || !nextStatus}>更新状态</button>
            {statusError ? <p className="inline-error" role="alert">{statusError}</p> : null}
          </form>
        ) : <p className="empty-copy">该工单已进入终态，不能继续流转。</p>}

        <div className="approval-block">
          <div>
            <strong>内部审批</strong>
            <p>{detail.request ? `为 ${detail.request.action} 请求创建 execute_${detail.request.action} 审批。` : '该工单没有关联执行请求，不能创建执行审批。'}</p>
          </div>
          <button className="button button-secondary" type="button" disabled={isMutating || !detail.request} onClick={onCreateApproval}>创建审批</button>
          {approval ? (
            <div className="approval-record">
              <dl className="case-ids">
                <IdRow label="approval_id" value={approval.id} />
                <IdRow label="action" value={approval.action} />
                <IdRow label="status" value={approval.status} />
                <IdRow label="expires_at" value={formatTimestamp(approval.expires_at)} />
              </dl>
              {approval.status === 'pending' ? (
                <div className="approval-decision">
                  <label>
                    决定理由
                    <textarea value={decisionReason} onChange={(event) => setDecisionReason(event.target.value)} rows={2} />
                  </label>
                  <div>
                    <button className="button button-primary" type="button" disabled={isMutating || !decisionReason.trim()} onClick={() => onDecideApproval('approved', decisionReason.trim())}>批准审批</button>
                    <button className="button button-danger" type="button" disabled={isMutating || !decisionReason.trim()} onClick={() => onDecideApproval('rejected', decisionReason.trim())}>拒绝审批</button>
                  </div>
                </div>
              ) : <p>决定：{approval.decision_reason}</p>}
            </div>
          ) : null}
        </div>

        <div className="execute-block">
          <div>
            <strong>人工代触发执行</strong>
            <p>这里只触发原 ExecutionService。没有客户确认时，服务端必须返回 confirmation_required。</p>
          </div>
          <button className="button button-danger" type="button" disabled={isMutating || !detail.request} onClick={onExecute}>请求服务端代执行</button>
          {executionResult ? (
            <StateNotice kind="success" title="服务端执行成功">
              {executionResult.order_id}：{executionResult.before_status} → {executionResult.after_status}
              {executionResult.idempotent_replay ? '（幂等复用原结果）' : ''}
            </StateNotice>
          ) : null}
        </div>

        {actionError ? <StateNotice kind="error" title="操作未完成">{actionError}</StateNotice> : null}
      </section>
    </article>
  )
}
