# 阶段 4.5B：咨询分流与售后闭环验收报告

日期：2026-11-14

## 1. 范围与结论

本轮只完成 4.5B：内容安全先检、FAQ/政策、实时商品、本人订单/物流、取消/退货、含糊与超范围请求的统一分流，以及多轮追问和客户明确请求后的人工转交。无法自动解决时不自动创建工单。没有开始 4.5C 的全量顾客/商家文案中文化和人工回复闭环，也没有勾选阶段 4.5 收尾。

4.5B 四项验收均通过：内容安全节点位于任何意图路由和工具调用之前；政策回答保留已验证来源，商品咨询读取当前业务库；订单查询与写操作继续受服务端身份、归属、确认、重检、事务、幂等和审计保护；成功执行后模拟商店从同一 PostgreSQL 读到最新订单状态。

## 2. 实现闭环

### 2.1 内容安全先检

- `ContentSafetyChecker` 是无网络、无 LLM 的确定性基线，返回严格 `SafetyDecision`。
- 拦截要求有上下文的短语，而不是单个关键词；测试明确覆盖“杀菌功能”、“秒杀商品”、“订单被取消”、“中午回答”不被误拦。
- 被拦截请求不进入 Triage、Policy、Order、Resolution 或 Executor，`tool_results` 为空，不会更改订单或创建工单。被拦截的原始文本不写入 `messages`，只保存中文安全回复与分类代码。
- 每个允许的客服回合 trace 也以 `content_safety: allowed` 开始，开发者可检查先后顺序。

边界：这是当前演示范围的可测试规则集，不是通用内容安全模型，不能据此宣称覆盖任意隐喻、变体或多语言风险。

### 2.2 咨询分流与中文展示投影

- 对话返回 `consultation_route`：`faq_policy`、`product`、`order_logistics`、`after_sales`、`unclear`、`out_of_scope`、`evidence_insufficient`、`data_unavailable`、`human_handoff` 或 `content_blocked`。
- FAQ/政策继续通过 `PolicyAgent` 在已导入的固定文档中检索；客户端回复将命中条款投影为不扩大原意的中文要点，并列出 `policy.md § <section>` 等可核对来源。
- 商品咨询调用受限的 `get_product_details` 工具，价格和可用性从当前 `products` 表读取。测试在两轮之间修改数据库价格，第二轮立即返回新价格，证明没有使用前端静态数据或 RAG 猜测实时事实。
- 订单状态使用确定性中文映射；商品名使用与 4.5A 一致的固定映射原则，未知英文名不被臆测翻译，而显示为带 ID 的“模拟商品”。

### 2.3 多轮追问与客户主动转交

- 缺订单号、商品标识、退货商品项/数量或退款途径时，沿用持久化 checkpoint 的 `TriageResult`、结构化任务与消息序列继续下一轮。
- 正常售后缺少必要参数（如取消原因）时只追问，不误称“无法解决”；补齐参数后继续生成待确认方案。含糊、超范围、证据不足、数据不可用、规则冲突或执行失败时说明当前无法解决，并提示可回复“转人工”。自动流程不因连续失败创建工单。
- 路由次数限制只作用于单轮图处理，不跨整个顾客会话累积；历史聊天和 checkpoint 恢复后仍可发起新的取消申请。追问原因时客户回复“不想取消了”，服务端清除该轮待澄清意图，订单保持不变。提供原因后仍需确认具体取消方案，原因本身不授权写入。
- 只有“请帮我转人工客服”类明确动作意图立即建单。单纯询问“你是人工客服吗”不建单。
- 建单回复明确表达“尚未处理完成”和“人工处理不会替代客户确认”，不伪报成功。

### 2.4 售后写操作与商店同步

- 取消与退货继续复用 `ExecutionService`，内容安全和咨询分流不能直接设置 `user_confirmed`。
- 未确认时订单保持原状态；确认只对与当前客户、订单、提案版本、摘要和有效期绑定的请求生效。
- 执行前重新读取并锁定订单，重跑硬规则；事务成功后写审计。重复确认返回已有结果，不二次写入。
- React 只在 `execution_result.status == "succeeded"` 时使订单 Query 失效并重读当前订单详情；错误文本或回复中的“成功”字样不能驱动界面成功态。

## 3. API 示例

### 实时商品咨询

```http
POST /api/v1/multi-agent/chat
X-Session-Id: <verified-session>
Content-Type: application/json

{"message":"商品 9523456873 现在多少钱？"}

HTTP/1.1 200
{
  "task_status":"queried",
  "consultation_route":"product",
  "safety":{"allowed":true,"category":"allowed","reason_code":null},
  "final_response":"商品 T 恤（商品标识 9523456873）当前有 ..."
}
```

### 政策 FAQ

```http
POST /api/v1/multi-agent/chat
X-Session-Id: <verified-session>
Content-Type: application/json

{"message":"取消订单需要什么条件？"}

HTTP/1.1 200
{
  "task_status":"policy_answered",
  "consultation_route":"faq_policy",
  "final_response":"根据当前检索到的政策资料：...\n\n来源：\n- policy.md § Cancel pending order"
}
```

### 内容拦截

```http
POST /api/v1/multi-agent/chat
X-Session-Id: <verified-session>
Content-Type: application/json

{"message":"<contextual harmful instruction>"}

HTTP/1.1 200
{
  "task_status":"content_blocked",
  "consultation_route":"content_blocked",
  "safety":{"allowed":false,"category":"harmful_instruction","reason_code":"content_harmful_instruction"},
  "tool_results":[],
  "final_response":"这段内容涉及可能造成伤害或违法获取信息的具体请求，我不能协助。..."
}
```

## 4. 验收结果

| 检查 | 结果 |
|---|---|
| 完整后端 pytest（含真实 PostgreSQL 随机 schema） | 220 passed，0 failed，0 skipped |
| Ruff | 通过 |
| 前端 Vitest | 8 files，39 passed，0 failed |
| ESLint / TypeScript / 生产构建 | 全部通过 |
| Chromium + 真实 FastAPI + 真实 PostgreSQL | 8 passed，0 failed |
| E2E schema 清理 | 创建 1，清理 1，残留 0 |
| Docker Compose | db/api/frontend 均 healthy |
| 外部 LLM 调用 | 0 |

主要命令：

```powershell
$env:TEST_DATABASE_URL = '<isolated PostgreSQL demo URL>'
.venv_tau/Scripts/python -m pytest -q -rs -p no:cacheprovider --basetemp=.tmp/pytest-phase45b-full
.venv_tau/Scripts/python -m ruff check backend scripts tests

Set-Location frontend
npm run lint
npm run typecheck
npm run test -- --run
npm run build
npm run test:e2e
```

`test:e2e` 的 4.5B 场景使用同一浏览器会话依次执行实时商品咨询、政策 FAQ、内容拦截以及两次含糊请求，断言两次都只提示可请求人工且页面不出现新工单。原有浏览器场景同时继续验证取消、退货、未确认零写入、审批不替代客户确认、并发状态变化失败和开发者 trace。

## 5. 未完成项与风险

- 4.5C 要求的全量顾客可见文案中文化尚未完成；确认摘要、个别硬规则失败详情和旧轨迹中仍可能存在英文。本报告不宣称阶段 4.5 已完成。
- 人工回复传回顾客窗口属于 4.5C；当前 4.5B 只完成可审计工单创建和客户侧等待状态。
- 内容安全是明确的确定性基线而非全能分类器。若将项目推向真实公网，需另行定义风险分类法、误拦/漏拦指标、人工复核和隐私保留策略，不能直接把本阶段规则当作生产安全网关。
- 运行中商品、订单和客户数据仍是 τ-bench Retail 模拟数据；取消和退货只更改本地演示数据库，不连接真实支付、物流或邮件系统。
