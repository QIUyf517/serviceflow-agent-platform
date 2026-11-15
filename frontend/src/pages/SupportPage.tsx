import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'

import { ApiError } from '../api/errors'
import { newIdempotencyKey } from '../api/idempotency'
import {
  clearSessionId,
  clearSupportContext,
  readSessionId,
  readSupportContext,
  saveSessionId,
  saveSupportContext,
} from '../api/sessionStore'
import { serviceflowApi } from '../api/serviceflow'
import type {
  CheckoutResult,
  ConversationResponse,
  ExecutionResult,
  IdentityInput,
  PendingConfirmation,
  Product,
  ProductVariant,
  ResolutionProposal,
  SupportThread,
  TaskPlanItem,
  TaskProgress,
  Ticket,
} from '../api/types'
import { ConfirmationPanel } from '../components/ConfirmationPanel'
import { ConversationPanel, type ChatMessage } from '../components/ConversationPanel'
import { IdentityGate } from '../components/IdentityGate'
import { OrdersPanel } from '../components/OrdersPanel'
import { ProductCatalog } from '../components/ProductCatalog'
import { StateNotice } from '../components/StateNotice'
import { StoreCart, type CartLine } from '../components/StoreCart'
import { SupportDialog } from '../components/SupportDialog'
import { TaskProgress as TaskProgressPanel } from '../components/TaskProgress'
import { TicketPanel } from '../components/TicketPanel'
import { useTraceWorkspace } from '../app/TraceWorkspaceContext'
import { productName } from '../utils/productLocale'

type PagePhase = 'booting' | 'verification' | 'verified' | 'error'

interface ViewState {
  taskStatus: string
  taskPlan: TaskPlanItem[]
  pendingConfirmation: PendingConfirmation | null
  executionResult: ExecutionResult | null
  resolutionProposal: ResolutionProposal | null
  failureReason: string | null
  ticket: Ticket | null
  finalResponse: string
}

const EMPTY_VIEW: ViewState = {
  taskStatus: '',
  taskPlan: [],
  pendingConfirmation: null,
  executionResult: null,
  resolutionProposal: null,
  failureReason: null,
  ticket: null,
  finalResponse: '',
}

function fromConversation(response: ConversationResponse): ViewState {
  return {
    taskStatus: response.task_status,
    taskPlan: response.task_plan,
    pendingConfirmation: response.pending_confirmation,
    executionResult: response.execution_result,
    resolutionProposal: response.resolution_proposal,
    failureReason: response.failure_reason,
    ticket: response.ticket,
    finalResponse: response.final_response,
  }
}

function fromProgress(progress: TaskProgress): ViewState {
  return {
    taskStatus: progress.task_status,
    taskPlan: progress.task_plan,
    pendingConfirmation: progress.pending_confirmation,
    executionResult: progress.execution_result,
    resolutionProposal: progress.resolution_proposal,
    failureReason: null,
    ticket: null,
    finalResponse: /Routing limit reached|Read-only query completed|Please provide:|Cancellation rejected|Action is pending confirmation/.test(progress.final_response)
      ? '已恢复上一轮处理状态，请继续描述你的需求。'
      : progress.final_response,
  }
}

const ERROR_MESSAGES: Record<string, string> = {
  identity_required: '403：身份核验尚未完成或已失效，请重新核验。',
  identity_not_verified: '提供的信息与唯一模拟账户不匹配。',
  identity_evidence_required: '请填写邮箱，或完整填写姓名与邮编。',
  session_not_found: '404：服务会话不存在，页面将创建新会话。',
  task_state_not_found: '404：这个会话还没有可恢复的任务。',
  order_not_found: '404：没有找到该订单，或它不属于当前账户。',
  network_unavailable: '无法连接后端，请确认 FastAPI 已在 127.0.0.1:8000 启动。',
  database_unavailable: '业务数据库暂时不可用，请稍后重试。',
  confirmation_expired: '确认已过期，操作没有执行。请重新发起方案。',
  order_changed: '订单状态已经变化，旧方案没有执行。请重新查询。',
  variant_unavailable: '所选商品规格已经不可购买，请移除后重新选择。',
  payment_method_invalid: '支付方式不可用，请选择当前账户中的支付方式。',
  gift_card_insufficient: '礼品卡余额不足，本次订单没有创建。',
  idempotency_key_conflict: '结算内容已经变化，请重新提交订单。',
  checkout_quantity_invalid: '单个规格最多购买 10 件，整笔订单最多 20 件。',
  ticket_message_idempotency_conflict: '这条人工消息的重试内容不一致，请重新发送。',
  ticket_message_idempotency_key_invalid: '人工消息请求标识无效，请重新发送。',
  ticket_terminal: '人工工单已经结束，请重新发起咨询。',
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return ERROR_MESSAGES[error.code] ?? `请求失败：${error.code}`
  return '发生未知错误，请重试。'
}

function messageId(): string {
  return crypto.randomUUID()
}

export function SupportPage() {
  const queryClient = useQueryClient()
  const traceWorkspace = useTraceWorkspace()
  const [phase, setPhase] = useState<PagePhase>('booting')
  const [sessionId, setSessionId] = useState<string | null>(() => readSessionId())
  const [bootError, setBootError] = useState<string>()
  const [verificationNotice, setVerificationNotice] = useState<string>()
  const [retryVersion, setRetryVersion] = useState(0)
  const [recovered, setRecovered] = useState(false)
  const [view, setView] = useState<ViewState>(EMPTY_VIEW)
  const [localMessages, setLocalMessages] = useState<ChatMessage[]>([])
  const [chatError, setChatError] = useState<string>()
  const [selectedProduct, setSelectedProduct] = useState<Awaited<ReturnType<typeof serviceflowApi.getProduct>> | null>(null)
  const [productDialogOpen, setProductDialogOpen] = useState(false)
  const [productDetailError, setProductDetailError] = useState<string>()
  const [selectedOrder, setSelectedOrder] = useState<Awaited<ReturnType<typeof serviceflowApi.getOrder>> | null>(null)
  const [detailError, setDetailError] = useState<string>()
  const [cartLines, setCartLines] = useState<CartLine[]>([])
  const [checkoutError, setCheckoutError] = useState<string>()
  const [checkoutResult, setCheckoutResult] = useState<CheckoutResult | null>(null)
  const [supportDialogOpen, setSupportDialogOpen] = useState(false)
  const [supportOrderId, setSupportOrderId] = useState<string | null>(null)
  const [supportThread, setSupportThread] = useState<SupportThread | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const sendInFlight = useRef(false)
  const ticketKey = useRef(newIdempotencyKey('ticket'))
  const checkoutKey = useRef(newIdempotencyKey('checkout'))

  const customerTicketsQuery = useQuery({
    queryKey: ['customer-tickets', sessionId],
    queryFn: serviceflowApi.customerTickets,
    enabled: phase === 'verified' && supportDialogOpen,
    refetchInterval: supportDialogOpen ? 5_000 : false,
  })
  const threadTickets = supportThread
    ? customerTicketsQuery.data?.filter((ticket) => ticket.thread_id === supportThread.thread_id)
    : undefined
  const serverActiveTicket = threadTickets?.find(
    (ticket) => ticket.status !== 'closed' && ticket.status !== 'cancelled',
  )
  const chatTicket = view.ticket && view.ticket.thread_id === supportThread?.thread_id
    ? view.ticket
    : null
  const activeTicket = serverActiveTicket ?? (chatTicket
    ? {
        id: chatTicket.id,
        ticket_no: chatTicket.ticket_no,
        status: chatTicket.status,
        order_id: chatTicket.order_id ?? null,
        thread_id: chatTicket.thread_id ?? supportThread?.thread_id ?? null,
      }
    : null)
  const activeTicketId = activeTicket?.id
  const humanHandoffActive = Boolean(
    activeTicket
      && activeTicket.status !== 'closed'
      && activeTicket.status !== 'cancelled',
  )
  const threadConversationQuery = useQuery({
    queryKey: ['thread-conversation', sessionId, supportOrderId, supportThread?.thread_id],
    queryFn: () => serviceflowApi.customerConversation(supportOrderId),
    enabled: phase === 'verified' && supportDialogOpen && Boolean(supportThread),
    refetchInterval: supportDialogOpen ? 5_000 : false,
    retry: false,
  })
  // The thread history is the only message source across orders; local messages
  // only bridge the first turn before the server list contains it.
  const threadMessages: ChatMessage[] = threadConversationQuery.data?.length
    ? threadConversationQuery.data.map((item) => ({
        id: `thread-${item.sequence}`,
        role: item.role,
        text: item.content,
      }))
    : localMessages
  const supportRequestSeq = useRef(0)

  async function bindSupportThread(orderId: string | null) {
    const seq = ++supportRequestSeq.current
    setSupportOrderId(orderId)
    setSupportDialogOpen(true)
    setSupportThread(null)
    setLocalMessages([])
    setChatError(undefined)
    // Confirmation state belongs to one thread and must never follow the customer
    // to another order.
    setView(EMPTY_VIEW)
    setRecovered(false)
    try {
      const thread = await serviceflowApi.openSupportThread(orderId)
      if (seq !== supportRequestSeq.current) return
      setSupportThread(thread)
      const progress = await serviceflowApi.currentTask(orderId).catch(() => null)
      if (seq !== supportRequestSeq.current || !progress) return
      setView(fromProgress(progress))
      setRecovered(true)
    } catch (error) {
      if (seq === supportRequestSeq.current) setChatError(errorMessage(error))
    }
  }

  useEffect(() => {
    let cancelled = false

    async function createNewSession() {
      const created = await serviceflowApi.createSession()
      if (cancelled) return
      saveSessionId(created.session_id)
      setSessionId(created.session_id)
      setVerificationNotice(undefined)
      setPhase('verification')
    }

    async function bootstrap() {
      setPhase('booting')
      setBootError(undefined)
      const savedSession = readSessionId()
      if (!savedSession) {
        try {
          await createNewSession()
        } catch (error) {
          if (!cancelled) {
            setBootError(errorMessage(error))
            setPhase('error')
          }
        }
        return
      }

      setSessionId(savedSession)
      try {
        const progress = await serviceflowApi.currentTask()
        if (cancelled) return
        const restored = fromProgress(progress)
        setView(restored)
        setRecovered(true)
        setPhase('verified')
        if (restored.pendingConfirmation) {
          const restoredOrder = progress.thread_kind === 'order'
            ? progress.thread_order_id ?? restored.pendingConfirmation.order_id
            : null
          void bindSupportThread(restoredOrder)
        } else {
          const savedContext = readSupportContext()
          if (savedContext !== null) {
            void bindSupportThread(savedContext === 'general' ? null : savedContext)
          }
        }
      } catch (error) {
        if (cancelled) return
        if (error instanceof ApiError && error.code === 'session_not_found') {
          clearSessionId()
          setSessionId(null)
          try {
            await createNewSession()
          } catch (createError) {
            if (!cancelled) {
              setBootError(errorMessage(createError))
              setPhase('error')
            }
          }
          return
        }
        if (error instanceof ApiError && error.code === 'identity_required') {
          setVerificationNotice(undefined)
          setPhase('verification')
          return
        }
        if (error instanceof ApiError && error.code === 'task_state_not_found') {
          setVerificationNotice(undefined)
          setPhase('verified')
          const savedContext = readSupportContext()
          if (savedContext !== null) {
            void bindSupportThread(savedContext === 'general' ? null : savedContext)
          }
          return
        }
        setBootError(errorMessage(error))
        setPhase('error')
      }
    }

    void bootstrap()
    return () => {
      cancelled = true
    }
  }, [retryVersion])

  const productsQuery = useQuery({
    queryKey: ['products', sessionId],
    queryFn: serviceflowApi.listProducts,
    enabled: Boolean(sessionId) && phase !== 'booting' && phase !== 'error',
  })

  const ordersQuery = useQuery({
    queryKey: ['orders', sessionId],
    queryFn: serviceflowApi.listOrders,
    enabled: phase === 'verified' && Boolean(sessionId),
  })

  const userQuery = useQuery({
    queryKey: ['current-user', sessionId],
    queryFn: serviceflowApi.currentUser,
    enabled: phase === 'verified' && Boolean(sessionId),
  })

  const verifyMutation = useMutation({
    mutationFn: (identity: IdentityInput) => {
      if (!sessionId) throw new ApiError(404, 'session_not_found')
      return serviceflowApi.verifyIdentity(sessionId, identity)
    },
    onSuccess: () => {
      setVerificationNotice(undefined)
      setPhase('verified')
      setRecovered(false)
      void queryClient.invalidateQueries({ queryKey: ['orders', sessionId] })
      void queryClient.invalidateQueries({ queryKey: ['current-user', sessionId] })
      const savedContext = readSupportContext()
      if (savedContext !== null) {
        void bindSupportThread(savedContext === 'general' ? null : savedContext)
      }
    },
  })

  const detailMutation = useMutation({
    mutationFn: serviceflowApi.getOrder,
    onMutate: () => {
      setDetailError(undefined)
      setSelectedOrder(null)
    },
    onSuccess: setSelectedOrder,
    onError: (error) => setDetailError(errorMessage(error)),
  })

  const productDetailMutation = useMutation({
    mutationFn: serviceflowApi.getProduct,
    onMutate: () => {
      setProductDetailError(undefined)
      setSelectedProduct(null)
    },
    onSuccess: setSelectedProduct,
    onError: (error) => setProductDetailError(errorMessage(error)),
  })

  const switchCustomerMutation = useMutation({
    mutationFn: serviceflowApi.createSession,
    onSuccess: (created) => {
      clearSessionId()
      saveSessionId(created.session_id)
      setSessionId(created.session_id)
      setPhase('verification')
      setVerificationNotice('已建立新的模拟顾客会话，请重新核验身份。')
      setRecovered(false)
      setView(EMPTY_VIEW)
      setLocalMessages([])
      setChatError(undefined)
      setSelectedOrder(null)
      setDetailError(undefined)
      setSelectedProduct(null)
      setProductDialogOpen(false)
      setProductDetailError(undefined)
      setCartLines([])
      setCheckoutError(undefined)
      setCheckoutResult(null)
      setSupportDialogOpen(false)
      setSupportOrderId(null)
      setSupportThread(null)
      clearSupportContext()
      ticketKey.current = newIdempotencyKey('ticket')
      checkoutKey.current = newIdempotencyKey('checkout')
      sendInFlight.current = false
      traceWorkspace.clear()
      queryClient.removeQueries({ queryKey: ['orders'] })
      queryClient.removeQueries({ queryKey: ['current-user'] })
    },
  })

  const checkoutMutation = useMutation({
    mutationFn: (paymentMethodId: string) =>
      serviceflowApi.checkout(
        {
          items: cartLines.map((line) => ({
            item_id: line.variant.item_id,
            quantity: line.quantity,
          })),
          payment_method_id: paymentMethodId,
        },
        checkoutKey.current,
      ),
    onMutate: () => {
      setCheckoutError(undefined)
      setCheckoutResult(null)
    },
    onSuccess: (result) => {
      setCheckoutResult(result)
      setCartLines([])
      setSelectedOrder(result.order)
      checkoutKey.current = newIdempotencyKey('checkout')
      void queryClient.invalidateQueries({ queryKey: ['orders', sessionId] })
      void queryClient.invalidateQueries({ queryKey: ['current-user', sessionId] })
    },
    onError: (error) => setCheckoutError(errorMessage(error)),
  })

  const chatMutation = useMutation({
    mutationFn: ({ message, requestId }: { message: string; requestId?: string }) =>
      serviceflowApi.chat(message, requestId, supportOrderId),
    onMutate: ({ message }) => {
      setChatError(undefined)
      setLocalMessages((current) => [...current, { id: messageId(), role: 'user', text: message }])
    },
    onSuccess: (response) => {
      traceWorkspace.record(response)
      const next = fromConversation(response)
      setView(next)
      if (next.ticket) void queryClient.invalidateQueries({ queryKey: ['customer-tickets', sessionId] })
      if (next.finalResponse) {
        setLocalMessages((current) => [
          ...current,
          { id: messageId(), role: 'assistant', text: next.finalResponse },
        ])
      }
      if (next.executionResult?.status === 'succeeded') {
        void queryClient.invalidateQueries({ queryKey: ['orders', sessionId] })
        if (selectedOrder?.order_id === next.executionResult.order_id) {
          detailMutation.mutate(next.executionResult.order_id)
        }
      }
      void queryClient.invalidateQueries({
        queryKey: ['thread-conversation', sessionId, supportOrderId],
      })
    },
    onError: (error) => setChatError(errorMessage(error)),
    onSettled: () => {
      sendInFlight.current = false
    },
  })

  const ticketMessageMutation = useMutation({
    mutationFn: ({ ticketId, message, idempotencyKey }: { ticketId: string; message: string; idempotencyKey: string }) =>
      serviceflowApi.replyToTicket(ticketId, message, idempotencyKey),
    onMutate: ({ message }) => {
      setChatError(undefined)
      setLocalMessages((current) => [...current, { id: messageId(), role: 'user', text: message }])
    },
    onSuccess: (response) => {
      setView((current) => current.ticket
        ? { ...current, ticket: { ...current.ticket, status: response.status } }
        : current)
      void queryClient.invalidateQueries({ queryKey: ['customer-tickets', sessionId] })
      void queryClient.invalidateQueries({
        queryKey: ['thread-conversation', sessionId, supportOrderId],
      })
    },
    onError: (error) => setChatError(errorMessage(error)),
    onSettled: () => {
      sendInFlight.current = false
    },
  })

  const ticketMutation = useMutation({
    mutationFn: () =>
      serviceflowApi.createTicket(
        {
          category: 'customer_requested_human',
          severity: 'medium',
          priority: 3,
          reason_code: 'customer_requested_human',
          summary: supportOrderId
            ? `顾客就订单 ${supportOrderId} 请求人工客服。`
            : '顾客在通用咨询中请求人工客服。',
          requested_action: {
            action: view.pendingConfirmation?.action_type ?? 'human_review',
            source: 'web_user_page',
          },
          ...(supportOrderId ? { order_id: supportOrderId } : {}),
          ...(view.pendingConfirmation ? { request_id: view.pendingConfirmation.request_id } : {}),
          ...(supportThread ? { thread_id: supportThread.thread_id } : {}),
        },
        ticketKey.current,
      ),
    onSuccess: (ticket) => {
      setView((current) => ({ ...current, ticket }))
      void queryClient.invalidateQueries({ queryKey: ['customer-tickets', sessionId] })
    },
  })

  function resetCheckoutState() {
    checkoutKey.current = newIdempotencyKey('checkout')
    setCheckoutError(undefined)
    setCheckoutResult(null)
  }

  function addToCart(product: Product, variant: ProductVariant) {
    resetCheckoutState()
    setCartLines((current) => {
      const existing = current.find((line) => line.variant.item_id === variant.item_id)
      if (existing) {
        return current.map((line) =>
          line.variant.item_id === variant.item_id
            ? { ...line, quantity: Math.min(10, line.quantity + 1) }
            : line,
        )
      }
      return [
        ...current,
        {
          productId: product.product_id,
          productName: product.name,
          variant,
          quantity: 1,
        },
      ]
    })
  }

  function changeCartQuantity(itemId: string, quantity: number) {
    resetCheckoutState()
    setCartLines((current) =>
      current.map((line) => line.variant.item_id === itemId ? { ...line, quantity } : line),
    )
  }

  function removeCartLine(itemId: string) {
    resetCheckoutState()
    setCartLines((current) => current.filter((line) => line.variant.item_id !== itemId))
  }

  function openSupport(orderId: string) {
    setSupportOrderId(orderId)
    setSupportDialogOpen(true)
    saveSupportContext(orderId)
    if (selectedOrder?.order_id !== orderId) detailMutation.mutate(orderId)
    void bindSupportThread(orderId)
  }

  function openGeneralSupport() {
    setSupportOrderId(null)
    setSupportDialogOpen(true)
    saveSupportContext(null)
    void bindSupportThread(null)
  }

  const closeSupport = useCallback(() => {
    setSupportDialogOpen(false)
    setSupportThread(null)
    clearSupportContext()
  }, [])
  const closeProduct = useCallback(() => {
    setProductDialogOpen(false)
    setSelectedProduct(null)
    setProductDetailError(undefined)
  }, [])

  function openProduct(productId: string) {
    setProductDialogOpen(true)
    productDetailMutation.mutate(productId)
  }

  function sendMessage(message: string, requestId = view.pendingConfirmation?.request_id) {
    if (sendInFlight.current) return
    sendInFlight.current = true
    if (!requestId && humanHandoffActive && activeTicketId) {
      ticketMessageMutation.mutate({
        ticketId: activeTicketId,
        message,
        idempotencyKey: newIdempotencyKey('customer-message'),
      })
      return
    }
    chatMutation.mutate({ message, ...(requestId ? { requestId } : {}) })
  }

  function decide(decision: 'confirm' | 'reject') {
    const request = view.pendingConfirmation
    if (!request || request.status !== 'pending_confirmation') return
    sendMessage(decision === 'confirm' ? '确认' : '拒绝', request.request_id)
  }

  const normalizedSearch = searchQuery.trim().toLocaleLowerCase('zh-CN')
  const visibleProducts = productsQuery.data?.filter((product) => {
    if (!normalizedSearch) return true
    return productName(product.name, product.product_id)
      .toLocaleLowerCase('zh-CN')
      .includes(normalizedSearch)
  })

  if (phase === 'booting') {
    return (
      <div className="page-state-wrap">
        <StateNotice kind="loading" title="正在连接服务端会话">
          只会在本机保存随机 session_id，不保存客户资料或确认记录。
        </StateNotice>
      </div>
    )
  }

  if (phase === 'error') {
    return (
      <div className="page-state-wrap">
        <StateNotice
          kind="error"
          title="服务台暂时无法启动"
          action={
            <button className="button button-secondary" type="button" onClick={() => setRetryVersion((value) => value + 1)}>
              重试连接
            </button>
          }
        >
          {bootError}
        </StateNotice>
      </div>
    )
  }

  return (
    <div className="store-page">
      <div className="store-utility">
        <span>欢迎来到 ServiceFlow 模拟商城</span>
        <nav aria-label="商城快捷导航">
          <a href="#catalog">商品分类</a>
          <a href="#cart">购物车（{cartLines.reduce((sum, line) => sum + line.quantity, 0)}）</a>
          <a href="#customer-service">我的订单</a>
        </nav>
      </div>

      <header className="commerce-header">
        <div>
          <p>ServiceFlow</p>
          <strong>安心选 · 放心问</strong>
        </div>
        <label className="store-search">
          <span className="sr-only">搜索商品</span>
          <input
            type="search"
            value={searchQuery}
            placeholder="搜索中文商品名"
            onChange={(event) => setSearchQuery(event.target.value)}
          />
          <b>搜索</b>
        </label>
        <a className="header-cart" href="#cart">购物车 <strong>{cartLines.length}</strong></a>
      </header>

      <nav className="category-strip" aria-label="商品分类">
        <strong>全部商品</strong>
        <span>数码家电</span>
        <span>居家生活</span>
        <span>运动户外</span>
        <span>服饰个护</span>
      </nav>

      <div className="store-shop-layout">
        <ProductCatalog
          products={visibleProducts}
          selectedProduct={selectedProduct}
          isDetailOpen={productDialogOpen}
          isLoading={productsQuery.isLoading}
          isDetailLoading={productDetailMutation.isPending}
          errorMessage={productsQuery.error ? errorMessage(productsQuery.error) : undefined}
          detailErrorMessage={productDetailError}
          onSelect={openProduct}
          onAddToCart={addToCart}
          onCloseDetail={closeProduct}
        />
        <StoreCart
          lines={cartLines}
          verified={phase === 'verified'}
          profile={userQuery.data}
          isProfileLoading={userQuery.isLoading}
          isCheckingOut={checkoutMutation.isPending}
          checkoutError={checkoutError}
          checkoutResult={checkoutResult}
          onQuantityChange={changeCartQuantity}
          onRemove={removeCartLine}
          onCheckout={(paymentMethodId) => checkoutMutation.mutate(paymentMethodId)}
        />
      </div>

      <section className="store-service" id="customer-service" aria-labelledby="service-title">
        <header className="service-heading">
          <div>
            <h2 id="service-title">我的订单</h2>
          </div>
          <div className="customer-session-state">
            <button className="text-button" type="button" onClick={openGeneralSupport}>
              通用咨询
            </button>
            {phase === 'verified' ? (
              <>
                <span>身份已核验</span>
                <button
                  className="text-button"
                  type="button"
                  disabled={switchCustomerMutation.isPending}
                  onClick={() => switchCustomerMutation.mutate()}
                >
                  {switchCustomerMutation.isPending ? '正在切换…' : '切换模拟顾客'}
                </button>
              </>
            ) : null}
          </div>
        </header>

        {phase === 'verification' ? (
          <IdentityGate
            isPending={verifyMutation.isPending}
            errorMessage={verifyMutation.error ? errorMessage(verifyMutation.error) : verificationNotice}
            onVerify={(identity) => verifyMutation.mutate(identity)}
          />
        ) : null}

        {phase === 'verified' ? (
          <OrdersPanel
            orders={ordersQuery.data}
            selectedOrder={selectedOrder}
            isLoading={ordersQuery.isLoading}
            isDetailLoading={detailMutation.isPending}
            errorMessage={ordersQuery.error ? errorMessage(ordersQuery.error) : undefined}
            detailErrorMessage={detailError}
            onSelect={(orderId) => detailMutation.mutate(orderId)}
            onContactSupport={openSupport}
          />
        ) : null}
      </section>

      <SupportDialog open={supportDialogOpen && (phase === 'verified' || supportOrderId === null)} orderId={supportOrderId} onClose={closeSupport}>
        <div className="support-dialog-grid">
          <div>
              <ConversationPanel
                messages={threadMessages}
                isPending={chatMutation.isPending || ticketMessageMutation.isPending}
                errorMessage={chatError}
                onSend={sendMessage}
              />
              <ConfirmationPanel
                request={view.pendingConfirmation}
                result={view.executionResult}
                isPending={chatMutation.isPending || ticketMessageMutation.isPending}
                failureReason={view.failureReason}
                onDecision={decide}
              />
          </div>
          <aside>
              <TaskProgressPanel status={view.taskStatus} plan={view.taskPlan} recovered={recovered} />
              <TicketPanel
                ticket={activeTicket ? { id: activeTicket.id, ticket_no: activeTicket.ticket_no, status: activeTicket.status } : null}
                isPending={ticketMutation.isPending}
                errorMessage={ticketMutation.error ? errorMessage(ticketMutation.error) : undefined}
                onCreate={() => ticketMutation.mutate()}
              />
          </aside>
        </div>
      </SupportDialog>
    </div>
  )
}
