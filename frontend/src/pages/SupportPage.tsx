import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'

import { ApiError } from '../api/errors'
import { newIdempotencyKey } from '../api/idempotency'
import { clearSessionId, readSessionId, saveSessionId } from '../api/sessionStore'
import { serviceflowApi } from '../api/serviceflow'
import type {
  ConversationResponse,
  ExecutionResult,
  IdentityInput,
  PendingConfirmation,
  ResolutionProposal,
  TaskPlanItem,
  TaskProgress,
  Ticket,
} from '../api/types'
import { ConfirmationPanel } from '../components/ConfirmationPanel'
import { ConversationPanel, type ChatMessage } from '../components/ConversationPanel'
import { IdentityGate } from '../components/IdentityGate'
import { OrdersPanel } from '../components/OrdersPanel'
import { StateNotice } from '../components/StateNotice'
import { TaskProgress as TaskProgressPanel } from '../components/TaskProgress'
import { TicketPanel } from '../components/TicketPanel'
import { useTraceWorkspace } from '../app/TraceWorkspaceContext'

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
    finalResponse: progress.final_response,
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
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [chatError, setChatError] = useState<string>()
  const [selectedOrder, setSelectedOrder] = useState<Awaited<ReturnType<typeof serviceflowApi.getOrder>> | null>(null)
  const [detailError, setDetailError] = useState<string>()
  const sendInFlight = useRef(false)
  const ticketKey = useRef(newIdempotencyKey('ticket'))

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
        if (restored.finalResponse) {
          setMessages([
            {
              id: messageId(),
              role: 'assistant',
              text: restored.finalResponse,
              recovered: true,
            },
          ])
        }
        setPhase('verified')
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
        if (
          error instanceof ApiError &&
          (error.code === 'identity_required' || error.code === 'task_state_not_found')
        ) {
          setVerificationNotice(errorMessage(error))
          setPhase('verification')
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

  const ordersQuery = useQuery({
    queryKey: ['orders', sessionId],
    queryFn: serviceflowApi.listOrders,
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

  const chatMutation = useMutation({
    mutationFn: ({ message, requestId }: { message: string; requestId?: string }) =>
      serviceflowApi.chat(message, requestId),
    onMutate: ({ message }) => {
      setChatError(undefined)
      setMessages((current) => [...current, { id: messageId(), role: 'user', text: message }])
    },
    onSuccess: (response) => {
      traceWorkspace.record(response)
      const next = fromConversation(response)
      setView(next)
      if (next.finalResponse) {
        setMessages((current) => [
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
          summary: 'Customer requested human support from the ServiceFlow user page.',
          requested_action: {
            action: view.pendingConfirmation?.action_type ?? 'human_review',
            source: 'web_user_page',
          },
          ...(selectedOrder ? { order_id: selectedOrder.order_id } : {}),
          ...(view.pendingConfirmation ? { request_id: view.pendingConfirmation.request_id } : {}),
        },
        ticketKey.current,
      ),
    onSuccess: (ticket) => setView((current) => ({ ...current, ticket })),
  })

  function sendMessage(message: string, requestId = view.pendingConfirmation?.request_id) {
    if (sendInFlight.current) return
    sendInFlight.current = true
    chatMutation.mutate({ message, ...(requestId ? { requestId } : {}) })
  }

  function decide(decision: 'confirm' | 'reject') {
    const request = view.pendingConfirmation
    if (!request || request.status !== 'pending_confirmation') return
    sendMessage(decision === 'confirm' ? '确认' : '拒绝', request.request_id)
  }

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

  if (phase === 'verification') {
    return (
      <IdentityGate
        isPending={verifyMutation.isPending}
        errorMessage={verifyMutation.error ? errorMessage(verifyMutation.error) : verificationNotice}
        onVerify={(identity) => verifyMutation.mutate(identity)}
      />
    )
  }

  return (
    <div className="support-page">
      <header className="support-intro">
        <div>
          <p className="status-kicker">可信售后协作</p>
          <h1>先看清，再确认。</h1>
        </div>
        <p>订单事实来自业务数据库；取消和退货只有在服务端返回执行结果后才算成功。</p>
      </header>
      <div className="support-grid">
        <div className="support-main">
          <OrdersPanel
            orders={ordersQuery.data}
            selectedOrder={selectedOrder}
            isLoading={ordersQuery.isLoading}
            isDetailLoading={detailMutation.isPending}
            errorMessage={ordersQuery.error ? errorMessage(ordersQuery.error) : undefined}
            detailErrorMessage={detailError}
            onSelect={(orderId) => detailMutation.mutate(orderId)}
          />
          <ConversationPanel
            messages={messages}
            isPending={chatMutation.isPending}
            errorMessage={chatError}
            onSend={sendMessage}
          />
          <ConfirmationPanel
            request={view.pendingConfirmation}
            result={view.executionResult}
            isPending={chatMutation.isPending}
            failureReason={view.failureReason}
            onDecision={decide}
          />
        </div>
        <div className="support-side">
          <TaskProgressPanel status={view.taskStatus} plan={view.taskPlan} recovered={recovered} />
          <TicketPanel
            ticket={view.ticket}
            isPending={ticketMutation.isPending}
            errorMessage={ticketMutation.error ? errorMessage(ticketMutation.error) : undefined}
            onCreate={() => ticketMutation.mutate()}
          />
        </div>
      </div>
    </div>
  )
}
