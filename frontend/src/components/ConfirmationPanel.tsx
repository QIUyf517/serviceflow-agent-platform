import type { ExecutionResult, PendingConfirmation } from '../api/types'
import { StateNotice } from './StateNotice'
const ORDER_STATUS: Record<string, string> = { pending: '待处理', processed: '已处理', delivered: '已送达', cancelled: '已取消', 'return requested': '已申请退货' }
function orderStatusLabel(status: string): string { return ORDER_STATUS[status] ?? '状态已更新' }

interface ConfirmationPanelProps {
  request: PendingConfirmation | null
  result: ExecutionResult | null
  isPending: boolean
  failureReason?: string | null
  onDecision: (decision: 'confirm' | 'reject') => void
}

function actionLabel(action: PendingConfirmation['action_type']): string {
  if (action === 'cancel') return '取消订单'
  if (action === 'return') return '提交退货申请'
  return '修改收货地址'
}

function valueLabel(value: unknown): string {
  if (value === 'ordered by mistake') return '下错单'
  if (value === 'no longer needed') return '不再需要'
  if (Array.isArray(value)) return value.join('、')
  if (value && typeof value === 'object') {
    const address = value as Record<string, unknown>
    const addressParts = ['country', 'state', 'city', 'address1', 'address2']
      .map((key) => address[key])
      .filter((part) => typeof part === 'string' && part.trim())
    if (addressParts.length) return addressParts.join(' ')
    return JSON.stringify(value)
  }
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
        {result.action_type === 'modify_address'
          ? `${result.order_id}：收货地址已修改`
          : `${result.order_id}：${orderStatusLabel(result.before_status)} → ${orderStatusLabel(result.after_status)}`}
        {result.idempotent_replay ? '（重复请求复用了原结果）' : ''}
      </StateNotice>
    )
  }

  if (failureReason) {
    return (
      <StateNotice kind="error" title="操作没有执行">
        订单状态以服务端最新结果为准，可调整诉求或转人工处理。
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
          <dt>操作</dt>
          <dd>{actionLabel(request.action_type)}</dd>
        </div>
        <div>
          <dt>订单号</dt>
          <dd>{request.order_id}</dd>
        </div>
        {Object.entries(request.proposed_parameters).map(([key, value]) => (
          <div key={key}>
            <dt>{key === 'reason' ? '原因' : key === 'item_quantities' ? '商品项与数量' : key === 'payment_method_id' ? '退款途径' : key === 'address' ? '新收货地址' : '操作参数'}</dt>
            <dd>{valueLabel(value)}</dd>
          </div>
        ))}
      </dl>
      <p className="confirmation-note">请核对以上内容。确认后才会处理；处理前会再次检查订单状态。</p>
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
