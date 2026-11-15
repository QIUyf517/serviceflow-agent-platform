export interface IdentityInput {
  email?: string
  first_name?: string
  last_name?: string
  zip_code?: string
}

export interface PaymentMethod {
  id?: string
  source: string
  brand?: string
  last_four?: string
  balance?: number
}

export interface UserProfile {
  user_id: string
  name: { first_name: string; last_name: string }
  address: Record<string, string>
  email: string
  payment_methods: Record<string, PaymentMethod>
  orders: string[]
}

export interface ProductSummary {
  product_id: string
  name: string
  min_price: number
  max_price: number
  available_variants: number
  total_variants: number
  option_names: string[]
}

export interface ProductVariant {
  item_id: string
  options: Record<string, string>
  available: boolean
  price: number
}

export interface Product {
  product_id: string
  name: string
  variants: Record<string, ProductVariant>
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

export interface CheckoutInput {
  items: Array<{ item_id: string; quantity: number }>
  payment_method_id: string
}

export interface CheckoutResult {
  order: Order
  idempotent_replay: boolean
  created_at: number
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
  order_id?: string | null
  thread_id?: string | null
  [key: string]: unknown
}

export interface SupportThread {
  thread_id: string
  kind: 'order' | 'general'
  order_id: string | null
  status: 'open' | 'closed'
  created_at: number
  updated_at: number
}

export interface ThreadMessage {
  sequence: number
  role: 'user' | 'assistant' | 'operator'
  content: string
  thread_id: string | null
  created_at: number
}

export interface ConversationResponse {
  trace_id: string | null
  task_status: string
  thread_id?: string
  thread_order_id?: string | null
  thread_kind?: 'order' | 'general' | 'session'
  consultation_route?:
    | 'content_blocked'
    | 'faq_policy'
    | 'product'
    | 'order_logistics'
    | 'after_sales'
    | 'unclear'
    | 'out_of_scope'
    | 'evidence_insufficient'
    | 'data_unavailable'
    | 'human_handoff'
  safety?: {
    allowed: boolean
    category: string
    reason_code: string | null
  }
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
  thread_order_id?: string | null
  thread_kind?: 'order' | 'general' | 'session'
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
  thread_id?: string
}
