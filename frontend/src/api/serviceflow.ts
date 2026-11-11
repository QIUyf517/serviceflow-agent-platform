import { apiClient } from './client'
import type {
  ConversationResponse,
  IdentityInput,
  Order,
  TaskProgress,
  Ticket,
  TicketCreateInput,
} from './types'

const API = '/api/v1'

export const serviceflowApi = {
  createSession: () =>
    apiClient.request<{ session_id: string }>(`${API}/sessions`, {
      method: 'POST',
      requiresSession: false,
    }),

  verifyIdentity: (sessionId: string, identity: IdentityInput) =>
    apiClient.request<{ user_id: string }>(`${API}/sessions/${encodeURIComponent(sessionId)}/verify`, {
      method: 'POST',
      body: identity,
      requiresSession: false,
    }),

  listOrders: () => apiClient.request<Order[]>(`${API}/orders`),

  getOrder: (orderId: string) =>
    apiClient.request<Order>(`${API}/orders/${encodeURIComponent(orderId)}`),

  chat: (message: string, requestId?: string) =>
    apiClient.request<ConversationResponse>(`${API}/multi-agent/chat`, {
      method: 'POST',
      body: {
        message,
        ...(requestId ? { request_id: requestId } : {}),
      },
    }),

  currentTask: () => apiClient.request<TaskProgress>(`${API}/multi-agent/tasks/current`),

  createTicket: (input: TicketCreateInput, idempotencyKey: string) =>
    apiClient.request<Ticket>(`${API}/tickets`, {
      method: 'POST',
      body: input,
      idempotencyKey,
    }),
}
