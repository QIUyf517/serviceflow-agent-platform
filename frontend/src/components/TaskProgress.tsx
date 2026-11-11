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

export function TaskProgress({ status, plan, recovered }: TaskProgressProps) {
  return (
    <aside className="task-progress" aria-labelledby="progress-title">
      <div className="section-heading compact">
        <div>
          <p className="section-label">当前任务</p>
          <h2 id="progress-title">处理进度</h2>
        </div>
        <span className="task-status">{status || '等待诉求'}</span>
      </div>
      {recovered ? <p className="recovered-note">已从服务端恢复当前任务</p> : null}
      {plan.length ? (
        <ol className="task-rail">
          {plan.map((task) => (
            <li className={`task-${task.status}`} key={task.task_id}>
              <span>{stageLabels[task.target_agent] ?? task.intent}</span>
              <small>{task.status}</small>
            </li>
          ))}
        </ol>
      ) : (
        <p className="empty-copy">说明问题后，这里会显示服务端任务步骤。</p>
      )}
    </aside>
  )
}
