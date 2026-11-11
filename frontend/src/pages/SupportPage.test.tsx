import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { App } from '../app/App'
import type { ConversationResponse, Order, PendingConfirmation, TaskProgress } from '../api/types'

const ORDER: Order = {
  order_id: '#W100',
  status: 'pending',
  items: [
    {
      item_id: 'item-1',
      product_id: 'product-1',
      name: '灰蓝通勤包',
      price: 128,
      options: { color: 'gray' },
    },
  ],
  fulfillments: [],
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

type FetchHandler = (request: Request) => Response | Promise<Response>

function inputUrl(input: URL | RequestInfo): string {
  if (typeof input === 'string') return input
  if (input instanceof URL) return input.href
  return input.url
}

function installBackend(handler?: FetchHandler) {
  const fetchMock = vi.fn<typeof fetch>(async (input, init) => {
    const request =
      input instanceof Request
        ? new Request(input, init)
        : new Request(new URL(inputUrl(input), window.location.origin), init)
    if (handler) {
      const response = await handler(request)
      if (response) return response
    }
    if (request.method === 'POST' && request.url.endsWith('/api/v1/sessions')) {
      return json({ session_id: 'session-1' })
    }
    if (request.method === 'POST' && request.url.includes('/verify')) {
      return json({ user_id: 'user-1' })
    }
    if (request.method === 'GET' && request.url.endsWith('/api/v1/orders')) {
      return json([ORDER])
    }
    if (request.method === 'GET' && request.url.endsWith('/api/v1/orders/%23W100')) {
      return json(ORDER)
    }
    throw new Error(`Unhandled request: ${request.method} ${request.url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

async function verifyUser(expectOrder = true) {
  const user = userEvent.setup()
  await screen.findByRole('heading', { name: '订单信息只对本人开放' })
  await user.type(screen.getByLabelText('模拟账户邮箱'), 'customer@example.invalid')
  await user.click(screen.getByRole('button', { name: '核验并查看订单' }))
  if (expectOrder) await screen.findByText('#W100')
  return user
}

function pending(action: 'cancel' | 'return'): PendingConfirmation {
  return {
    request_id: `${action}-request-1`,
    idempotency_key: `chat-idempotency-${action}-1`,
    task_id: `${action}-task`,
    proposal_id: `${action}-proposal`,
    proposal_version: 1,
    order_id: '#W100',
    action_type: action,
    proposed_parameters:
      action === 'cancel'
        ? { reason: 'ordered by mistake' }
        : { item_quantities: { 'item-1': 1 }, payment_method_id: 'card-1' },
    summary:
      action === 'cancel'
        ? 'Cancel order #W100; reason=ordered by mistake'
        : 'Register return request for order #W100; refund is not disbursed',
    status: 'pending_confirmation',
    confirmation_expires_at: 2_000_000_000,
    confirmation_text: `confirm ${action}_order order=#W100`,
  }
}

function conversation(
  action: 'cancel' | 'return',
  overrides: Partial<ConversationResponse> = {},
): ConversationResponse {
  const request = pending(action)
  return {
    trace_id: 'trace-1',
    task_status: 'pending_confirmation',
    request_id: request.request_id,
    pending_confirmation: request,
    resolution_proposal: {
      proposal_id: request.proposal_id,
      task_id: request.task_id,
      action_type: action,
      order_id: request.order_id,
      proposed_parameters: request.proposed_parameters,
      explanation: '规则校验通过，等待确认。',
      status: 'pending_confirmation',
      validated: true,
    },
    eligibility_result: {
      status: 'eligible',
      validated: true,
      rule_code: null,
      checked_order_status: action === 'cancel' ? 'pending' : 'delivered',
      explanation: 'eligible',
    },
    execution_result: null,
    failure_reason: null,
    task_plan: [
      {
        task_id: 'order-check',
        intent: `${action}_order`,
        target_agent: 'order',
        required_inputs: [],
        dependencies: [],
        status: 'completed',
      },
      {
        task_id: 'confirmation',
        intent: `${action}_order`,
        target_agent: 'confirmation',
        required_inputs: [],
        dependencies: ['order-check'],
        status: 'ready',
      },
    ],
    ticket: null,
    final_response: `方案已生成，等待确认${action === 'cancel' ? '取消' : '退货'}。`,
    ...overrides,
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('SupportPage identity and orders', () => {
  it('creates a session, verifies identity, and only then requests orders', async () => {
    const fetchMock = installBackend()
    render(<App />)

    await screen.findByRole('heading', { name: '订单信息只对本人开放' })
    expect(fetchMock.mock.calls.some(([input]) => inputUrl(input).endsWith('/api/v1/orders'))).toBe(false)

    await verifyUser()

    const urls = fetchMock.mock.calls.map(([input]) => inputUrl(input))
    expect(urls.some((url) => url.endsWith('/api/v1/orders'))).toBe(true)
    const verifyCall = fetchMock.mock.calls.find(([input]) => inputUrl(input).includes('/verify'))
    expect(verifyCall).toBeDefined()
  })

  it('queries an order detail from the real detail path', async () => {
    const fetchMock = installBackend()
    render(<App />)
    const user = await verifyUser()

    await user.click(screen.getByRole('button', { name: /#W100/ }))

    expect(await screen.findByRole('article', { name: '订单 #W100 详情' })).toHaveTextContent('灰蓝通勤包')
    expect(fetchMock.mock.calls.some(([input]) => inputUrl(input).endsWith('/api/v1/orders/%23W100'))).toBe(true)
  })

  it('shows an empty state without inventing orders', async () => {
    installBackend((request) => {
      if (request.method === 'GET' && request.url.endsWith('/api/v1/orders')) return json([])
      return undefined as never
    })
    render(<App />)
    await verifyUser(false)
    expect(await screen.findByText('暂无订单')).toBeInTheDocument()
  })

  it('shows the safe 404 state when an order detail is unavailable', async () => {
    installBackend((request) => {
      if (request.method === 'GET' && request.url.endsWith('/api/v1/orders/%23W100')) {
        return json({ error: { code: 'order_not_found' } }, 404)
      }
      return undefined as never
    })
    render(<App />)
    const user = await verifyUser()
    await user.click(screen.getByRole('button', { name: /#W100/ }))

    expect(await screen.findByText(/404：没有找到该订单/)).toBeInTheDocument()
  })
})

describe('SupportPage conversation and confirmation', () => {
  it.each([
    ['cancel', 'cancel（取消订单）', 'reason', 'ordered by mistake'],
    ['return', 'return（提交退货申请）', 'payment_method_id', 'card-1'],
  ] as const)(
    'renders a concrete %s proposal while waiting for confirmation',
    async (action, actionText, parameter, value) => {
      installBackend((request) => {
        if (request.method === 'POST' && request.url.endsWith('/api/v1/multi-agent/chat')) {
          return json(conversation(action))
        }
        return undefined as never
      })
      render(<App />)
      const user = await verifyUser()

      await user.type(screen.getByLabelText('输入售后问题'), `${action} order #W100`)
      await user.click(screen.getByRole('button', { name: '发送消息' }))

      const region = await screen.findByRole('heading', { name: '核对即将执行的操作' })
      const panel = region.closest('section')
      expect(panel).toHaveTextContent(actionText)
      expect(panel).toHaveTextContent('order_id')
      expect(panel).toHaveTextContent('#W100')
      expect(panel).toHaveTextContent(parameter)
      expect(panel).toHaveTextContent(value)
    },
  )

  it('shows rejection and execution failure without claiming success', async () => {
    let chatCount = 0
    installBackend((request) => {
      if (request.method === 'POST' && request.url.endsWith('/api/v1/multi-agent/chat')) {
        chatCount += 1
        if (chatCount === 1) return json(conversation('cancel'))
        return json(
          conversation('cancel', {
            task_status: 'confirmation_rejected',
            pending_confirmation: { ...pending('cancel'), status: 'rejected' },
            final_response: '方案已拒绝，订单没有变更。',
          }),
        )
      }
      return undefined as never
    })
    render(<App />)
    const user = await verifyUser()
    await user.type(screen.getByLabelText('输入售后问题'), 'cancel order #W100')
    await user.click(screen.getByRole('button', { name: '发送消息' }))
    await user.click(await screen.findByRole('button', { name: '拒绝方案' }))

    expect(await screen.findByText('方案已拒绝，订单没有变更。')).toBeInTheDocument()
    expect(screen.queryByText('服务端已执行成功')).not.toBeInTheDocument()
  })

  it('uses execution_result as the only success signal and surfaces failure', async () => {
    let chatCount = 0
    installBackend((request) => {
      if (request.method === 'POST' && request.url.endsWith('/api/v1/multi-agent/chat')) {
        chatCount += 1
        if (chatCount === 1) return json(conversation('cancel'))
        return json(
          conversation('cancel', {
            task_status: 'execution_failed',
            pending_confirmation: { ...pending('cancel'), status: 'failed' },
            failure_reason: 'order_changed',
            final_response: '订单已变化，本次操作未执行。',
          }),
        )
      }
      return undefined as never
    })
    render(<App />)
    const user = await verifyUser()
    await user.type(screen.getByLabelText('输入售后问题'), 'cancel order #W100')
    await user.click(screen.getByRole('button', { name: '发送消息' }))
    await user.click(await screen.findByRole('button', { name: '确认取消订单' }))

    expect(await screen.findByText('操作没有执行')).toBeInTheDocument()
    expect(screen.getByText(/order_changed/)).toBeInTheDocument()
    expect(screen.queryByText('服务端已执行成功')).not.toBeInTheDocument()
  })

  it('protects against duplicate submit clicks', async () => {
    let resolveChat: ((response: Response) => void) | undefined
    let chatCalls = 0
    installBackend((request) => {
      if (request.method === 'POST' && request.url.endsWith('/api/v1/multi-agent/chat')) {
        chatCalls += 1
        return new Promise<Response>((resolve) => {
          resolveChat = resolve
        })
      }
      return undefined as never
    })
    render(<App />)
    const user = await verifyUser()
    await user.type(screen.getByLabelText('输入售后问题'), 'show order #W100')
    await user.dblClick(screen.getByRole('button', { name: '发送消息' }))

    expect(chatCalls).toBe(1)
    act(() => {
      resolveChat?.(json(conversation('cancel')))
    })
  })
})

describe('SupportPage handoff and recovery', () => {
  it('creates a human ticket with one stable idempotency key and says it is waiting', async () => {
    const ticketKeys: string[] = []
    installBackend((request) => {
      if (request.method === 'POST' && request.url.endsWith('/api/v1/tickets')) {
        ticketKeys.push(request.headers.get('Idempotency-Key') ?? '')
        return json({ id: 'ticket-1', ticket_no: 'T-2026-1', status: 'open' })
      }
      return undefined as never
    })
    render(<App />)
    const user = await verifyUser()
    await user.click(screen.getByRole('button', { name: '创建人工工单' }))

    expect(await screen.findByText(/等待人工处理/)).toBeInTheDocument()
    expect(screen.queryByText(/已处理完成/)).not.toBeInTheDocument()
    expect(ticketKeys).toHaveLength(1)
    expect(ticketKeys[0]?.startsWith('ticket-')).toBe(true)
  })

  it('restores current task from the server after refresh before loading orders', async () => {
    window.localStorage.setItem('serviceflow.session_id', 'restored-session')
    const request = pending('return')
    const progress: TaskProgress = {
      thread_id: 'restored-session',
      task_status: 'pending_confirmation',
      current_task: 'confirmation',
      task_plan: conversation('return').task_plan,
      order_context: { order_id: '#W100', status: 'delivered' },
      policy_context: [{ source: 'policy.md' }],
      resolution_proposal: conversation('return').resolution_proposal,
      eligibility_result: conversation('return').eligibility_result,
      pending_confirmation: request,
      execution_result: null,
      final_response: '退货方案仍在等待你的确认。',
    }
    const fetchMock = installBackend((incoming) => {
      if (incoming.method === 'GET' && incoming.url.endsWith('/api/v1/multi-agent/tasks/current')) {
        return json(progress)
      }
      return undefined as never
    })
    render(<App />)

    expect(await screen.findByText('已从服务端恢复当前任务')).toBeInTheDocument()
    expect(screen.getByText('退货方案仍在等待你的确认。')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '核对即将执行的操作' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('#W100')).toBeInTheDocument())
    expect(
      fetchMock.mock.calls.some(
        ([input, init]) => inputUrl(input).endsWith('/api/v1/sessions') && init?.method === 'POST',
      ),
    ).toBe(false)
  })

  it('keeps orders hidden when task recovery returns 403', async () => {
    window.localStorage.setItem('serviceflow.session_id', 'unverified-session')
    const fetchMock = installBackend((request) => {
      if (request.method === 'GET' && request.url.endsWith('/api/v1/multi-agent/tasks/current')) {
        return json({ error: { code: 'identity_required' } }, 403)
      }
      return undefined as never
    })
    render(<App />)

    expect(await screen.findByRole('heading', { name: '订单信息只对本人开放' })).toBeInTheDocument()
    expect(screen.getByText(/403：身份核验尚未完成/)).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input]) => inputUrl(input).endsWith('/api/v1/orders'))).toBe(false)
  })
})
