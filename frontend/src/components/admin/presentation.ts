import type { CloseReason, TicketCategory, TicketStatus } from '../../api/adminTypes'

export const TICKET_STATUSES: TicketStatus[] = [
  'open',
  'assigned',
  'in_progress',
  'waiting_customer',
  'resolved',
  'closed',
  'cancelled',
]

export const TICKET_CATEGORIES: TicketCategory[] = [
  'unsupported_request',
  'high_risk',
  'rule_conflict',
  'execution_failed',
  'clarification_exhausted',
  'customer_requested_human',
]

export const CLOSE_REASONS: CloseReason[] = [
  'resolved_by_agent',
  'resolved_by_operator',
  'customer_unresponsive',
  'duplicate',
  'rejected',
  'out_of_scope',
]

export const STATUS_LABELS: Record<TicketStatus, string> = {
  open: '待分配',
  assigned: '已分配',
  in_progress: '处理中',
  waiting_customer: '等待客户',
  resolved: '已解决',
  closed: '已关闭',
  cancelled: '已取消',
}

export const CATEGORY_LABELS: Record<TicketCategory, string> = {
  unsupported_request: '不支持的请求',
  high_risk: '高风险',
  rule_conflict: '规则冲突',
  execution_failed: '执行失败',
  clarification_exhausted: '澄清次数耗尽',
  customer_requested_human: '客户要求人工',
}

export const CLOSE_REASON_LABELS: Record<CloseReason, string> = {
  resolved_by_agent: '由 Agent 解决',
  resolved_by_operator: '由客服解决',
  customer_unresponsive: '客户未响应',
  duplicate: '重复工单',
  rejected: '请求被拒绝',
  out_of_scope: '超出处理范围',
}

const TRANSITIONS: Record<TicketStatus, TicketStatus[]> = {
  open: ['assigned', 'cancelled'],
  assigned: ['in_progress', 'cancelled'],
  in_progress: ['waiting_customer', 'resolved', 'cancelled'],
  waiting_customer: ['in_progress', 'resolved', 'cancelled'],
  resolved: ['in_progress', 'closed'],
  closed: [],
  cancelled: [],
}

export function allowedTransitions(status: TicketStatus): TicketStatus[] {
  return TRANSITIONS[status]
}

export function formatTimestamp(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value * 1_000))
}
