import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import type {
  ApprovalRecord,
  CloseReason,
  OperatorExecutionResult,
  TicketFilters,
  TicketStatus,
} from '../api/adminTypes'
import { ApiError } from '../api/errors'
import { operatorApi } from '../api/operator'
import { clearOperatorToken, readOperatorToken, saveOperatorToken } from '../api/operatorStore'
import { OperatorGate } from '../components/admin/OperatorGate'
import { TicketCaseFile } from '../components/admin/TicketCaseFile'
import { TicketLedger, type TicketFilterDraft } from '../components/admin/TicketLedger'

const EMPTY_DRAFT: TicketFilterDraft = {
  status: '',
  category: '',
  assignee: '',
  createdFrom: '',
  createdTo: '',
}

const DEFAULT_FILTERS: TicketFilters = { offset: 0, limit: 10 }

const ADMIN_ERRORS: Record<string, string> = {
  operator_token_required: '需要独立的 X-Operator-Token；客户 session 不能代替操作员认证。',
  operator_unauthorized: 'X-Operator-Token 无效；客户 session 不能代替操作员认证。',
  operator_auth_not_configured: '后端尚未配置本地演示操作员 token。',
  ticket_not_found: '工单不存在。',
  ticket_status_transition_invalid: '服务端拒绝了非法状态迁移，工单状态没有变化。',
  ticket_close_reason_required: '关闭或取消工单必须选择合法 close_reason。',
  ticket_terminal: '终态工单不能再分配。',
  approval_request_binding_invalid: '审批与工单或客户请求的绑定不一致。',
  approval_already_decided: '审批已经有决定，不能重复审批。',
  approval_expired: '审批已经过期。',
  operator_approval_required: '人工执行前需要有效的操作员审批。',
  confirmation_required: 'confirmation_required：审批不能替代客户确认，本次人工执行未发生。',
  confirmation_binding_invalid: '客户确认与当前请求不匹配，本次人工执行未发生。',
  execution_in_progress: '相同业务请求正在执行，请等待后再读取结果。',
  database_unavailable: '业务数据库暂时不可用。',
  network_unavailable: '无法连接后端，请确认 FastAPI 已启动。',
}

function adminError(error: unknown): string {
  if (error instanceof ApiError) return ADMIN_ERRORS[error.code] ?? `请求失败：${error.code}`
  return '发生未知错误。'
}

function epoch(value: string): number | undefined {
  if (!value) return undefined
  const parsed = Date.parse(value)
  return Number.isNaN(parsed) ? undefined : Math.floor(parsed / 1_000)
}

export function AdminPage() {
  const queryClient = useQueryClient()
  const [authenticated, setAuthenticated] = useState(() => Boolean(readOperatorToken()))
  const [authVersion, setAuthVersion] = useState(0)
  const [draft, setDraft] = useState<TicketFilterDraft>(EMPTY_DRAFT)
  const [filters, setFilters] = useState<TicketFilters>(DEFAULT_FILTERS)
  const [selectedTicketId, setSelectedTicketId] = useState<string | null>(null)
  const [approval, setApproval] = useState<ApprovalRecord | null>(null)
  const [executionResult, setExecutionResult] = useState<OperatorExecutionResult | null>(null)
  const [actionError, setActionError] = useState<string>()

  const listQuery = useQuery({
    queryKey: ['operator', 'tickets', authVersion, filters],
    queryFn: () => operatorApi.listTickets(filters),
    enabled: authenticated,
    refetchInterval: authenticated ? 5_000 : false,
  })

  const detailQuery = useQuery({
    queryKey: ['operator', 'ticket', authVersion, selectedTicketId],
    queryFn: () => operatorApi.getTicket(selectedTicketId ?? ''),
    enabled: authenticated && Boolean(selectedTicketId),
    refetchInterval: authenticated && selectedTicketId ? 5_000 : false,
    refetchIntervalInBackground: true,
  })

  const auditQuery = useQuery({
    queryKey: ['operator', 'ticket-audit', authVersion, selectedTicketId],
    queryFn: () => operatorApi.getAudit(selectedTicketId ?? ''),
    enabled: authenticated && Boolean(selectedTicketId),
    refetchInterval: authenticated && selectedTicketId ? 5_000 : false,
    refetchIntervalInBackground: true,
  })

  function refreshTicket() {
    void queryClient.invalidateQueries({ queryKey: ['operator', 'tickets'] })
    void queryClient.invalidateQueries({ queryKey: ['operator', 'ticket', authVersion, selectedTicketId] })
    void queryClient.invalidateQueries({ queryKey: ['operator', 'ticket-audit', authVersion, selectedTicketId] })
  }

  const assignMutation = useMutation({
    mutationFn: (assignee: string) => operatorApi.assignTicket(selectedTicketId ?? '', assignee),
    onMutate: () => setActionError(undefined),
    onSuccess: refreshTicket,
    onError: (error) => setActionError(adminError(error)),
  })

  const statusMutation = useMutation({
    mutationFn: ({ status, closeReason }: { status: TicketStatus; closeReason?: CloseReason }) =>
      operatorApi.changeStatus(selectedTicketId ?? '', status, closeReason),
    onMutate: () => setActionError(undefined),
    onSuccess: refreshTicket,
    onError: (error) => setActionError(adminError(error)),
  })

  const approvalMutation = useMutation({
    mutationFn: () => {
      const request = detailQuery.data?.request
      if (!request) throw new ApiError(409, 'ticket_execution_request_required')
      return operatorApi.createApproval(
        selectedTicketId ?? '',
        request.request_id,
        `execute_${request.action}`,
        request.proposed_parameters,
      )
    },
    onMutate: () => setActionError(undefined),
    onSuccess: (result) => {
      setApproval(result)
      refreshTicket()
    },
    onError: (error) => setActionError(adminError(error)),
  })

  const decisionMutation = useMutation({
    mutationFn: ({ decision, reason }: { decision: 'approved' | 'rejected'; reason: string }) => {
      if (!approval) throw new ApiError(404, 'approval_not_found')
      return operatorApi.decideApproval(selectedTicketId ?? '', approval.id, decision, reason)
    },
    onMutate: () => setActionError(undefined),
    onSuccess: (result) => {
      setApproval(result)
      refreshTicket()
    },
    onError: (error) => setActionError(adminError(error)),
  })

  const executeMutation = useMutation({
    mutationFn: () => operatorApi.executeTicket(selectedTicketId ?? ''),
    onMutate: () => {
      setActionError(undefined)
      setExecutionResult(null)
    },
    onSuccess: (result) => {
      setExecutionResult(result)
      refreshTicket()
    },
    onError: (error) => setActionError(adminError(error)),
  })

  const replyMutation = useMutation({
    mutationFn: (content: string) => operatorApi.replyTicket(selectedTicketId ?? '', content),
    onMutate: () => setActionError(undefined),
    onSuccess: refreshTicket,
    onError: (error) => setActionError(adminError(error)),
  })

  const authError = listQuery.error instanceof ApiError && listQuery.error.status === 401
    ? adminError(listQuery.error)
    : undefined

  function unlock(token: string) {
    saveOperatorToken(token)
    setAuthenticated(true)
    setAuthVersion((value) => value + 1)
  }

  function lock() {
    clearOperatorToken()
    setAuthenticated(false)
    setSelectedTicketId(null)
    setApproval(null)
    setExecutionResult(null)
    queryClient.removeQueries({ queryKey: ['operator'] })
  }

  function applyFilters() {
    setFilters({
      offset: 0,
      limit: filters.limit,
      ...(draft.status ? { status: draft.status } : {}),
      ...(draft.category ? { category: draft.category } : {}),
      ...(draft.assignee.trim() ? { assignee: draft.assignee.trim() } : {}),
      ...(epoch(draft.createdFrom) !== undefined ? { createdFrom: epoch(draft.createdFrom) } : {}),
      ...(epoch(draft.createdTo) !== undefined ? { createdTo: epoch(draft.createdTo) } : {}),
    })
    setSelectedTicketId(null)
  }

  function selectTicket(ticketId: string) {
    setSelectedTicketId(ticketId)
    setApproval(null)
    setExecutionResult(null)
    setActionError(undefined)
  }

  if (!authenticated || authError) {
    return <OperatorGate errorMessage={authError} onUnlock={unlock} />
  }

  const isMutating =
    assignMutation.isPending ||
    statusMutation.isPending ||
    approvalMutation.isPending ||
    decisionMutation.isPending ||
    executeMutation.isPending
    || replyMutation.isPending

  return (
    <div className="admin-page">
      <header className="admin-intro">
        <div>
          <p className="status-kicker">人工接管工作区</p>
          <h1>案件先于动作。</h1>
          <p role="status">当前列表 {listQuery.data?.total ?? 0} 张工单，自动检查新请求。</p>
        </div>
        <div>
          <p>本地演示认证，不是生产 IAM。操作员不能代客户确认，审批也不能绕过 ExecutionService。</p>
          <button className="text-button" type="button" onClick={lock}>清除操作员 token</button>
        </div>
      </header>
      <div className="admin-workspace">
        <TicketLedger
          result={listQuery.data}
          selectedTicketId={selectedTicketId}
          draft={draft}
          isLoading={listQuery.isLoading}
          errorMessage={listQuery.error ? adminError(listQuery.error) : undefined}
          onDraftChange={setDraft}
          onFilter={applyFilters}
          onSelect={selectTicket}
          onPage={(direction) => setFilters((current) => ({
            ...current,
            offset: Math.max(0, current.offset + (direction === 'next' ? current.limit : -current.limit)),
          }))}
        />
        <TicketCaseFile
          key={`${selectedTicketId ?? 'none'}-${detailQuery.data?.status ?? 'empty'}`}
          detail={detailQuery.data}
          audit={auditQuery.data?.events}
          isLoading={detailQuery.isLoading || auditQuery.isLoading}
          isMutating={isMutating}
          errorMessage={detailQuery.error ? adminError(detailQuery.error) : auditQuery.error ? adminError(auditQuery.error) : undefined}
          actionError={actionError}
          approval={approval}
          executionResult={executionResult}
          onAssign={(assignee) => assignMutation.mutate(assignee)}
          onStatus={(status, closeReason) => statusMutation.mutate({ status, ...(closeReason ? { closeReason } : {}) })}
          onCreateApproval={() => approvalMutation.mutate()}
          onDecideApproval={(decision, reason) => decisionMutation.mutate({ decision, reason })}
          onExecute={() => executeMutation.mutate()}
          onReply={(content) => replyMutation.mutate(content)}
        />
      </div>
    </div>
  )
}
