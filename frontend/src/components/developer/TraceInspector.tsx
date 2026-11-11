import type { PersistedTrace } from '../../api/developerTypes'
import type { ConversationResponse, TaskProgress, TraceEvent } from '../../api/types'
import { safeJson } from '../../utils/safeDisplay'

interface TraceInspectorProps {
  latest: ConversationResponse | null
  persisted: PersistedTrace | null
  task: TaskProgress | null
}

function valueOf(record: Record<string, unknown> | null | undefined, key: string): string | null {
  const value = record?.[key]
  return typeof value === 'string' && value ? value : null
}

function unique(values: Array<string | null | undefined>): string[] {
  return [...new Set(values.filter((value): value is string => Boolean(value)))]
}

function outcomeOf(latest: ConversationResponse | null, events: TraceEvent[]): 'success' | 'failure' | 'waiting' {
  if (latest?.execution_result?.status === 'succeeded' || latest?.task_status === 'completed') return 'success'
  if (
    latest?.failure_reason
    || latest?.task_status === 'failed'
    || events.some((event) => event.status === 'error' || event.status === 'failed' || Boolean(event.error))
  ) return 'failure'
  return 'waiting'
}

function formatMs(value: number | null | undefined): string {
  return typeof value === 'number' ? `${Math.round(value * 100) / 100} ms` : '未提供'
}

function timingText(value: unknown): string {
  return typeof value === 'string' && value ? value : '—'
}

export function TraceInspector({ latest, persisted, task }: TraceInspectorProps) {
  const events = persisted?.events ?? latest?.trace ?? task?.trace ?? []
  const metrics = latest?.metrics
  const plan = task?.task_plan.length ? task.task_plan : latest?.task_plan ?? []
  const nodes = unique([
    ...(metrics?.nodes ?? []),
    ...events.map((event) => event.node),
  ])
  const tools = latest?.tool_results ?? []
  const tokenUsage = persisted ? persisted.token_usage : metrics?.token_usage
  const outcome = outcomeOf(latest, events)
  const requestId = latest?.request_id ?? task?.pending_confirmation?.request_id ?? null
  const ticketId = latest?.ticket ? valueOf(latest.ticket, 'id') ?? valueOf(latest.ticket, 'ticket_no') : null
  const orderId = latest?.execution_result?.order_id
    ?? latest?.pending_confirmation?.order_id
    ?? latest?.resolution_proposal?.order_id
    ?? valueOf(task?.order_context ?? null, 'order_id')

  if (!latest && !persisted && !task) {
    return (
      <section className="trace-empty">
        <p className="section-label">观察窗口</p>
        <h2>还没有可显示的运行记录</h2>
        <p>先在用户服务台发送消息，或使用当前 session_id 读取服务端任务和 trace。</p>
      </section>
    )
  }

  return (
    <div className="trace-inspector">
      <section className="trace-overview">
        <div>
          <p className="section-label">运行判读</p>
          <h2>{outcome === 'success' ? '成功 trace' : outcome === 'failure' ? '失败 trace' : '进行中 / 等待中'}</h2>
        </div>
        <span className={`trace-outcome outcome-${outcome}`}>{outcome}</span>
        <dl className="trace-facts">
          <div><dt>trace_id</dt><dd>{persisted?.trace_id ?? latest?.trace_id ?? '—'}</dd></div>
          <div><dt>task_status</dt><dd>{task?.task_status ?? latest?.task_status ?? '—'}</dd></div>
          <div><dt>current_task</dt><dd>{task?.current_task ?? '—'}</dd></div>
          <div><dt>总耗时</dt><dd>{formatMs(persisted?.elapsed_ms ?? metrics?.elapsed_ms)}</dd></div>
          <div><dt>Provider</dt><dd>{metrics?.provider ?? '当前接口未返回'}</dd></div>
          <div><dt>模型</dt><dd>{metrics?.model ?? '当前接口未返回'}</dd></div>
        </dl>
      </section>

      <section className="trace-section" aria-labelledby="trace-links-title">
        <h3 id="trace-links-title">业务关联</h3>
        <dl className="trace-facts trace-links">
          <div><dt>request_id</dt><dd>{requestId ?? '—'}</dd></div>
          <div><dt>ticket</dt><dd>{ticketId ?? '—'}</dd></div>
          <div><dt>order_id</dt><dd>{orderId ?? '—'}</dd></div>
        </dl>
      </section>

      <section className="trace-section" aria-labelledby="trace-plan-title">
        <div className="trace-section-heading">
          <h3 id="trace-plan-title">任务计划与依赖</h3><span>{plan.length} 项</span>
        </div>
        {plan.length ? (
          <ol className="plan-ledger">
            {plan.map((item) => (
              <li key={item.task_id}>
                <div><strong>{item.intent}</strong><span>{item.status}</span></div>
                <p>{item.target_agent} · 依赖：{item.dependencies.length ? item.dependencies.join('、') : '无'}</p>
              </li>
            ))}
          </ol>
        ) : <p className="empty-copy">服务端没有返回任务计划。</p>}
      </section>

      <section className="trace-section" aria-labelledby="trace-nodes-title">
        <div className="trace-section-heading">
          <h3 id="trace-nodes-title">Agent 节点顺序</h3><span>{nodes.length} 个</span>
        </div>
        {nodes.length ? (
          <ol className="node-sequence">
            {nodes.map((node, index) => <li key={`${node}-${index}`}><span>{index + 1}</span>{node}</li>)}
          </ol>
        ) : <p className="empty-copy">当前记录没有节点序列。</p>}
        {(metrics?.node_timings_ms?.length || events.length) ? (
          <div className="timing-ledger">
            {(metrics?.node_timings_ms ?? events).map((timing, index) => (
              <div key={`${String(timing.node)}-${index}`}>
                <strong>{timing.node ?? `event-${index + 1}`}</strong>
                <span>{formatMs(timing.elapsed_ms)}</span>
                <small>{timingText(('result' in timing ? timing.result : undefined) ?? ('status' in timing ? timing.status : undefined))}</small>
                <small>{timingText(('error_code' in timing ? timing.error_code : undefined) ?? ('code' in timing ? timing.code : undefined))}</small>
              </div>
            ))}
          </div>
        ) : null}
      </section>

      <section className="trace-section" aria-labelledby="trace-tools-title">
        <div className="trace-section-heading">
          <h3 id="trace-tools-title">工具调用</h3><span>{tools.length} 次</span>
        </div>
        {tools.length ? (
          <div className="tool-ledger">
            {tools.map((tool, index) => (
              <details key={`${tool.tool ?? 'tool'}-${index}`}>
                <summary>
                  <strong>{tool.tool ?? `tool-${index + 1}`}</strong>
                  <span>{tool.status ?? 'unknown'} / {tool.code ?? '无错误码'}</span>
                </summary>
                <pre>{safeJson(tool)}</pre>
              </details>
            ))}
          </div>
        ) : <p className="empty-copy">持久化 trace 接口不返回工具结果；请在同一标签页查看最新聊天响应。</p>}
      </section>

      <section className="trace-section" aria-labelledby="trace-runtime-title">
        <h3 id="trace-runtime-title">运行与 token 使用</h3>
        <dl className="trace-facts">
          <div><dt>Provider</dt><dd>{metrics?.provider ?? '当前接口未返回'}</dd></div>
          <div><dt>模型</dt><dd>{metrics?.model ?? '当前接口未返回'}</dd></div>
          <div><dt>token_usage</dt><dd>{tokenUsage ? safeJson(tokenUsage) : '未提供（null）'}</dd></div>
        </dl>
        {metrics?.provider === 'mock_local' ? <p className="mock-disclosure">当前 Provider 是 mock_local，不是 DeepSeek，也没有外部模型调用。</p> : null}
      </section>

      <section className="trace-section" aria-labelledby="trace-events-title">
        <div className="trace-section-heading">
          <h3 id="trace-events-title">脱敏事件</h3><span>{events.length} 条</span>
        </div>
        {events.length ? (
          <ol className="event-ledger">
            {events.map((event, index) => (
              <li key={`${event.node ?? 'event'}-${index}`}>
                <strong>{event.node ?? `event-${index + 1}`}</strong>
                <pre>{safeJson(event)}</pre>
              </li>
            ))}
          </ol>
        ) : <p className="empty-copy">没有 trace 事件。</p>}
      </section>
    </div>
  )
}
