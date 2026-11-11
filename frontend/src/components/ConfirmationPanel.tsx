import type { ExecutionResult, PendingConfirmation } from '../api/types'
import { StateNotice } from './StateNotice'

interface ConfirmationPanelProps {
  request: PendingConfirmation | null
  result: ExecutionResult | null
  isPending: boolean
  failureReason?: string | null
  onDecision: (decision: 'confirm' | 'reject') => void
}

function actionLabel(action: PendingConfirmation['action_type']): string {
  return action === 'cancel' ? '取消订单' : '提交退货申请'
}

function valueLabel(value: unknown): string {
  if (Array.isArray(value)) return value.join('、')
  if (value && typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

export function ConfirmationPanel({
  request,
  result,
  isPending,
  failureReason,
  onDecision,
}: ConfirmationPanelProps) {
  if (result?.status === 'succeeded') {
    return (
      <StateNotice kind="success" title="服务端已执行成功">
        {result.order_id}：{result.before_status} → {result.after_status}
        {result.idempotent_replay ? '（重复请求复用了原结果）' : ''}
      </StateNotice>
    )
  }

  if (failureReason) {
    return (
      <StateNotice kind="error" title="操作没有执行">
        {failureReason}。订单状态以服务端最新结果为准，可调整诉求或转人工处理。
      </StateNotice>
    )
  }

  if (!request || request.status !== 'pending_confirmation') return null

  return (
    <section className="confirmation-panel" aria-labelledby="confirmation-title">
      <div className="confirmation-heading">
        <span aria-hidden="true">!</span>
        <div>
          <p className="section-label">需要你的明确确认</p>
          <h2 id="confirmation-title">核对即将执行的操作</h2>
        </div>
      </div>
      <dl className="action-summary">
        <div>
          <dt>action</dt>
          <dd>{request.action_type}（{actionLabel(request.action_type)}）</dd>
        </div>
        <div>
          <dt>order_id</dt>
          <dd>{request.order_id}</dd>
        </div>
        {Object.entries(request.proposed_parameters).map(([key, value]) => (
          <div key={key}>
            <dt>{key}</dt>
            <dd>{valueLabel(value)}</dd>
          </div>
        ))}
      </dl>
      <p className="confirmation-note">{request.summary}</p>
      <div className="confirmation-actions">
        <button
          className="button button-danger"
          type="button"
          disabled={isPending}
          onClick={() => onDecision('confirm')}
        >
          {isPending ? '正在提交…' : `确认${actionLabel(request.action_type)}`}
        </button>
        <button
          className="button button-secondary"
          type="button"
          disabled={isPending}
          onClick={() => onDecision('reject')}
        >
          拒绝方案
        </button>
      </div>
    </section>
  )
}
