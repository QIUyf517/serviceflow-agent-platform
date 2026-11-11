# ServiceFlow 开发任务清单

> 约定：Codex **按阶段推进**；每阶段都有独立验收标准；完成后记录测试结果与 Git 提交。

## 阶段 0：项目初始化与数据勘察（首轮只做这一阶段）

- [x] 创建 `backend/`、`frontend/`、`scripts/`、`tests/`、`data/raw/`、`data/processed/` 基础目录及 `.gitignore`、`.env.example`。
- [x] 创建 Python 项目配置（推荐 `uv`/`pyproject.toml`），确保 FastAPI + pytest + ruff 可运行。
- [x] 实现 `scripts/fetch_tau_retail.py`：下载/拷贝指定版本τ-bench Retail数据；记录仓库commit、来源、哈希。
- [x] 实现 `scripts/inspect_tau_retail.py`：输出JSON 顶层键、记录数量、抽样字段和政策文档信息；不得输出完整客户隐私字段到日志。
- [x] 实现基本数据结构校验与导入方案文档（不要先凭猜测建全量业务表）。
- [x] 配置本地PostgreSQL（Docker Compose），实现导入用户/商品/订单的**可复位**种子脚本；先追求可靠性，允许利用JSONB保存非核心嵌套字段。
- [x] 测试导入幂等性：重复导入不会重复插入记录；校验行数与原数据一致。

**验收：** 一条命令能检查数据、导入DB、运行测试；输出数据结构报告与导入结果。无需LLM Key。

### 阶段 0 执行记录（2026-11-01）

阶段状态：**已完成，真实 PostgreSQL 一键验收通过**。以下为初次受阻时的历史记录，最终结果见本节末尾的「PostgreSQL 最终验收」。详情见 `docs/PHASE0_REPORT.md`。

| 任务 | 必要验证及实际结果 |
|---|---|
| 目录与环境 | 目录及忽略规则检查；初始 Python 3.11.4，已本地安装 3.12.16 并创建 `.venv312`；未找到 Docker、PostgreSQL 服务/安装目录 |
| Python / FastAPI | `python -m pytest -q` 中健康接口返回 200 与实际 JSON，未实现的订单接口 404；pytest 可运行，ruff 最终检查通过；依赖已锁定 |
| 下载 | 官方固定 commit `da0835f6c67baef58bdda18f2a3b037dfb3a1754`，8 个文件下载成功并逐项验证 SHA256；离线获取/重复获取/篡改检测测试通过 |
| 检查 | 真实检查报告已输出：500 users、50 products、1000 orders、591 variants、2978 order items；脱敏报告测试通过 |
| 校验与方案 | 基本结构、ID、一致性、归属、引用、状态校验；6 类非法输入拒绝测试通过；见 `docs/DATA_IMPORT.md` |
| PostgreSQL 导入/复位 | Compose、JSONB 表与事务脚本已实现；连接尝试返回 OperationalError；未验证真实 PostgreSQL，因此本项不勾选 |
| 数量与幂等性 | SQLite 测试替身下真实数据初次/重复/复位数量一致，失败回滚、源版本切换保护通过；PostgreSQL 集成测试跳过，因此本项不勾选 |

初次总测试：**12 passed, 1 skipped**，另有 1 条上游 TestClient/httpx 弃用警告。ruff 检查通过。初次 `python -m scripts.phase0` 在数据库导入处失败；该阻塞现已通过下述真实 PostgreSQL 验收解除。

Git：本次开始时整个 `ServiceFlow/` 为未跟踪规划包，本次未创建提交；没有可报告的实现提交 SHA，来源 commit 仅指上游数据版本。

### Windows Docker 安装补充（2026-11-01）

- 按用户要求下载至 `D:\Downloads\Docker\Docker Desktop Installer.exe`（620,496,816 字节），Docker Inc 数字签名 Valid。
- Docker Desktop 4.97.0 安装至 `D:\Docker`，安装器退出码 0；WSL 数据根通过安装参数指定为 `D:\DockerData`，实际运行位置待首次启动后确认。
- WSL 3.0.3 安装退出码 0，日志明确提示系统组件重启后生效；未自动重启电脑。
- 已验证 Docker CLI 29.9.2、Compose v5.6.1；项目 `docker compose config --quiet` 退出码 0。
- 当前引擎管道尚不存在，PostgreSQL 验收仍未完成。重启 Windows、启动 `D:\Docker\Docker Desktop.exe` 并完成首次启动后，再运行 README 一键命令。
- 新增两个管理员安装辅助脚本，PowerShell AST 语法检查通过；运行结果日志位于 D 盘安装包目录。未把安装器退出成功等同于引擎/数据库测试通过。

### 项目目录整理（2026-11-01）

- [x] 将原 `ServiceFlow/` 内的文档、源码、脚本、数据、配置及本地环境移至 Git 仓库根目录；保留外层 `.git/`，移除空子目录，迁移前检查无重名目标。
- [x] 在新位置重建 `.venv312`，从本地缓存恢复锁定依赖并重新安装 editable 后端；修复 `.venv` 引导环境路径，无需重新下载数据或依赖。
- [x] README 与阶段报告的操作位置统一为仓库根目录；脚本通过文件位置计算 ROOT，无需改动数据路径代码。
- [x] 迁移后复验：pytest **12 passed, 1 skipped**（PostgreSQL 未配置），ruff 通过，8 个原始文件哈希通过，数据检查报告重新生成且数量一致，Compose 配置解析退出码 0；原始数据、环境和密钥路径仍被 Git 忽略。

整理不改变阶段 0 验收状态：PostgreSQL 真实导入仍待 Docker 引擎启动后验证；本次未开展阶段 1。

### PostgreSQL 最终验收（2026-11-01）

- [x] Docker Engine 29.9.2 可连接；实际容器数据磁盘为 `D:\DockerData\disk\docker_data.vhdx`。
- [x] `docker compose up -d --wait db` 退出 0，容器 healthy；PostgreSQL 16.15，仅映射 `127.0.0.1:5432`。
- [x] `.venv312/Scripts/python -m scripts.phase0` 退出 0：原始文件校验、结构报告、真实导入两次、**13 passed / 0 skipped**、ruff 均通过。
- [x] `scripts.seed_database --reset` 后再次导入均成功，真实库数量为 500 users、50 products、1000 orders；三张业务表的嵌套字段均为 JSONB。
- [x] PostgreSQL 测试在独立临时 schema 验证初次/重复导入及变更快照复位；测试结束后残留 `phase0_*` schema 数量为 0。
- [x] `data/manifest.json` 已生成，包含真实来源与导入数量；无客户明细输出。

实际测试有两条非阻断警告：上游 TestClient/httpx 弃用警告，以及 pytest 缓存写入权限警告；测试断言、数据库验证和一键命令均成功。数据库容器保留运行供后续使用。尚未创建 Git 提交；本轮止于阶段 0，未实现阶段 1。

## 阶段 1：业务领域与单 Agent 基线

- [x] 编写订单、用户、商品查询服务；支持当前用户授权约束。
- [x] 实现确定性政策校验服务，覆盖身份核验、取消待处理订单、一个退货场景。
- [x] 实现确认请求/确认令牌/操作提案状态机，未确认不能执行写操作。
- [x] 实现业务工具：`find_user`、`get_user_details`、`get_order_details`、`get_product_details`、`propose_cancel_order`、`confirm_and_execute`（产品工具名可不同于τ-bench适配器）。
- [x] 实现单 Agent + Tool Calling 基线；支持没有 LLM 密钥的 Fake Provider 测试。
- [x] 最小 `/api/chat` 接口，能完成端到端完整操作并记录操作历史。
- [x] 集成测试：身份未验证、别人订单、订单状态错误、无确认、重复操作。

**验收：** API手动演示从用户身份核验到订单取消成功；无确认不变更数据；单测/集成测试通过。

### 阶段 1 执行记录（2026-11-01）

本阶段在独立测试 schema 验证真实 PostgreSQL 读写；完整测试 **26 passed**、ruff 通过，本机 Uvicorn 健康接口返回 200。实现查询、取消、地址/支付/商品修改、退货和换货的确定性规则、提案确认和审计；Mock LangGraph 演示身份核验→查询→取消确认。官方评分与真实 LLM 测试未进行，评估入口只输出未评定指标。详见 `docs/PHASE1_REPORT.md`；未进入阶段 2。

## 阶段 1.5：真实 LLM 单 Agent 与 τ-bench 评估接入

- [x] 检查 Git 状态和忽略规则，排除密钥后建立阶段 1 本地提交；未推送远程。
- [x] 保留 Mock；加入可配置的真实 Tool Calling Provider、完整对话状态、结构化结果及轨迹。
- [x] 服务端继续承担身份、授权、提案确认、事务和幂等校验；真实模型不直接写数据库。
- [x] 使用独立 PostgreSQL schema 实测真实 DeepSeek 查询、取消、地址修改和退货，结束清理。
- [x] 实现官方 τ-bench 文本 Agent 适配器，核验固定 commit、原始文件哈希和任务划分。
- [x] 运行官方小样本联调；成功与失败轨迹分开保留。
- [x] 固定 10 项官方原始训练任务、模型、用户模拟器、随机种子、步数和评分配置，运行初步基线。
- [x] 产品与官方评估分别记录成功率、工具调用、延迟、Token、成本估计及失败信息。
- [x] pytest 与 ruff 通过，更新 README 和阶段报告。

验收范围、样本选择限制和实际指标见 `docs/PHASE1_5_REPORT.md`。本轮停止于阶段 1.5，不进入阶段 2。

## 阶段 2：多 Agent 与策略检索

### 阶段 2.1：架构设计与共享状态（2026-11-02）

- [x] 核对工作区、阶段 0/1/1.5 代码与阶段 1.5 评估记录；不把现有单 Agent 成绩作为多 Agent 结果。
- [x] 新增独立 `app.multi_agent.state.AgentState`、状态初始化及受控增量更新；明确身份/确认由服务端掌握。
- [x] 编写共享状态与 LangGraph 消息归并测试，验证单 Agent 入口仍可导入。
- [x] 编写 `docs/PHASE2_ARCHITECTURE.md`，给出职责、字段权限、工具白名单、错误策略与公平对照方案。

阶段 2.1 完成；专业 Agent、Supervisor、Policy 检索、RAG、完整工作流及多 Agent 评估仍在后续阶段，下面阶段 2 总任务保持未完成。

阶段 2.1 补充验收（2026-11-02）：完整 pytest 套件收集 **53 项，49 passed、0 failed、4 skipped**；`ruff check backend scripts tests` 与格式检查通过。共享状态、原有单 Agent、业务服务和 FastAPI API 测试均通过。跳过的 3 项 PostgreSQL 集成测试需要 `TEST_DATABASE_URL` 和运行中的 Docker 引擎；本次 Docker Desktop 虽已尝试后台启动，但 `dockerDesktopLinuxEngine` 管道不存在，数据库连接超时。另 1 项官方适配器测试因当前 `.venv312` 未安装 `tau2` 而跳过；这些测试未被删除或改为 Mock，不能把本次结果称为真实 PostgreSQL/官方适配器复验。

问题根因与最小修复：受限执行环境下，pytest 默认系统临时目录无法创建编号目录；本次用工作区内全新、被 Git 忽略的 `--basetemp=.pytest_phase21_acceptance2` 完成运行。受限环境的 Windows `asyncio` 在 `socket._fallback_socketpair` 的 `accept` 等待，连无数据库依赖的健康接口也卡住；解除该本地 socket 限制后，同一 TestClient 请求立即返回 200。应用无自定义 lifespan，卡住发生在进入应用、数据库和 LLM 调用之前，不是 2.1 状态模块回归。解除限制后发现既有 `test_health` 在数据库关闭时得到 503 而非期望的缺头 422；仅将该测试接入已有 SQLite `service` fixture 并在 `finally` 清理依赖覆盖，保留真实 TestClient 请求和原断言，不改业务逻辑。

可复现验收命令：`.venv312/Scripts/python -m pytest -q -rs -p no:cacheprovider -o faulthandler_timeout=30 --basetemp=.pytest_phase21_skipreasons`（需允许本地 loopback socket）；`.venv312/Scripts/python -m ruff check backend scripts tests`。待 Docker 引擎可用后，可按 README 设置 `TEST_DATABASE_URL` 再运行相同套件，以补验 3 项 PostgreSQL 测试。该记录形成时阶段 2.2 尚未开始。

### 阶段 2.2：Supervisor + Triage（2026-11-02）

- [x] 定义 `TriageResult` 和 `TaskPlan`，支持多意图、缺失信息和依赖计划。
- [x] 实现 Mock/真实 Provider Triage，严格解析、有限重试及编号原文校验。
- [x] 实现确定性 Supervisor、最大路由次数和非法目标安全兜底。
- [x] 实现 LangGraph 最小规划图、多轮会话内存状态与独立调试 API；不执行专业节点。
- [x] 新增 Triage、Supervisor、工作流与 API 自动化测试；更新 README 和阶段报告。

阶段 2.2 完整验收：`.venv312/Scripts/python -m pytest -q -rs -p no:cacheprovider -o faulthandler_timeout=30 --basetemp=.pytest_phase22_acceptance2` 收集 **88 项，84 passed、0 failed、4 skipped**；`.venv312/Scripts/python -m ruff check backend scripts tests` 通过。跳过项与阶段 2.1 相同：3 项需要未启动的 PostgreSQL/Docker，1 项需要当前 `.venv312` 未安装的 `tau2`。真实 `deepseek-v4-flash` 合成输入烟测及首次订单号 `#` 丢失后修复情况见 `docs/PHASE2_2_REPORT.md`；不计入 pytest。阶段 2 总任务保持未完成，不开始阶段 2.3。

### 阶段 2.3：Order Agent 只读订单查询（2026-11-02）

- [x] 复用 `RetailService`、服务端会话和订单归属校验；只增加独立只读工具适配与严格参数模型。
- [x] 实现 Order Agent 的确定性工具选择、受限字段投影、错误码、工具次数上限和运行轨迹。
- [x] 将 Order Agent 接入 LangGraph 规划图，查询后经 Supervisor 结果处理安全终止；未实现的子任务保持未完成。
- [x] 覆盖订单列表、详情、状态、商品、物流已有字段、权限隔离、多轮补号及单 Agent/API 回归。
- [x] 使用隔离 PostgreSQL schema 补跑原先跳过的数据库测试，使用 `.venv_tau` 补跑官方适配器测试；更新 README 与阶段报告。

阶段 2.3 只读查询验收记录及实际测试结果见 `docs/PHASE2_3_REPORT.md`。阶段 2 总任务仍未完成；Policy、Resolution、RAG 与写操作不属于本阶段。

### 阶段 2.4：Policy Agent + RAG 政策检索（2026-11-02）

- [x] 验证固定 τ-bench Retail `policy.md` 的 commit、SHA256、大小与标题结构，不修改官方原文。
- [x] 实现 H2 业务条款 + H3 子规则聚合切分、版本元数据、幂等导入与显式重建。
- [x] 实现可测试的关键词基线、Top-K、分数、来源与空证据处理。
- [x] 实现可配置 Embedding Provider 与 PostgreSQL pgvector 导入/检索路径；当前环境缺 pgvector 与 Embedding Key，未伪造向量结果。
- [x] 实现 Policy Agent、服务端引用、证据不足回答、Prompt Injection 防护和 `AgentState.policy_context` 更新。
- [x] 接入 `Triage → Supervisor → Policy → Supervisor result`，复合任务可先完成 Order/Policy 并保留未实现任务。
- [x] 新增 30 条标注检索集、评估脚本、单元/API/PostgreSQL/回归测试与阶段报告。

阶段 2.4 验收：关键词检索 30 条实测 Recall@3 **1.000**、MRR **0.961111**、平均延迟 **0.961 ms**；向量指标为 N/A。`.venv_tau` 完整套件 **126 passed、0 skipped**，`ruff check backend scripts tests` 通过。详见 `docs/PHASE2_4_REPORT.md`。本轮不进入 2.5。

### 阶段 2.5A：Resolution Agent 方案生成与决策整合（2026-11-02）

- [x] 定义 `ResolutionProposal`、证据引用与独立 `EligibilityResult`，区分生成建议和确定性规则结果。
- [x] 实现本地 Resolution 生成器，支持取消、修改、退货、换货及缺失信息识别；非法结构安全拒绝。
- [x] 新增 `RetailService.validate_action` 只读接口，在深拷贝上复用执行硬规则，不创建操作提案或审计记录。
- [x] 将依赖顺序调整为 Order/Policy → Resolution → Guard，并接入 LangGraph；Confirmation/Executor 保持阻塞且不执行。
- [x] 扩展 `AgentState` 与调试 API，输出方案、资格结果、待确认信息、风险、最终回复和累计轨迹。
- [x] 保留关键词检索回退和单 Agent/API；覆盖错误模型建议、身份/会话隔离、多轮补充、重复方案与零写入。
- [x] 更新 README、自动化测试和 `docs/PHASE2_5A_REPORT.md`。

阶段 2.5A 完整验收：本机 PostgreSQL 16 隔离 schema、`.venv_tau` 官方适配器与 FastAPI TestClient 全部纳入，**144 passed、0 skipped**；`ruff check backend scripts tests` 通过。Resolution 未调用外部 LLM，pgvector 仍未完成真实环境验证，默认关键词检索已覆盖端到端方案生成。确认、执行、人工审批、持久化恢复和前端未实现；本轮停止，不进入阶段 2.5B。详见 `docs/PHASE2_5A_REPORT.md`。

### 阶段 2.5B：安全业务执行与订单取消闭环（2026-11-02）

- [x] 新增与 LLM 解耦、仅允许取消的 `ExecutionService`，复用 `RetailService._apply`、身份/归属校验和数据库事务。
- [x] 持久化执行请求、方案/参数摘要、订单版本、确认记录和数据库唯一幂等键。
- [x] 实现服务端具体确认文本、确认/拒绝、有效期及方案/订单/用户/版本绑定；拒绝布尔确认绕过。
- [x] 执行前重新读取并锁定订单，校验行版本、当前规则和确认绑定；成功写入真实订单状态。
- [x] 实现重复执行结果复用、幂等键冲突拒绝、同订单并发仅一次转换及事务异常回滚。
- [x] 新增细粒度执行审计，区分方案、资格、确认、成功执行和失败执行。
- [x] 接入非 LLM LangGraph Confirmation Gate、Execution Node、Supervisor Result 和真实数据库结果回复。
- [x] 新增创建/查询请求、确认/拒绝、执行、订单状态及审计查询 API。
- [x] 完成 SQLite 单元、FastAPI、真实 PostgreSQL 隔离 schema 并发和全套回归测试；更新 README 与阶段报告。

阶段 2.5B 最终验收：`.venv_tau` 完整套件 **163 passed、0 failed、0 skipped**；`ruff check backend scripts tests` 通过。真实 PostgreSQL 测试中两个确认请求并发取消同一订单，严格得到一次成功和一次 `order_changed`，订单版本只增加 1；未确认场景保持 `pending`。随机 `phase25b_*` schema 测试后残留为 0。未调用外部 LLM，未修改正式演示订单或官方 τ-bench 数据/评分器。多 Agent 修改、退货、换货执行及 2.5C 均未开始。详见 `docs/PHASE2_5B_REPORT.md`。

### 阶段 2.5C：订单取消端到端 Multi-Agent 闭环（2026-11-04）

- [x] 新增统一自然语言会话入口，串联既有 Triage、Supervisor、Order、Policy、Resolution、Guard、Confirmation 和 Execution 节点。
- [x] 实现两轮取消、拒绝、重复确认、修改订单号、改变诉求、确认过期和等待期间订单状态变化的确定性状态处理。
- [x] 将旧待确认请求持久化为 `superseded`，使旧确认失效；执行仍复用 2.5B 数据库幂等、锁、事务和审计边界。
- [x] 禁用阶段 1 旧 HTTP 写入口及聊天布尔确认路径，新增绕过回归；保留查询型单 Agent Baseline 和内部服务契约。
- [x] 新增当前任务查询、完整 Agent trace/工具次数/延迟输出及隔离 PostgreSQL 演示脚本。
- [x] 新增 FastAPI 多轮、隔离、过期、状态竞争、旧 API 安全测试和 PostgreSQL 两轮测试代码。
- [x] 更新 README 与 `docs/PHASE2_5C_REPORT.md`；未扩展修改、退货或换货执行。
- [x] 在真实 PostgreSQL 16 随机 schema 中运行 2.5C 两轮测试和演示；确认成功写入、未确认零写入、审计完整且 schema 零残留。

阶段 2.5C 最终验收：`.venv_tau` 全套 **169 passed、0 failed、0 skipped**；`ruff check backend scripts tests` 通过。新增 PostgreSQL 两轮测试 **1 passed**；演示实测成功订单从 pending 变为 cancelled，未确认反例保持 pending，成功链路 4 类审计齐全，`phase25c_*` schema 残留为 0。未调用外部 LLM，未修改官方 τ-bench 数据或评分器。详见 `docs/PHASE2_5C_REPORT.md`。

- [x] 用 LangGraph 实现 Triage、Order、Policy、Resolution 四个专业节点，以及确定性 Guard/Executor（可从 2 个 Agent 起步再扩展）。
- [x] 为 Agent 设置独立工具白名单；跨节点传递结构化 State，不传递完整用户数据库。
- [x] Policy Agent v1 直接引用 `policy.md` 相关标题段落；记录证据来源。
- [x] 新增业务FAQ/商品手册文档集，再引入 pgvector Embedding检索，做RAG召回测试。
- [x] 记录 trace_id、节点耗时、工具调用、Token使用情况（无统计则标为缺失）。
- [x] 证明相同业务案例在单 Agent 与多 Agent 均能运行。

**验收：** 至少查询、取消、退货三种端到端场景；检索可溯源；无未经授权的数据写入。

### 阶段 2.6：阶段 2 收尾与验收（2026-11-04）

- [x] 核对全部专业节点、结构化 State 和工具白名单；跨节点写工具调用、模型自设身份/确认及文档指令绕过均被拒绝。
- [x] 在共享 `ExecutionService` 上补齐退货申请的多轮确认、事务、行锁、硬规则重校验、数据库幂等和审计闭环；不伪报真实退款。
- [x] 新增两份 ServiceFlow 自编非权威文档、版本/来源/SHA256 manifest、幂等导入和显式重建。
- [x] 使用 PostgreSQL pgvector 0.8.7 与真实本地多语言 MiniLM（384 维）完成索引、Agent 路径和 30 条同标注集检索评估；保留关键词默认路径。
- [x] 补齐 `trace_id`、任务/请求关联、逐节点实测耗时、结果/错误码、工具调用数、Provider/模型/配置和实际 Token 字段；Mock Token 为 `null`。
- [x] 新增共享安全执行边界的受控单 Agent 入口，并在六个独立随机 schema 中完成查询、取消、退货的单/多 Agent 同案例验证。
- [x] 运行完整 pytest 与 ruff，更新 README、报告和脱敏结果文件；未进入阶段 3。

阶段 2.6 最终验收记录见 `docs/PHASE2_6_REPORT.md`。本轮完整 pytest 为 **181 passed、0 failed、0 skipped**（最终文档提交前再次复验）；真实 PostgreSQL/pgvector 退货测试使用随机 `phase26_*` schema 并清理。阶段 2 产品验收已满足，但这不是官方 τ-bench 对照实验，也不表示多 Agent 优于单 Agent。真实外部聊天 LLM 未调用；完整会话持久化恢复、前端、人工审批及阶段 3 工作保持未开始。

## 阶段 3：工单、持久化与人工接管

- [x] 建立 `tickets`、`messages`、`approvals`、`audit_events`；保留既有 `agent_conversations`、`execution_requests` 过渡兼容且不迁移历史数据。
- [x] 接入 LangGraph PostgreSQL checkpointer；跨请求/进程恢复会话、处理中任务及等待确认状态。
- [x] 为写操作实现幂等键、唯一约束、事务、执行租约与失败补偿/分类重试方案。
- [x] 实现人工接管 API；对不支持/高风险/规则冲突/不可重试失败等确定性建单且不假装已处理。
- [x] 注入异常：LLM/工具超时、并发与串行重复请求、进程在确认后中断、订单状态变化。

### 阶段 3 执行记录（2026-11-09）

阶段 3 最终验收使用本机 PostgreSQL 16.15 专用 `serviceflow_demo`、随机隔离 schema、SQLite 显式测试替身、FastAPI TestClient 和已安装的官方适配器：**204 passed、0 failed、0 skipped**，`ruff check backend scripts tests` 通过。最终 `phase3_%` 与全套已知随机测试 schema 残留均为 **0**；外部 LLM 调用 **0**。故障注入脚本使用合成数据，覆盖超时、重复请求、确认后中断和订单变化；未修改 τ-bench 官方数据、任务、工具或评分器。

验收中两次全套运行曾为 **191 passed、13 failed**，13 项均因专用 PostgreSQL 容器在 2026-11-09 23:14（Asia/Shanghai）以 exit 255 异常退出而连接超时；`OOMKilled=false`，数据库日志没有自身 fatal/panic。重启并确认 healthy 后，同一全套测试全部通过。阶段 3 的表、恢复语义、状态机、API 与逐场景证据见 `docs/PHASE3_REPORT.md`。阶段 4 尚未开始。

**验收：** 可以复现故障并稳定恢复；重复请求只产生一次业务变更。

## 阶段 4：前端与管理后台

- [x] React 用户聊天页：消息、业务操作确认、订单卡片、错误展示。
- [x] 管理后台：工单列表、详情、人工审批/接管、审计日志。
- [x] 开发者页：Agent轨迹、工具调用、耗时、失败定位。
- [x] Docker Compose 启动服务；附种子数据和演示账户说明。

**验收：** 浏览器端完成查询 → 取消/退货 → 审计/人工接管的完整演示。

### 阶段 4A 执行记录（2026-11-11）

仅完成前端基础与用户聊天页；管理后台、开发者页、Compose 前端编排和阶段 4 整体验收仍未完成。React 页面接入现有真实 API，覆盖会话、身份核验、订单列表/详情、多轮对话、取消/退货确认、任务恢复和人工建单。前端自动化 **17 passed**，lint、typecheck、build 和 npm audit 通过；没有调用外部 LLM。范围、测试证据和未验证项见 `docs/PHASE4A_REPORT.md`。

### 阶段 4B 执行记录（2026-11-11）

在阶段 4A 既有 React 工程内完成管理后台与开发者追踪页，没有重建前端、修改后端契约或新增业务能力。管理端使用独立 `X-Operator-Token`，覆盖工单过滤分页、脱敏详情/审计、分配、合法状态流转、关闭原因、审批和人工代触发；审批不能替代客户确认。开发者页展示聊天响应和服务端任务/trace 的节点、工具、耗时、Provider、token usage 与业务关联，并对跨 session trace 安全拒绝。最终前端自动化 **7 files、30 passed、0 failed**；lint、typecheck、build 通过，外部 LLM 调用 **0**。Compose 前端编排和浏览器整体验收仍未完成，因此阶段 4 整体没有标记完成。详见 `docs/PHASE4B_REPORT.md`。

### 阶段 4C 与阶段 4 收尾记录（2026-11-11）

Compose 已编排 PostgreSQL、FastAPI 与 React/Nginx，三项服务均有健康检查并按健康依赖启动；普通启动不导入或复位数据，种子数据仅通过 `tools` profile 显式执行。最终后端全套 **204 passed、0 failed、0 skipped**，ruff 通过；前端 **7 files、30 passed、0 failed**，lint、typecheck、build 均通过。Playwright 使用 Chromium 连接真实 FastAPI 与真实 PostgreSQL，**6 passed、0 failed**，覆盖查询、取消、退货、未确认零写入、人工接管、审批不能替代客户确认、成功/失败 trace 与刷新恢复。随机 `phase4_e2e_*` schema 清理后残留 **0**；Docker 中 db、api、frontend 均为 healthy；外部 LLM 调用 **0**。阶段 4 的全部验收门槛已满足，详见 `docs/PHASE4_REPORT.md`。阶段 5 未开始。

## 阶段 5：评测与求职交付

- [ ] 按 `docs/EVALUATION.md` 实现保留集 + 自建异常集。
- [ ] 把单 Agent 与多 Agent 接入同一 τ-bench 原版评测接口（按上游版本实际约束适配）。
- [ ] 固定模型、提示词版本、采样设置、调用预算，收集成功率、违规率、延迟、成本。
- [ ] 测试身份隔离、无确认拒绝、恶意提示、重复写入与服务恢复。
- [ ] 完成 README、架构图、演示脚本、实际结果与失败案例报告。

**验收：** 实验可重复，官方分数与扩展指标明确分开，无伪造数据。

## 可选阶段 6：模型微调（不阻塞主项目）

- [ ] 仅从允许的训练集及有来源的成功轨迹构造 SFT/LoRA 数据。
- [ ] 隔离测试集，去除评分答案、敏感字段；记录许可证与数据谱系。
- [ ] 与未微调模型在统一测试下对比，并报告成本和效果。
