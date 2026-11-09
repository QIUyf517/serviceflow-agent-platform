# ServiceFlow — 可信多 Agent 智能售后平台

> 状态：阶段 2.5B 已完成多 Agent 订单取消的可信确认、受控执行、数据库幂等/行锁和细粒度审计闭环。修改、退货、换货仍只生成方案，不执行；人工审批、完整恢复和前端尚未实现。

## 项目定位

基于 **τ-bench Retail 的模拟业务数据和政策**，开发一个可演示的电商售后系统：用户可以咨询订单、查询商品、申请取消/修改订单以及退换货；系统用 **LangGraph 多 Agent + 受控业务工具 + 规则校验 + 明确确认 + 可恢复状态** 完成工作，并用公开基准和自建异常场景评估可靠性。

- 目标用户：电商客户（聊天窗口）、售后客服/主管（工单与人工接管）、开发者（执行轨迹与评测）。
- 核心价值：**从回答问题升级为安全地完成售后业务**。
- 求职亮点：Tool Calling、RAG、业务 API、Multi-Agent、状态持久化、权限/幂等、可复现评测。

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

`POST /api/v1/operations` 的 `kind` 还支持 `modify_address`（完整 address）、`modify_payment`（payment_method_id）、`modify_items` / `exchange`（item_ids、new_item_ids、payment_method_id）及 `return`（item_ids、payment_method_id）。全部走同一提案、明确确认、订单版本重校验、数据库事务、幂等和审计路径。`GET /api/v1/users/me`、`GET /api/v1/orders/{id}`、`GET /api/v1/products/{id}` 均要求已核验会话。操作仅修改本地模拟数据库；支付历史变更不是外部资金退款或真实邮件发送。

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

产品对照脚本为每次运行创建并清理随机 PostgreSQL schema；结果不是官方 τ-bench 分数。Mock/本地编排的 Token 使用为 `null`，未填写推测成本；真实外部聊天 LLM 本轮未调用。完整实现、安全边界和实测证据见 [阶段 2.6 报告](docs/PHASE2_6_REPORT.md)。阶段 3 的完整会话持久化恢复、人工审批和前端仍未实现。
