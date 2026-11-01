# ServiceFlow — 可信多 Agent 智能售后平台

> 状态：阶段 1 本地开发与验收完成；已有业务 API、规则服务和 LangGraph 单 Agent Mock 基线。真实 LLM 与官方 τ-bench 评分未运行，无前端或多 Agent。

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
