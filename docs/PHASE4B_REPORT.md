# 阶段 4B：管理后台与开发者页验收报告

日期：2026-11-11

## 1. 范围与结论

本轮只完成阶段 4B：在阶段 4A 的 React + TypeScript + Vite 工程内增加管理后台和开发者追踪页。没有重新搭建前端，没有进入阶段 5，没有修改后端 API 字段含义，没有新增后端业务能力，没有启用外部 DeepSeek，也没有执行 Docker/Compose 最终验收或创建阶段 4 最终提交。

开始前核对了 Git 状态、阶段 4A 代码与报告。阶段 4A 基线的 `npm run lint`、`npm run typecheck` 和 **17 项前端测试**均通过；既有工作区变更全部保留。本轮最终前端自动化为 **7 个测试文件、30 passed、0 failed**。`npm run lint`、`npm run typecheck`、`npm run build` 均退出 0；外部 LLM 调用 **0**。

## 2. 管理后台

路由：`/admin`

### 认证边界

- 操作员只使用独立 `X-Operator-Token`；客户 `X-Session-Id` 不能替代。
- token 由操作员输入，只保存在当前标签页 `sessionStorage`；不进入 URL、源码、Vite 构建变量或 localStorage。
- 页面明确标注当前机制是本地演示认证，不是生产 IAM。
- 管理端没有“代客户确认”入口；审批决定不会创建或修改客户确认。

### 列表、详情和操作

实际接入的既有 API：

| 方法 | 路径 | 页面用途 |
|---|---|---|
| GET | `/api/v1/tickets` | 状态、类别、客服、创建时间过滤和 offset/limit 分页 |
| GET | `/api/v1/tickets/{ticket_id}` | 脱敏摘要、脱敏会话和 session/request/order 关联 |
| GET | `/api/v1/tickets/{ticket_id}/audit` | 追加式审计时间线 |
| POST | `/api/v1/tickets/{ticket_id}/assign` | 分配客服 |
| POST | `/api/v1/tickets/{ticket_id}/status` | 合法状态迁移及关闭原因 |
| POST | `/api/v1/tickets/{ticket_id}/approvals` | 为关联执行请求创建内部审批 |
| POST | `/api/v1/tickets/{ticket_id}/approvals/{approval_id}/decision` | 批准或拒绝审批 |
| POST | `/api/v1/tickets/{ticket_id}/execute` | 代触发既有 `ExecutionService` |

前端状态选项严格使用后端状态机允许的下一状态。`closed` 和 `cancelled` 必须选择后端定义的合法 `close_reason`，否则请求不会发出；服务端仍执行最终验证。工单列表同时显示状态、优先级和严重程度标签。

详情隐藏 system 消息和完整 Prompt，并对摘要、会话、请求参数与审计 payload 做防御性脱敏：邮箱、完整地址、卡号、API Key、Prompt 以及评测参考动作/评分字段不显示。页面只展示关联 ID，不用客户 session 获取管理数据。

审批通过后，人工执行仍调用原服务端端点。缺少客户确认时如实显示 `confirmation_required`，不展示成功；仅当服务端返回 `execution_result.status="succeeded"` 才显示执行成功。请求期间按钮禁用，防止并发重复点击；后续重试由服务端复用执行请求已有幂等键，页面如实显示 `idempotent_replay`。

## 3. 开发者追踪页

路由：`/developer`

页面有两类真实数据源：

1. 同一标签页内最近一次 `POST /api/v1/multi-agent/chat` 响应中的 `trace`、`tool_results`、`metrics` 和 `task_plan`。这些数据只保存在 React 内存，不写 localStorage/sessionStorage。
2. `GET /api/v1/multi-agent/tasks/current` 和 `GET /api/v1/traces/{trace_id}`。两个请求都显式携带客户 `X-Session-Id`；session 不进入 URL。

页面展示：

- `trace_id`、`task_status`、`current_task`。
- task plan、目标 Agent 和依赖。
- Agent 节点顺序、节点状态、错误码、节点耗时和总耗时。
- 工具名称、状态、错误码和脱敏负载。
- Provider、模型、`token_usage`。
- request/ticket/order 关联。
- 服务端结果驱动的成功、失败或等待状态。

`mock_local` 明确显示为 Mock，不标成 DeepSeek；`token_usage: null` 显示“未提供（null）”，不推测 Token 或成本。不存在和跨 session 的 trace 均由服务端返回 `trace_not_found`，页面使用同一 404 文案，不泄露归属。

持久化 trace API 当前只返回 `events`、`elapsed_ms` 和 `token_usage`，不返回工具结果、Provider、模型或 task plan。页面对此显示“当前接口未返回”，不会用静态数据补齐；完整工具与 Provider 信息只能来自当前标签页最新聊天响应。

## 4. 视觉、响应式与无障碍

- 延续阶段 4A 的配色、字体和键盘焦点，不引入第二套设计系统。
- 管理页采用“派工账本 + 案件卷宗”，开发者页采用密集的节点/时间账本，避免同质卡片墙。
- 桌面多栏在窄屏折叠为单栏；表格允许横向滚动，详情不再 sticky。
- 表单都有 label，操作按钮有禁用态，错误使用 alert/状态组件，页面保留跳转主要内容链接。
- 保留 `prefers-reduced-motion` 处理。

## 5. 测试证据

最终按要求运行：

```powershell
cd frontend
npm run lint
npm run typecheck
npm run test -- --run
npm run build
```

实际结果：

| 命令 | 结果 |
|---|---|
| `npm run lint` | 退出 0，0 errors，0 warnings |
| `npm run typecheck` | 退出 0 |
| `npm run test -- --run` | **7 files passed，30 tests passed，0 failed** |
| `npm run build` | 退出 0；Vite 转换 97 modules；JS 345.37 kB（gzip 106.70 kB），CSS 22.83 kB（gzip 5.29 kB） |

阶段 4B 新增 **13 项**自动化测试，加上阶段 4A 的 17 项后共 30 项。覆盖：

- 无 operator token 前置拒绝；客户 session 不能替代 operator token。
- operator 请求头隔离、列表过滤和服务端分页。
- 非法状态不出现在允许选项中；关闭原因缺失时不发请求。
- 工单详情、会话、审计和 trace 脱敏。
- 审批批准后仍不能替代客户确认；`confirmation_required` 不伪报成功。
- 人工执行并发重复点击保护与服务端 `idempotent_replay` 展示。
- 显式客户 session 的 trace 请求边界。
- task plan、依赖、节点、工具、耗时、Provider 和错误定位。
- 空 `token_usage`。
- trace 不存在和跨 session 的同形 404 拒绝。

测试中的网络响应是 Vitest/jsdom 的隔离替身，只用于验证真实 URL、请求头、错误解析和响应驱动渲染，不进入生产构建，不充当运行时假 API。

## 6. 已核实的边界与未验证项

- 已阅读并按现有 `ticketing.py`、`main.py`、`execution.py`、`database.py` 契约接线；没有修改后端字段或写操作语义。
- 后端没有“列出某工单审批”的 GET API。新建审批可在当前页面决定，刷新后只能通过审计时间线查看历史，不能恢复可操作的 pending approval。这是现有 API 能力限制，不是前端伪造补齐。
- 尚未在真实浏览器连接本机 PostgreSQL 完成管理、审批、客户确认和人工执行的人工端到端演示。
- 尚未做 Playwright E2E、视觉截图回归、屏幕阅读器人工审查和生产 IAM 集成。
- 尚未做 Compose 前端编排、演示账户最终说明和阶段 4 浏览器整体验收；`TASKS.md` 的该项保持未勾选，阶段 4 整体未完成。
- 本轮没有重跑后端 pytest 或 PostgreSQL 集成套件；阶段 4B 没有改动后端，前端兼容性依据代码契约审阅和网络层测试，仍需真实联调补验。
- 本轮没有重新运行 `npm audit`；阶段 4A 报告的 0 vulnerabilities 是当时结果，不能当作本轮重新验证。
- 未创建阶段 4 最终提交，未进入阶段 5。
