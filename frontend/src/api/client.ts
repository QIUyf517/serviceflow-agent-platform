import { ApiError, parseApiError } from './errors'
import { readSessionId } from './sessionStore'

export interface RequestOptions extends Omit<RequestInit, 'body' | 'headers'> {
  body?: unknown
  headers?: Record<string, string>
  requiresSession?: boolean
  idempotencyKey?: string
}

export class ApiClient {
  constructor(
    private readonly baseUrl = '',
    private readonly sessionProvider: () => string | null = readSessionId,
    private readonly fetcher?: typeof fetch,
  ) {}

  async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const { body, headers: customHeaders, requiresSession = true, idempotencyKey, ...init } =
      options
    const headers = new Headers(customHeaders)
    headers.set('Accept', 'application/json')

    if (body !== undefined) {
      headers.set('Content-Type', 'application/json')
    }

    if (requiresSession) {
      const sessionId = this.sessionProvider()
      if (!sessionId) {
        throw new ApiError(403, 'session_required')
      }
      headers.set('X-Session-Id', sessionId)
    }

    if (idempotencyKey) {
      headers.set('Idempotency-Key', idempotencyKey)
    }

    let response: Response
    try {
      const fetcher = this.fetcher ?? globalThis.fetch
      response = await fetcher(`${this.baseUrl}${path}`, {
        ...init,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      })
    } catch (error) {
      throw new ApiError(0, 'network_unavailable', error)
    }

    if (!response.ok) {
      throw await parseApiError(response)
    }

    if (response.status === 204) {
      return undefined as T
    }
    return (await response.json()) as T
  }
}

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? ''

export const apiClient = new ApiClient(apiBaseUrl)
