# ServiceFlow — 可信多 Agent 智能售后平台

> 状态：阶段 5 已完成。独立保留集没有复现开发集优势：单 Agent **51/120（42.50%）**，多 Agent V3 **45/120（37.50%）**，配对 McNemar `p=0.238`。证据不支持 V3 优越，也不足以证明确定劣势；holdout 已冻结。结果使用 DeepSeek 自定义 Judge，不具备官方默认 τ-bench 分数资格。

## 项目定位

基于 **τ-bench Retail 的模拟业务数据和政策**，开发一个可演示的电商售后系统：用户可以咨询订单、查询商品、申请取消/修改订单以及退换货；系统用 **LangGraph 多 Agent + 受控业务工具 + 规则校验 + 明确确认 + 可恢复状态** 完成工作，并用公开基准和自建异常场景评估可靠性。

- 目标用户：电商客户（聊天窗口）、售后客服/主管（工单与人工接管）、开发者（执行轨迹与评测）。
- 核心价值：**从回答问题升级为安全地完成售后业务**。
- 求职亮点：Tool Calling、RAG、业务 API、Multi-Agent、状态持久化、权限/幂等、可复现评测。

## 已实现安全架构

```mermaid
flowchart LR
  C[顾客 / 商家客服] --> API[FastAPI + 服务端会话]
  API --> ID[身份、归属、订单线程]
  ID --> SUP[确定性 Supervisor]
  SUP --> T[Triage]
  SUP --> O[Order 只读]
  SUP --> P[Policy 检索]
  SUP --> R[Resolution 提案]
  O --> DB[(PostgreSQL)]
  P --> KB[(政策索引 / pgvector)]
  R --> G[确定性 Guard]
  G -->|只读| REPLY[中文回复]
  G -->|写操作| CONFIRM[具体摘要 + 客户明确确认]
  CONFIRM --> RECHECK[执行前重读与规则复核]
  RECHECK --> TX[事务 + 幂等键 + 审计]
  TX --> DB
  G -->|超范围/失败| HUMAN[人工工单]
```

LLM 只理解、规划、解释和选择白名单工具；身份授权、订单资格、确认绑定及数据写入均由服务端确定性代码决定。多 Agent 是被评估的架构选项，不是预设优于单 Agent 的结论。

## 文件导航

- [AGENTS.md](AGENTS.md)：Codex 的项目级执行准则（请放仓库根目录）。
- [TASKS.md](TASKS.md)：各阶段按顺序执行的任务与验收门槛。
- [docs/PROJECT_SPEC.md](docs/PROJECT_SPEC.md)：产品需求、用户场景、业务流程、边界。
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)：Agent编排、状态机、API与业务层。
- [docs/PHASE2_ARCHITECTURE.md](docs/PHASE2_ARCHITECTURE.md)：阶段 2.1 共享状态与专业节点接口契约。
- [docs/PHASE2_2_REPORT.md](docs/PHASE2_2_REPORT.md)：阶段 2.2 Triage、Supervisor 与调试入口验收。
- [docs/PHASE2_3_REPORT.md](docs/PHASE2_3_REPORT.md)：阶段 2.3 Order Agent 查询、授权与数据库验收。
- [docs/PHASE2_4_REPORT.md](docs/PHASE2_4_REPORT.md)：阶段 2.4 Policy Agent、政策知识库与检索评估。
- [docs/PHASE2_5A_REPORT.md](docs/PHASE2_5A_REPORT.md)：阶段 2.5A Resolution Agent、只读规则校验与验收。
- [docs/PHASE2_5B_REPORT.md](docs/PHASE2_5B_REPORT.md)：阶段 2.5B 可信确认、订单取消执行与并发验收。
- [docs/PHASE4A_REPORT.md](docs/PHASE4A_REPORT.md)：阶段 4A 前端基础与用户服务台验收。
- [docs/PHASE4B_REPORT.md](docs/PHASE4B_REPORT.md)：阶段 4B 管理后台与开发者追踪页验收。
- [docs/PHASE4_REPORT.md](docs/PHASE4_REPORT.md)：阶段 4 Compose、真实浏览器验收与总体验收。
- [docs/PHASE4_5A_REPORT.md](docs/PHASE4_5A_REPORT.md)：阶段 4.5A 模拟商店、顾客会话隔离与真实浏览器验收。
- [docs/PHASE4_5B_REPORT.md](docs/PHASE4_5B_REPORT.md)：阶段 4.5B 内容安全、咨询分流、售后闭环与真实浏览器验收。
- [docs/PHASE4_5C_REPORT.md](docs/PHASE4_5C_REPORT.md)：阶段 4.5C 中文体验、双向人工会话与后台聊天窗口。
- [docs/PHASE4_5D_REPORT.md](docs/PHASE4_5D_REPORT.md)：阶段 4.5D 订单独立会话线程、串话修复与旧库迁移。
- [docs/PHASE4_5_ACCEPTANCE_REPORT.md](docs/PHASE4_5_ACCEPTANCE_REPORT.md)：阶段 4.5 最终人工与自动化验收记录。
- [docs/PHASE5A_REPORT.md](docs/PHASE5A_REPORT.md)：阶段 5A 评测配置、保留集边界、自建异常集与烟测验收。
- [docs/PHASE5B_HOLDOUT_REPORT.md](docs/PHASE5B_HOLDOUT_REPORT.md)：阶段 5B 保留集对照、统计结论与事故披露。
- [reports/summary.md](reports/summary.md)：阶段 5 最终指标、四组证据矩阵、成本与失败分类。
- [docs/PHASE5_REPORT.md](docs/PHASE5_REPORT.md)：阶段 5 最终验收与求职交付说明。
- [docs/DATA_AND_RAG.md](docs/DATA_AND_RAG.md)：τ-bench 下载导入、RAG、数据隔离。
- [docs/EVALUATION.md](docs/EVALUATION.md)：基线实验、官方与扩展评测、指标。
- [CODEX_START_HERE.md](CODEX_START_HERE.md)：第一条可以复制给 Codex 的任务提示。

## 技术选型

- Python 3.12（兼容上游 τ-bench 当前对 Python >=3.12,<3.14 的要求）
- FastAPI + Pydantic、LangGraph、PostgreSQL、pgvector（RAG 第二阶段）
- React + TypeScript + Vite（在 API 闭环跑通后启动）
- pytest、ruff、Docker Compose；可选 Langfuse（观测）
- LLM Provider 做成可配置适配层，不把某家 API 绑定进业务层

## 优先顺序（必须遵循）

1. P0a：从官方 τ-bench Retail **下载且校验** `db.json`、`policy.md`、`tasks.json`、`split_tasks.json`；导入本地可复位业务库。
2. P0b：实现 API + **单 Agent 基线**，处理查询、取消和一类退货流程，并完成严格的身份校验、确认后写入。
3. P0c：将代码逐步拆成专业 Agent + 确定性验证节点，始终保留单 Agent 供对照。
4. P1：RAG、工单管理、可恢复执行、人工审核、异常注入、正式评测。
5. P2：前端体验、美化与部署；模型微调仅为可选研究，不是首版阻塞项。

## 项目成功标准（不是预设实验结果）

- 端到端支持：身份核验 → 订单查询 → 政策检查 → 生成操作提案 → 用户确认 → 规则引擎验证 → 执行 → 审计 → 回复。
- 未核验不透露订单数据；无明确确认不执行写操作；重复请求不重复写入。
- 数据可重建、执行可追溯、有测试报告，有单 Agent / 多 Agent 公平对照。
- 演示环境成绩与官方 τ-bench 结果**分开报告**；没有实测数据不得编造提升百分比。

## 权威参考

- τ-bench 官方仓库：https://github.com/sierra-research/tau2-bench
- τ-bench Retail 数据目录：https://github.com/sierra-research/tau2-bench/tree/main/data/tau2/domains/retail
- τ-bench Agent 示例：https://github.com/sierra-research/tau2-bench/tree/main/examples/agents
- τ-bench 评分机制：https://github.com/sierra-research/tau2-bench/blob/main/docs/evaluation.md
- LangGraph 文档：https://docs.langchain.com/oss/python/langgraph/overview

## 阶段 0 运行说明

项目文件已整理到 Git 仓库根目录，`backend/`、`docs/`、`scripts/` 与 `.git/` 同级。以下命令均在仓库根目录执行，无需再进入 `ServiceFlow/` 子目录。需要 Python 3.12、uv；数据库需要 Docker Compose 或独立 PostgreSQL。无需 LLM Key。

```powershell
uv venv --python 3.12 .venv312
uv pip install --python .venv312/Scripts/python.exe -r requirements-dev.lock
uv pip install --python .venv312/Scripts/python.exe --no-deps -e backend
Copy-Item .env.example .env
docker compose up -d --wait db
.venv312/Scripts/python -m scripts.phase0
```

当前机器本次已在 `.venv/Scripts/uv.exe` 安装 uv，并在 `.python/` 安装 Python 3.12.16；若没有全局 uv，可用该路径运行。已有 `.env` 时请手动比对，勿覆盖个人配置。Linux/macOS 将 `.venv312/Scripts/python` 替换为 `.venv312/bin/python`。锁文件记录本次 Windows 验证依赖，跨平台需重新解析环境相关依赖。

一键命令依次执行固定版本获取/哈希检查、结构报告、导入两次、pytest（启用 PostgreSQL 集成测试）、ruff。任何一步失败即返回非零，不宣称验收成功。结构报告写入 `data/processed/structure_report.json`，成功导入的来源及数量写入 `data/manifest.json`。原始文件的版本、获取时间和逐文件 SHA256 始终保存在 `data/raw/tau2/<commit>/manifest.json`。

单独运行与离线使用：

```powershell
.venv312/Scripts/python -m scripts.fetch_tau_retail
.venv312/Scripts/python -m scripts.inspect_tau_retail --output data/processed/structure_report.json
.venv312/Scripts/python -m scripts.seed_database
# 明确复位：仅重建此演示库的导入表数据，保留表结构
.venv312/Scripts/python -m scripts.seed_database --reset
# 离线源仓库必须干净，HEAD 必须等于指定完整 commit
.venv312/Scripts/python -m scripts.fetch_tau_retail --local-repository C:/path/to/tau2-bench --commit da0835f6c67baef58bdda18f2a3b037dfb3a1754
.venv312/Scripts/python -m pytest -q
.venv312/Scripts/python -m ruff check backend scripts tests
```

pytest 默认将缓存写入仓库根目录的 `.pytest_cache/`，该目录已被 Git 忽略。测试使用的 `tmp_path` 临时数据库通常放在系统临时目录；运行测试时不要指定仓库根目录下的 `--basetemp=.pytest_*`，以免再次留下测试临时目录。若本机 `.pytest_cache/` 无写入权限，可用 `-p no:cacheprovider` 跳过缓存写入；若系统临时目录也无写入权限，需先为 `tmp_path` 提供可写的临时位置。

普通 pytest 可不连接数据库，SQLite 仅作为显式测试替身。设置 `TEST_DATABASE_URL` 后才运行 PostgreSQL 测试；测试创建独立临时 schema 并清理，不与演示表共享内容。数据库名称必须以 `_demo` 结尾，官方评测环境不得使用这个演示数据库。源快照变化必须显式 `--reset`，同版本重复导入不会覆盖已发生的演示业务修改。

存活 API（仅存活检查，不表示数据库就绪）：

```powershell
.venv312/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
Invoke-RestMethod http://127.0.0.1:8000/api/v1/health
```

`GET /api/v1/health` 无输入，HTTP 200 输出 `{"status":"ok"}`；OpenAPI 位于 `/docs`。

阶段 0 最终验证：一键命令退出 0，**13 passed、0 skipped**，ruff 通过；真实 PostgreSQL 16.15 中 500 用户、50 商品、1000 订单。详见 [阶段 0 报告](docs/PHASE0_REPORT.md) 与 [数据映射](docs/DATA_IMPORT.md)。

## 阶段 1 启动与 API 示例

安装更新后的锁定依赖，启动已有 PostgreSQL，再启动 API：

```powershell
.venv/Scripts/uv pip sync --python .venv312/Scripts/python.exe requirements-dev.lock
.venv/Scripts/uv pip install --python .venv312/Scripts/python.exe --no-deps -e backend
docker compose up -d --wait db
.venv312/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

本地模拟身份核验支持邮箱或姓名+邮编，仅供模拟业务演示。会话 ID 是 bearer 凭据，应保密；未核验不能读取客户资料。以下示例需替换为数据库中对应的模拟邮箱和本人订单号，输出值仅示意：

```powershell
$s = Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/sessions
# 输出：{"session_id":"<随机会话ID>"}
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/api/v1/sessions/$($s.session_id)/verify" -ContentType application/json -Body '{"email":"customer@example.com"}'
# 输出：{"user_id":"<对应客户ID>"}
$h = @{ 'x-session-id' = $s.session_id }
Invoke-RestMethod http://127.0.0.1:8000/api/v1/orders -Headers $h
# 输出：本人订单 JSON 数组；无身份时 HTTP 403 {"error":{"code":"identity_required"}}
$p = Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/operations -Headers $h -ContentType application/json -Body '{"kind":"cancel","order_id":"#W0000000","reason":"no longer needed"}'
# 输出：{"proposal_id":"<ID>","status":"proposed","action":{...},"summary":"..."}
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/api/v1/operations/$($p.proposal_id)/confirm" -Headers $h -ContentType application/json -Body '{"confirmed":true}'
# 输出：{"proposal_id":"<ID>","status":"succeeded","order_id":"#W0000000","order_status":"cancelled","row_version":2}
```

`POST /api/v1/operations` 的 `kind` 还支持 `modify_address`（完整 address）、`modify_payment`（payment_method_id）、`modify_items` / `exchange`（item_ids、new_item_ids、payment_method_id）及 `return`（item_ids、payment_method_id）。全部走同一提案、明确确认、订单版本重校验、数据库事务、幂等和审计路径。`GET /api/v1/users/me`、`GET /api/v1/orders`和 `GET /api/v1/orders/{id}` 要求已核验会话；公开商品目录 `GET /api/v1/products` 和 `GET /api/v1/products/{id}` 只要求服务端已建立的有效会话，不返回客户资料。操作仅修改本地模拟数据库；支付历史变更不是外部资金退款或真实邮件发送。

聊天入口 `POST /api/v1/chat` 的输入示例为 `{"message":"cancel order #W0000000 because ordered by mistake"}`，输出包含 `trace_id`、`provider:"mock"`、调用数/耗时、`token_usage:null` 和 `response`（含提案 ID）。之后发送 `{"message":"yes","proposal_id":"<该提案ID>"}` 才可执行。Mock 只识别有限的演示表达；可通过 `ToolSelector` 替换模型，但本轮没有真实模型测试。提案 15 分钟后失效；状态变化需重新提案。原始 τ-bench 任务和评分条件不会进入运行时。

完整验证命令：

```powershell
$env:TEST_DATABASE_URL = (.venv312/Scripts/python -c "from app.config import Settings; print(Settings().database_url)")
.venv312/Scripts/python -m pytest -q -p no:cacheprovider
.venv312/Scripts/python -m ruff check backend scripts tests
```

PostgreSQL 测试创建/清理 `phase0_*` 与 `phase1_*` 临时 schema；普通测试使用 SQLite 替身。`scripts.eval_baseline` 是独立 schema 的任务 ID 烟测入口，输出 `task_completed:null`，不得当作官方评分。细节与限制见 [阶段 1 报告](docs/PHASE1_REPORT.md)。

Windows 环境：Docker Desktop 安装至 `D:\Docker`，引擎已启动，容器数据磁盘确认为 `D:\DockerData\disk\docker_data.vhdx`。数据库容器保持运行；若当前终端尚未更新 PATH，可使用 `& 'D:/Docker/resources/bin/docker.exe' compose up -d --wait db`。停止数据库用 `docker compose stop db`，保留数据卷以便后续使用。

## 阶段 1.5：真实 LLM 与官方文本评估

Mock 仍为默认模式。真实模型通过兼容 OpenAI Chat Completions 的 Tool Calling 接口调用；当前已用 `.env` 中的 DeepSeek 配置实测。将以下配置写入**未跟踪的** `.env`，不要提交密钥：

```dotenv
AGENT_PROVIDER=openai_compatible
AGENT_MODEL=deepseek-flash
AGENT_BASE_URL=https://api.deepseek.com
AGENT_API_KEY=<your-key>
```

现有 `LLM_API_KEY`、`LLM_MODEL_ID`、`LLM_BASE_URL` 也能作为回退配置。若使用其他兼容 Provider，替换模型和地址即可。Mock 模式设置 `AGENT_PROVIDER=mock`，不需要密钥。真实模型的查询和写操作均调用服务端工具；写操作先返回具体提案，客户须在同一会话发送 `yes` 和对应 `proposal_id` 才执行。会话消息和工具轨迹保存在 PostgreSQL；通过 `GET /api/v1/traces/{trace_id}` 携带原会话的 `x-session-id` 读取。会话 ID 是访问凭据。

```powershell
# API 已启动且已有经核验会话 $s 时
$h = @{ 'x-session-id' = $s.session_id }
$body = @{ message = 'Please check order #W0000000' } | ConvertTo-Json
$turn = Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/chat -Headers $h -ContentType application/json -Body $body
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/traces/$($turn.trace_id)" -Headers $h
# 写操作返回 proposal_id 后：
$confirm = @{ message = 'yes'; proposal_id = '<returned-proposal-id>' } | ConvertTo-Json
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/chat -Headers $h -ContentType application/json -Body $confirm
```

`scripts.verify_live_workflows` 从固定的公开 Retail 快照创建临时 PostgreSQL schema，执行查询、取消、地址修改及退货，结束删除 schema；不会修改正式演示表。真实调用会产生少量 API 费用。

```powershell
.venv312/Scripts/python -m scripts.verify_live_workflows
```

官方适配器依赖固定 commit `da0835f6c67baef58bdda18f2a3b037dfb3a1754` 的独立 τ-bench 安装，不能混用产品数据库。先克隆该 commit 到被忽略的 `vendor/tau2-bench` 并安装到独立 Python 环境；脚本会核对 Git HEAD、四个官方原始文件哈希。以下命令会生成固定任务清单；加 `--run` 才调用真实模型。官方用户模拟器也使用 DeepSeek，密钥从同一个 `.env` 读取。

```powershell
git clone https://github.com/sierra-research/tau2-bench.git vendor/tau2-bench
git -C vendor/tau2-bench checkout da0835f6c67baef58bdda18f2a3b037dfb3a1754
.venv/Scripts/uv venv --python 3.12 .venv_tau
.venv/Scripts/uv pip install --python .venv_tau/Scripts/python.exe -e backend -e vendor/tau2-bench pytest ruff
.venv_tau/Scripts/python -m scripts.run_tau2_baseline --phase smoke
.venv_tau/Scripts/python -m scripts.run_tau2_baseline --phase smoke --run
.venv_tau/Scripts/python -m scripts.run_tau2_baseline --phase baseline --run
.venv_tau/Scripts/python -m scripts.run_tau2_baseline --phase baseline --summarize-only
# 单独重复一次并保留新轨迹
.venv_tau/Scripts/python -m scripts.run_tau2_baseline --phase baseline --run --run-id repeat2
```

当前固定样本为 Retail `train` 中按官方顺序选出的前 10 项无 `communicate_info` 的原始任务，烟测是其中前 2 项；这是因为上游默认语义裁判需要单独的 OpenAI 裁判密钥。样本选择已记录，**不能把本样本成绩称作官方完整 Retail 成绩**。脚本不修改官方任务、工具或评分器，也不把任务答案传给 Agent。产品评估结果位于 `reports/raw/product_live/`，官方结果位于 `reports/raw/official/`；两者单独统计。详见 [阶段 1.5 报告](docs/PHASE1_5_REPORT.md)。

## 阶段 2.1：共享状态与接口契约

`backend/app/multi_agent/state.py` 提供独立于单 Agent 基线的 `AgentState`、`new_agent_state` 和 `apply_agent_update`。模块没有接入 `/api/v1/chat`；阶段 2.1 不提供多 Agent API。初始化输入示例：`new_agent_state("server-session-id")`，输出的 `session_id` 和 `thread_id` 均为该 ID，`user_id`、`order_context` 为 `None`，消息及错误列表为空。只有服务端从已核验会话读取用户 ID 后才能设置身份字段；模型输出不能授权订单查询或写入。设计和各节点输入输出见 [阶段 2.1 架构文档](docs/PHASE2_ARCHITECTURE.md)。

```powershell
.venv312/Scripts/python -m pytest -q -p no:cacheprovider tests/test_multi_agent_state.py
.venv312/Scripts/python -m ruff check backend scripts tests
```

## 阶段 2.2：意图识别与任务规划预览

`POST /api/v1/debug/plan` 使用已有会话的 `x-session-id`，输入自然语言后返回 Triage 结构化结果、任务计划、下一目标、缺失信息和节点轨迹。阶段 2.2 初次验收时该入口只规划；当前已增加只读 Order、Policy、Resolution 与确定性资格校验。该入口始终不创建或执行业务写操作；现有 `/api/v1/chat` 仍是单 Agent 基线。默认 `AGENT_PROVIDER=mock` 使用可重复的本地分类/证据回答；设置 `AGENT_PROVIDER=openai_compatible` 时 Triage 和 Policy 复用现有模型配置，Resolution 仍使用本地生成器，不向外部模型发送订单上下文。

```powershell
# 先用现有 POST /api/v1/sessions 创建 $sid；订单业务查询仍需先核验身份
$h = @{ 'x-session-id' = $sid }
$body = @{ message = '查询订单123的状态，并咨询退货政策' } | ConvertTo-Json
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/debug/plan -Headers $h -ContentType application/json -Body $body
```

响应含 `input`、`triage`（`intent`、`intents`、`order_id` 等）、`task_plan`、`next_agent`、`missing_information`、`task_status`、`trace` 和 `final_response`。阶段 2.2 的历史规划结果见 [阶段 2.2 报告](docs/PHASE2_2_REPORT.md)；当前只读执行结果见下节。

## 阶段 2.3：Order Agent 只读查询

先通过现有 `POST /api/v1/sessions` 创建会话，并通过 `/api/v1/sessions/{id}/verify` 完成服务端身份核验；会话 ID 是访问凭据。使用真实数据库中**属于该客户**的订单号替换以下占位符。公开商品查询仍需有效会话，但无需客户身份核验。调试入口会返回真实业务库字段的受限投影，不返回地址、支付历史或客户资料。

```powershell
$h = @{ 'x-session-id' = $sid }
$body = @{ message = '查询订单<本人订单号>的状态' } | ConvertTo-Json
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/debug/plan -Headers $h -ContentType application/json -Body $body
```

输出示例（合成测试订单 `o`）：`{"triage":{"intent":"order_query","order_id":"o"},"task_status":"queried","next_agent":"end","task_plan":[{"task_id":"order-lookup","target_agent":"order","status":"completed"}],"tool_results":[{"tool":"get_order_status","status":"ok","code":null}],"order_data":{"order-lookup":{"kind":"status","source":"business_database","order_id":"o","status":"pending"}}}`。这是字段摘录，完整响应还包含 `input`、`trace`、`order_context`、`state` 等。缺订单号时先返回 `clarification`；同会话下一轮补充编号后继续查询。未核验身份无法读取私人订单；查询他人订单返回 `order_not_found`。复合售后请求现在会在 Order 与 Policy 依赖完成后进入 Resolution；进程重启后调试会话状态仍不会恢复。详见 [阶段 2.3 报告](docs/PHASE2_3_REPORT.md)。

```powershell
$env:TEST_DATABASE_URL = (.venv312/Scripts/python -c "from app.config import Settings; print(Settings().database_url)")
.venv_tau/Scripts/python -m pytest -q -rs -p no:cacheprovider -o faulthandler_timeout=45 --basetemp=.tmp/pytest-work
.venv312/Scripts/python -m ruff check backend scripts tests
```

上述完整测试命令需运行中的 PostgreSQL 和装有 `tau2` 的独立 `.venv_tau`；Windows TestClient 在受限本地 socket 环境可能挂起，需允许本机 loopback。`--basetemp` 使用工作区内可写目录。

## 阶段 2.4：Policy Agent 与政策检索

政策源固定为阶段 0 校验过的 `policy.md`（commit `da0835f6c67baef58bdda18f2a3b037dfb3a1754`）。导入器按 H2 业务条款分成 7 个 chunk，并将 H3 子规则保留在父条款内；保存标题路径、来源、commit、SHA256 和稳定 chunk ID。重复导入不新增记录，源文变更需显式 `--rebuild`。

```powershell
# 幂等构建关键词索引
.venv312/Scripts/python -m scripts.index_policy
# 政策源确认变更后重建
.venv312/Scripts/python -m scripts.index_policy --rebuild
# 仅当 PostgreSQL 已安装 pgvector 且配置 Embedding Key 时
.venv312/Scripts/python -m scripts.index_policy --vector
.venv312/Scripts/python -m scripts.evaluate_policy_retrieval --output reports/phase2_4_retrieval.json
```

默认 `POLICY_RETRIEVAL_STRATEGY=keyword`。向量模式使用同一 PostgreSQL 中的 `vector(n)`、OpenAI-compatible `/embeddings` 接口和独立 `POLICY_EMBEDDING_*` 配置；不引入独立向量库。当前本机 PostgreSQL 16.15 实测没有可用的 pgvector 扩展，且未配置 Embedding 专用 Key，因此向量评估显式为 `unavailable`，没有用关键词成绩冒充。

调试请求示例（政策咨询不要求客户身份；查询具体私有订单仍必须核验）：

```powershell
$s = Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/sessions
$h = @{ 'x-session-id' = $s.session_id }
$body = @{ message = '已送达商品的换货政策是什么？' } | ConvertTo-Json
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/debug/plan -Headers $h -ContentType application/json -Body $body
```

响应新增 `policy_retrieval` 和 `policy_context`：前者包含原始查询、关键词列表、检索方法、Top-K、耗时、分数、完整片段及来源；后者是写入 `AgentState` 的最小证据。Policy Agent 的引用由服务端从真实命中生成，LLM 只能生成标注为“模型解释”的文本；不得将政策检索作为订单操作授权。详见 [阶段 2.4 报告](docs/PHASE2_4_REPORT.md)。

## 阶段 2.5A：Resolution Agent 只读方案生成

售后写意图按 `Order/Policy → Resolution → 确定性只读校验` 运行。`ResolutionProposal.eligibility_status` 是方案结论，`eligibility_result.validated` 表示现有 `RetailService` 硬规则是否实际校验；只有规则接受的方案才显示 `pending_confirmation`，但本阶段不会调用 `RetailService.propose` 或 `confirm`，不会写 `operation_proposals`、`operation_audit` 或订单数据。

```powershell
$h = @{ 'x-session-id' = $sid }
$body = @{ message = '帮我取消订单<本人订单号> because ordered by mistake' } | ConvertTo-Json
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/debug/plan -Headers $h -ContentType application/json -Body $body
```

成功响应的关键字段示例：`{"task_status":"proposal_ready","resolution_proposal":{"action_type":"cancel","eligibility_status":"eligible","validated":true,"status":"pending_confirmation"},"eligibility_result":{"status":"eligible","validated":true,"rule_code":null},"pending_action":{"proposal_id":"resolution_<稳定摘要>"}}`。`pending_action` 只是阶段 2.5A 的只读建议摘要，不是数据库中的可执行操作提案。缺少原因、商品、支付方式等参数时返回 `needs_clarification`；规则冲突时返回 `ineligible`；模型/生成器建议与硬规则不一致时以硬规则为准并设置 `model_rule_conflict`。

调试响应同时包含 `input`、`triage`、`task_plan`、`order_data`、`policy_context`、`policy_retrieval`、`resolution_proposal`、`eligibility_result`、`missing_information`、`final_response`、当轮 `trace` 和累计 `full_trace`。默认关键词检索可独立运行，不依赖尚未真实验收的 pgvector。Resolution 当前只使用本地确定性生成器；即使启用真实 Provider，也不会把订单上下文交给 Resolution 的外部 LLM。

```powershell
$env:TEST_DATABASE_URL = (.venv312/Scripts/python -c "from app.config import Settings; print(Settings().database_url)")
.venv_tau/Scripts/python -m pytest -q -rs -p no:cacheprovider -o faulthandler_timeout=45 --basetemp=.tmp/pytest-work
.venv312/Scripts/python -m ruff check backend scripts tests
```

2026-11-02 实际完整验收为 **144 passed、0 skipped**，Ruff 通过；包含真实 PostgreSQL 隔离 schema 和官方适配器回归，但没有外部 Resolution LLM 调用。详见 [阶段 2.5A 报告](docs/PHASE2_5A_REPORT.md)。

## 阶段 2.5B：受控订单取消执行

多 Agent 取消执行使用独立于 LLM 的 `ExecutionService`。`/api/v1/debug/plan` 仍只生成和校验 `ResolutionProposal`；随后必须显式创建持久化执行请求，回显服务端生成的具体确认文本，再调用受控执行节点。执行节点会重新校验会话身份、订单归属、方案/确认摘要、有效期、订单版本和当前业务规则，并在同一事务内锁定订单、更新状态与写入审计。

最小 API 流程（会修改当前配置数据库中的指定模拟订单，请只在隔离测试库或明确可修改的演示库使用）：

```powershell
$h = @{ 'x-session-id' = $sid }
$planBody = @{ message = '帮我取消订单<本人待处理订单号> because ordered by mistake' } | ConvertTo-Json
$plan = Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/debug/plan -Headers $h -ContentType application/json -Body $planBody

$key = 'cancel-20261102-example-0001'
$requestBody = @{ proposal_id = $plan.resolution_proposal.proposal_id; idempotency_key = $key } | ConvertTo-Json
$request = Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/multi-agent/cancel-requests -Headers $h -ContentType application/json -Body $requestBody
# request.status=pending_confirmation；此时订单尚未改变

$decisionBody = @{ decision = 'confirm'; confirmation_text = $request.confirmation_text } | ConvertTo-Json
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/api/v1/multi-agent/cancel-requests/$($request.request_id)/decisions" -Headers $h -ContentType application/json -Body $decisionBody

$executeHeaders = @{ 'x-session-id' = $sid; 'Idempotency-Key' = $key }
$result = Invoke-RestMethod -Method Post "http://127.0.0.1:8000/api/v1/multi-agent/cancel-requests/$($request.request_id)/execute" -Headers $executeHeaders
Invoke-RestMethod http://127.0.0.1:8000/api/v1/orders/<订单号> -Headers $h
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/multi-agent/cancel-requests/$($request.request_id)/audit" -Headers $h
```

拒绝使用 `decision='reject'`。新确认接口不接受 `{"confirmed":true}`；确认文本绑定当前用户、订单、取消原因、Resolution proposal ID 和版本。执行请求与幂等键持久化在数据库，不依赖 Python 内存防重。相同键相同请求返回同一结果，相同键绑定不同参数返回 `idempotency_key_conflict`。并发取消使用请求行锁、订单行锁和 `row_version`，只有一次状态转换能成功。

审计事件按生命周期区分 `proposal_generated`、`eligibility_validated`、`user_confirmed`/`user_rejected`、`execution_succeeded`/`execution_failed`，包含任务、订单、方案、规则结果、确认记录、前后状态和失败代码，不包含邮箱、API Key 或完整客户资料。

```powershell
$env:TEST_DATABASE_URL = (.venv312/Scripts/python -c "from app.config import Settings; print(Settings().database_url)")
.venv_tau/Scripts/python -m pytest -q -rs -p no:cacheprovider -o faulthandler_timeout=45 --basetemp=.tmp/pytest-work
.venv312/Scripts/python -m ruff check backend scripts tests
```

2026-11-02 最终完整验收为 **163 passed、0 skipped**，Ruff 通过；真实 PostgreSQL 随机 schema 验证成功取消、未确认零写入及双请求并发竞争，测试结束后 `phase25b_*` schema 残留为 0。执行链使用可重复 Mock/本地 Resolution，没有向外部 LLM 发送订单数据。详见 [阶段 2.5B 报告](docs/PHASE2_5B_REPORT.md)。

## 阶段 2.5C：订单取消多轮 Multi-Agent 闭环

统一入口 `POST /api/v1/multi-agent/chat` 把自然语言取消请求接入既有 Triage、Supervisor、Order、Policy、Resolution、Eligibility Guard、Confirmation Gate 和 ExecutionService。第一轮只生成并持久化待确认请求；第二轮必须携带同一 `request_id`，并由已验证会话回复“确认”、服务端具体挑战文本或“拒绝”。可信确认来自数据库记录，不由 LLM 或客户端布尔值设置。`GET /api/v1/multi-agent/tasks/current` 可读取当前 AgentState 投影；既有请求查询、决策、执行、订单和审计 API 保持可用。

```powershell
$h = @{ 'x-session-id' = $sid }
$firstBody = @{ message = 'Please cancel order <本人待处理订单号> because ordered by mistake' } | ConvertTo-Json
$first = Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/multi-agent/chat -Headers $h -ContentType application/json -Body $firstBody
# first.task_status=pending_confirmation；数据库订单尚未改变

$confirmBody = @{ message = '确认'; request_id = $first.request_id } | ConvertTo-Json
$done = Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/multi-agent/chat -Headers $h -ContentType application/json -Body $confirmBody
# done.task_status=executed；execution_result 来自真实数据库事务结果

Invoke-RestMethod http://127.0.0.1:8000/api/v1/multi-agent/tasks/current -Headers $h
Invoke-RestMethod "http://127.0.0.1:8000/api/v1/multi-agent/cancel-requests/$($first.request_id)/audit" -Headers $h
```

用户修改订单号或改变诉求会把旧请求持久化为 `superseded` 并使旧确认失效；拒绝、过期、订单版本变化、越权和重复确认都有确定性终态。重复确认已成功请求只返回 `idempotent_replay=true`，不会再次修改订单或新增成功审计。当前会话编排状态仍是进程内 `SessionStateStore`，但待确认请求、确认、幂等结果和审计均已持久化；完整聊天恢复不属于本阶段。

阶段 1 的 `POST /api/v1/operations`、`POST /api/v1/operations/{proposal_id}/confirm` 以及带 `proposal_id` 的 `POST /api/v1/chat` 现返回 HTTP 410，错误码分别提示迁移到 multi-agent 流程。查询型单 Agent Baseline、内部服务契约及官方 τ-bench 适配器保留，旧 HTTP 布尔确认不能再形成订单写入。

隔离 PostgreSQL 演示：

```powershell
.venv_tau/Scripts/python -m scripts.demo_phase25c_cancel --output reports/phase25c_demo.json
```

脚本只创建随机 `phase25c_demo_*` schema，展示成功两轮取消和未确认零写入反例，并在退出时删除 schema。自动化使用 Mock Triage、关键词 Policy 与本地 Resolution，不调用外部 LLM，也不依赖未完成真实验证的 pgvector。

2026-11-04 最终完整验收为 **169 passed、0 failed、0 skipped**，Ruff 通过；包含真实 PostgreSQL 随机 schema、FastAPI、事务/并发、旧 API 安全和官方适配器回归。演示实测订单 `pending → pending（未确认）→ cancelled（确认后）`，未确认反例保持 pending，4 类成功链路审计齐全；测试和演示结束后 `phase25c_*` schema 残留为 0。结果保存在 `reports/phase25c_demo.json`。未调用外部 LLM，详见 [阶段 2.5C 报告](docs/PHASE2_5C_REPORT.md)。

## 阶段 2.6：阶段 2 收尾与验收

阶段 2 现支持查询、取消和退货三种产品侧闭环。统一多 Agent 会话入口仍是 `POST /api/v1/multi-agent/chat`；退货输入必须给出本人已送达订单、商品项数量和退款途径，例如：

```powershell
$h = @{ 'x-session-id' = $sid }
$returnBody = @{
  message = 'Please return delivered order <订单号> under the return policy item_quantities=<item_id>:1 payment_method_id=<method_id>'
} | ConvertTo-Json
$pending = Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/multi-agent/chat -Headers $h -ContentType application/json -Body $returnBody
# pending.task_status=pending_confirmation；订单仍为 delivered
$confirm = @{ message = '确认退货'; request_id = $pending.request_id } | ConvertTo-Json
$done = Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/v1/multi-agent/chat -Headers $h -ContentType application/json -Body $confirm
# done.execution_result.after_status='return requested'
```

退货专用的显式 API 与取消 API 对称：`POST /api/v1/multi-agent/return-requests`、`GET /return-requests/{request_id}`、`POST /decisions`、`POST /execute`、`GET /audit`。它们使用同一 `ExecutionService`、服务端挑战文本、有效期、方案摘要、数据库幂等键、行锁、规则重校验和审计。成功只表示退货申请已登记；系统不连接真实支付网络，不声称退款到账或邮件已发送。旧 `/operations` 和布尔确认入口仍返回 410。

`POST /api/v1/single-agent/controlled-chat` 是产品侧受控单 Agent 基线。它和多 Agent 使用相同身份、只读工具、固定政策、硬规则、确认与 ExecutionService，可运行相同查询/取消/退货案例；它不恢复旧写入口。示例请求结构与多 Agent 相同，写操作第二轮携带第一轮返回的 `request.request_id`。

本地真实向量路径使用固定 Docker 镜像 `pgvector/pgvector:0.8.7-pg16-trixie` 和 FastEmbed `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`（384 维）。演示 FAQ/商品说明位于 `data/knowledge/`，manifest 记录版本、来源和 SHA256；它们明确为 ServiceFlow 自编非权威文档，不包含实时用户/订单/支付数据，也不会进入写意图的授权证据。默认仍是关键词检索。

```powershell
docker compose up -d db
.venv_tau/Scripts/python -m pip install -r requirements-rag-local.lock
$env:POLICY_EMBEDDING_PROVIDER = 'fastembed'
$env:POLICY_LOCAL_EMBEDDING_CACHE = '.cache/fastembed'
.venv_tau/Scripts/python -m scripts.index_policy --vector --rebuild-vector
# 文档确认变更时才显式重建
.venv_tau/Scripts/python -m scripts.index_policy --rebuild --vector --rebuild-vector
.venv_tau/Scripts/python -m scripts.evaluate_policy_retrieval --output reports/phase2_6_retrieval.json
```

本轮 30 条同标注集真实结果：关键词 Recall@3 `1.000000`、MRR `0.944444`、引用相关准确率 `0.383333`、平均延迟 `1.058 ms`；向量 Recall@3 `0.833333`、MRR `0.633333`、引用相关准确率 `0.277778`、平均延迟 `13.674 ms`；两者引用来源完整性均为 `1.0`。小样本只用于工程检索比较，不能说明多 Agent 或向量检索总体更优。

验证命令：

```powershell
$env:TEST_DATABASE_URL = 'postgresql+psycopg://serviceflow:serviceflow_local@127.0.0.1:5432/serviceflow_demo'
.venv_tau/Scripts/python -m pytest -q --basetemp=.tmp/pytest-phase26-full -p no:cacheprovider
.venv_tau/Scripts/python -m ruff check .
.venv_tau/Scripts/python -m scripts.evaluate_phase2_product_cases --output reports/phase2_6_product_cases.json
```

产品对照脚本为每次运行创建并清理随机 PostgreSQL schema；结果不是官方 τ-bench 分数。Mock/本地编排的 Token 使用为 `null`，未填写推测成本；真实外部聊天 LLM 本轮未调用。阶段 2 的完整实现、安全边界和实测证据见 [阶段 2.6 报告](docs/PHASE2_6_REPORT.md)。

## 阶段 3：持久化恢复、工单与人工接管

阶段 3 沿用原有业务表和 `ExecutionService`，不重建或迁移 `agent_conversations`、`execution_requests`、`execution_audit_events` 的历史数据。新增表如下：

| 表 | 用途 | 关键约束 |
|---|---|---|
| `tickets` | 脱敏人工工单 | `ticket_no`、建单幂等键唯一；关闭必须有原因 |
| `messages` | 规范化会话消息 | `(session_id, sequence)` 唯一；按会话/时间索引 |
| `approvals` | 操作员审批记录 | 工单/请求/动作防重复；审批不能替代客户确认 |
| `audit_events` | 工单、接管、审批、恢复的统一追加日志 | 只写脱敏负载；不替代细粒度执行审计 |

PostgreSQL 的 JSON 字段使用 JSONB，显式 SQLite 测试替身使用 JSON。实时用户、订单、支付事实不进入向量库或 checkpoint；订单事实仍只从业务数据库读取。

### LangGraph checkpointer 与恢复语义

生产/演示 PostgreSQL 使用官方 `langgraph-checkpoint-postgres` 的 `PostgresSaver` 和 psycopg 连接池，复用 `DATABASE_URL`。首次连接自动执行 checkpointer 的幂等 `setup()`；阶段 4.5D 起，`thread_id` 由服务端解析为订单或通用咨询对应的 `support_thread` ID，不再直接复用 `session_id`。API 只接受业务范围参数，不接受客户端指定 thread ID。

```powershell
$env:DATABASE_URL = 'postgresql+psycopg://serviceflow:serviceflow_local@127.0.0.1:5432/serviceflow_demo'
$env:CHECKPOINT_POOL_MIN_SIZE = '1'
$env:CHECKPOINT_POOL_MAX_SIZE = '5'
$env:CHECKPOINT_POOL_TIMEOUT_SECONDS = '10'
.venv_tau/Scripts/python -m uvicorn app.main:app --app-dir backend --reload
```

规范化 `messages` 是会话历史，LangGraph checkpoint 保存受限状态投影。进程重启后可以恢复多轮澄清、`task_plan` 未完成项、执行请求与等待确认绑定；缓存未命中会从 checkpoint 重建。邮箱、完整地址、支付凭据、API Key 在写 checkpoint 前脱敏。

恢复不等于业务 Exactly-once。执行前仍重新校验会话身份、订单归属、确认有效期、请求状态、订单 `row_version` 和当前硬规则。`executing` 请求使用短租约；进程在租约提交后中断时，租约到期才允许其他 worker 恢复。瞬时连接/锁等待/序列化错误按配置退避重试，每次都重新读单；规则冲突、越权、订单变化和幂等冲突不重试。

### 工单与审批 API

客户显式建单只允许 `customer_requested_human`，使用客户 `X-Session-Id` 和独立建单幂等键。返回值明确说明工单尚未处理完成：

```powershell
$customerHeaders = @{
  'X-Session-Id' = $sid
  'Idempotency-Key' = 'customer-human-handoff-0001'
}
$ticketBody = @{
  category = 'customer_requested_human'
  summary = '请转人工处理此问题'
  requested_action = @{ action = 'human_review' }
} | ConvertTo-Json -Depth 4
$ticket = Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/v1/tickets `
  -Headers $customerHeaders -ContentType application/json -Body $ticketBody
# 示例：ticket.status='open'
#       ticket.message='已创建工单 SF-...，尚未处理完成。'
```

操作员使用独立的演示 token，不复用客户会话。该机制只用于本地演示，不是生产 IAM；真实值只放 `.env`：

```powershell
$env:OPERATOR_DEMO_TOKEN = '<local-only-token>'
$operatorHeaders = @{ 'X-Operator-Token' = $env:OPERATOR_DEMO_TOKEN }

# 分页/过滤列表
$list = Invoke-RestMethod -Method Get `
  -Uri 'http://127.0.0.1:8000/api/v1/tickets?status=open&limit=20&offset=0' `
  -Headers $operatorHeaders

# 分配并流转；非法迁移返回 ticket_status_transition_invalid
$assignBody = @{ assignee = 'operator-demo' } | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/tickets/$($ticket.id)/assign" `
  -Headers $operatorHeaders -ContentType application/json -Body $assignBody
$statusBody = @{ status = 'in_progress' } | ConvertTo-Json
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/tickets/$($ticket.id)/status" `
  -Headers $operatorHeaders -ContentType application/json -Body $statusBody
```

审批请求和决定示例：

```powershell
$approvalBody = @{
  request_id = $requestId
  action = 'execute_cancel'
  proposed_params = @{ reason = 'ordered by mistake' }
} | ConvertTo-Json -Depth 4
$approval = Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/tickets/$($ticket.id)/approvals" `
  -Headers $operatorHeaders -ContentType application/json -Body $approvalBody
# 示例：approval.status='pending'

$decisionBody = @{
  decision = 'approved'
  reason = '已核对工单与现有请求绑定'
} | ConvertTo-Json
$decision = Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/tickets/$($ticket.id)/approvals/$($approval.id)/decision" `
  -Headers $operatorHeaders -ContentType application/json -Body $decisionBody
# 示例：decision.status='approved'
```

完整接口还包括 `GET /api/v1/tickets/{ticket_id}`、`GET /api/v1/tickets/{ticket_id}/audit` 和关闭状态流转。关闭原因只能是 `resolved_by_agent`、`resolved_by_operator`、`customer_unresponsive`、`duplicate`、`rejected`、`out_of_scope`。`POST /api/v1/tickets/{ticket_id}/execute` 仅代为触发原 `ExecutionService`：必须已有操作员审批和该客户的有效确认；操作员不能创建或替代客户确认。

确定性接管触发包括：不支持诉求、硬规则/模型规则冲突、高风险、写操作政策证据不足、不可重试执行失败、澄清路由上限及客户明确要求人工。工单回复只表示登记待处理，不表示订单已修改。

### 故障注入与已知边界

```powershell
$env:TEST_DATABASE_URL = 'postgresql+psycopg://serviceflow:serviceflow_local@127.0.0.1:5432/serviceflow_demo'
.venv_tau/Scripts/python -m scripts.inject_phase3_failures
.venv_tau/Scripts/python -m pytest -q -rs -p no:cacheprovider --basetemp=.tmp/pytest-phase3-full
.venv_tau/Scripts/python -m ruff check backend scripts tests
```

故障脚本只使用合成数据和随机 `phase3_failures_*` schema，覆盖 LLM/工具超时、并发与串行重复请求、确认后进程中断、等待确认期间订单变化，最后强制清理。2026-11-09 最终实测为 **204 passed、0 failed、0 skipped**，ruff 通过，阶段 3 和全套随机测试 schema 残留均为 0，外部 LLM 调用为 0。

已知边界：阶段 3 不包含阶段 4 前端/管理后台；操作员 token 仅为本地演示；不执行修改/换货；系统不连接真实支付或通知网络；审批、checkpoint 和工单都不能替代数据库幂等、客户确认或服务端硬规则。完整证据见 [阶段 3 报告](docs/PHASE3_REPORT.md)。

## 阶段 4A：用户售后聊天页

阶段 4A 新增 `frontend/` React + TypeScript + Vite 工程，只包含用户服务台，不包含管理后台或开发者页。页面使用 React Router 和 TanStack Query，开发服务器将 `/api` 代理到 `http://127.0.0.1:8000`。多 Agent 聊天接口仍由后端固定使用本地 Mock Triage 和关键词政策检索，本阶段不启用外部 DeepSeek。

先按前文启动 PostgreSQL 与 FastAPI，再在另一个终端启动前端：

```powershell
cd frontend
npm install
npm run dev
```

浏览器打开 `http://127.0.0.1:5173/support`。页面首次访问调用 `POST /api/v1/sessions`，只把返回的随机 `session_id` 保存到浏览器 localStorage；邮箱、姓名、邮编、订单、支付信息和确认记录都不写入本地存储。刷新时先调用 `GET /api/v1/multi-agent/tasks/current`，成功后才认为身份已恢复并请求订单；返回 403 时重新显示核验门，不请求订单。

主要请求/响应示例（字段沿用现有后端契约）：

```http
POST /api/v1/sessions

{"session_id":"<server-session-id>"}

POST /api/v1/sessions/<server-session-id>/verify
Content-Type: application/json

{"email":"<tau-bench 模拟账户邮箱>"}

{"user_id":"<server-owned-user-id>"}

POST /api/v1/multi-agent/chat
X-Session-Id: <server-session-id>
Content-Type: application/json

{"message":"请取消订单 #W0000000，因为下错单了"}

{
  "task_status":"pending_confirmation",
  "request_id":"<request-id>",
  "pending_confirmation":{
    "action_type":"cancel",
    "order_id":"#W0000000",
    "proposed_parameters":{"reason":"ordered by mistake"}
  },
  "execution_result":null
}
```

确认或拒绝通过同一聊天接口发送 `{"message":"确认","request_id":"<request-id>"}` 或 `{"message":"拒绝","request_id":"<request-id>"}`。前端只有在服务端返回 `execution_result.status="succeeded"` 时显示执行成功；普通回复文本或本地按钮状态都不能推断成功。显式人工建单调用 `POST /api/v1/tickets` 并为同一次逻辑请求稳定复用 `Idempotency-Key`，成功后始终显示“等待人工处理”，不显示“已处理完成”。

前端验收命令：

```powershell
cd frontend
npm run lint
npm run typecheck
npm run test -- --run
npm run build
```

本阶段自动化结果为 **17 passed**，生产构建成功，`npm audit` 为 0 个已知漏洞。自动化使用 jsdom 和网络层替身验证前端状态机及真实 URL/请求头，不把测试响应打包进运行时代码。尚未完成真实浏览器 + PostgreSQL 的人工全流程、视觉截图回归、管理/开发者页面和 Compose 前端编排；因此阶段 4 整体仍未完成。详见 [阶段 4A 报告](docs/PHASE4A_REPORT.md)。

## 阶段 4B：管理后台与开发者追踪页

阶段 4B 在同一个 `frontend/` 工程中增加 `/admin` 和 `/developer`，没有重建阶段 4A 工程。运行前继续按前文启动 PostgreSQL、FastAPI 和 Vite。

### 管理后台

浏览器打开 `http://127.0.0.1:5173/admin`。输入后端 `.env` 中的本地演示 `OPERATOR_DEMO_TOKEN`；前端只把值放在当前标签页的 `sessionStorage`，请求时发送独立 `X-Operator-Token`，不会发送或复用客户 `X-Session-Id`。该认证明确只是本地演示机制，不是生产 IAM。

管理页使用以下真实接口：

- `GET /api/v1/tickets`：按状态、类别、客服和时间过滤并分页。
- `GET /api/v1/tickets/{ticket_id}` 与 `/audit`：读取脱敏详情、会话、关联 ID 和审计时间线。
- `POST /assign` 与 `/status`：分配客服和执行后端允许的状态迁移；关闭/取消必须选择合法 `close_reason`。
- `POST /approvals` 与 `/approvals/{approval_id}/decision`：创建、批准或拒绝内部审批。
- `POST /execute`：代触发既有 `ExecutionService`，不能生成客户确认；缺少确认时如实显示 `confirmation_required`。

审批通过不等于客户确认，人工执行成功也只以服务端 `execution_result.status="succeeded"` 为准。重复执行使用服务端执行请求原有的幂等键；页面在请求期间禁用重复点击，并如实显示 `idempotent_replay`。现有后端没有审批列表读取接口，因此页面刷新后只能从审计时间线查看审批历史，不能重新构造可操作的待审批记录。

### 开发者追踪页

浏览器打开 `http://127.0.0.1:5173/developer`。页面可查看同一标签页内最近一次 `/multi-agent/chat` 响应中的 `trace`、`tool_results`、`metrics` 和 `task_plan`，也可使用客户 session 边界读取：

```http
GET /api/v1/multi-agent/tasks/current
X-Session-Id: <server-session-id>

GET /api/v1/traces/<trace-id>
X-Session-Id: <server-session-id>
```

不存在和跨 session 的 trace 都显示同一安全 404，不泄露归属。页面展示节点顺序、工具状态/错误码、节点和总耗时、任务依赖及 request/ticket/order 关联。Provider 为 `mock_local` 时明确标为 Mock，不显示为 DeepSeek；`token_usage: null` 显示为“未提供”，不推测 Token 或成本。完整 Prompt、API Key、邮箱、完整地址、支付卡数据以及 τ-bench 参考动作/评分条件都会被隐藏或脱敏。

最新聊天的详细 trace 只保存在 React 页面内存中。刷新后 `tasks/current` 可恢复当前任务，`traces/{trace_id}` 可恢复持久化事件、耗时和 token usage；后者当前不返回工具结果、Provider 或模型，因此页面明确显示“当前接口未返回”，不会补造数据。

阶段 4B 最终前端验收为 **7 test files、30 passed、0 failed**；lint、typecheck 和生产 build 均退出 0。仍未做真实浏览器 + PostgreSQL 人工全流程、Playwright/截图/屏幕阅读器审查和 Compose 前端编排，所以阶段 4 整体仍未完成。详见 [阶段 4B 报告](docs/PHASE4B_REPORT.md)。

## 阶段 4C：Docker Compose 与浏览器演示

阶段 4C 没有新增业务能力。Compose 只编排已有 PostgreSQL、FastAPI 与 React/Nginx；API 固定使用 `AGENT_PROVIDER=mock` 和关键词政策检索，不读取外部 LLM Key。API 运行镜像只包含固定版本的 `policy.md` 和产品知识，不包含 τ-bench `tasks.json`；完整只读原始数据只进入显式种子镜像。

首次本地启动时，从占位符模板创建未跟踪配置，并替换两个 `<...>` 值。不要把真实密码或 token 写回 `.env.example`：

```powershell
Copy-Item .env.example .env.phase4
# 编辑 .env.phase4：设置本地数据库密码和独立 operator token
docker compose config
docker compose up -d --build
docker compose ps
```

`db` 健康后才启动 `api`，`api` 健康后才启动 `frontend`。访问入口：

- `http://127.0.0.1:5173/store`：模拟商品目录、顾客身份核验、本人订单和内嵌客服；`/support` 保留为兼容跳转。
- `http://127.0.0.1:5173/admin`：操作员工单、审批和人工代触发。
- `http://127.0.0.1:5173/developer`：当前任务与成功/失败 trace。
- `http://127.0.0.1:8000/docs`：FastAPI OpenAPI。

普通 `docker compose up` **不会**导入或复位数据，也不会覆盖已有 `flowagent_demo_pgdata` 卷。仅在明确需要导入固定演示快照时执行：

```powershell
docker compose --profile tools run --rm seed
```

该命令同版本重复执行不会覆盖已发生的演示业务修改。本机验收导入为 500 个模拟用户、50 个商品和 1000 个模拟订单。只有明确接受复位演示业务数据时，才把 seed 服务命令临时改为追加 `--reset`；不要对官方评测数据库使用该命令。演示库必须以 `_demo` 结尾，官方评测继续使用物理隔离的数据库/环境。

本地认证边界：客户 `session_id` 只用于客户 API；操作员 token 只放内存或当前标签页 `sessionStorage`，通过 `X-Operator-Token` 发送。这是演示认证，不是生产 IAM。操作员审批不能替代客户明确确认；缺少确认时人工执行返回 `confirmation_required`。前端镜像不包含数据库密码、API Key 或 operator token。

完整阶段 4 验收命令：

```powershell
$env:TEST_DATABASE_URL = 'postgresql+psycopg://serviceflow:<local-demo-database-password>@127.0.0.1:5432/serviceflow_demo'
.venv_tau/Scripts/python -m pytest -q -rs -p no:cacheprovider --basetemp=.tmp/pytest-phase4-full
.venv_tau/Scripts/python -m ruff check backend scripts tests

Set-Location frontend
npm run lint
npm run typecheck
npm run test -- --run
npm run build
npm run test:e2e
Set-Location ..
```

`test:e2e` 使用 Chromium、真实 FastAPI 和真实 PostgreSQL，为每次运行创建 `phase4_e2e_<随机值>` schema，注入隔离的合成测试数据，并在成功或失败后终止测试进程、删除该 schema。最终实测：后端 **204 passed**；前端 **30 passed**；Playwright **6 passed**；ruff、lint、typecheck、build 全部通过；三个 Compose 服务均 healthy；随机 schema 残留 **0**；外部 LLM 调用 **0**。完整场景、API 映射、风险与历史失败见 [阶段 4 总报告](docs/PHASE4_REPORT.md)。

## 阶段 4.5A：模拟商店与顾客身份

主入口现为 `http://127.0.0.1:5173/store`。中文商城支持搜索、在弹窗中选择商品规格、购物车和模拟下单；规格较多时只在弹窗内部滚动，移动端使用底部抽屉。商品目录可在身份核验前查看；结算、本人订单和客服只在核验后开放。每笔订单内有“联系商家客服”，点击后打开携带该订单号上下文的智能客服对话框。点击“切换模拟顾客”会创建新 session，清除购物车、旧订单、对话、当前任务和内存 trace，并要求重新核验。后端不允许已绑定 session 改绑其他顾客，订单访问始终使用 session 中的服务端身份，不接受前端 `user_id` 授权。

新增目录接口示例：

```http
POST /api/v1/sessions

GET /api/v1/products
X-Session-Id: <server-session-id>

GET /api/v1/products/<product-id>
X-Session-Id: <server-session-id>

POST /api/v1/orders
X-Session-Id: <verified-server-session-id>
Idempotency-Key: checkout-<unique-key>
Content-Type: application/json

{"items":[{"item_id":"<variant-id>","quantity":1}],"payment_method_id":"<account-payment-method-id>"}

HTTP/1.1 200
{"order":{"order_id":"#W<generated>","status":"pending","items":[...]},"idempotent_replay":false,"created_at":<unix-time>}

GET /api/v1/orders
X-Session-Id: <unverified-session-id>

HTTP/1.1 403
{"error":{"code":"identity_required"}}
```

`GET /products` 返回商品 ID、名称、价格范围、可用/全部规格数和选项名；`GET /products/{id}` 返回完整规格。`POST /orders` 不信任前端传入的价格、顾客、地址或商品信息：它从已核验 session、`products` 与 `users` 重新读取权威值，在同一事务中创建订单、更新顾客订单索引并写入 `order_creations` 幂等审计；同一键同一请求只返回原订单，换内容或换身份使用同一键会返回 409。该接口仅模拟本地订单与支付记录，不调用真实支付渠道。目录、订单和客服均读取同一 PostgreSQL 业务库，不使用前端静态商品或假 API。顾客页通过确定性展示层将固定快照的 50 个英文商品名、全部规格字段和实际规格值转为中文，原始 ID 与上游数据保持不变。

2026-11-13 实测：后端 **208 passed、0 failed、0 skipped**；前端 **8 files、38 passed、0 failed**；Chromium **7 passed、0 failed**；Ruff、ESLint、TypeScript 和生产构建均通过；PostgreSQL/FastAPI/frontend 三个 Compose 服务均 healthy；E2E 随机 schema 残留 **0**；外部 LLM 调用 **0**。详见 [阶段 4.5A 报告](docs/PHASE4_5A_REPORT.md)。

## 阶段 4.5B：咨询分流与售后闭环

`POST /api/v1/multi-agent/chat` 现在先执行不调用外部模型的内容安全检查，再分流到 FAQ/政策、实时商品、本人订单/物流、取消/退货、含糊或超范围请求。检查使用有上下文的短语规则，不因“杀”、“取消”等单一词误拦正常商品或售后咨询。它是当前演示范围内的确定性基线，不应被误解为能覆盖任意自然语言风险的通用安全分类器。

咨询结果增加 `consultation_route` 与 `safety` 字段；开发者 trace 的第一个节点为 `content_safety`。政策回答仅使用现有政策索引命中的条款并附来源；商品价格/可用性来自当前 `products` 表；订单查询继续从服务端 session 获得客户身份并校验归属。正常业务缺少必要参数（如取消原因）时只追问，不误称“无法解决”；含糊、超范围、证据不足、数据不可用、规则冲突或执行失败时，系统说明当前无法解决并提示可回复“转人工”，无论重复失败多少次都不自动建单。明确要求转人工才会建单，仅询问“你是人工客服吗”不会误触发。

API 示例（需使用已核验的服务端 session）：

```http
POST /api/v1/multi-agent/chat
X-Session-Id: <verified-server-session-id>
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

```http
POST /api/v1/multi-agent/chat
X-Session-Id: <verified-server-session-id>
Content-Type: application/json

{"message":"取消订单需要什么条件？"}

HTTP/1.1 200
{
  "task_status":"policy_answered",
  "consultation_route":"faq_policy",
  "final_response":"根据当前检索到的政策资料：...\n\n来源：\n- policy.md § Cancel pending order"
}
```

取消和退货仍使用阶段 2.5B–2.6 的硬边界：具体提案 → 客户明确确认 → 执行前重读订单 → 硬规则 → 事务/幂等/审计。前端只在服务端返回 `execution_result.status=succeeded` 时刷新订单列表和当前详情，不根据自然语言“成功”字样更改界面状态。

2026-11-14 阶段 4.5B 当轮实测：后端 **220 passed、0 failed、0 skipped**；前端 **8 files、39 passed、0 failed**；Chromium + 真实 FastAPI/PostgreSQL **8 passed、0 failed**；Ruff、ESLint、TypeScript 和生产构建均通过；E2E 随机 schema 残留 **0**；Compose 的 db/api/frontend 均 healthy；外部 LLM 调用 **0**。详见 [阶段 4.5B 报告](docs/PHASE4_5B_REPORT.md)。这是阶段性历史记录；当前完成状态以本文顶部和阶段 4.5 最终验收报告为准。

## 阶段 4.5C：中文体验与人工接管

客户明确转人工后，商家后台自动检查新工单，可在工单详情中查看脱敏会话与归属核验后的订单状态及商品项数量，输入人工回复。人工回复会保存到同一业务数据库，并在顾客客服窗口显示。工单状态使用中文展示；人工回复和审批都不构成客户对订单写操作的确认。

活动人工工单建立后，顾客继续输入的内容不再交给 Agent，而是通过独立的顾客工单消息接口绑定到同一 `ticket_id`。服务端重新校验已核验会话、顾客和工单归属，使用幂等键防止重复消息，并写入不含消息正文的 `customer_replied` 审计事件。若工单原为 `waiting_customer` 或 `resolved`，顾客回复会将其恢复为 `in_progress`。管理后台当前工单详情与审计每 5 秒刷新，即使标签页处于后台也能读取新消息。

顾客客服支持在同一已核验会话中连续追问。刷新页面后，从服务端 `messages` 表恢复最近 200 条顾客、智能客服和人工消息；切换模拟顾客会建立新会话，不能读取上一位顾客的对话。取消订单时可先问原因，顾客补充“不再需要了”（含常见错字“不在需要了”）后生成具体操作提案；仍须顾客明确确认才会执行取消。历史接口示例：

```powershell
$h = @{ 'x-session-id' = $sid } # 已核验的本顾客会话
Invoke-RestMethod 'http://127.0.0.1:8000/api/v1/customer/conversation' -Headers $h
# 输出示例：[{"sequence":1,"role":"user","content":"取消这个订单","created_at":1730000000}]
```

```http
POST /api/v1/tickets/<ticket-id>/reply
X-Operator-Token: <demo-operator-token>
Content-Type: application/json

{"content":"人工客服正在核对这笔订单。"}

HTTP/1.1 200
{"sequence":8,"content":"人工客服正在核对这笔订单。","created_at":<unix-time>}

GET /api/v1/customer/tickets/<ticket-id>/updates
X-Session-Id: <verified-customer-session>

HTTP/1.1 200
{"ticket_no":"<ticket-no>","status":"open","messages":[{"sequence":8,"content":"人工客服正在核对这笔订单。","created_at":<unix-time>}]}
```

顾客在人工工单中的后续回复使用独立接口，不调用 `/api/v1/multi-agent/chat`：

```http
POST /api/v1/customer/tickets/<ticket-id>/messages
X-Session-Id: <verified-customer-session>
Idempotency-Key: customer-message-<random-id>
Content-Type: application/json

{"content":"好的，请继续帮我处理。"}

HTTP/1.1 200
{"sequence":9,"content":"好的，请继续帮我处理。","created_at":<unix-time>,"status":"in_progress","idempotent_replay":false}
```

2026-11-15 双向人工会话修订后实测：后端 **226 passed**，前端 **8 files、40 passed**，真实 FastAPI/PostgreSQL/Chromium **10 passed**，临时 schema 残留 **0**；Ruff、lint、typecheck、build 均通过。浏览器场景使用两个标签页验证“人工回复到达顾客 → 顾客继续回复 → 已打开的后台自动显示”，同时断言顾客后续消息不进入 Agent。详见 [阶段 4.5C 报告](docs/PHASE4_5C_REPORT.md)。这是阶段性历史记录；阶段 4.5 后续已完成最终验收。

刷新恢复兼容说明：旧版本从订单对话自然语言“转人工”创建的活动工单可能没有 `order_id`。阶段 4.5D 起，这类未绑定订单的工单固定归入“通用咨询”线程，不再自动挂到任意订单窗口；订单窗口只恢复与本订单线程绑定的工单。旧 LangGraph 检查点也会按当前状态模型补齐缺失通道，避免升级后因缺少 `triage_result` 返回 500。该修订验证结果为真实 PostgreSQL 后端 **227 passed**、前端 **8 files、41 passed**，静态检查与生产构建通过。

人工后台的会话记录与回复输入现已合并为同一个聊天窗口。顾客消息左对齐、人工客服右对齐、智能客服历史使用中性样式；打开工单后仍每 5 秒同步详情，并自动显示最新消息。回复框位于消息区正下方，Enter 发送、Shift+Enter 换行。分配、状态流转、审批和代执行保留在单独的“工单治理”区域，人工回复不构成客户确认。该界面修订后前端 **8 files、42 passed**，ESLint、TypeScript、生产构建和实际页面视觉检查通过。

## 阶段 4.5D：订单独立会话线程（串话修复）

阶段 4.5C 的人工工单详情按 `session_id` 读取最近 20 条消息，同一顾客的不同订单会混进同一个客服窗口。4.5D 不再用会话或消息文本近似订单范围，而是引入服务端拥有的 `support_threads`：

- 每个 `(session, order)` 一条 `kind='order'` 线程；每会话一条 `kind='general'` 通用咨询线程。
- `messages.thread_id` 与 `tickets.thread_id` 绑定线程；工单详情只返回本线程消息。
- 顾客发送的 `order_id` 只是请求参数；线程由服务端在核验身份并校验订单归属后创建或恢复，客户端不能指定 `thread_id` 越权读取。
- LangGraph 检查点按线程隔离，订单 A 的意图、补充信息和待确认请求不会出现在订单 B。
- 订单线程内的消息若提及另一笔订单，服务端直接拒绝并提示从该订单重新打开客服窗口。
- 通用咨询线程只提供咨询能力；取消、退货、换货和修改等写请求返回 `order_thread_required`，必须从目标订单进入客服窗口。
- 同一句同时提到当前订单和其他订单时零部分执行，并使当前未执行提案失效；同一订单的多个商品仍可经一次明确确认在一个事务中处理。

### 线程 API

```http
POST /api/v1/support/threads
X-Session-Id: <verified-customer-session>
Content-Type: application/json

{"order_id":"#W1006327"}

HTTP/1.1 200
{"thread_id":"<thread-id>","kind":"order","order_id":"#W1006327","status":"open","created_at":<unix-time>,"updated_at":<unix-time>}
```

`{}` 返回该会话的“通用咨询”线程；其他顾客的订单返回 404，未核验会话请求订单线程返回 403。聊天、任务恢复和会话历史都接受 `order_id`，服务端再次解析线程：

```http
POST /api/v1/multi-agent/chat          {"message":"帮我取消订单","order_id":"#W1006327"}
GET  /api/v1/multi-agent/tasks/current?order_id=#W1006327
GET  /api/v1/customer/conversation?order_id=#W1006327
```

通用线程发起写操作时返回安全引导，不创建执行请求：

```json
{"task_status":"order_thread_required","pending_confirmation":null,"execution_result":null,"tool_results":[],"thread_kind":"general","final_response":"通用咨询不能修改订单。请在“我的订单”中打开需要处理的订单客服窗口，每个窗口只处理其绑定订单。"}
```

响应新增 `thread_id`、`thread_order_id`、`thread_kind`；工单详情新增 `thread` 与 `related_tickets`（同一订单历史、其他订单数量，默认折叠）。顾客端标题固定显示“正在咨询订单 #…”，切换订单即切换线程并清空上一订单的确认状态；刷新页面会恢复上次打开的订单窗口及其线程。

### 旧数据迁移

列与表的结构升级在服务启动时幂等执行，也可单独运行：

```powershell
$env:PYTHONPATH="backend"
.\.venv_tau\Scripts\python.exe scripts/migrate_support_threads.py
# 示例输出：{"order_threads_created":2,"general_threads_created":8,"tickets_bound":7,"tickets_with_order_conflict":0,"messages_bound_to_ticket":2,"messages_bound_to_general":57}
```

迁移只使用工单已有的 `order_id` 和 `ticket_id` 建立绑定；无法可靠判断订单的旧工单与散落消息进入“通用咨询”线程，不按时间或自然语言猜测。`tickets_with_order_conflict` 输出便于人工复核。本机演示库实测创建 2 个订单线程、8 个通用线程，绑定 7 张工单，冲突 0，重复执行为全 0。

### 验收结果

2026-11-15 实测：后端完整 **235 passed、0 failed、0 skipped**（含真实 PostgreSQL 随机 schema 的 15 项）；前端 **8 files、43 passed**；真实 Chromium + FastAPI + PostgreSQL **11 passed**，新增双订单用例验证“打开订单 A 写入消息 → 切到订单 B 无 A 的消息 → 刷新恢复 B 线程 → 再切回 A 仍有 A 的消息”；`ruff check backend scripts tests`、ESLint、TypeScript 与生产构建通过；E2E 随机 schema 残留 **0**；外部 LLM 调用 **0**。详见 [阶段 4.5D 报告](docs/PHASE4_5D_REPORT.md)。

## 阶段 4.5 最终验收

2026-11-15，用户按收尾清单完成人工浏览器复核并确认全部通过；随后再次独立运行完整后端、前端和真实浏览器测试，结果分别为 **235 passed**、**43 passed** 和 **11 passed**，所有静态检查与生产构建通过，临时数据库 schema 残留 **0**，外部 LLM 调用 **0**。阶段 4.5 正式验收完成，具体证据、边界和命令见 [阶段 4.5 最终验收报告](docs/PHASE4_5_ACCEPTANCE_REPORT.md)。

2026-11-19 顾客用语回归修复：订单客服窗口中的“这个订单不要了”“这单不想要了”等表达现在进入取消方案，原因确定性映射为“不再需要”，不会直接执行写入。确认摘要改为中文，不再在顾客聊天中显示内部英文确认令牌。例如，在已核验且绑定订单 `#W1006327` 的窗口请求：

```http
POST /api/v1/multi-agent/chat
X-Session-Id: <已核验会话>
Content-Type: application/json

{"message":"这个订单不要了","order_id":"#W1006327"}

HTTP/1.1 200
{"task_status":"pending_confirmation","pending_confirmation":{"order_id":"#W1006327","proposed_parameters":{"reason":"no longer needed"},"summary":"取消订单 #W1006327；原因：不再需要"},"final_response":"待确认：取消订单 #W1006327；原因：不再需要。请核对操作内容；确认请回复“确认”，拒绝请回复“拒绝”。订单尚未修改。"}
```

示例仅列出关键字段；实际响应还包含请求 ID、追踪和策略结果。只有客户随后明确确认、服务端重检通过才执行。验证：完整后端 **253 passed、0 failed、0 skipped**（含本地 PostgreSQL 临时 schema），Ruff 通过；外部 LLM 调用 **0**。

2026-11-19 补充模型理解：订单客服窗口先用本地规则处理明确表达；规则无法识别或取消原因不明时，用配置的兼容模型分类。例如“这笔我下错了，帮我撤掉”会识别为取消、原因 `ordered by mistake`，再由服务端绑定当前订单、检索取消政策、校验资格，并返回待确认摘要。模型仅给出意图和原因，不能决定订单归属或执行写入。模型返回无效 JSON、编造订单号、低置信度结果或接口故障时回退到本地解析，无法确认的表达继续追问。通用咨询窗口仍禁止订单写操作，不调用模型处理写动作。

本地 Compose 的 `api` 服务在 `.env` 提供 `LLM_API_KEY`、`LLM_MODEL_ID`、`LLM_BASE_URL` 时启用 `CUSTOMER_TRIAGE_PROVIDER=hybrid`；缺少密钥时自动使用本地规则。可设 `CUSTOMER_TRIAGE_PROVIDER=mock` 关闭外部模型调用。每次需要模型理解的消息会增加一次模型请求和相应延迟与费用，明确规则命中的消息没有模型费用。示例输入输出：

```http
POST /api/v1/multi-agent/chat
X-Session-Id: <已核验会话>
Content-Type: application/json

{"message":"这笔我下错了，帮我撤掉","order_id":"#W1006327"}

HTTP/1.1 200
{"task_status":"pending_confirmation","pending_confirmation":{"order_id":"#W1006327","proposed_parameters":{"reason":"ordered by mistake"}},"final_response":"待确认：取消订单 #W1006327；原因：下错单。请核对操作内容；确认请回复“确认”，拒绝请回复“拒绝”。订单尚未修改。"}
```

以上为预期响应的关键字段示例，具体措辞取决于服务器展示映射。验证命令：`.\.venv_tau\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.pytest_model_full`（本机 PostgreSQL 测试需设置 `TEST_DATABASE_URL`）；`.\.venv_tau\Scripts\python.exe -m ruff check backend scripts tests`。
本次实际结果：完整后端 **259 passed、0 failed、0 skipped**，Ruff 通过；真实 DeepSeek 分类烟测 **1 次成功**。本机运行中的 API 已更新并通过健康检查。若以后重新创建 API 容器，请先执行 `docker compose up -d --build api` 使工作区代码写入新镜像；当前运行容器内的热更新本身不会进入旧镜像。

## 阶段 5A：评测准备与异常集

阶段 5A 固定了 τ-bench Retail 上游 commit 和原始文件哈希，沿用 10 项 train 开发样本，并把官方完整 40 项 test split 声明为保留集。准备代码只对 `tasks.json` 做字节哈希校验，不解析或暴露任务正文、参考动作与评分条件；5A 不运行保留集、不产生官方分数。

自建可靠性集包含身份、授权、确认、政策、提案绑定、幂等、状态竞争、故障恢复、不支持写动作和恶意文档注入 10 类场景。每个场景都绑定现有或新增的真实 pytest 节点，并明确 `official_score_eligible=false`。官方结果和自建结果使用不同输出命名空间。

```powershell
# 只校验配置、哈希、split 和测试引用
.\.venv_tau\Scripts\python.exe -m scripts.prepare_phase5a

# 无密钥运行 10 类可靠性烟测；不会运行官方保留集
.\.venv_tau\Scripts\python.exe -m scripts.prepare_phase5a --run-smoke
```

2026-11-18 最终实测：5A 烟测 **11 passed**，完整后端 **239 passed、0 failed、0 skipped**，Ruff 通过；外部 LLM 调用 **0**，官方保留集执行 **0**，正式分数生成 **0**。配置见 [eval_config.json](reports/eval_config.json)，实际烟测记录见 [phase5a_smoke.json](reports/phase5a_smoke.json)，完整边界和已知限制见 [阶段 5A 报告](docs/PHASE5A_REPORT.md)。

## 阶段 5B：公平对照执行（已完成）

单 Agent 与“确定性 Supervisor + 专职角色”的多 Agent 已接到同一个上游 τ-bench Retail 接口。两者共享原版工具清单、同一确定性 Guard、相同模型与任务集合，并强制每任务最多 6 次工具调用、单次最多 1024 输出 token、累计最多 120000 token。多 Agent 的角色只缩小当轮工具可见范围，不改变服务端身份、归属和明确确认规则。被测 Agent、用户模拟器和语义 Judge 统一使用 DeepSeek；保留上游语义评分 Prompt，但替换了默认 Judge 模型，因此只能称为“官方任务上的 DeepSeek 自定义评测”。

默认命令只生成计划，不调用外部模型：

```powershell
.\.venv_tau\Scripts\python.exe -m scripts.run_phase5b_official --split development
.\.venv_tau\Scripts\python.exe -m scripts.run_phase5b_official --split holdout

# 自建可靠性轨道：Mock/确定性测试，无外部模型费用
.\.venv_tau\Scripts\python.exe -m scripts.run_phase5b_reliability
```

2026-11-18 已运行自建可靠性轨道：**10/10 通过**，外部 LLM 调用 0。开发集单 Agent **22/30（73.33%）**，多 Agent v1 **8/30（26.67%）**、v2 **15/30（50.00%）**、v3 **24/30（80.00%）**。V3 修复了确认后角色丢失，但 2026-11-20 完成的独立 test 保留集没有复现开发集优势：单 Agent **51/120（42.50%）**，V3 **45/120（37.50%）**，V3 低 5 个百分点；McNemar 精确双侧 `p=0.238`，近似配对 95% 区间为 −11.9 至 +1.9 个百分点。结论是 V3 未证明优于单 Agent，同时也不能把本次差距解释为确定劣势。该 holdout 已冻结，禁止继续用于调参或同版本重跑。

保留集可恢复记录约 2036.38 万 token，Agent 与顾客模拟器峰值费率估算 `$1.7985`（保守按 7.2 元/美元约 `¥12.95`）；语义 Judge、单 Agent 任务 5 的 3 次不可恢复 token 和失败请求未完整计入，实际费用以 Provider 账单为准。评分保留上游 Prompt，但 Judge 使用 DeepSeek，因此结果不是官方默认 τ-bench 分数。详见 [5B 保留集报告](docs/PHASE5B_HOLDOUT_REPORT.md)和[结构化对照结果](reports/phase5b_holdout_comparison.json)。

冻结的 10 项开发样本不含 `communicate_info`；保留集的 `communicate_info` 与 `nl_assertions` 均由 `deepseek/deepseek-flash` 按未修改的上游语义 Prompt 评分。V3 已冻结，5B 已完成；5C 只分析冻结结果，不得用该 holdout 继续修改 V3。详见 [阶段 5B 进度报告](docs/PHASE5B_PROGRESS.md)、[V3 冻结报告](docs/PHASE5B_V3_FREEZE_REPORT.md)、[保留集报告](docs/PHASE5B_HOLDOUT_REPORT.md)和[v3 开发集对照](reports/phase5b_v3_development_comparison.json)。

## 阶段 5C：结果分析与求职交付（已完成）

5C 没有重跑或调优 holdout。`scripts.build_phase5c_report` 从冻结的逐次 CSV、开发/保留集汇总和本地脱敏轨迹重算配对统计、延迟、可比 usage 子集及失败双轴分类，并用 SHA256 记录输入。原始轨迹继续位于被 Git 忽略的 `reports/raw/`，不会把模拟客户明细、任务正文或评分参考动作提交到交付报告。

```mermaid
flowchart LR
  F[固定上游 commit / 哈希] --> DEV[10 项 train 开发样本]
  F --> HOLD[40 项 test 保留集]
  DEV --> FREEZE[V3 冻结]
  FREEZE --> HOLD
  HOLD --> PAIR[120 对单 Agent / V3 trial]
  REL[10 个自建可靠性场景] --> SEP[独立工程可靠性轨道]
  PAIR --> OUT[配对统计 / 延迟 / token / 成本 / 失败分类]
  SEP --> OUT
  OUT --> REPORT[summary + 结构化 JSON + 失败目录]
```

四组证据不能伪装为四组同口径实验：规则流程只有 10 个自建确定性场景；单 Agent 与 V3 才有 120 对官方任务自定义 Judge 结果；恢复增强只有 `REL-008` 的 1/1 专项证据。可靠性 10/10 仅表示绑定断言在本次各一次执行中通过，不是生产环境“100% 可靠率”。

只读复现与演示：

```powershell
# 重新计算并检查 JSON、Markdown、SVG 与冻结输入一致；不调用模型、不写数据库
.\.venv_tau\Scripts\python.exe -m scripts.build_phase5c_report --check

# 输出一页求职演示摘要
.\.venv_tau\Scripts\python.exe -m scripts.demo_phase5c

# 5C 专项测试
.\.venv_tau\Scripts\python.exe -m pytest -q tests/test_phase5c_analysis.py -p no:cacheprovider --basetemp=.tmp/pytest-phase5c
```

主要交付为[最终评测摘要](reports/summary.md)、[结构化分析](reports/phase5c_analysis.json)、[失败目录](reports/failures/phase5c_failure_catalog.md)和[阶段 5 验收报告](docs/PHASE5_REPORT.md)。5C 不修改业务 API；既有顾客写操作输入/输出示例和服务端安全边界保持不变。

2026-11-22 最终实测：5C 专项 **5 passed**；带真实 PostgreSQL 随机 schema 的完整后端 **269 passed、0 failed、0 skipped（101.68s）**；Ruff、报告一致性检查和只读演示通过；`phase*` 测试 schema 残留 **0**；外部 LLM 调用 **0**，holdout 重跑 **0**。
