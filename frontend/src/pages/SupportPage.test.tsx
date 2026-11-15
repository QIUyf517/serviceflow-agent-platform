import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { App } from '../app/App'
import type {
  ConversationResponse,
  Order,
  PendingConfirmation,
  Product,
  ProductSummary,
  TaskProgress,
  UserProfile,
} from '../api/types'

const PRODUCT_SUMMARY: ProductSummary = {
  product_id: 'product-1',
  name: '灰蓝通勤包',
  min_price: 128,
  max_price: 138,
  available_variants: 1,
  total_variants: 2,
  option_names: ['color'],
}

const PRODUCT: Product = {
  product_id: 'product-1',
  name: '灰蓝通勤包',
  variants: {
    'item-1': {
      item_id: 'item-1',
      options: { color: 'gray' },
      available: true,
      price: 128,
    },
    'item-2': {
      item_id: 'item-2',
      options: { color: 'blue' },
      available: false,
      price: 138,
    },
  },
}

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

const USER: UserProfile = {
  user_id: 'user-1',
  name: { first_name: '测试', last_name: '顾客' },
  address: {
    address1: '测试路 1 号',
    address2: '',
    city: '杭州',
    state: '浙江',
    country: '中国',
    zip: '310000',
  },
  email: 'customer@example.invalid',
  payment_methods: {
    'card-1': {
      id: 'card-1',
      source: 'credit_card',
      brand: '银联',
      last_four: '1234',
    },
  },
  orders: ['#W100'],
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

function threadFor(orderId: string | null) {
  return {
    thread_id: orderId ? `thread-${orderId}` : 'thread-general',
    kind: orderId ? 'order' : 'general',
    order_id: orderId,
    status: 'open',
    created_at: 1_700_000_000,
    updated_at: 1_700_000_000,
  }
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
    if (request.method === 'POST' && request.url.endsWith('/api/v1/support/threads')) {
      const body = await request.json().catch(() => ({})) as { order_id?: string }
      return json(threadFor(body.order_id ?? null))
    }
    if (request.method === 'GET' && request.url.includes('/api/v1/customer/conversation')) {
      return json([])
    }
    if (request.method === 'POST' && request.url.includes('/verify')) {
      return json({ user_id: 'user-1' })
    }
    if (request.method === 'GET' && request.url.endsWith('/api/v1/products')) {
      return json([PRODUCT_SUMMARY])
    }
    if (request.method === 'GET' && request.url.endsWith('/api/v1/products/product-1')) {
      return json(PRODUCT)
    }
    if (request.method === 'GET' && request.url.endsWith('/api/v1/orders')) {
      return json([ORDER])
    }
    if (request.method === 'GET' && request.url.endsWith('/api/v1/users/me')) {
      return json(USER)
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

async function openOrderSupport(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole('button', { name: '联系商家客服' }))
  await screen.findByRole('dialog', { name: '正在咨询订单 #W100' })
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
  window.localStorage.clear()
})

describe('SupportPage identity and orders', () => {
  it('shows the real product catalog before identity verification and keeps orders hidden', async () => {
    const fetchMock = installBackend()
    render(<App />)

    expect(await screen.findByRole('heading', { name: '灰蓝通勤包' })).toBeInTheDocument()
    expect(screen.getByText('金额 128.00 – 138.00')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '订单信息只对本人开放' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: '主要导航' })).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input]) => inputUrl(input).endsWith('/api/v1/orders'))).toBe(false)
  })

  it('opens product detail through the product detail API', async () => {
    const fetchMock = installBackend()
    render(<App />)
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: '查看商品' }))

    expect(await screen.findByRole('dialog', { name: '灰蓝通勤包' })).toBeInTheDocument()
    expect(await screen.findByRole('article', { name: '商品 灰蓝通勤包 详情' })).toHaveTextContent('暂不可用')
    expect(fetchMock.mock.calls.some(([input]) => inputUrl(input).endsWith('/api/v1/products/product-1'))).toBe(true)
  })

  it('adds an available variant to the cart and creates a real order after identity verification', async () => {
    let checkoutBody: unknown
    let checkoutKey = ''
    installBackend(async (request) => {
      if (request.method === 'POST' && request.url.endsWith('/api/v1/orders')) {
        checkoutBody = await request.json()
        checkoutKey = request.headers.get('Idempotency-Key') ?? ''
        return json({
          order: { ...ORDER, order_id: '#W200' },
          idempotent_replay: false,
          created_at: 1_800_000_000,
        })
      }
      return undefined as never
    })
    render(<App />)
    const user = userEvent.setup()

    await user.click(await screen.findByRole('button', { name: '查看商品' }))
    await user.click(await screen.findByRole('button', { name: '加入购物车' }))
    expect(screen.getByRole('link', { name: '核验身份后结算' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '关闭' }))

    await verifyUser()
    await user.click(await screen.findByRole('button', { name: '提交模拟订单' }))

    expect(await screen.findByText(/订单 #W200 已创建/)).toBeInTheDocument()
    expect(checkoutKey.startsWith('checkout-')).toBe(true)
    expect(checkoutBody).toEqual({
      items: [{ item_id: 'item-1', quantity: 1 }],
      payment_method_id: 'card-1',
    })
  })

  it('opens the intelligent support dialog from the selected order', async () => {
    installBackend()
    render(<App />)
    const user = await verifyUser()

    await openOrderSupport(user)

    expect(screen.getByText(/会明确附带这笔订单号/)).toBeInTheDocument()
    expect(screen.getByLabelText('输入售后问题')).toBeInTheDocument()
  })

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

  it('creates a new session and requires verification when switching customers', async () => {
    let sessionCount = 0
    const fetchMock = installBackend((request) => {
      if (request.method === 'POST' && request.url.endsWith('/api/v1/sessions')) {
        sessionCount += 1
        return json({ session_id: `session-${sessionCount}` })
      }
      return undefined as never
    })
    render(<App />)
    const user = await verifyUser()

    await user.click(screen.getByRole('button', { name: '切换模拟顾客' }))

    expect(await screen.findByText('已建立新的模拟顾客会话，请重新核验身份。')).toBeInTheDocument()
    expect(screen.queryByText('#W100')).not.toBeInTheDocument()
    await user.type(screen.getByLabelText('模拟账户邮箱'), 'second@example.invalid')
    await user.click(screen.getByRole('button', { name: '核验并查看订单' }))

    await waitFor(() => {
      const verifyUrls = fetchMock.mock.calls
        .map(([input]) => inputUrl(input))
        .filter((url) => url.includes('/verify'))
      expect(verifyUrls.some((url) => url.includes('/sessions/session-2/verify'))).toBe(true)
    })
  })
})

describe('SupportPage conversation and confirmation', () => {
  it('renders the server safety response without presenting a write as successful', async () => {
    installBackend((request) => {
      if (request.method === 'POST' && request.url.endsWith('/api/v1/multi-agent/chat')) {
        return json(conversation('cancel', {
          task_status: 'content_blocked',
          consultation_route: 'content_blocked',
          safety: {
            allowed: false,
            category: 'harmful_instruction',
            reason_code: 'content_harmful_instruction',
          },
          request_id: null,
          pending_confirmation: null,
          resolution_proposal: null,
          eligibility_result: null,
          task_plan: [],
          final_response: '这段内容涉及可能造成伤害的具体请求，我不能协助。',
        }))
      }
      return undefined as never
    })
    render(<App />)
    const user = await verifyUser()
    await openOrderSupport(user)

    await user.type(screen.getByLabelText('输入售后问题'), '不安全请求')
    await user.click(screen.getByRole('button', { name: '发送消息' }))

    expect(await screen.findByText(/我不能协助/)).toBeInTheDocument()
    expect(screen.queryByText('服务端已执行成功')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '核对即将执行的操作' })).not.toBeInTheDocument()
  })

  it.each([
    ['cancel', '取消订单', '原因', '下错单'],
    ['return', '提交退货申请', '退款途径', 'card-1'],
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
      await openOrderSupport(user)

      await user.type(screen.getByLabelText('输入售后问题'), `${action} order #W100`)
      await user.click(screen.getByRole('button', { name: '发送消息' }))

      const region = await screen.findByRole('heading', { name: '核对即将执行的操作' })
      const panel = region.closest('section')
      expect(panel).toHaveTextContent(actionText)
      expect(panel).toHaveTextContent('订单号')
      expect(panel).toHaveTextContent('#W100')
      expect(panel).toHaveTextContent(parameter)
      expect(panel).toHaveTextContent(value)
    },
  )

  it('shows rejection and execution failure without claiming success', async () => {
    let chatCount = 0
    const chatBodies: Array<{ message: string; request_id?: string }> = []
    installBackend(async (request) => {
      if (request.method === 'POST' && request.url.endsWith('/api/v1/multi-agent/chat')) {
        chatBodies.push(await request.json() as { message: string; request_id?: string })
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
    await openOrderSupport(user)
    await user.type(screen.getByLabelText('输入售后问题'), 'cancel order #W100')
    await user.click(screen.getByRole('button', { name: '发送消息' }))
    await user.click(await screen.findByRole('button', { name: '拒绝方案' }))

    expect(await screen.findByText('方案已拒绝，订单没有变更。')).toBeInTheDocument()
    expect(chatBodies[1]).toEqual({
      message: '拒绝',
      request_id: 'cancel-request-1',
      order_id: '#W100',
    })
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
    await openOrderSupport(user)
    await user.type(screen.getByLabelText('输入售后问题'), 'cancel order #W100')
    await user.click(screen.getByRole('button', { name: '发送消息' }))
    await user.click(await screen.findByRole('button', { name: '确认取消订单' }))

    expect(await screen.findByText('操作没有执行')).toBeInTheDocument()
    expect(screen.getByText(/订单状态以服务端最新结果为准/)).toBeInTheDocument()
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
    await openOrderSupport(user)
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
        return json({
          id: 'ticket-1',
          ticket_no: 'T-2026-1',
          status: 'open',
          order_id: '#W100',
          thread_id: 'thread-#W100',
        })
      }
      return undefined as never
    })
    render(<App />)
    const user = await verifyUser()
    await openOrderSupport(user)
    await user.click(screen.getByRole('button', { name: '创建人工工单' }))

    expect(await screen.findByText(/人工处理进度/)).toBeInTheDocument()
    expect(screen.queryByText(/已处理完成/)).not.toBeInTheDocument()
    expect(ticketKeys).toHaveLength(1)
    expect(ticketKeys[0]?.startsWith('ticket-')).toBe(true)
  })

  it('routes customer follow-up messages to the active human ticket instead of the Agent', async () => {
    let agentCalls = 0
    let ticketCreated = false
    let customerMessageBody: { content: string } | undefined
    let customerMessageKey = ''
    installBackend(async (request) => {
      if (request.method === 'POST' && request.url.endsWith('/api/v1/tickets')) {
        ticketCreated = true
        return json({
          id: 'ticket-1',
          ticket_no: 'T-2026-1',
          status: 'open',
          order_id: '#W100',
          thread_id: 'thread-#W100',
        })
      }
      if (request.method === 'GET' && request.url.endsWith('/api/v1/customer/tickets')) {
        return json(ticketCreated
          ? [{
              id: 'ticket-1',
              ticket_no: 'T-2026-1',
              status: 'open',
              order_id: '#W100',
              thread_id: 'thread-#W100',
            }]
          : [])
      }
      if (request.method === 'GET' && request.url.endsWith('/api/v1/customer/tickets/ticket-1/updates')) {
        return json({ ticket_no: 'T-2026-1', status: 'open', messages: [] })
      }
      if (request.method === 'POST' && request.url.endsWith('/api/v1/customer/tickets/ticket-1/messages')) {
        customerMessageBody = await request.json() as { content: string }
        customerMessageKey = request.headers.get('Idempotency-Key') ?? ''
        return json({
          sequence: 2,
          content: customerMessageBody.content,
          created_at: 1_700_000_030,
          status: 'in_progress',
          idempotent_replay: false,
        })
      }
      if (request.method === 'POST' && request.url.endsWith('/api/v1/multi-agent/chat')) {
        agentCalls += 1
        return json(conversation('return'))
      }
      return undefined as never
    })
    render(<App />)
    const user = await verifyUser()
    await openOrderSupport(user)
    await user.click(screen.getByRole('button', { name: '创建人工工单' }))
    await screen.findByText(/人工处理进度/)

    await user.type(screen.getByLabelText('输入售后问题'), '好的，请继续处理')
    await user.click(screen.getByRole('button', { name: '发送消息' }))

    await waitFor(() => {
      expect(customerMessageBody?.content).toBe('好的，请继续处理')
    })
    expect(customerMessageKey.startsWith('customer-message-')).toBe(true)
    expect(agentCalls).toBe(0)
  })

  it('keeps a legacy unbound ticket out of order windows and inside general consultation', async () => {
    window.localStorage.setItem('serviceflow.session_id', 'restored-session')
    let agentCalls = 0
    let customerMessage = ''
    installBackend(async (request) => {
      if (request.method === 'GET' && request.url.includes('/api/v1/multi-agent/tasks/current')) {
        return json({ error: { code: 'task_state_not_found' } }, 404)
      }
      if (request.method === 'GET' && request.url.endsWith('/api/v1/customer/tickets')) {
        return json([{
          id: 'legacy-ticket',
          ticket_no: 'T-LEGACY',
          status: 'in_progress',
          order_id: null,
          thread_id: 'thread-general',
          thread_kind: 'general',
        }])
      }
      if (request.method === 'POST' && request.url.endsWith('/api/v1/customer/tickets/legacy-ticket/messages')) {
        customerMessage = ((await request.json()) as { content: string }).content
        return json({
          sequence: 3,
          content: customerMessage,
          created_at: 1_700_000_030,
          status: 'in_progress',
          idempotent_replay: false,
        })
      }
      if (request.method === 'POST' && request.url.endsWith('/api/v1/multi-agent/chat')) {
        agentCalls += 1
        return json(conversation('return'))
      }
      return undefined as never
    })
    render(<App />)
    const user = userEvent.setup()
    await screen.findByText('#W100')
    await openOrderSupport(user)
    expect(screen.queryByText(/人工处理进度/)).not.toBeInTheDocument()

    await user.type(screen.getByLabelText('输入售后问题'), 'show order #W100')
    await user.click(screen.getByRole('button', { name: '发送消息' }))
    await waitFor(() => expect(agentCalls).toBe(1))

    await user.click(screen.getByRole('button', { name: '关闭' }))
    await user.click(screen.getByRole('button', { name: '通用咨询' }))
    await screen.findByRole('dialog', { name: '售前与售后咨询' })
    expect(await screen.findByText(/人工处理进度/)).toBeInTheDocument()

    await user.type(screen.getByLabelText('输入售后问题'), '好的，请继续处理')
    await user.click(screen.getByRole('button', { name: '发送消息' }))
    await waitFor(() => expect(customerMessage).toBe('好的，请继续处理'))
    expect(agentCalls).toBe(1)
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
      if (incoming.method === 'GET' && incoming.url.includes('/api/v1/multi-agent/tasks/current')) {
        return json(progress)
      }
      if (incoming.method === 'GET' && incoming.url.includes('/api/v1/customer/conversation')) {
        return json([{
          sequence: 1,
          role: 'assistant',
          content: '退货方案仍在等待你的确认。',
          thread_id: 'restored-session',
          created_at: 1_700_000_000,
        }])
      }
      return undefined as never
    })
    render(<App />)

    expect(await screen.findByText('已从服务端恢复当前任务')).toBeInTheDocument()
    expect(await screen.findByText('退货方案仍在等待你的确认。')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '核对即将执行的操作' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getAllByText('#W100').length).toBeGreaterThan(1))
    expect(
      fetchMock.mock.calls.some(
        ([input, init]) => inputUrl(input).endsWith('/api/v1/sessions') && init?.method === 'POST',
      ),
    ).toBe(false)
  })

  it('treats an unverified saved session as a normal identity gate without a red error', async () => {
    window.localStorage.setItem('serviceflow.session_id', 'unverified-session')
    const fetchMock = installBackend((request) => {
      if (request.method === 'GET' && request.url.includes('/api/v1/multi-agent/tasks/current')) {
        return json({ error: { code: 'identity_required' } }, 403)
      }
      return undefined as never
    })
    render(<App />)

    expect(await screen.findByRole('heading', { name: '订单信息只对本人开放' })).toBeInTheDocument()
    expect(screen.queryByText(/403：身份核验尚未完成/)).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input]) => inputUrl(input).endsWith('/api/v1/orders'))).toBe(false)
  })

  it('restores a verified session with no current support task without asking for identity again', async () => {
    window.localStorage.setItem('serviceflow.session_id', 'verified-session')
    const fetchMock = installBackend((request) => {
      if (request.method === 'GET' && request.url.includes('/api/v1/multi-agent/tasks/current')) {
        return json({ error: { code: 'task_state_not_found' } }, 404)
      }
      return undefined as never
    })
    render(<App />)

    expect(await screen.findByText('#W100')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: '订单信息只对本人开放' })).not.toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([input]) => inputUrl(input).endsWith('/api/v1/users/me'))).toBe(true)
  })
})

describe('SupportPage order threads', () => {
  it('shows only the conversation that belongs to the opened order', async () => {
    const secondOrder: Order = { ...ORDER, order_id: '#W200' }
    installBackend((request) => {
      if (request.method === 'GET' && request.url.endsWith('/api/v1/orders')) {
        return json([ORDER, secondOrder])
      }
      if (request.method === 'GET' && request.url.endsWith('/api/v1/orders/%23W200')) {
        return json(secondOrder)
      }
      if (request.method === 'GET' && request.url.includes('/api/v1/customer/conversation')) {
        const orderId = new URL(request.url).searchParams.get('order_id')
        return json(orderId === '#W100'
          ? [{ sequence: 1, role: 'user', content: '订单A的历史消息', thread_id: 'thread-#W100', created_at: 1 }]
          : [{ sequence: 2, role: 'user', content: '订单B的历史消息', thread_id: 'thread-#W200', created_at: 2 }])
      }
      return undefined as never
    })
    render(<App />)
    const user = await verifyUser()

    await user.click(screen.getAllByRole('button', { name: '联系商家客服' })[0]!)
    await screen.findByRole('dialog', { name: '正在咨询订单 #W100' })
    expect(await screen.findByText('订单A的历史消息')).toBeInTheDocument()
    expect(screen.queryByText('订单B的历史消息')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: '关闭' }))
    await user.click(screen.getAllByRole('button', { name: '联系商家客服' })[1]!)
    await screen.findByRole('dialog', { name: '正在咨询订单 #W200' })
    expect(await screen.findByText('订单B的历史消息')).toBeInTheDocument()
    expect(screen.queryByText('订单A的历史消息')).not.toBeInTheDocument()
  })
})