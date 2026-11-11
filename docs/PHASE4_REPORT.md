# 阶段 4：前端、Compose 与真实浏览器验收报告

日期：2026-11-11

## 1. 范围与结论

阶段 4 分三步完成：4A 建立 React 前端与客户聊天页，4B 在同一工程内增加管理后台和开发者页，4C 只完成 Docker Compose、真实浏览器验收、文档和阶段收尾。本阶段没有进入阶段 5，没有新增后端业务能力，没有实现修改/换货，没有修改 τ-bench 官方文件，也没有启用外部 DeepSeek。

最终验收满足阶段 4 门槛：后端 **204 passed、0 failed、0 skipped**；前端 **7 files、30 passed、0 failed**；Playwright Chromium **6 passed、0 failed**；PostgreSQL、FastAPI、React/Nginx 三个 Compose 服务均为 healthy；浏览器测试连接真实 FastAPI 和真实 PostgreSQL；随机测试 schema 残留 **0**；外部 LLM 调用 **0**。因此只勾选 `TASKS.md` 阶段 4 的最后一项，使阶段 4 四项全部完成；阶段 5 保持未勾选。

## 2. 4A–4C 文件清单

阶段 4A/4B 的历史报告分别保存在 `docs/PHASE4A_REPORT.md` 和 `docs/PHASE4B_REPORT.md`。阶段 4 最终相关文件如下：

| 子阶段 | 文件 | 作用 |
|---|---|---|
| 4A 基础 | `frontend/package.json`、`package-lock.json`、`index.html`、`vite.config.ts`、`tsconfig*.json`、`eslint.config.js` | React、TypeScript、Vite、Router、TanStack Query、Vitest、ESLint 配置 |
| 4A 应用 | `frontend/src/app/*`、`main.tsx`、`styles/global.css` | 路由、Query Client、共享 trace 工作区、响应式和无障碍基础 |
| 4A 客户页 | `frontend/src/pages/SupportPage.tsx`、`frontend/src/components/{IdentityGate,OrdersPanel,ConversationPanel,ConfirmationPanel,TaskProgress,TicketPanel,StateNotice}.tsx` | 身份、订单、多轮对话、确认/拒绝、任务恢复和人工工单 |
| 4A 请求层 | `frontend/src/api/{client,errors,idempotency,sessionStore,serviceflow,types}.ts` | 客户 session、统一错误、幂等键和真实 API 调用 |
| 4B 管理页 | `frontend/src/pages/AdminPage.tsx`、`frontend/src/components/admin/*`、`frontend/src/api/{operator,operatorStore,adminTypes}.ts` | 独立操作员认证、工单列表/详情/审计/审批/执行 |
| 4B 开发者页 | `frontend/src/pages/DeveloperPage.tsx`、`frontend/src/components/developer/TraceInspector.tsx`、`frontend/src/api/{developer,developerTypes}.ts` | 当前任务、成功/失败 trace、工具、耗时和关联 ID |
| 4A/4B 单测 | `frontend/src/**/*.test.ts(x)`、`frontend/src/test/setup.ts` | 7 个文件、30 项前端单元/组件测试 |
| 4C 容器 | `docker-compose.yml`、`.dockerignore`、`backend/Dockerfile`、`frontend/Dockerfile`、`frontend/nginx.conf`、`.env.example`、`.gitignore` | db/api/frontend 健康编排、显式种子镜像、秘密与构建产物隔离 |
| 4C 浏览器 | `frontend/playwright.config.ts`、`frontend/e2e/phase4.spec.ts`、`frontend/e2e/run-e2e.mjs`、`scripts/run_phase4_e2e.py` | 真实浏览器、真实 API、隔离 PostgreSQL schema、强制清理 |
| 4C 文档 | `README.md`、`TASKS.md`、`docs/PHASE4_REPORT.md` | 启动、演示、验收证据和阶段收尾 |

删除了仅用于占位的 `frontend/.gitkeep`。没有提交 `.env.phase4`、`node_modules`、`dist`、Playwright trace/截图/视频、数据库卷或测试日志。

## 3. 页面、路由与 API 映射

| 页面 | 路由 | 真实 API |
|---|---|---|
| 客户服务台 | `/support`；`/` 重定向至此 | `POST /sessions`、`POST /sessions/{sid}/verify`、`GET /orders`、`GET /orders/{oid}`、`POST /multi-agent/chat`、`GET /multi-agent/tasks/current`、`POST /tickets` |
| 管理后台 | `/admin` | `GET /tickets`、`GET /tickets/{id}`、`GET /tickets/{id}/audit`、`POST /assign`、`POST /status`、`POST /approvals`、`POST /approvals/{approval_id}/decision`、`POST /execute` |
| 开发者页 | `/developer` | `GET /traces/{trace_id}`、`GET /multi-agent/tasks/current`，以及当前标签页聊天响应中的 `trace`、`tool_results`、`metrics`、`task_plan` |
| 未知路由 | `*` | 本地 404 页面，不触发业务写入 |

表中路径均以 `/api/v1` 为前缀。Nginx 将 `/api/` 代理到 `api:8000`；Vite 的测试/开发代理使用显式的本机 API 地址。运行时代码没有静态订单 JSON、固定响应或假 API。

## 4. 鉴权、确认和数据边界

- 客户 `session_id` 是 bearer 凭据。前端只在 localStorage 保存这一随机 ID，用于演示刷新恢复；客户资料、订单、支付信息和确认记录不落本地副本。服务端身份恢复成功前不请求订单。
- 操作员使用独立 `X-Operator-Token`。值只由操作员输入并保存在当前标签页 sessionStorage，不进入 URL、源码、构建变量或前端镜像；客户 session 不能替代它。该机制明确只是本地演示认证，不是生产 IAM。
- 客户确认与内部审批是两个不同条件。审批通过不会创建客户确认，也不能代客户确认；缺少有效客户确认时，人工代触发必须返回并显示 `confirmation_required`。
- 确认区显示具体 `action`、`order_id` 和参数摘要。前端只在服务端 `execution_result.status === "succeeded"` 时显示成功，不能从按钮状态或自然语言推断业务完成。
- 客户工单只显示 open/等待人工处理，不显示已处理完成。写请求继续依赖服务端事务、订单版本重校验、硬规则、幂等键和审计。
- 管理和 trace 展示做防御性脱敏：不显示邮箱、完整地址、卡号、API Key、完整 Prompt 或 τ-bench 参考动作/评分条件。
- Compose 明确设置 `AGENT_PROVIDER=mock` 与关键词检索。API 运行镜像不包含 `tasks.json`；前端镜像检查未发现数据库密码、API Key 或 operator token。外部 LLM 调用次数为 **0**。
- 演示数据库名为 `serviceflow_demo`，复用现有 `flowagent_demo_pgdata` 卷；官方评测继续使用独立环境，不与演示库共享写入。

## 5. Docker 启动、种子数据与演示

本地配置只从占位符模板复制，真实值不提交：

```powershell
Copy-Item .env.example .env.phase4
# 替换 .env.phase4 内全部 <...> 占位符
docker compose config
docker compose up -d --build
docker compose ps
```

启动依赖为 `db healthy → api healthy → frontend`。普通启动不运行 seed、不 reset 数据，也不删除或覆盖现有卷。最终实测三个服务均为 healthy，API `/api/v1/health` 返回 `ok`，前端 `/healthz` 返回 HTTP 200。

显式导入固定演示快照：

```powershell
docker compose --profile tools run --rm seed
```

本次执行成功，结果为 **500 users、50 products、1000 orders**。同版本重复导入不覆盖演示业务修改；`--reset` 只能在操作者明确接受复位演示数据时手动追加，普通启动绝不自动执行。seed 使用单独镜像 target 才复制完整只读原始数据，API runtime 只复制运行所需政策和知识文件。

演示顺序：在 `/support` 用 τ-bench 本地模拟账户完成身份核验和客户流程；在 `/admin` 输入 `.env.phase4` 的独立 operator token 处理人工工单；在 `/developer` 使用同一客户 session 边界查看当前任务和 trace。不存在或跨 session 的 trace 统一返回安全 404。

## 6. 真实浏览器验收

`npm run test:e2e` 由 Python 编排器完成以下工作：创建随机 `phase4_e2e_<uuid>` PostgreSQL schema；导入六组隔离合成数据；删除所有外部 Provider Key 环境变量；启动真实 FastAPI 和 Vite；用 Chromium 运行 Playwright；无论成功或失败都终止进程并删除全部 `phase4_e2e_*` schema。测试没有路由拦截或假 API。

用户要求的八项验收映射到六个串行测试：

1. 身份核验后才查询本人订单。
2. 取消方案展示具体摘要，客户确认后订单变为 cancelled，执行审计可见；同一测试查看成功 trace，Provider 如实为 Mock。
3. 退货方案经客户确认后显示服务端真实终态 `return requested`。
4. 方案生成后不确认，订单状态和版本零写入；刷新后从 `tasks/current` 恢复待确认状态。
5. 客户请求人工后工单为 open；管理后台分配并流转至 in_progress，审计可见。
6. 操作员审批 approved 但客户未确认时，人工执行被 `confirmation_required` 拒绝。
7. 开发者页分别展示真实成功 trace 和由订单竞争产生的真实失败 trace（`order_changed`）。
8. 刷新恢复已由第 4 项覆盖待确认状态；验收要求是“待确认或处理中”，因此没有伪造额外处理中场景。

最终 Playwright 结果为 **6 passed、0 failed，8.0 秒**；创建的 schema 删除 1 个，随后编排器与独立 SQL 查询均确认残留为 **0**。Playwright trace、截图和视频均关闭，避免产生敏感产物。

## 7. 完整测试结果

| 命令 | 最终结果 |
|---|---|
| `$env:TEST_DATABASE_URL=...serviceflow_demo; .venv_tau/Scripts/python -m pytest -q -rs -p no:cacheprovider --basetemp=.tmp/pytest-phase4-full` | **204 passed、0 failed、0 skipped，54.89s**；使用真实 PostgreSQL |
| `.venv_tau/Scripts/python -m ruff check backend scripts tests` | 退出 0，All checks passed |
| `npm run lint` | 退出 0 |
| `npm run typecheck` | 退出 0 |
| `npm run test -- --run` | **7 files、30 passed、0 failed，12.92s** |
| `npm run build` | 退出 0；97 modules；JS 345.37 kB（gzip 106.70 kB），CSS 22.83 kB（gzip 5.29 kB） |
| `npm run test:e2e` | **6 passed、0 failed，8.0s**；真实 Chromium/FastAPI/PostgreSQL |
| `docker compose config` | 退出 0 |
| `docker compose up -d --build` | 退出 0；api/frontend 镜像构建成功 |
| `docker compose ps` | db、api、frontend 全部 healthy |
| `docker compose --profile tools run --rm seed` | 退出 0；500/50/1000；一次性容器已删除 |

实施过程中没有把失败隐藏为通过：一次前端全套测试因 Vitest 误收集 `e2e/` 而在 30 项单测通过后退出失败，修正测试排除规则后重新执行全部四项前端门禁并通过；Playwright 前三轮分别暴露状态元素定位、异步建单时序和重复文案严格定位问题，逐一修正后最终两轮均为 6/6。失败轮次创建的随机 schema 同样清理为 0。

## 8. 清理、已知边界与未完成项

- E2E 启动的 FastAPI/Vite 进程已终止；seed 一次性容器已自动删除；随机测试 schema 残留 0。没有执行 `docker compose down --volumes`，用户的演示数据库卷被保留。最终三个演示服务保持 healthy，便于复核。
- 已验证 Chromium，没有做 Firefox/WebKit 矩阵、截图回归或屏幕阅读器人工审查；不能把基本无障碍实现表述为完整 WCAG 认证。
- 现有后端没有工单审批列表 GET API，管理页刷新后只能从审计查看历史审批，不能恢复可操作的 pending approval。
- 持久化 trace API 不返回当前聊天响应中的全部工具结果、Provider、模型和 task plan；页面明确显示字段未提供，不补造。
- localStorage session 和 operator token 都只适合本地演示；生产环境仍需安全 cookie、真实 IAM、登出/轮换、CSRF 与更严格 CSP。
- 不支持修改/换货执行，不连接真实支付、邮件或客服系统；没有调用外部 LLM；阶段 5 评测尚未开始。

## 9. 阶段判定

阶段 4 的四个任务项均已满足并勾选。这里的“完成”仅指仓库定义的阶段 4 产品演示和验收，不代表生产就绪，也不代表官方 τ-bench 成绩或多 Agent 优于单 Agent。阶段 5 应继续保持官方评测与产品扩展评测隔离，并在固定模型、样本、预算和重复次数后再报告结果。
