import type { ExecutionResult } from './types'

export type TicketStatus =
  | 'open'
  | 'assigned'
  | 'in_progress'
  | 'waiting_customer'
  | 'resolved'
  | 'closed'
  | 'cancelled'

export type TicketCategory =
  | 'unsupported_request'
  | 'high_risk'
  | 'rule_conflict'
  | 'execution_failed'
  | 'clarification_exhausted'
  | 'customer_requested_human'

export type CloseReason =
  | 'resolved_by_agent'
  | 'resolved_by_operator'
  | 'customer_unresponsive'
  | 'duplicate'
  | 'rejected'
  | 'out_of_scope'

export interface TicketRecord {
  id: string
  ticket_no: string
  session_id: string
  thread_id: string | null
  user_id: string | null
  order_id: string | null
  request_id: string | null
  category: TicketCategory
  severity: string
  priority: number
  status: TicketStatus
  reason_code: string
  summary: string
  requested_action: Record<string, unknown>
  agent_state_digest: string
  assignee: string | null
  created_at: number
  updated_at: number
  closed_at: number | null
  close_reason: CloseReason | null
  idempotent_replay?: boolean
}

export interface TicketListResponse {
  items: TicketRecord[]
  total: number
  offset: number
  limit: number
}

export interface TicketRequestProjection {
  request_id: string
  action: 'cancel' | 'return'
  order_id: string
  status: string
  proposal_id: string
  proposed_parameters: Record<string, unknown>
  confirmation_expires_at: number
  failure_reason: string | null
}

export interface TicketConversationMessage {
  role: 'user' | 'assistant' | 'system' | 'operator'
  content: string
  sequence: number
  created_at: number
}

export interface RelatedTicket {
  id: string
  ticket_no: string
  order_id: string | null
  status: TicketStatus
  created_at: number
}

export interface TicketDetail extends TicketRecord {
  order?: { order_id: string; status: string; item_count: number } | null
  thread: {
    thread_id: string
    kind: 'order' | 'general'
    order_id: string | null
    status: string
  } | null
  related_tickets: {
    same_order: RelatedTicket[]
    other_orders: { total: number; items: RelatedTicket[] }
  }
  session: {
    session_id: string
    identity_verified: boolean
  }
  request: TicketRequestProjection | null
  conversation: TicketConversationMessage[]
  audit_summary: {
    event_count: number
    event_types: Record<string, number>
    last_event_at: number | null
  }
}

export interface TicketAuditEvent {
  id: string
  event_type: string
  session_id: string
  ticket_id: string | null
  request_id: string | null
  order_id: string | null
  actor: 'user' | 'agent' | 'operator' | 'system'
  payload: Record<string, unknown>
  created_at: number
}

export interface ApprovalRecord {
  id: string
  ticket_id: string
  request_id: string | null
  action: string
  proposed_params: Record<string, unknown>
  status: 'pending' | 'approved' | 'rejected' | 'expired'
  operator_id: string | null
  decision_reason: string | null
  created_at: number
  decided_at: number | null
  expires_at: number
}

export interface TicketFilters {
  status?: TicketStatus
  category?: TicketCategory
  assignee?: string
  createdFrom?: number
  createdTo?: number
  offset: number
  limit: number
}

export type OperatorExecutionResult = ExecutionResult
