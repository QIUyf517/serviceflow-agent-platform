# 阶段 4A：前端基础与用户聊天页验收报告

日期：2026-11-11

## 1. 范围与结论

本轮只完成阶段 4A：React 前端基础和用户售后聊天页。没有实现管理后台、开发者页、前端 Compose 编排或阶段 5；没有新增后端业务能力，没有修改既有 API 字段含义，没有启用外部 DeepSeek。

开始时 Git 工作区干净，`frontend/` 只有 `.gitkeep`，不存在可复用或需要保留的前端实现。最终实现接入现有 FastAPI 真实路径；运行时代码没有静态订单 JSON、假 API 或固定业务响应。测试中的响应是隔离的网络层替身，不进入生产构建。

前端最终自动化 **17 passed、0 failed**；`npm run lint`、`npm run typecheck`、`npm run build` 退出 0。依赖安装后的 `npm audit` 为 **0 vulnerabilities**。外部 LLM 调用 **0**。

## 2. 前端基础

### 工程与路由

- React 19 + TypeScript + Vite。
- React Router：`/support` 为用户服务台；未知路径显示 404 页面。
- TanStack Query 统一管理订单查询和请求失效，不在组件内散落缓存策略。
- Vite 开发代理将 `/api` 转发到 `127.0.0.1:8000`，无需修改后端 CORS。
- ESLint、严格 TypeScript、Vitest、Testing Library 和 jsdom 已配置。

### 请求层

`frontend/src/api/client.ts` 统一实现：

- JSON 编码和 `Accept` / `Content-Type`。
- 受保护请求添加 `X-Session-Id`。
- 建单添加调用方提供的 `Idempotency-Key`。
- 解析 `{"error":{"code":"..."}}`、FastAPI `detail` 和非 JSON 网关错误。
- 网络失败归一化为 `network_unavailable`。
- 无本地 session 时在发出受保护请求前安全拒绝。

只允许 localStorage 保存 `serviceflow.session_id`。身份资料、订单、支付信息、聊天确认和工单内容只保存在当前页面内存或服务端。

### 视觉与无障碍

页面采用售后“服务处理台”信息结构：对话和订单位于主轴，服务端任务进度位于窄轨。视觉层级主要依靠分区线、状态色和信息密度，不使用同质化卡片墙。实现了：

- 桌面双栏、窄屏单栏。
- 跳转主要内容链接、语义化标题与 landmark。
- 表单 label、按钮禁用态、可见键盘焦点。
- `aria-live` 状态更新、错误 `alert`。
- `prefers-reduced-motion` 降低动画。

## 3. 用户页面闭环

实际调用以下既有 API：

| 方法 | 路径 | 前端用途 |
|---|---|---|
| POST | `/api/v1/sessions` | 首次访问创建服务端会话 |
| POST | `/api/v1/sessions/{sid}/verify` | 邮箱或姓名+邮编核验 |
| GET | `/api/v1/orders` | 核验后读取本人订单 |
| GET | `/api/v1/orders/{oid}` | 打开本人订单详情 |
| POST | `/api/v1/multi-agent/chat` | 多轮查询、方案、确认与拒绝 |
| GET | `/api/v1/multi-agent/tasks/current` | 刷新后恢复服务端任务 |
| POST | `/api/v1/tickets` | 客户显式创建人工工单 |

页面能力：

- 首次创建或从 localStorage 读取 session。
- 恢复成功或重新核验成功前不启用订单 Query。
- 展示订单列表、状态、商品和已有物流字段。
- 多轮消息只使用后端 `final_response`，不在前端生成业务结论。
- 取消/退货确认区明确展示 `action`、`order_id` 和 `proposed_parameters`。
- 确认与拒绝都携带服务端 `request_id`；请求进行中用同步 ref 和按钮禁用双重防重复点击。
- 只以 `execution_result.status === "succeeded"` 显示成功；失败原因明确显示为未执行。
- 显式建单使用组件生命周期内稳定的幂等键；失败重试复用同一键。
- 工单成功仅显示“等待人工处理”和服务端状态，不显示已处理完成。
- 刷新恢复展示服务端当前任务、计划、方案、确认和最终回复；不伪造完整聊天历史。

## 4. 状态与错误

已实现并测试或由组件覆盖：

- session 创建、订单查询、订单详情和聊天 loading。
- 无订单与无消息 empty。
- 网络、数据库、身份、确认过期、订单变化等 error。
- `identity_required` 403 返回核验门，订单请求保持禁用。
- `order_not_found` 404 使用不区分不存在/越权的安全文案。
- 路由 404 返回服务台入口。

## 5. 测试

最终验收命令：

```powershell
cd frontend
npm run lint
npm run typecheck
npm run test -- --run
npm run build
```

自动化共 **17 tests**：

- API Client 5：session/header、稳定幂等键、无 session 前置拒绝、业务错误和非 JSON 错误解析。
- 用户页面 12：身份核验、未核验不查订单、订单列表/详情、empty、404、取消等待确认、退货等待确认、拒绝、执行失败、重复点击、人工工单、服务端刷新恢复、恢复 403 隔离（部分断言共享同一用例）。

实现过程中如实处理的失败：

1. 初次依赖解析报告 10 个漏洞（含 2 critical）；升级 Vitest/Vite 并覆盖受影响的 minimatch 后，audit 降为 0。
2. 最新 jsdom 31 不支持本机 Node 22.17；改为仍受支持的 jsdom 29.1 系列。
3. 初次 API Client 测试复用了已消费的 `Response`；改为每次调用创建新响应。
4. 页面测试最初因 Client 在模块初始化时捕获原始 `fetch` 而全部失败；改为请求时解析 `globalThis.fetch`，定向页面测试最终 12/12 通过。

这些失败没有计入最终通过数。

## 6. 安全边界

- 页面不提供客户身份绕过；订单 Query 的 `enabled` 只在服务端任务恢复成功或 verify 成功后打开。
- 客户确认不能由前端布尔状态替代，只发送自然语言决定和服务端请求 ID。
- 前端不读取或依赖 τ-bench `tasks.json` 参考动作或评分条件。
- 订单和支付事实不进入前端本地持久化、向量库或静态资源。
- 后端仍是授权、资格、事务、行版本、幂等和审计的唯一可信边界。
- 本阶段没有恢复旧写 API，没有接入外部 LLM。

## 7. 未验证项与风险

- 尚未在真实浏览器连接本机 PostgreSQL 完成一次人工端到端演示；自动化验证的是前端状态机、请求路径/头和响应驱动渲染。
- 尚未做 Playwright 浏览器 E2E、截图回归和屏幕阅读器人工审查。
- 后端没有读取完整会话历史的客户 API；刷新只能用 `tasks/current` 恢复当前任务和最后回复，不能恢复完整聊天消息列表。
- localStorage 中的 session ID 是 bearer 凭据；本地演示可接受，生产环境需要更强的安全 cookie、过期和登出策略。
- 管理后台、开发者页、前端 Compose/部署、演示账户文档仍属于后续阶段 4 工作。

因此只能勾选 `TASKS.md` 的“React 用户聊天页”单项，不能把阶段 4 整体标记为完成。
