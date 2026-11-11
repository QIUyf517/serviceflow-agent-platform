export interface IdentityInput {
  email?: string
  first_name?: string
  last_name?: string
  zip_code?: string
}

export interface OrderItem {
  item_id: string
  product_id: string
  name?: string
  options?: Record<string, string>
  price: number
}

export interface Fulfillment {
  item_ids: string[]
  tracking_id: string[]
}

export interface Order {
  order_id: string
  status: string
  items: OrderItem[]
  fulfillments?: Fulfillment[]
  payment_history?: Array<Record<string, unknown>>
  [key: string]: unknown
}

export interface TaskPlanItem {
  task_id: string
  intent: string
  target_agent: string
  required_inputs: string[]
  dependencies: string[]
  status: 'pending' | 'ready' | 'blocked' | 'completed' | 'failed'
}

export interface TraceEvent {
  node?: string | null
  status?: string | null
  code?: string | null
  elapsed_ms?: number | null
  trace_id?: string | null
  [key: string]: unknown
}

export interface ToolResult {
  tool?: string | null
  status?: string | null
  code?: string | null
  elapsed_ms?: number | null
  [key: string]: unknown
}

export interface TraceMetrics {
  elapsed_ms: number
  node_count: number
  tool_calls: number
  nodes?: Array<string | null>
  node_timings_ms?: Array<{
    node?: string | null
    elapsed_ms?: number | null
    result?: string | null
    error_code?: string | null
  }>
  provider: string
  model: string | null
  run_config?: { temperature?: number | null; seed?: number | null }
  token_usage: Record<string, number> | null
}

export interface PendingConfirmation {
  request_id: string
  idempotency_key: string
  task_id: string
  proposal_id: string
  proposal_version: number
  order_id: string
  action_type: 'cancel' | 'return'
  proposed_parameters: Record<string, unknown>
  summary: string
  status:
    | 'pending_confirmation'
    | 'confirmed'
    | 'executing'
    | 'rejected'
    | 'expired'
    | 'superseded'
    | 'succeeded'
    | 'failed'
  confirmation_expires_at: number
  confirmation_text?: string | null
}

export interface ExecutionResult {
  request_id: string
  proposal_id: string
  confirmation_id: string
  status: 'succeeded'
  action_type: 'cancel' | 'return'
  order_id: string
  before_status: string
  after_status: string
  row_version: number
  idempotent_replay: boolean
}

export interface ResolutionProposal {
  proposal_id: string
  task_id: string
  action_type: string
  order_id: string | null
  proposed_parameters: Record<string, unknown>
  explanation: string
  status: string
  validated: boolean
}

export interface EligibilityResult {
  status: 'eligible' | 'ineligible' | 'unknown'
  validated: boolean
  rule_code: string | null
  checked_order_status: string | null
  explanation: string
}

export interface Ticket {
  id: string
  ticket_no: string
  status: string
  message?: string
  [key: string]: unknown
}

export interface ConversationResponse {
  trace_id: string | null
  task_status: string
  request_id: string | null
  pending_confirmation: PendingConfirmation | null
  resolution_proposal: ResolutionProposal | null
  eligibility_result: EligibilityResult | null
  execution_result: ExecutionResult | null
  failure_reason: string | null
  task_plan: TaskPlanItem[]
  ticket: Ticket | null
  trace?: TraceEvent[]
  tool_results?: ToolResult[]
  metrics?: TraceMetrics
  final_response: string
}

export interface TaskProgress {
  thread_id: string
  task_status: string
  current_task: string | null
  task_plan: TaskPlanItem[]
  order_context: { order_id?: string; status?: string } | null
  policy_context: Array<Record<string, unknown>>
  resolution_proposal: ResolutionProposal | null
  eligibility_result: EligibilityResult | null
  pending_confirmation: PendingConfirmation | null
  execution_result: ExecutionResult | null
  trace?: TraceEvent[]
  final_response: string
}

export interface TicketCreateInput {
  category: 'customer_requested_human'
  severity: string
  priority: number
  reason_code: string
  summary: string
  requested_action: Record<string, unknown>
  order_id?: string
  request_id?: string
}
