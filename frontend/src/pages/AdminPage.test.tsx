import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { ApprovalRecord, TicketDetail, TicketRecord } from '../api/adminTypes'
import { App } from '../app/App'

const TICKET: TicketRecord = {
  id: 'ticket-1',
  ticket_no: 'TK-2026-0001',
  session_id: 'session-customer-1',
  user_id: 'user-1',
  order_id: '#W100',
  request_id: 'request-1',
  category: 'execution_failed',
  severity: 'high',
  priority: 3,
  status: 'open',
  reason_code: 'execution_failed',
  summary: '客户 customer@example.invalid 要求取消；地址：上海市测试路 88 号',
  requested_action: { action: 'cancel', api_key: 'secret-value' },
  agent_state_digest: 'digest',
  assignee: null,
  created_at: 1_700_000_000,
  updated_at: 1_700_000_000,
  closed_at: null,
  close_reason: null,
}

const DETAIL: TicketDetail = {
  ...TICKET,
  session: { session_id: 'session-customer-1', identity_verified: true },
  request: {
    request_id: 'request-1',
    action: 'cancel',
    order_id: '#W100',
    status: 'pending_confirmation',
    proposal_id: 'proposal-1',
    proposed_parameters: { reason: 'ordered_by_mistake' },
    confirmation_expires_at: 2_000_000_000,
    failure_reason: null,
  },
  conversation: [
    { role: 'system', content: '完整系统 Prompt 不应出现', sequence: 1, created_at: 1_700_000_000 },
    { role: 'user', content: '联系 customer@example.invalid，地址：上海市测试路 88 号', sequence: 2, created_at: 1_700_000_010 },
  ],
  audit_summary: { event_count: 1, event_types: { ticket_created: 1 }, last_event_at: 1_700_000_020 },
}

const APPROVAL: ApprovalRecord = {
  id: 'approval-1',
  ticket_id: 'ticket-1',
  request_id: 'request-1',
  action: 'execute_cancel',
  proposed_params: { reason: 'ordered_by_mistake' },
  status: 'pending',
  operator_id: null,
  decision_reason: null,
  created_at: 1_700_000_020,
  decided_at: null,
  expires_at: 2_000_000_000,
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function requestOf(input: URL | RequestInfo, init?: RequestInit): Request {
  if (input instanceof Request) return new Request(input, init)
  const raw = input instanceof URL ? input.href : input
  return new Request(new URL(raw, window.location.origin), init)
}

function inputUrl(input: URL | RequestInfo): string {
  if (typeof input === 'string') return input
  if (input instanceof URL) return input.href
  return input.url
}

type BackendOptions = {
  execute?: (call: number) => Response | Promise<Response>
}

function installBackend(options: BackendOptions = {}) {
  let executeCalls = 0
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const request = requestOf(input, init)
    const url = new URL(request.url)
    expect(request.headers.get('X-Operator-Token')).toBe('operator-demo-token')
    expect(request.headers.has('X-Session-Id')).toBe(false)

    if (request.method === 'GET' && url.pathname === '/api/v1/tickets') {
      const offset = Number(url.searchParams.get('offset') ?? 0)
      const limit = Number(url.searchParams.get('limit') ?? 10)
      return json({ items: [TICKET], total: 21, offset, limit })
    }
    if (request.method === 'GET' && url.pathname === '/api/v1/tickets/ticket-1') return json(DETAIL)
    if (request.method === 'GET' && url.pathname.endsWith('/ticket-1/audit')) {
      return json({
        ticket_id: 'ticket-1',
        events: [{
          id: 'audit-1',
          event_type: 'ticket_created',
          session_id: 'session-customer-1',
          ticket_id: 'ticket-1',
          request_id: 'request-1',
          order_id: '#W100',
          actor: 'system',
          payload: { email: 'customer@example.invalid', prompt: 'do not expose' },
          created_at: 1_700_000_020,
        }],
      })
    }
    if (request.method === 'POST' && url.pathname.endsWith('/approvals')) return json(APPROVAL)
    if (request.method === 'POST' && url.pathname.endsWith('/approval-1/decision')) {
      return json({ ...APPROVAL, status: 'approved', operator_id: 'operator-demo', decision_reason: '已复核', decided_at: 1_700_000_030 })
    }
    if (request.method === 'POST' && url.pathname.endsWith('/execute')) {
      executeCalls += 1
      if (options.execute) return options.execute(executeCalls)
      return json({ error: { code: 'confirmation_required' } }, 409)
    }
    if (request.method === 'POST' && url.pathname.endsWith('/status')) return json(TICKET)
    throw new Error(`Unhandled request: ${request.method} ${request.url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderAdmin(withToken = true) {
  window.history.replaceState({}, '', '/admin')
  if (withToken) window.sessionStorage.setItem('serviceflow.operator_token', 'operator-demo-token')
  return render(<App />)
}

async function openTicket(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole('button', { name: /TK-2026-0001/ }))
  await screen.findByRole('heading', { name: 'TK-2026-0001' })
}

describe('AdminPage', () => {
  it('does not accept a customer session in place of an operator token', () => {
    window.localStorage.setItem('serviceflow.session_id', 'customer-session')
    const fetchMock = vi.fn<typeof fetch>()
    vi.stubGlobal('fetch', fetchMock)

    renderAdmin(false)

    expect(screen.getByRole('heading', { name: '进入人工处理台' })).toBeInTheDocument()
    expect(screen.getByText(/不是生产 IAM/)).toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('applies list filters and server pagination', async () => {
    const user = userEvent.setup()
    const fetchMock = installBackend()
    renderAdmin()
    await screen.findByText('TK-2026-0001')

    await user.selectOptions(screen.getByLabelText('状态'), 'assigned')
    await user.selectOptions(screen.getByLabelText('类别'), 'execution_failed')
    await user.type(screen.getByLabelText('客服'), 'operator-1')
    await user.type(screen.getByLabelText('创建时间从'), '2026-01-01T08:00')
    await user.type(screen.getByLabelText('创建时间至'), '2026-01-02T08:00')
    await user.click(screen.getByRole('button', { name: '应用过滤' }))

    await waitFor(() => {
      const calls = fetchMock.mock.calls.map(([input]) => inputUrl(input))
      expect(calls.some((url) => url.includes('status=assigned') && url.includes('category=execution_failed') && url.includes('assignee=operator-1'))).toBe(true)
      expect(calls.some((url) => url.includes('created_from=') && url.includes('created_to='))).toBe(true)
    })

    await user.click(screen.getByRole('button', { name: '下一页' }))
    await waitFor(() => {
      expect(fetchMock.mock.calls.some(([input]) => inputUrl(input).includes('offset=10'))).toBe(true)
    })
  })

  it('offers only legal transitions, requires a close reason, and redacts details', async () => {
    const user = userEvent.setup()
    const fetchMock = installBackend()
    renderAdmin()
    await openTicket(user)

    const statusSelect = screen.getByLabelText('合法状态流转')
    expect(within(statusSelect).queryByRole('option', { name: '已解决' })).not.toBeInTheDocument()
    expect(screen.queryByText('完整系统 Prompt 不应出现')).not.toBeInTheDocument()
    expect(screen.queryByText('customer@example.invalid')).not.toBeInTheDocument()
    expect(screen.getAllByText(/\[REDACTED/).length).toBeGreaterThan(0)
    expect(screen.queryByText(/上海市测试路/)).not.toBeInTheDocument()

    await user.selectOptions(statusSelect, 'cancelled')
    await user.click(screen.getByRole('button', { name: '更新状态' }))
    expect(screen.getByRole('alert')).toHaveTextContent('必须选择合法 close_reason')
    expect(fetchMock.mock.calls.filter(([input, init]) => inputUrl(input).endsWith('/status') && init?.method === 'POST')).toHaveLength(0)
  })

  it('does not treat an approved operator approval as customer confirmation', async () => {
    const user = userEvent.setup()
    installBackend()
    renderAdmin()
    await openTicket(user)

    await user.click(screen.getByRole('button', { name: '创建审批' }))
    await screen.findByText('approval-1')
    await user.type(screen.getByLabelText('决定理由'), '已复核')
    await user.click(screen.getByRole('button', { name: '批准审批' }))
    await screen.findByText('决定：已复核')
    await user.click(screen.getByRole('button', { name: '请求服务端代执行' }))

    expect(await screen.findByText(/confirmation_required：审批不能替代客户确认/)).toBeInTheDocument()
    expect(screen.queryByText('服务端执行成功')).not.toBeInTheDocument()
  })

  it('prevents concurrent execution clicks and reports server idempotent replay', async () => {
    const user = userEvent.setup()
    let resolveExecution: ((response: Response) => void) | undefined
    const pendingExecution = new Promise<Response>((resolve) => { resolveExecution = resolve })
    const fetchMock = installBackend({
      execute: (call) => call === 1
        ? pendingExecution
        : json({
          request_id: 'request-1',
          proposal_id: 'proposal-1',
          confirmation_id: 'confirmation-1',
          status: 'succeeded',
          action_type: 'cancel',
          order_id: '#W100',
          before_status: 'pending',
          after_status: 'cancelled',
          row_version: 2,
          idempotent_replay: true,
        }),
    })
    renderAdmin()
    await openTicket(user)

    const executeButton = screen.getByRole('button', { name: '请求服务端代执行' })
    await user.dblClick(executeButton)
    expect(fetchMock.mock.calls.filter(([input]) => inputUrl(input).endsWith('/execute'))).toHaveLength(1)
    resolveExecution?.(json({ error: { code: 'confirmation_required' } }, 409))
    await screen.findByText(/confirmation_required/)

    await user.click(screen.getByRole('button', { name: '请求服务端代执行' }))
    expect(await screen.findByText(/幂等复用原结果/)).toBeInTheDocument()
  })
})
