import { describe, expect, it, vi } from 'vitest'

import { ApiClient } from './client'
import { ApiError, parseApiError } from './errors'

describe('ApiClient', () => {
  it('sends session, JSON, and stable idempotency headers', async () => {
    const fetcher = vi.fn<typeof fetch>().mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify({ ticket_no: 'T-1' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      ),
    )
    const client = new ApiClient('/api', () => 'session-1', fetcher)

    await client.request('/v1/tickets', {
      method: 'POST',
      body: { summary: '需要人工协助' },
      idempotencyKey: 'ticket-logical-request-1',
    })
    await client.request('/v1/tickets', {
      method: 'POST',
      body: { summary: '需要人工协助' },
      idempotencyKey: 'ticket-logical-request-1',
    })

    expect(fetcher).toHaveBeenCalledTimes(2)
    for (const call of fetcher.mock.calls) {
      const headers = call[1]?.headers as Headers
      expect(headers.get('X-Session-Id')).toBe('session-1')
      expect(headers.get('Idempotency-Key')).toBe('ticket-logical-request-1')
      expect(headers.get('Content-Type')).toBe('application/json')
    }
  })

  it('does not send a session header when creating a session', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ session_id: 'new-session' }), { status: 200 }),
    )
    const client = new ApiClient('', () => null, fetcher)

    await client.request('/api/v1/sessions', { method: 'POST', requiresSession: false })

    const headers = fetcher.mock.calls[0]?.[1]?.headers as Headers
    expect(headers.has('X-Session-Id')).toBe(false)
  })

  it('blocks protected requests before fetch when no session exists', async () => {
    const fetcher = vi.fn<typeof fetch>()
    const client = new ApiClient('', () => null, fetcher)

    await expect(client.request('/api/v1/orders')).rejects.toMatchObject({
      status: 403,
      code: 'session_required',
    })
    expect(fetcher).not.toHaveBeenCalled()
  })
})

describe('parseApiError', () => {
  it('reads ServiceFlow business errors', async () => {
    const error = await parseApiError(
      new Response(JSON.stringify({ error: { code: 'identity_required' } }), {
        status: 403,
      }),
    )
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 403, code: 'identity_required' })
  })

  it('falls back safely for a non-JSON response', async () => {
    const error = await parseApiError(new Response('gateway failed', { status: 502 }))
    expect(error).toMatchObject({ status: 502, code: 'http_502' })
  })
})
