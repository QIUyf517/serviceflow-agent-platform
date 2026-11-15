import type {
  ApprovalRecord,
  CloseReason,
  OperatorExecutionResult,
  TicketAuditEvent,
  TicketDetail,
  TicketFilters,
  TicketListResponse,
  TicketRecord,
  TicketStatus,
} from './adminTypes'
import { apiClient, type RequestOptions } from './client'
import { ApiError } from './errors'
import { readOperatorToken } from './operatorStore'

const API = '/api/v1'

async function operatorRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const token = readOperatorToken()
  if (!token) throw new ApiError(401, 'operator_token_required')
  return apiClient.request<T>(path, {
    ...options,
    requiresSession: false,
    headers: {
      ...options.headers,
      'X-Operator-Token': token,
    },
  })
}

function ticketPath(ticketId: string, suffix = ''): string {
  return `${API}/tickets/${encodeURIComponent(ticketId)}${suffix}`
}

export const operatorApi = {
  listTickets: (filters: TicketFilters) => {
    const query = new URLSearchParams({
      offset: String(filters.offset),
      limit: String(filters.limit),
    })
    if (filters.status) query.set('status', filters.status)
    if (filters.category) query.set('category', filters.category)
    if (filters.assignee) query.set('assignee', filters.assignee)
    if (filters.createdFrom !== undefined) query.set('created_from', String(filters.createdFrom))
    if (filters.createdTo !== undefined) query.set('created_to', String(filters.createdTo))
    return operatorRequest<TicketListResponse>(`${API}/tickets?${query.toString()}`)
  },

  getTicket: (ticketId: string) => operatorRequest<TicketDetail>(ticketPath(ticketId)),
  replyTicket: (ticketId: string, content: string) =>
    operatorRequest<{ sequence: number; content: string; created_at: number }>(ticketPath(ticketId, '/reply'), { method: 'POST', body: { content } }),

  getAudit: (ticketId: string) =>
    operatorRequest<{ ticket_id: string; events: TicketAuditEvent[] }>(
      ticketPath(ticketId, '/audit'),
    ),

  assignTicket: (ticketId: string, assignee: string) =>
    operatorRequest<TicketRecord>(ticketPath(ticketId, '/assign'), {
      method: 'POST',
      body: { assignee },
    }),

  changeStatus: (ticketId: string, status: TicketStatus, closeReason?: CloseReason) =>
    operatorRequest<TicketRecord>(ticketPath(ticketId, '/status'), {
      method: 'POST',
      body: {
        status,
        ...(closeReason ? { close_reason: closeReason } : {}),
      },
    }),

  createApproval: (
    ticketId: string,
    requestId: string | null,
    action: string,
    proposedParams: Record<string, unknown>,
  ) =>
    operatorRequest<ApprovalRecord>(ticketPath(ticketId, '/approvals'), {
      method: 'POST',
      body: {
        ...(requestId ? { request_id: requestId } : {}),
        action,
        proposed_params: proposedParams,
      },
    }),

  decideApproval: (
    ticketId: string,
    approvalId: string,
    decision: 'approved' | 'rejected',
    reason: string,
  ) =>
    operatorRequest<ApprovalRecord>(
      ticketPath(ticketId, `/approvals/${encodeURIComponent(approvalId)}/decision`),
      {
        method: 'POST',
        body: { decision, reason },
      },
    ),

  executeTicket: (ticketId: string) =>
    operatorRequest<OperatorExecutionResult>(ticketPath(ticketId, '/execute'), {
      method: 'POST',
    }),
}
