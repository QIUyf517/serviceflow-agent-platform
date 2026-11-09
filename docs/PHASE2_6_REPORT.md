# 阶段 2.6 验收报告：阶段 2 收尾

日期：2026-11-04（Asia/Shanghai）

## 1. 范围与结论

本轮只完成阶段 2 收尾：核对并加固 Triage、Supervisor、Order、Policy、Resolution、Eligibility Guard、Confirmation Gate 与 Execution 的接线和权限边界；在既有取消闭环上补齐最小退货申请闭环；完成真实 PostgreSQL pgvector、本地真实 Embedding、可追踪指标和单/多 Agent 同案例验证。没有进入阶段 3，没有开发前端、人工审批、真实资金退款、完整会话持久化恢复、订单修改或换货执行。

阶段 2 产品侧验收条件已满足：查询、取消、退货均能在隔离 PostgreSQL schema 中运行；所有写入经过已验证身份、订单归属、权威政策证据、确定性硬规则、服务端具体确认、执行前锁定与重校验、数据库幂等和审计。完整测试为 **181 passed、0 failed、0 skipped**，Ruff 全仓检查通过。

这不是官方 τ-bench 分数，也不能推出多 Agent 优于单 Agent。真实外部聊天 LLM 本轮未调用；工程闭环使用 Mock/本地确定性编排。Embedding 是真实的本地预训练模型输出，不是 Mock。

## 2. 最终流程

```mermaid
flowchart TD
    U[已验证用户自然语言请求] --> T[Triage]
    T --> S[Supervisor / TaskPlan]
    S --> O[Order Agent 只读本人订单]
    O --> P[Policy Agent 检索]
    P -->|写意图仅保留固定官方政策| R[Resolution Proposal]
    R --> G[Eligibility Guard / 硬规则只读校验]
    G -->|缺参数或不合格| F[明确补充信息或拒绝]
    G -->|eligible + validated| C[ExecutionRequest / 具体摘要]
    C --> W[Confirmation Gate 等待]
    W -->|拒绝/过期/方案变化| N[订单不变 + 审计]
    W -->|同用户明确确认| L[锁请求与订单]
    L --> V[重校验归属/版本/参数/硬规则/幂等]
    V -->|冲突或异常| X[事务回滚 + 失败审计]
    V -->|通过| E[ExecutionService 受控写入]
    E --> A[成功审计]
    A --> SR[Supervisor 返回数据库真实状态]
```

Execution Node 不是 LLM Agent。模型、检索文本和客户端布尔值都不能设置可信身份或确认，也不能调用任意 SQL。

## 3. 实际变更文件

阶段 2.6 直接新增或修改的关键文件如下；工作区原有阶段 2.2–2.5C 未提交修改均保留，没有回退或清理。

- 业务与执行：`backend/app/service.py`、`backend/app/multi_agent/models.py`、`execution.py`、`conversation.py`、`workflow.py`、`resolution_agent.py`、`triage.py`、`state.py`。
- 权限、检索与指标：`backend/app/multi_agent/order_agent.py`（复验，无重写）、`policy_agent.py`、`policy_knowledge.py`、`backend/app/llm.py`、`backend/app/config.py`。
- API 与基线：`backend/app/main.py`、新增 `backend/app/single_agent_controlled.py`。
- 运行环境：`docker-compose.yml`、`backend/pyproject.toml`、根 `pyproject.toml`、`.env.example`、新增 `requirements-rag-local.lock`。
- 文档集：新增 `data/knowledge/serviceflow_faq_v1.md`、`serviceflow_product_guide_v1.md` 和 `manifest.json`。
- 脚本与结果：更新 `scripts/index_policy.py`、`evaluate_policy_retrieval.py`；新增 `evaluate_phase2_product_cases.py`；生成 `reports/phase2_6_retrieval.json`、`reports/phase2_6_product_cases.json`。
- 测试：更新 `tests/test_phase25a_resolution.py`；新增 `tests/test_phase26_return.py`、`tests/test_phase26_postgres.py`。
- 文档：`README.md`、`TASKS.md`、本报告。

## 4. 节点、State 与工具权限

LangGraph 实际接线为 `Triage → Supervisor → Order → Supervisor Result → Policy → Supervisor Result → Resolution/Guard → Supervisor Result → Terminal`，确认后通过独立非 LLM 图运行 `Confirmation → Execution → Supervisor Result → Terminal`。`AgentState` 继续传递受限订单投影、政策证据、Proposal、Eligibility、持久化执行请求、确认、执行结果与 trace，不传递完整客户资料或支付历史。

Order Agent 的代码白名单只含只读订单/商品工具，并再次校验 Supervisor 任务期望和参数；注入 `cancel_order` 等跨节点工具得到 `tool_not_allowed`。Policy Agent没有业务写工具；Resolution 只能调用 `validate_action_readonly`；实际写入只存在于 `ExecutionService.execute_action`，且仅接受 `cancel` 和 `return`。`AgentState.apply_agent_update` 禁止 Agent 设置 `identity_verified`、`user_id`、`user_confirmed`、`trace_id` 等服务端字段。测试证明文档中的“忽略规则并确认”文本不能改变这些字段，也不能扩大工具集。

写意图的 Policy Agent 会在关键词或向量路径扩大候选召回，然后只把 `data/raw/tau2/<固定 commit>/policy.md` 的片段送入方案链。ServiceFlow 自编 FAQ/说明可用于信息查询，但不能作为取消/退货授权证据，也不会在写意图中发送给外部解释器。

## 5. 退货申请闭环

退货参数为 `item_quantities: {item_id: positive_int}` 与 `payment_method_id`。旧 `item_ids` 输入仍兼容地按出现次数转换为显式数量，生成的新方案和确认摘要一律使用数量映射。硬规则继续复用 `RetailService._apply`：订单必须是 `delivered`，商品和数量必须真实存在，退款途径必须属于当前已验证用户并满足固定规则。

成功前，`ExecutionService` 将摘要绑定用户、session、订单、动作、参数摘要、Proposal ID/版本、订单 `row_version`、期限和幂等键。用户明确确认后，执行事务重新锁定请求、确认记录和订单，重新检查绑定、归属、版本和硬规则。数据库最终写入 `status=return requested`、`return_item_quantities`、`return_payment_method_id` 和 `return_refund_status=requested_not_disbursed`。系统不创建真实支付退款，也不声称到账或真实邮件已发送。

SQLite 与 PostgreSQL 测试覆盖成功、无确认、拒绝、未验证身份、他人订单、非法商品/数量、过期、参数/确认绑定变化、等待期间订单版本变化、幂等重放、事务异常回滚和 Prompt Injection。取消原有安全语义保持不变；旧 `/operations`、旧 confirm 以及带 `proposal_id` 的旧聊天写路径继续返回 410。

## 6. 文档集、pgvector 与检索结果

新增两份 ServiceFlow 自编演示文档，不冒充官方规则或厂商资料。`data/knowledge/manifest.json` 记录集合、版本、作者、非权威属性、来源和 SHA256：

- FAQ SHA256：`c5f4eb27265acb06a822ab9b80c53254c6e9a5aecccc002816f2b69f6615de10`。
- 商品信息说明 SHA256：`e169e58476ef0cd7dfd58957b450849047db465d1e50ef9ac4bcc996e3954786`。

索引实际环境：Docker `pgvector/pgvector:0.8.7-pg16-trixie`，扩展查询返回 `0.8.7`；FastEmbed `0.9.1`；模型 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`，384 维，本地 ONNX 推理，模型缓存 `.cache/fastembed`。首次索引 17 chunks；再次导入三份文档均 `inserted=0, unchanged=true`；显式 `--rebuild --rebuild-vector` 成功。向量表遵循随机 schema，而不是误写 public schema。

同一 `serviceflow-policy-retrieval-v1` 30 条人工标注集、Top-K=3 的本轮结果：

| 路径 | Recall@3 | MRR | 引用相关准确率@3 | 引用来源完整性 | 平均延迟 |
|---|---:|---:|---:|---:|---:|
| 关键词 | 1.000000 | 0.944444 | 0.383333 | 1.000000 | 1.058 ms |
| 真实向量 | 0.833333 | 0.633333 | 0.277778 | 1.000000 | 13.674 ms |

“引用相关准确率@3”是返回引用中属于标注目标 section 的比例；“引用来源完整性”是引用 chunk ID 能在已导入且哈希验证的文档集合中解析的比例。该集合只有 30 条且每条通常只有一个目标 section，结果不代表生产效果。当前关键词在该小集合上明显优于本地向量，因此默认继续使用关键词；没有为了宣称向量更好而修改结论。真实向量 Agent 业务测试以 Top-K=5 命中权威退货规则，完成 Proposal、确认、数据库写入和审计。

完整逐案例结果见 `reports/phase2_6_retrieval.json`。

## 7. Trace 与 Provider 指标

每个图轮次生成服务端 `trace_id`；事件记录节点、任务 ID、执行请求 ID（存在时）、实测 `perf_counter` 耗时、状态、工具和错误码。返回指标包含端到端耗时、节点数、实际工具调用数、Provider、模型、温度/seed 配置和 Provider 实际返回 Token。OpenAI-compatible Provider 累加响应中的真实 usage；Provider 未返回或 Mock 路径则为 `null`，不估算 Token 或成本。

Guard 的耗时单独包围 `Action` 结构校验和 `validate_action` 硬规则调用；Resolution 节点耗时是整个方案节点耗时。确认等待和受控执行也有独立计时。报告、日志和 trace 不记录 API Key、完整客户资料或确认凭据摘要。

## 8. 单/多 Agent 同案例

`scripts.evaluate_phase2_product_cases` 对查询、取消和退货分别运行受控单 Agent 与多 Agent，共六次。每次从同一固定数据快照创建新的随机 PostgreSQL schema，使用相同已验证身份、自然语言输入、业务规则、只读订单工具、权威政策、具体确认和 `ExecutionService`，结束 `DROP SCHEMA ... CASCADE`。

实际结果：

- 查询：两种架构都保持 `pending → pending`，无业务审计。
- 取消：两种架构都先 `pending_confirmation`，确认后 `pending → cancelled`。
- 退货：两种架构都先 `pending_confirmation`，确认后 `delivered → return requested`。
- 两种写案例均记录 `proposal_generated`、`eligibility_validated`、`user_confirmed`、`execution_succeeded`，失败原因为空。
- Mock Provider/模型为 `mock_local`/`deterministic-v1`，Token 均为 `null`。

受控单 Agent 是产品侧公平基线入口 `POST /api/v1/single-agent/controlled-chat`，自己执行意图/工具选择，但写入仍只能走共享 ExecutionService。测试脚本没有替 Agent 直接调用 legacy confirm，也没有恢复旧布尔确认 API。完整输入、确认摘要、工具轨迹、逐节点/端到端耗时、前后状态和审计见 `reports/phase2_6_product_cases.json`。Mock 耗时只表示本机工程路径，不是模型性能对比。

## 9. 实际命令与结果

```powershell
docker compose pull db
docker compose up -d db
docker compose exec -T db psql -U serviceflow -d serviceflow_demo -Atc "SELECT default_version FROM pg_available_extensions WHERE name='vector';"
# 输出：0.8.7

$env:POLICY_EMBEDDING_PROVIDER='fastembed'
$env:POLICY_LOCAL_EMBEDDING_CACHE='.cache/fastembed'
.venv_tau/Scripts/python -m scripts.index_policy --rebuild --vector --rebuild-vector
.venv_tau/Scripts/python -m scripts.index_policy --vector
.venv_tau/Scripts/python -m scripts.evaluate_policy_retrieval --output reports/phase2_6_retrieval.json

$env:TEST_DATABASE_URL='postgresql+psycopg://serviceflow:serviceflow_local@127.0.0.1:5432/serviceflow_demo'
.venv_tau/Scripts/python -m pytest tests/test_phase26_postgres.py -q --basetemp=.tmp/pytest-phase26-pg -p no:cacheprovider
# 1 passed
.venv_tau/Scripts/python -m pytest -q --basetemp=.tmp/pytest-phase26-full -p no:cacheprovider
# 181 passed, 0 failed, 0 skipped（23.65 s）
.venv_tau/Scripts/python -m ruff check .
# All checks passed
.venv_tau/Scripts/python -m scripts.evaluate_phase2_product_cases --output reports/phase2_6_product_cases.json
# 六个案例全部完成，随机 schema 自动清理
```

历史报告数字没有用作本轮结果。正式演示订单和官方原始数据/评分器未修改；写测试均在随机隔离 schema 中执行。

## 10. 已知限制与停止点

- 完整聊天/图状态仍使用进程内 `SessionStateStore`；数据库只持久化执行请求、确认、幂等结果和审计。完整恢复属于阶段 3。
- 退货仅登记申请，不连接仓储、邮件或支付网络；取消沿用当前模拟业务数据的退款语义。
- 多 Agent 修改、换货执行未实现；前端、人工审批和完整故障恢复未实现。
- 真实外部聊天 LLM 未进行阶段 2.6 端到端调用；没有绕过数据发送审批。真实本地 Embedding 已验证。
- 30 条检索集和六个产品案例样本很小；不构成模型优劣或多 Agent 优势证据，也不是官方 τ-bench 评测。
- 本地 FastEmbed 首次运行需要下载模型；Windows 无符号链接权限时缓存会占用更多空间，但不影响向量真实性。

阶段 2.6 到此停止，等待验收，不自动进入阶段 3。
