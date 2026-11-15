import { apiClient } from './client'
import type {
  CheckoutInput,
  CheckoutResult,
  ConversationResponse,
  IdentityInput,
  Order,
  Product,
  ProductSummary,
  SupportThread,
  TaskProgress,
  ThreadMessage,
  Ticket,
  TicketCreateInput,
  UserProfile,
} from './types'

const API = '/api/v1'

function orderQuery(orderId?: string | null): string {
  return orderId ? `?order_id=${encodeURIComponent(orderId)}` : ''
}

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

  currentUser: () => apiClient.request<UserProfile>(`${API}/users/me`),

  listProducts: () => apiClient.request<ProductSummary[]>(`${API}/products`),

  getProduct: (productId: string) =>
    apiClient.request<Product>(`${API}/products/${encodeURIComponent(productId)}`),

  listOrders: () => apiClient.request<Order[]>(`${API}/orders`),

  checkout: (input: CheckoutInput, idempotencyKey: string) =>
    apiClient.request<CheckoutResult>(`${API}/orders`, {
      method: 'POST',
      body: input,
      idempotencyKey,
    }),

  getOrder: (orderId: string) =>
    apiClient.request<Order>(`${API}/orders/${encodeURIComponent(orderId)}`),

  chat: (message: string, requestId?: string, orderId?: string | null) =>
    apiClient.request<ConversationResponse>(`${API}/multi-agent/chat`, {
      method: 'POST',
      body: {
        message,
        ...(requestId ? { request_id: requestId } : {}),
        ...(orderId ? { order_id: orderId } : {}),
      },
    }),

  currentTask: (orderId?: string | null) =>
    apiClient.request<TaskProgress>(`${API}/multi-agent/tasks/current${orderQuery(orderId)}`),

  openSupportThread: (orderId?: string | null) =>
    apiClient.request<SupportThread>(`${API}/support/threads`, {
      method: 'POST',
      body: orderId ? { order_id: orderId } : {},
    }),

  customerConversation: (orderId?: string | null) =>
    apiClient.request<ThreadMessage[]>(`${API}/customer/conversation${orderQuery(orderId)}`),

  createTicket: (input: TicketCreateInput, idempotencyKey: string) =>
    apiClient.request<Ticket>(`${API}/tickets`, {
      method: 'POST',
      body: input,
      idempotencyKey,
    }),

  customerTickets: () => apiClient.request<Array<{ id: string; ticket_no: string; status: string; order_id: string | null; thread_id: string | null; thread_kind?: 'order' | 'general' }>>(`${API}/customer/tickets`),
  ticketUpdates: (ticketId: string) => apiClient.request<{ ticket_no: string; status: string; messages: Array<{ sequence: number; content: string; created_at: number }> }>(`${API}/customer/tickets/${encodeURIComponent(ticketId)}/updates`),

  replyToTicket: (ticketId: string, content: string, idempotencyKey: string) =>
    apiClient.request<{ sequence: number; content: string; created_at: number; status: string; idempotent_replay: boolean }>(
      `${API}/customer/tickets/${encodeURIComponent(ticketId)}/messages`,
      {
        method: 'POST',
        body: { content },
        idempotencyKey,
      },
    ),
}
