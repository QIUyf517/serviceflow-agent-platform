import type { TaskPlanItem } from '../api/types'

interface TaskProgressProps {
  status: string
  plan: TaskPlanItem[]
  recovered: boolean
}

const stageLabels: Record<string, string> = {
  order: '核对订单',
  policy: '检查政策',
  resolution: '生成方案',
  guard: '规则校验',
  confirmation: '等待确认',
  executor: '服务端执行',
}
const statusLabels: Record<string, string> = {
  unsupported: '暂无法处理', route_limit: '本次处理受限', clarification: '等待补充信息', needs_clarification: '等待补充信息',
  pending_confirmation: '等待确认', confirmation_rejected: '已拒绝', executed: '已执行', execution_failed: '执行失败',
  queried: '查询完成', query_failed: '查询失败', policy_answered: '政策已答复', policy_failed: '政策依据不足',
  proposal_ready: '方案已生成', ineligible: '不符合规则', content_blocked: '内容已拦截', handoff_created: '已转人工',
  planned: '处理中', partial: '部分完成', triage_error: '需要重新描述', resolution_failed: '方案生成失败',
}
const stepLabels: Record<string, string> = { blocked: '等待条件', pending: '待处理', ready: '可处理', completed: '已完成', failed: '失败', skipped: '已跳过' }

export function TaskProgress({ status, plan, recovered }: TaskProgressProps) {
  return (
    <aside className="task-progress" aria-labelledby="progress-title">
      <div className="section-heading compact">
        <div>
          <p className="section-label">当前任务</p>
          <h2 id="progress-title">处理进度</h2>
        </div>
        <span className="task-status">{statusLabels[status] ?? (status ? '处理中' : '等待诉求')}</span>
      </div>
      {recovered ? <p className="recovered-note">已从服务端恢复当前任务</p> : null}
      {plan.length ? (
        <ol className="task-rail">
          {plan.map((task) => (
            <li className={`task-${task.status}`} key={task.task_id}>
              <span>{stageLabels[task.target_agent] ?? '处理任务'}</span>
              <small>{stepLabels[task.status] ?? '处理中'}</small>
            </li>
          ))}
        </ol>
      ) : (
        <p className="empty-copy">说明问题后，这里会显示服务端任务步骤。</p>
      )}
    </aside>
  )
}
