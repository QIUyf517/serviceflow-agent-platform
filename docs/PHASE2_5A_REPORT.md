# 阶段 2.5A 验收报告：Resolution Agent 只读方案生成

日期：2026-11-02

## 1. 范围与结论

本阶段完成 Resolution Agent 的最小可运行闭环：读取已授权的订单投影和 Policy Agent 证据，生成结构化售后建议，再由服务端现有硬规则进行只读校验。支持取消、修改、退货和换货；信息不足、规则拒绝和可进入确认的情况分别返回 `needs_clarification`、`ineligible` 和 `pending_confirmation`。

本阶段没有执行取消、修改、退货或换货，没有调用 `RetailService.propose`/`confirm`，没有写订单、业务 proposal 或审计表，也没有实现人工审批、前端、完整恢复或 2.5B。

## 2. 实际修改文件

- `backend/app/multi_agent/models.py`：新增 `ResolutionProposal`、`EligibilityResult`、证据模型及状态枚举。
- `backend/app/multi_agent/resolution_agent.py`：新增本地方案生成、严格输出校验、证据整合、只读规则校验和风险标记。
- `backend/app/multi_agent/state.py`：增加 `resolution_proposal`、`eligibility_result`、`risk_flags`，继续保护身份和确认字段。
- `backend/app/multi_agent/supervisor.py`：依赖顺序改为 Order/Policy → Resolution → Guard → Confirmation → Executor。
- `backend/app/multi_agent/workflow.py`：接入 Resolution 路由、依赖推进、多轮证据复用、终态回复和完整轨迹输出。
- `backend/app/multi_agent/triage.py`：补充多轮参数合并及离线 Mock 的有限参数提取。
- `backend/app/service.py`：新增 `ActionValidation` 和 `validate_action` 只读规则接口。
- `backend/app/main.py`：扩展现有 `/api/v1/debug/plan` 的 2.5A 行为和版本说明。
- `tests/test_phase25a_resolution.py`、`tests/test_phase25a_api.py`：新增 Resolution、规则冲突、API、隔离和零写入测试。
- `tests/test_phase22_workflow.py`、`tests/test_phase23_order.py`、`tests/test_phase24_policy.py`：更新新依赖契约下的回归断言。
- `README.md`、`TASKS.md`、本报告：运行说明、API 示例、结果和限制。

仓库开始时已有阶段 2.2–2.4 未提交文件和其他改动；本阶段没有回退或覆盖这些用户已有工作。

## 3. 输入、输出与职责边界

Resolution 输入：当前 `TaskPlan` 中依赖已完成的 Resolution 任务、服务端绑定身份、Order Agent 的受限订单详情/状态、Policy Agent 的真实来源证据、Triage 提取参数。订单地址、支付历史和完整客户资料不进入 AgentState；规则校验需要的这些数据由 `RetailService` 在服务端重新按会话和订单归属读取。

Resolution 输出：`ResolutionProposal` 包含只读建议 ID、任务、动作、参数、订单/政策证据、缺失信息、建议资格、确认/人工复核标志、风险和解释；`EligibilityResult` 单独包含硬规则状态、`validated`、规则错误码和校验时订单状态。共享状态还更新 `missing_information`、`pending_action`、`risk_flags`、`next_agent`、`current_task` 和 trace。

`pending_action` 仅是本阶段建议摘要，不是 `operation_proposals` 表记录，不能传给现有确认 API 执行。

## 4. 生成建议与规则验证如何区分

本地生成器只把 Triage 参数组装成候选 `Action`，并可给出 `eligible/ineligible/unknown` 建议。候选先经过 Pydantic 严格结构、动作与参数白名单校验，再交给 `RetailService.validate_action`。

`validate_action` 重新检查服务端会话、订单归属并读取当前订单/客户数据，然后只在 `deepcopy` 上调用与真实执行相同的 `_apply` 规则。它不启动写事务、不 flush 变更、不创建 `ProposalRow` 或 `AuditRow`。只有该结果能把 `validated` 设为 `true`。若生成建议和规则结果冲突，以规则结果为准并记录 `model_rule_conflict`；测试已覆盖模型错误地同意取消已送达订单，结果仍为 `ineligible`。

即使规则返回 eligible，状态也只是 `pending_confirmation`，`user_confirmed` 仍是服务端保护的 `false`，Confirmation/Executor 不运行。

## 5. 复杂任务与多轮处理

Supervisor 为每个写意图建立：`order-lookup` 和政策任务 → Resolution proposal → Guard → Confirmation → Executor。只有依赖全部完成的任务会变为 ready。Resolution 本轮处理一个 ready 写任务；确认和执行保持阻塞。

当 Resolution 因缺少取消原因、修改类型、商品、目标变体或支付方式而请求补充时，同一会话下一轮会合并新参数，并复用同一订单的已有 Order/Policy 结果。本阶段测试用调用计数确认补充取消原因时没有重复订单查询；稳定摘要使相同会话、任务、参数和证据生成同一建议 ID。切换会话会生成不同 ID，状态按服务端 session 隔离。

当前只保留一个活动 `resolution_proposal`；包含多个独立写动作的复杂请求不会在一轮内生成一组可确认方案，这是已知限制，不把它伪装成完整复合执行。

## 6. LLM 与检索说明

Resolution 本阶段没有真正调用外部 LLM。默认和真实 Provider 配置下，Resolution 都使用可测试的本地确定性生成器；原因是仓库当前没有独立、可审计的“向外部 Resolution LLM 发送脱敏订单上下文”审批开关，不能通过默认开启绕过授权。真实 Provider 仍只沿用已有 Triage/Policy 行为。

测试使用真实固定 `policy.md` 的关键词检索路径。取消多轮和退货 API 场景均得到真实政策 chunk；退货场景命中 `Return delivered order`。pgvector 与 Embedding Key 仍未在真实环境可用，向量检索没有被伪造；Resolution 不依赖它。

## 7. API 与轨迹

`POST /api/v1/debug/plan` 继续要求有效 `x-session-id`；私有订单还要求服务端身份核验。响应现包含：

- `input`、`triage`、`task_plan`、`next_agent`、`current_task`；
- `order_data`、`order_context`、`policy_context`、`policy_retrieval`；
- `resolution_proposal`、`eligibility_result`、`pending_action`、`missing_information`、`risk_flags`；
- `final_response`、当轮 `trace` 和会话内累计 `full_trace`。

所有成功方案回复都明确“需要后续明确确认”和“No business change was made”。普通订单查询和政策咨询保持原只读路径，不强制创建业务方案。

## 8. 测试结果

完整命令：

```powershell
$env:TEST_DATABASE_URL = (.venv312/Scripts/python -c "from app.config import Settings; print(Settings().database_url)")
.venv_tau/Scripts/python -m pytest -q -rs -p no:cacheprovider -o faulthandler_timeout=45 --basetemp=.pytest_phase25a_full1
.venv312/Scripts/python -m ruff check backend scripts tests
```

实际结果：

- pytest：**144 passed，0 failed，0 skipped**，耗时 13.92 秒；
- Ruff：`All checks passed!`；
- PostgreSQL：本机 Docker PostgreSQL 16 健康，数据库集成测试使用独立临时 schema；
- 官方适配器：使用已安装 `tau2` 的 `.venv_tau` 纳入完整回归；
- FastAPI TestClient：受限沙箱内 loopback 会停滞，按前阶段已记录原因放宽本机 loopback 后 **2 passed**，并包含在 144 项中；
- 外部 Resolution LLM：未调用，未产生这部分 Token 或费用。

新增测试覆盖：符合/不符合取消，修改缺参，真实退货政策，换货变体不存在，状态冲突，身份缺失，确认缺失，多意图依赖，政策为空，订单查询失败，非法生成参数，模型与规则冲突，多轮补充，会话隔离，重复方案、无写权限和原接口回归。测试还断言订单 JSON 不变且 `operation_proposals`、`operation_audit` 计数为零。

## 9. 已知限制与 2.5B 预留

- 调试会话状态仍为进程内存，无 checkpointer、跨进程恢复或 TTL；不应当作生产持久化。
- Resolution 的本地参数解析是有限演示语法；复杂自然语言需要未来经审批的结构化 Provider 或显式 API 参数。
- 当前只有一个活动方案，不支持一轮聚合多个独立写操作。
- eligible 结果不是授权；订单仍可能在未来确认与执行之间变化，2.5B 必须重新读取并校验。
- pgvector 未完成真实环境验证，当前以关键词检索为可靠基线。
- 未实现人工审批、风险工单、执行幂等、确认后重校验或完整恢复。

为 2.5B 预留：稳定的 `resolution_proposal`/`eligibility_result` 契约、`pending_action` 摘要、阻塞的 Confirmation/Executor TaskPlan 节点、服务端保护的 `user_confirmed`、以及 `validate_action` 只读入口。2.5B 若创建真实操作提案，必须生成新的数据库 proposal/幂等键，明确区分于 `resolution_*` 建议 ID，并在确认后、执行前再次读取订单与运行硬规则。
