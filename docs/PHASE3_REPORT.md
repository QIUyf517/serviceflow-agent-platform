# 阶段 3：工单、持久化与人工接管验收报告

日期：2026-11-09

## 1. 范围与结论

本阶段只实现工单、会话/图状态持久化、写操作恢复、人工接管、审批和故障注入。没有进入阶段 4/5，没有新增修改/换货执行，没有修改 τ-bench 官方数据、任务、工具或评分器。

最终验收：真实 PostgreSQL 全套 pytest **204 passed、0 failed、0 skipped**；`ruff check backend scripts tests` 通过；阶段 3 与全套随机测试 schema 残留均为 **0**；外部 LLM 调用 **0**。阶段 3 可标记完成。

## 2. 改动清单

### 3.1 数据模型

- `backend/app/database.py`
  - 新增 `tickets`、`messages`、`approvals`、`audit_events` SQLAlchemy 模型。
  - PostgreSQL 使用 JSONB，SQLite 显式测试替身使用 JSON。
  - 在既有 `execution_requests` 非破坏性追加租约字段。
  - seed reset 采用外键安全删除顺序；普通启动只 `create_all`，不删除历史数据。
- `tests/test_phase3_data_models.py`
  - 验证 SQLite/PostgreSQL 约束、索引、JSONB、旧 `agent_conversations` 保留和 reset 行为。

没有重建、改名或迁移 `users`、`products`、`orders`、`service_sessions`、`operation_proposals`、`operation_audit`、`execution_requests`、`confirmation_records`、`execution_audit_events`、`chat_traces`、`policy_documents`、`policy_chunks`、`agent_conversations` 的历史数据。

### 3.2 会话与图状态持久化

- `backend/app/multi_agent/checkpointing.py`
  - 官方 `langgraph-checkpoint-postgres` `PostgresSaver`。
  - psycopg 连接池复用 `DATABASE_URL`；随机 schema 测试使用受校验的 `search_path`。
  - serializer 采用应用 Pydantic 类型 allowlist。
- `backend/app/multi_agent/message_store.py`
  - 事务化规范消息 sequence。
  - checkpoint 前脱敏邮箱、地址、支付凭据和 API secret。
- `backend/app/multi_agent/state.py`、`workflow.py`、`conversation.py`、`main.py`
  - `graph.compile(checkpointer=...)`。
  - 服务端强制 `thread_id == session_id`。
  - `SessionStateStore` 仅作可选缓存；缓存未命中从 checkpoint 重建。
  - 进程重启后恢复澄清、未完成 `task_plan`、执行请求和等待确认绑定。
  - 订单/政策完整文本等瞬态字段不作为 checkpoint 授权事实；政策引用从数据库重新水合。
  - store 支持显式 `close`、上下文管理和短生命周期析构清理 psycopg pool。
- 依赖与配置：`backend/pyproject.toml`、`requirements-dev.lock`、`backend/app/config.py`、`.env.example`。
- `tests/test_phase3_persistence.py`
  - 真实 PostgreSQL 三次新 store 模拟重启并恢复三类状态。

### 3.3 写操作可靠性与失败补偿

- `backend/app/multi_agent/execution.py`
  - 继续以唯一 `ExecutionService` 作为取消/退货写入口。
  - 短事务领取执行租约；业务事务重新读取身份、确认、订单、row_version 和规则。
  - 可重试：连接中断、锁超时、序列化/死锁等瞬时数据库错误。
  - 不可重试：规则/绑定冲突、越权、订单变化、幂等键冲突。
  - 重试次数、退避、租约、锁超时和 statement timeout 可配置。
  - 成功、失败和恢复均保留细粒度执行审计；恢复同时写统一审计。
- `tests/test_phase3_execution_recovery.py`
  - SQLite 和真实 PostgreSQL 的租约中断、超时重试、订单变化、旧表补列测试。

### 3.4 工单与人工接管

- `backend/app/ticketing.py`
  - 幂等建单、脱敏投影、分页过滤、详情、分配、状态流转、关闭原因、审批和统一审计。
- `backend/app/main.py`
  - 工单/审批 REST API 和人工代触发执行 API。
  - `X-Operator-Token` 独立于 `X-Session-Id`，明确为演示机制。
- `backend/app/multi_agent/conversation.py`
  - 确定性接管触发；回复固定声明“已创建工单，尚未处理完成”。
- `tests/test_phase3_tickets.py`
  - 权限边界、状态机、脱敏、触发条件、审批与确认关系、真实 PostgreSQL 生命周期。

### 3.5 故障注入

- `scripts/inject_phase3_failures.py`
  - 只接受 `_demo` PostgreSQL，使用合成数据和随机 `phase3_failures_*` schema。
  - `finally` 清理，不读取/写入官方数据目录。
- `tests/test_phase3_failures.py`
  - SQLite 安全失败和真实 PostgreSQL 全场景验收。

### 3.6 文档与验收

- 更新 `README.md`、`TASKS.md`。
- 新增本报告。
- 阶段 2 未提交改动先提交为 `58be2fc feat: complete ServiceFlow phase 2 multi-agent workflows`。
- 阶段 3 最终提交仅本地创建，不推送。

## 3. 表结构

### `tickets`

字段：`id`、唯一可读 `ticket_no`、`session_id`、可空 `user_id/order_id/request_id`、`category`、`severity`、`priority`、`status`、`reason_code`、脱敏 `summary`、JSONB `requested_action`、`agent_state_digest`、可空 `assignee`、`created_at/updated_at/closed_at`、`close_reason`、唯一 `idempotency_key`。

category：`unsupported_request`、`high_risk`、`rule_conflict`、`execution_failed`、`clarification_exhausted`、`customer_requested_human`。

status：`open`、`assigned`、`in_progress`、`waiting_customer`、`resolved`、`closed`、`cancelled`。

close reason：`resolved_by_agent`、`resolved_by_operator`、`customer_unresponsive`、`duplicate`、`rejected`、`out_of_scope`。

### `messages`

字段：`id`、`session_id`、可空 `ticket_id`、`role`、`content`、JSONB `meta`、`trace_id`、`sequence`、`created_at`。`(session_id, sequence)` 唯一，并有 `(session_id, created_at)` 索引。`agent_conversations` 保留作过渡兼容。

### `approvals`

字段：`id`、`ticket_id`、可空 `request_id`、`action`、JSONB `proposed_params`、`status`、`operator_id`、`decision_reason`、`created_at/decided_at/expires_at`。工单/请求/动作组合防重复；无请求的审批另有 partial unique index。

### `audit_events`

统一追加事件：`ticket_created`、`ticket_assigned`、`ticket_status_changed`、`approval_requested`、`approval_decided`、`handoff_started`、`handoff_returned`、`recovery_attempted`、`recovery_succeeded`、`recovery_failed`。

`audit_events` 记录跨域工单、接管、审批和恢复摘要；`execution_audit_events` 继续记录请求/方案/确认/订单前后状态等细粒度执行生命周期。两者并存，不迁移历史事件，也不互相替代。

## 4. 关键设计决策

### Checkpointer 选型

使用官方同步 `PostgresSaver`，因为现有 FastAPI/SQLAlchemy 执行路径为同步路径，且项目已经以 PostgreSQL 为生产优先数据库。SQLite 仅使用 `InMemorySaver` 作为显式测试替身，不宣称具有跨进程恢复能力。

### 恢复语义

checkpoint 恢复的是编排状态，不是业务 Exactly-once。恢复后的任何写操作必须重新经过：

1. 服务端 session 身份绑定；
2. 订单归属校验；
3. execution request 与 confirmation record 绑定及有效期；
4. 当前订单 `row_version`；
5. 当前 `RetailService` 硬规则；
6. 数据库事务、幂等键和审计。

checkpoint 不保存完整客户资料、完整地址、支付凭据或密钥。`messages` 表可以保存会话原文，但工单详情和 checkpoint 只返回/保存脱敏投影；访问仍受操作员边界控制。

### 工单状态机

```mermaid
stateDiagram-v2
  [*] --> open
  open --> assigned
  open --> cancelled
  assigned --> in_progress
  assigned --> cancelled
  in_progress --> waiting_customer
  in_progress --> resolved
  in_progress --> cancelled
  waiting_customer --> in_progress
  waiting_customer --> resolved
  waiting_customer --> cancelled
  resolved --> in_progress
  resolved --> closed
  closed --> [*]
  cancelled --> [*]
```

非法迁移返回 `ticket_status_transition_invalid`。进入 `closed/cancelled` 必须提供分类原因。建单幂等键由服务端问题身份构造或由显式 API 提供并受唯一约束保护。

### 审批与客户确认

审批表达操作员内部治理决定；客户确认表达该客户对具体操作摘要的授权。两者必须分离：

- 操作员不能创建 confirmation record。
- 审批通过后，如果客户确认不存在、过期、已消费或绑定不一致，`ExecutionService` 仍拒绝执行。
- 人工代触发执行只复用原请求的幂等键和 `ExecutionService`，不新增写路径。

## 5. 恢复流程

```mermaid
flowchart TD
  A[收到 session_id] --> B[数据库读取会话身份]
  B --> C{进程缓存命中且身份一致?}
  C -->|是| D[使用缓存投影]
  C -->|否| E[PostgresSaver 按 session_id/thread_id 恢复]
  E --> F[规范 messages 水合并恢复 task_plan/请求绑定]
  D --> G{是否准备执行写操作?}
  F --> G
  G -->|否| H[继续澄清/计划/只读响应]
  G -->|是| I[读取 execution request 与确认记录]
  I --> J[领取短租约]
  J --> K[新事务锁定并重新读取订单]
  K --> L{身份/归属/版本/有效期/硬规则均有效?}
  L -->|否| M[回滚并记录明确失败码/必要时建单]
  L -->|是| N[同一事务完成业务变更、幂等结果与审计]
```

租约解决“确认已持久化、进程在执行前中断”的长期中间态。活动租约返回 `execution_in_progress`；到期租约可由新 worker 领取。唯一幂等键和订单行版本保证恢复不会重复业务变更。

## 6. API

实现：

- `POST /api/v1/tickets`
- `GET /api/v1/tickets`
- `GET /api/v1/tickets/{ticket_id}`
- `POST /api/v1/tickets/{ticket_id}/assign`
- `POST /api/v1/tickets/{ticket_id}/status`
- `POST /api/v1/tickets/{ticket_id}/approvals`
- `POST /api/v1/tickets/{ticket_id}/approvals/{approval_id}/decision`
- `GET /api/v1/tickets/{ticket_id}/audit`
- `POST /api/v1/tickets/{ticket_id}/execute`

现有 `/api/v1/multi-agent/chat`、`tasks/current`、cancel/return request 系列和 `/api/v1/debug/plan` 未做破坏性字段变更；聊天响应只追加可空 `ticket` 字段，触发接管时新增 `handoff_created` 状态。旧调用方无需迁移字段，若使用封闭枚举解析 `task_status`，需接受该新增值。

## 7. 故障注入实测

| 场景 | 注入 | 结果 |
|---|---|---|
| LLM/工具超时 | `httpx.ReadTimeout`；首次事务前 `OperationalError` | `model_request_failed` 不泄漏底层信息；工具重试重新读单后成功；一次写入 |
| 重复 API/执行 | 活动租约时并发相同请求；成功后串行重放 | 并发第二个为 `execution_in_progress`；串行为 `idempotent_replay=true`；成功审计 1 条 |
| 确认后中断 | 租约提交后抛出模拟进程终止 | 请求保持 `executing`、订单零写；租约到期后恢复成功；统一审计齐全 |
| 等待确认订单变化 | 外部修改状态和 row_version | `order_changed`，不重试，订单保持外部状态；工单 open 且不伪报完成；提示重提案 |
| 未确认 | 直接执行 pending request | `confirmation_required`；row_version 不变；成功审计 0 条 |

脚本实测输出：`schema_residual=0`、`external_llm_calls=0`。

## 8. 测试与故障记录

最终命令：

```powershell
$env:TEST_DATABASE_URL='postgresql+psycopg://serviceflow:serviceflow_local@127.0.0.1:5432/serviceflow_demo'
.venv_tau/Scripts/python -m pytest -q -rs -p no:cacheprovider -o faulthandler_timeout=60 --basetemp=.tmp/pytest-phase3-full-healthy-db
.venv_tau/Scripts/python -m ruff check backend scripts tests
```

最终结果：**204 passed、0 failed、0 skipped**，60.83 秒；ruff `All checks passed!`。真实 PostgreSQL 16.15、官方适配器回归、FastAPI TestClient、SQLite 替身均参与。

验收期间有两次全套运行得到 **191 passed、13 failed**。13 项全部是 PostgreSQL 建连超时。只读检查确认 `flowagent-db-1` 在 2026-11-09 23:14（Asia/Shanghai）以 exit 255 异常退出，`OOMKilled=false`，PostgreSQL 日志无数据库自身 fatal/panic 或连接耗尽记录。重启专用测试容器并确认 healthy 后，同一套测试 204 项全通过。该失败没有被隐藏或算作代码通过。

曾基于症状初步怀疑短生命周期 checkpointer pool 未释放；证据不足后撤回为根因判断。仍保留 `SessionStateStore.close()`、上下文管理和析构清理，作为正确的资源生命周期措施。容器 exit 255 属外部运行环境事件，不是应用恢复语义。

最终只读查询：`phase3_%` schema 残留 **0**；全套已知随机测试 schema 残留 **0**。

## 9. 未完成项与边界

- 阶段 4 前端和管理后台未开始。
- 演示操作员 token 不是生产 IAM/RBAC。
- 修改/换货仍不执行；取消/退货外的写能力未扩展。
- 不连接真实支付、邮件或短信网络。
- 尚未进行正式 τ-bench 多 Agent 对照评分；本阶段没有修改或读取参考动作/评分条件供 Agent 运行时使用。
- 外部 LLM 本阶段未调用；超时场景使用本地 `MockTransport`，仅验证安全错误归一化。
