import { describe, expect, it, vi } from 'vitest'

import { developerApi } from './developer'

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('developer API', () => {
  it('uses the explicit customer session and keeps it out of the URL', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(json({
      trace_id: 'trace-1', events: [], elapsed_ms: 3, token_usage: null,
    }))
    vi.stubGlobal('fetch', fetchMock)

    await developerApi.trace('session-owner', 'trace/with space')

    const [url, init] = fetchMock.mock.calls[0] ?? []
    const requestUrl = typeof url === 'string' ? url : url instanceof URL ? url.href : url?.url ?? ''
    expect(requestUrl).toContain('/api/v1/traces/trace%2Fwith%20space')
    expect(requestUrl).not.toContain('session-owner')
    const headers = init?.headers as Headers
    expect(headers.get('X-Session-Id')).toBe('session-owner')
    expect(headers.has('X-Operator-Token')).toBe(false)
  })

  it('preserves the service trace_not_found error', async () => {
    vi.stubGlobal('fetch', vi.fn<typeof fetch>().mockResolvedValue(
      json({ error: { code: 'trace_not_found' } }, 404),
    ))

    await expect(developerApi.trace('session-other', 'trace-1')).rejects.toMatchObject({
      status: 404,
      code: 'trace_not_found',
    })
  })
})
