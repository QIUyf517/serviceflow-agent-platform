import { useMutation } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import { developerApi } from '../api/developer'
import type { PersistedTrace } from '../api/developerTypes'
import { ApiError } from '../api/errors'
import { readSessionId } from '../api/sessionStore'
import type { TaskProgress } from '../api/types'
import { useTraceWorkspace } from '../app/TraceWorkspaceContext'
import { TraceInspector } from '../components/developer/TraceInspector'
import { StateNotice } from '../components/StateNotice'

const DEVELOPER_ERRORS: Record<string, string> = {
  session_required: '必须提供客户 session_id 才能读取当前任务或 trace。',
  session_not_found: '客户 session 不存在。',
  identity_required: '该 session 尚未完成身份核验。',
  task_state_not_found: '该 session 还没有可恢复的任务。',
  trace_not_found: '404：trace 不存在，或不属于当前 session。服务端不会透露跨 session 的 trace。',
  database_unavailable: '业务数据库暂时不可用。',
  network_unavailable: '无法连接后端，请确认 FastAPI 已启动。',
}

function developerError(error: unknown): string {
  if (error instanceof ApiError) return DEVELOPER_ERRORS[error.code] ?? `请求失败：${error.code}`
  return '发生未知错误。'
}

export function DeveloperPage() {
  const { latest, capturedAt } = useTraceWorkspace()
  const [sessionId, setSessionId] = useState(() => readSessionId() ?? '')
  const [traceId, setTraceId] = useState(() => latest?.trace_id ?? '')
  const [task, setTask] = useState<TaskProgress | null>(null)
  const [persisted, setPersisted] = useState<PersistedTrace | null>(null)

  const taskMutation = useMutation({
    mutationFn: () => developerApi.currentTask(sessionId.trim()),
    onMutate: () => setTask(null),
    onSuccess: setTask,
  })

  const traceMutation = useMutation({
    mutationFn: () => developerApi.trace(sessionId.trim(), traceId.trim()),
    onMutate: () => setPersisted(null),
    onSuccess: setPersisted,
  })

  function readTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (sessionId.trim()) taskMutation.mutate()
  }

  function readTrace(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (sessionId.trim() && traceId.trim()) traceMutation.mutate()
  }

  return (
    <div className="developer-page">
      <header className="developer-intro">
        <div>
          <p className="status-kicker">只读运行观察台</p>
          <h1>从节点看结果。</h1>
        </div>
        <p>读取仍受客户 session 边界约束；页面不展示完整 Prompt、密钥、客户资料或评测参考动作。</p>
      </header>

      <section className="trace-controls" aria-labelledby="trace-controls-title">
        <div>
          <p className="section-label">服务端查询</p>
          <h2 id="trace-controls-title">恢复任务与 trace</h2>
          <p>session_id 只用于本地演示恢复。trace_id 不进入 URL；查询结果只保留在页面内存中。</p>
        </div>
        <div className="trace-query-forms">
          <form onSubmit={readTask}>
            <label>
              客户 session_id
              <input value={sessionId} onChange={(event) => setSessionId(event.target.value)} autoComplete="off" />
            </label>
            <button className="button button-secondary" type="submit" disabled={!sessionId.trim() || taskMutation.isPending}>读取当前任务</button>
          </form>
          <form onSubmit={readTrace}>
            <label>
              trace_id
              <input value={traceId} onChange={(event) => setTraceId(event.target.value)} autoComplete="off" />
            </label>
            <button className="button button-secondary" type="submit" disabled={!sessionId.trim() || !traceId.trim() || traceMutation.isPending}>读取 trace</button>
          </form>
        </div>
      </section>

      {capturedAt ? <p className="capture-note">同一标签页最新聊天响应：{new Date(capturedAt).toLocaleTimeString('zh-CN')}</p> : null}
      {taskMutation.isPending || traceMutation.isPending ? <StateNotice kind="loading" title="正在读取服务端运行记录" /> : null}
      {taskMutation.error ? <StateNotice kind="error" title="当前任务读取失败">{developerError(taskMutation.error)}</StateNotice> : null}
      {traceMutation.error ? <StateNotice kind="error" title="trace 读取失败">{developerError(traceMutation.error)}</StateNotice> : null}

      <TraceInspector latest={latest} persisted={persisted} task={task} />
    </div>
  )
}
