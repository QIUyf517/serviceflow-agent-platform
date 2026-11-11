import { beforeEach, describe, expect, it, vi } from 'vitest'

import { operatorApi } from './operator'
import { saveOperatorToken } from './operatorStore'

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('operator API', () => {
  beforeEach(() => {
    window.sessionStorage.clear()
    window.localStorage.clear()
  })

  it('blocks requests without an operator token before fetch', async () => {
    window.localStorage.setItem('serviceflow.session_id', 'customer-session')
    const fetchMock = vi.fn<typeof fetch>()
    vi.stubGlobal('fetch', fetchMock)

    await expect(operatorApi.listTickets({ offset: 0, limit: 10 })).rejects.toMatchObject({
      status: 401,
      code: 'operator_token_required',
    })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('uses only X-Operator-Token and encodes filters and pagination', async () => {
    saveOperatorToken('operator-demo-token')
    window.localStorage.setItem('serviceflow.session_id', 'customer-session')
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
      json({ items: [], total: 0, offset: 20, limit: 10 }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await operatorApi.listTickets({
      status: 'assigned',
      category: 'execution_failed',
      assignee: 'operator-1',
      createdFrom: 1_700_000_000,
      createdTo: 1_700_003_600,
      offset: 20,
      limit: 10,
    })

    const [url, init] = fetchMock.mock.calls[0] ?? []
    const requestUrl = typeof url === 'string' ? url : url instanceof URL ? url.href : url?.url ?? ''
    expect(requestUrl).toContain('status=assigned')
    expect(requestUrl).toContain('category=execution_failed')
    expect(requestUrl).toContain('assignee=operator-1')
    expect(requestUrl).toContain('created_from=1700000000')
    expect(requestUrl).toContain('created_to=1700003600')
    expect(requestUrl).toContain('offset=20')
    const headers = init?.headers as Headers
    expect(headers.get('X-Operator-Token')).toBe('operator-demo-token')
    expect(headers.has('X-Session-Id')).toBe(false)
  })
})
