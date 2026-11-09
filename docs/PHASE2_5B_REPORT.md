# 阶段 2.5B 验收报告：安全业务执行与订单取消闭环

日期：2026-11-02（Asia/Shanghai）

## 1. 范围与结论

项目实际名称为 ServiceFlow，根目录为当前仓库。本阶段在 2.5A `ResolutionProposal`/`EligibilityResult` 之上完成取消订单的可信确认和真实数据库写入闭环：

`Triage → Order/Policy → Resolution → Eligibility Guard → Confirmation Gate → Execution Node → Supervisor Result → END`

执行结果来自数据库事务后的真实订单状态。修改、退货、换货仍只停留在 2.5A 方案层；本阶段没有开发人工审批、React、完整 checkpointer 恢复、新 RAG、模型微调或 2.5C。

## 2. 实际修改文件

- `backend/app/multi_agent/execution.py`：新增 `ExecutionService`、确认、幂等、事务、锁、审计和取消执行。
- `backend/app/database.py`：新增 `execution_requests`、`confirmation_records`、`execution_audit_events` 表并接入显式 reset 顺序。
- `backend/app/multi_agent/models.py`：新增执行请求、确认和执行结果 Pydantic 契约及流程状态。
- `backend/app/multi_agent/state.py`：新增执行状态字段、可信确认绑定和新操作确认清理；Agent 更新仍不能设置 `user_confirmed`。
- `backend/app/multi_agent/workflow.py`：新增非 LLM Confirmation Gate、Execution Node、Supervisor Result 和持久化上下文恢复入口。
- `backend/app/main.py`：新增取消请求、查询、决策、执行和审计 API；版本更新为 0.2.6。
- `tests/test_phase25b_execution.py`：确认、越权、幂等、篡改、回滚与审计单元测试。
- `tests/test_phase25b_api.py`：完整 API/LangGraph 成功路径、未确认路径及布尔确认拒绝。
- `tests/test_phase25b_postgres.py`：固定 Retail 快照在随机 PostgreSQL schema 中的真实写入、并发和未确认测试。
- `README.md`、`TASKS.md`、本报告：接口示例、验收记录和范围说明。

工作区开始时已有阶段 2.2–2.5A 的未提交改动；本阶段在其上增量实现，没有回退用户已有工作。

## 3. 取消执行流程

1. `/api/v1/debug/plan` 继续生成只读 `ResolutionProposal`，Policy 默认使用关键词检索。
2. `POST /api/v1/multi-agent/cancel-requests` 只接受当前会话内、已由硬规则验证为 eligible 的 cancel proposal。
3. `ExecutionService.prepare_cancel` 在数据库事务中重新读取服务端 session、验证订单归属、锁定订单、在深拷贝上重跑现有 `_apply` 规则，然后持久化执行请求和订单版本；订单尚不改变。
4. 服务端返回包含订单号、允许原因、proposal ID 和版本的具体 `confirmation_text`。
5. `POST .../decisions` 仅接受 `decision=confirm|reject` 和该具体文本。确认记录绑定 session 用户、订单、动作、proposal ID/版本/摘要并设置有效期。
6. `POST .../execute` 通过 LangGraph Confirmation Gate 后进入非 LLM Execution Node。
7. Execution Node 在新事务中锁定执行请求和订单，重新验证确认、摘要、有效期、订单版本、所有权及当前 `_apply` 硬规则。
8. 成功时同一事务更新订单 JSON、状态、用户退款相关模拟数据、`row_version`、请求/确认状态和成功审计；Supervisor Result 只根据该数据库结果生成最终回复。

本阶段没有让 LLM 访问 SQL、事务或写工具。Resolution proposal ID 不能直接交给旧确认服务执行；必须先通过新的持久化请求和确认 Gate。

## 4. 身份、确认与资格机制

- 身份来自 `service_sessions.user_id`，不接受请求体 user ID。每次创建、查询、确认、执行和审计查询都重新校验当前 session。
- 订单归属由现有 `_own_order` 服务端查询确定；不存在和他人订单均返回安全错误。
- 资格必须同时满足 proposal 和独立 `EligibilityResult` 均为 `validated=true, eligible`，随后准备和执行阶段还各自重跑硬规则。
- 新确认 API 不存在布尔 `confirmed` 字段。确认文本具体绑定订单、取消原因、proposal ID 和版本，错误文本、错误订单、篡改参数和过期确认均被拒绝。
- `AgentState.user_confirmed` 仍是保护字段；普通节点更新会得到 `protected_state_field`。只有从数据库读取到匹配的有效确认记录后，服务端绑定函数才能在执行图中设置它。
- 用户拒绝会把请求和确认记录持久化为 rejected，ExecutionService 返回 `confirmation_rejected`，订单不变。

## 5. 幂等、并发和事务

`execution_requests.idempotency_key` 是数据库唯一索引。参数摘要绑定用户、订单、动作和完整规范化 `Action`；proposal 摘要绑定完整结构化方案。相同键、相同绑定重复准备返回同一 request；相同键配不同用户、参数或 proposal 返回 `idempotency_key_conflict`。成功请求重复执行返回原数据库结果并标记 `idempotent_replay=true`，不新增退款、版本或成功审计。

执行事务先锁执行请求，再以 `SELECT ... FOR UPDATE` 锁订单，并比较准备时 `row_version`。两个独立确认请求并发取消同一订单时，只有先获得订单锁的一方能从 pending 变为 cancelled；另一方在锁释放后发现版本变化并返回 `order_changed`。不能依赖 Python 内存或 LangGraph checkpoint 防重。

故障注入测试在内存对象已变更但提交前抛出 SQLAlchemy 异常，订单状态和版本均回滚；随后以独立事务记录 `execution_failed/database_transaction_failed`。如果数据库本身完全不可用，失败审计只能 best effort，这是不可消除的单库故障边界。

## 6. 审计

新表 `execution_audit_events` 是 2.5B 的细粒度生命周期审计，和阶段 1 旧 `operation_audit` 保持兼容但不混用。事件类型包括：

- `proposal_generated`：持久化 Resolution proposal、task/request 关联；
- `eligibility_validated`：记录确定性规则结果；
- `user_confirmed`、`user_rejected`、`confirmation_failed`、`confirmation_expired`；
- `execution_succeeded`、`execution_failed`。

字段覆盖 request/task、用户 ID、订单、动作、proposal、资格结果、确认 ID、执行前后状态、结果/失败码和时间戳。没有保存邮箱、姓名、地址、API Key 或完整用户资料。审计查询必须使用原会话且重新验证用户。

## 7. API

- `POST /api/v1/multi-agent/cancel-requests`：从当前会话的 Resolution proposal 创建持久化取消请求。
- `GET /api/v1/multi-agent/cancel-requests/{request_id}`：查询具体摘要、状态、期限和待确认文本。
- `POST /api/v1/multi-agent/cancel-requests/{request_id}/decisions`：提交 `confirm` 或 `reject` 及具体确认文本。
- `POST /api/v1/multi-agent/cancel-requests/{request_id}/execute`：使用 `Idempotency-Key` 请求头进入受控执行图。
- `GET /api/v1/orders/{order_id}`：读取最终数据库订单状态。
- `GET /api/v1/multi-agent/cancel-requests/{request_id}/audit`：读取该请求审计。

完整 PowerShell 调用见 README。所有端点都要求有效 `x-session-id`；没有测试身份绕过参数。

## 8. 测试与真实场景

最终命令：

```powershell
$env:TEST_DATABASE_URL = (.venv312/Scripts/python -c "from app.config import Settings; print(Settings().database_url)")
.venv_tau/Scripts/python -m pytest -q -rs -p no:cacheprovider -o faulthandler_timeout=45 --basetemp=.pytest_phase25b_final
.venv312/Scripts/python -m ruff check backend scripts tests
```

实际结果：

- pytest：**163 passed，0 failed，0 skipped**，耗时 17.51 秒；
- Ruff：`All checks passed!`；
- FastAPI 成功链路包含 Proposal → 持久化请求 → 明确确认 → LangGraph Gate/Executor → cancelled → 审计；
- 未确认 API 链路返回 `confirmation_required`，真实订单保持 pending；
- PostgreSQL 使用固定 τ-bench Retail `db.json` 导入随机 `phase25b_*` schema，未修改官方文件；
- 两个已确认请求并发取消同一 pending 订单，实际结果为一次 `cancelled` 和一次 `order_changed`，订单 `row_version` 从 1 变 2；
- PostgreSQL 未确认场景保持 pending；测试清理后 `phase25b_*` schema 残留实测为 **0**；
- 全套回归包含单 Agent、Order、Policy、Resolution、PostgreSQL 和官方适配器。

覆盖了用户要求的正常/状态拒绝/已取消、未验证、非所有人、无确认、拒绝、过期、错误订单绑定、确认后篡改、幂等重放/冲突、并发、事务回滚、审计、数据库结果一致、Agent 不可自授权和既有模块回归。

## 9. LLM 与 Mock

本阶段执行和确认全部是确定性服务代码。自动化与真实 PostgreSQL端到端均使用 Mock Triage、关键词 Policy、本地 Resolution；没有调用外部 LLM，也没有向外部端点发送订单或客户数据。因此不能声称真实 LLM 端到端已经验证。真实 LLM 不影响执行授权：即使未来模型生成 proposal，仍必须通过相同的服务端资格、确认、版本、事务和幂等边界。

## 10. 已知安全边界与 2.5C

- Confirmation 文本不是第二因素；安全性依赖 `x-session-id` bearer 凭据，因此生产环境必须使用安全 Cookie/Token、TLS、CSRF 防护和会话吊销。
- 创建执行请求仍需要同进程 `SessionStateStore` 中的当前 Resolution proposal；请求一旦持久化，确认和执行可从数据库重建最小图状态，但完整会话/消息恢复不在本阶段。
- 当前使用 `Base.metadata.create_all` 增加表，没有生产迁移脚本；正式部署前需要 Alembic 等受控迁移。
- 单库完全不可用时无法保证失败审计写入，当前采用 best-effort；更强保证需要事务外审计通道或 outbox。
- 为保留公平回归，阶段 1 单 Agent `/api/v1/operations/{proposal_id}/confirm` 旧布尔确认接口仍存在；多 Agent 2.5B 路径不会调用它。生产收敛前应隔离或迁移该 legacy surface。
- 不自动重试失败执行；调用方必须读取失败状态并由人工或后续恢复策略决定。
- 修改、退货、换货执行未授权，ExecutionService 会拒绝非 cancel proposal。

阶段 2.5C 可在不放宽上述边界的前提下扩展修改/退货/换货的动作专属摘要与确认、实现持久化完整图恢复/outbox、收敛 legacy 确认接口、增加会话安全控制和正式数据库迁移。本轮未开始 2.5C。
