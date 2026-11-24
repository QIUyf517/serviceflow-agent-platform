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

## 阶段 4.5：模拟商店与中文客服体验（待开发）

> 依据 2026-11-13 用户确认的业务流程图，按 4.5A → 4.5B → 4.5C → 收尾验收推进。以下均为待办，不代表现有能力；每部分完成后按本文件的阶段完成定义记录测试和结果，再进入下一部分。复用阶段 1–4 的订单、政策、工单和审计服务；演示数据为 τ-bench Retail 模拟数据。

### 4.5A｜模拟商店与顾客身份（对应「顾客入口」第 1–2 条）

- [x] 建立模拟商店前台：商品列表/详情、购物车、事务化模拟下单、当前顾客订单页，以及从订单打开的智能客服对话框；商店与客服读取同一业务数据库。
- [x] 实现模拟顾客登录与服务端会话绑定。进入客服时沿用已核验身份，切换顾客必须重新核验；前端传入的 `user_id` 或订单号不能自行授权访问。
- [x] 验收：商店与客服读取同一份真实订单数据；未核验身份不得暴露订单或个人资料，跨顾客访问被服务端拒绝。

#### 4.5A 完成记录（2026-11-13）

新增 `/store` 中文模拟商城与同库商品目录/详情 API，保留 `/support` 兼容跳转。商城采用熟悉的中文电商信息结构，支持搜索、选规格、购物车和真实 `POST /orders` 模拟下单；商城不再显示重复的全局项目顶栏，商品详情使用打开即见、内部滚动的居中对话框（移动端为底部抽屉）。服务端在已核验身份下重读商品、地址和支付方式，以事务、幂等键和 `order_creations` 审计记录创建订单。未核验会话可读取公开商品，但下单、订单和个人资料返回 403；订单号不能越过 session 归属校验。每笔订单提供“联系商家客服”，点击打开绑定该订单上下文的智能客服对话框。正常的未核验会话安静进入身份门，不显示红色 403；已核验但暂无客服任务的会话不要求重复核验。切换顾客会创建新 session，并清除购物车、订单、对话、任务和内存 trace。商品名、规格字段和值均使用可测试的中文映射，原始数据不变。完整后端 **208 passed、0 failed、0 skipped**；前端 **8 files、38 passed、0 failed**；Chromium + 真实 FastAPI/PostgreSQL **7 passed、0 failed**；Ruff、lint、typecheck、build 通过；Compose 三项服务 healthy；随机 schema 残留 **0**；外部 LLM 调用 **0**。详见 `docs/PHASE4_5A_REPORT.md`。4.5B 及后续任务未开始。

### 4.5B｜咨询分流与售后闭环（对应「顾客入口」第 3–5 条）

- [x] 先做可测试的内容安全检查，再分流 FAQ/政策、商品咨询、订单/物流、取消/退货、表述不清及超范围请求；拦截时用中文说明，正常咨询不因简单关键词误判。
- [x] FAQ/政策沿用带来源的政策检索，商品咨询调用实时商品服务；业务参数缺失时中文追问并保留多轮上下文，不将正常追问标成无法解决。确实无法自动解决时提示可请求转人工，不自动创建工单；只有客户明确要求人工时才建单。
- [x] 订单/物流查询执行服务端身份与归属校验；取消/退货遵循具体提案 → 客户明确确认 → 执行前重检 → 事务、幂等与审计。操作完成后商店订单页显示同一数据库中的最新状态。
- [x] 验收：客服操作后商店订单状态同步；未经客户明确确认的写入为零，重复确认不会重复处理，越权访问被拒绝。

#### 4.5B 完成记录（2026-11-13；转人工策略于 2026-11-14 修订）

统一 `/api/v1/multi-agent/chat` 现在在意图分流前执行可独立测试的确定性内容安全检查，只对具备上下文的伤害、违法获取凭证等具体请求拦截，“秒杀商品”、“杀菌功能”、“订单取消”等正常文本不因单词命中被拦截。通过结构化 `consultation_route` 分流政策 FAQ、实时商品、订单/物流、售后写操作、含糊、超范围、证据不足和数据不可用；客户端查询回复由当前政策索引或业务数据库生成中文投影。任何无法自动处理的回合都明确回复“智能客服当前无法解决这个问题”，只追问或说明边界，并提示可回复“转人工”，不因重复失败自动建单。只有明确的转接意图才建单，“你是人工客服吗”不误触发。

取消/退货仍复用服务端提案、明确确认、执行前重读、事务、幂等和审计；前端仅在 `execution_result.status=succeeded` 时刷新同一业务库的订单列表和详情。2026-11-14 最终实测：后端 **220 passed、0 failed、0 skipped**；前端 **8 files、39 passed、0 failed**；Chromium + 真实 FastAPI/PostgreSQL **8 passed、0 failed**；Ruff、ESLint、TypeScript 和生产构建通过；E2E 随机 schema 残留 **0**；Compose 三项服务 healthy；外部 LLM 调用 **0**。详见 `docs/PHASE4_5B_REPORT.md`。4.5C 与阶段 4.5 收尾仍未开始。

### 4.5C｜中文体验与人工接管（对应「中文回复与人工接管」）

- [x] 顾客可见的 FAQ、商品、订单、提案、拒绝、失败、工单及完成提示统一使用准确中文，替换 `Read-only query completed from the business database.` 等英文技术提示；错误码和轨迹保留给开发者，失败不得显示为成功。
- [x] 商家后台自动检查新工单、显示关联会话和归属核验后的简要订单信息；客服可以接管并回复，顾客在客服窗口收到中文人工回复和工单状态。
- [x] 验收：两端状态文案一致；人工审批不代替客户明确确认，人工接管不绕过订单归属与写操作规则。

#### 4.5C 完成记录（2026-11-14）

新增操作员 `POST /api/v1/tickets/{ticket_id}/reply`，在事务中保存人工消息及审计；顾客通过本人已核验会话读取 `GET /api/v1/customer/tickets` 和 `GET /api/v1/customer/tickets/{ticket_id}/updates`，服务端拒绝跨顾客读取。后台每 5 秒检查新工单，展示按订单归属校验的状态与商品项数量；顾客对话框每 5 秒读取人工回复和中文状态。顾客可从同一已核验会话恢复最近 200 条对话；取消原因追问承接常见输入错字，仅生成待确认提案。取消/退货执行结果、确认面板和任务进度使用中文展示，失败不宣称成功。更新后后端完整测试 **225 passed**，前端 **39 passed**，真实浏览器 **10 passed**，随机 schema 残留 **0**；Ruff、ESLint、TypeScript 与生产构建通过。阶段 4.5 收尾验收仍是独立待办。

2026-11-15 修复人工接管仅支持“客服 → 顾客”的单向缺陷：新增身份与工单双重绑定、幂等的 `POST /api/v1/customer/tickets/{ticket_id}/messages`；活动人工工单期间顾客消息不再调用 Agent，`waiting_customer`/`resolved` 回复后恢复为 `in_progress`，写入 `customer_replied` 审计且不在审计负载中保存正文。后台当前工单详情和审计改为每 5 秒后台轮询。更新后的后端完整测试 **226 passed**，前端 **40 passed**，真实 Chromium/FastAPI/PostgreSQL **10 passed**，随机 schema 残留 **0**；Ruff、ESLint、TypeScript 与生产构建通过。收尾人工验收项仍待用户在新版页面复核后勾选。

同日人工复核又发现：由订单对话中的“转人工”建立的旧工单没有写入 `order_id`，页面刷新后前端按当前订单筛选时丢失该活动工单，后续顾客消息误入 Agent；旧 PostgreSQL 检查点同时可能缺少 `triage_result`，从而返回 HTTP 500。修订后，订单范围内的明确转人工会绑定经服务端归属校验的订单；前端可恢复同一已核验会话内的旧未绑定活动工单；恢复图状态时会补齐新版本状态通道。更新后的真实 PostgreSQL 后端全套 **227 passed**，前端 **8 files、41 passed**，Ruff、ESLint、TypeScript 与生产构建通过；Compose 三项服务 healthy。阶段 4.5 收尾人工验收仍未勾选。

同日根据人工客服可用性反馈，将后台分散的“脱敏会话”与“回复顾客”合并为同一个人工聊天窗口：顾客消息左对齐、人工客服右对齐、智能客服记录使用中性样式；消息区固定高度并在轮询收到新消息后定位至最新内容，回复框紧邻消息区，支持 Enter 发送与 Shift+Enter 换行。分配、状态流转、审批和代执行继续作为独立治理区，不与对话动作混杂。前端完整测试 **8 files、42 passed**，ESLint、TypeScript、生产构建通过；实际后台截图完成桌面视觉检查，更新后的 frontend 容器 healthy。收尾人工验收仍由用户复核后决定是否勾选。

### 4.5D｜订单独立会话线程（串话修复）

- [x] 后台工单详情只查询与本工单线程绑定的消息，不再按 `session_id` 读取整个会话。
- [x] 新增 `support_threads` 表与 `messages.thread_id`、`tickets.thread_id`；服务端按已核验身份和订单归属创建或恢复线程。
- [x] 顾客打开某笔订单只恢复该订单线程绑定的工单，取消“找不到订单工单时采用任意未绑定工单”的兼容逻辑；未绑定旧工单归入“通用咨询”。
- [x] LangGraph 检查点按线程隔离，待确认请求只在所属线程可见；切换线程不携带上一订单的确认状态。
- [x] 旧 PostgreSQL 表就地升级并回填线程，输出绑定、通用与冲突数量；不按时间或自然语言猜测订单。
- [x] 顾客端按订单切换聊天记录与标题，新增独立“通用咨询”入口；商家端突出订单号并提供同单历史折叠、其他订单默认收起。
- [x] 新增双订单隔离、刷新恢复、跨顾客 404、通用咨询不进入订单线程、切换线程无确认泄漏、人工回复不能替代客户确认的测试。

#### 4.5D 完成记录（2026-11-15）

根因是人工工单详情按 `session_id` 查询最近 20 条消息，同一顾客不同订单因此串话。现在每个 `(session, order)` 由服务端创建或恢复一条 `support_threads` 记录，`messages`、`tickets` 和 LangGraph 检查点全部挂到该线程；客户端只能提交 `order_id`，线程由服务端在核验身份与订单归属后解析，越权访问仍返回 404。订单线程内若提及另一笔订单会被确定性拒绝并提示从对应订单重新打开客服。未绑定订单的旧工单固定进入“通用咨询”线程，不再自动挂到任意订单窗口。

旧演示库执行 `scripts/migrate_support_threads.py` 实测创建 2 个订单线程、8 个通用线程，绑定 7 张工单，`tickets_with_order_conflict=0`，重复执行为全 0。最终验证：后端完整 **235 passed、0 failed、0 skipped**（含真实 PostgreSQL 随机 schema）；前端 **8 files、43 passed**；真实 Chromium + FastAPI + PostgreSQL **11 passed**，新增双订单用例验证打开 A 写入消息、切到 B 无 A 消息、刷新恢复 B 线程、再切回 A 仍只有 A 的消息；`ruff check backend scripts tests`、ESLint、TypeScript 与生产构建通过；E2E 随机 schema 残留 **0**；外部 LLM 调用 **0**。详见 `docs/PHASE4_5D_REPORT.md`。

### 阶段 4.5 收尾验收（独立一轮）

- [x] 浏览器全流程人工演示：FAQ → 商品咨询 → 本人订单 → 取消或退货 → 状态同步 → 工单提醒 → 人工回复；每段核对真实 API 与数据库结果。
- [x] 覆盖异常用例：含“中午回答”的含糊输入、超范围请求、内容拦截、证据不足、身份隔离、未确认零写入、重复确认和人工审批边界；断言顾客回复不含英文技术提示。
- [x] 运行后端 pytest/ruff、前端 lint/typecheck/test/build，以及连接真实 FastAPI + PostgreSQL 的 Chromium 关键场景；记录 passed/failed/skipped，更新 README、演示说明和阶段报告。

**阶段 4.5 验收门槛：** 顾客在模拟商店完成咨询和一项售后操作，商家后台可处理对应人工工单；两端数据一致、顾客回复为中文，安全边界与自动化测试通过。完成前保持上述任务未勾选。

#### 阶段 4.5 最终验收记录（2026-11-15）

用户已按收尾清单完成人工浏览器复核并确认全部通过。随后使用本地真实 PostgreSQL 演示数据库独立重跑：后端 **235 passed、0 failed、0 skipped**，Ruff 通过；前端 **8 files、43 passed**，ESLint、TypeScript 与生产构建通过；真实 Chromium + FastAPI + PostgreSQL 端到端测试 **11 passed**，随机 schema 已清理且残留 **0**；外部 LLM 调用 **0**。阶段 4.5 达到验收门槛并正式完成，阶段 5 尚未开始。详见 `docs/PHASE4_5_ACCEPTANCE_REPORT.md`。

#### 阶段 4.5 顾客用语回归修复（2026-11-19）

- [x] 在订单线程将“这个订单不要了”等口语识别为取消请求和“不再需要”原因；政策提问、商品诉求和通用咨询仍不触发订单写入。
- [x] 待确认消息使用中文具体摘要，不向顾客展示内部英文确认令牌；明确确认、订单归属、执行前重检及幂等机制保持原有约束。
- [x] 增加真实 API 回归：确认前订单不变、重复表达复用同一请求、确认后只修改绑定订单。完整后端 **253 passed、0 failed、0 skipped**（含本地 PostgreSQL 临时 schema）；Ruff 通过，外部 LLM 调用 **0**。
- [x] 订单客服入口接入可替换模型分类器：规则未识别的口语由模型提取意图和原因；无效输出、编造订单号、低置信度或接口故障回退本地规则；通用咨询仍不执行订单写操作。政策检索附加服务端意图词以覆盖“撤掉”等表达，业务授权和确认保持确定性。Mock 集成测试覆盖“下错了，帮我撤掉”且确认前零写入；真实 DeepSeek 分类烟测 1 次成功。完整后端 **259 passed、0 failed、0 skipped**，Ruff 通过。运行中 API 已加载更新文件并通过健康检查；Compose 重建镜像前需注意容器内热更新不会永久保留。

## 阶段 5：评测与求职交付

- [x] 按 `docs/EVALUATION.md` 实现保留集 + 自建异常集。
- [x] 把单 Agent 与多 Agent 接入同一 τ-bench 原版评测接口（按上游版本实际约束适配）。
- [x] 固定模型、提示词版本、采样设置、调用预算，收集成功率、违规率、延迟、成本。
- [x] 测试身份隔离、无确认拒绝、恶意提示、重复写入与服务恢复。
- [x] 完成 README、架构图、演示脚本、实际结果与失败案例报告。

**验收：** 实验可重复，官方分数与扩展指标明确分开，无伪造数据。

### 阶段 5A：评测框架、数据冻结与异常集（2026-11-18）

- [x] 固定官方 τ-bench Retail commit、四个原始文件哈希、10 项开发集和完整 40 项官方 test 保留集；开发集与保留集互斥。
- [x] 声明保留集在 5A 不用于 Prompt 调优或计分；准备代码只校验 `tasks.json` 哈希，不解析或向 Agent 暴露任务正文、参考动作和评分条件。
- [x] 将 10 类 ServiceFlow 自编异常场景写成独立 manifest，并逐项绑定可执行测试；明确这些结果不得标为官方 τ-bench 分数。
- [x] 新增严格 Pydantic 配置模型、manifest 哈希校验、官方 split 核验、测试节点发现和无密钥烟测入口。
- [x] 固定 5B 候选模型、温度、任务随机种子、重复次数、步数、工具预算、并发和四个对照组；实际价格在正式运行日期记录。
- [x] 运行 5A 烟测、完整 pytest 和 Ruff，生成真实烟测报告并更新 README、评测设计与阶段报告。

#### 5A 完成记录

`scripts.prepare_phase5a --run-smoke` 实际执行 **10 类场景、11 passed**，外部 LLM 调用 **0**，官方保留集执行 **0**，未生成正式分数。完整后端回归在真实 PostgreSQL 随机 schema 下为 **239 passed、0 failed、0 skipped**，Ruff 通过。首次烟测因复用了被中断进程占用的 Windows pytest 临时目录而报 `WinError 32`；修复为每次使用唯一 `basetemp` 后通过，属于编排问题而非业务断言失败。详见 `docs/PHASE5A_REPORT.md`。阶段 5B、5C 均未开始。

### 阶段 5B：公平对照运行与指标采集

- [x] 将单 Agent 与多 Agent 接入同一原版 τ-bench 接口，使用相同模型、工具、Guard、任务、步数与调用预算。
- [x] 先运行开发集并冻结实现：V3 单订单线程边界、实现哈希和失败分类已固化，原始失败轨迹完整保留。
- [x] 经独立预算确认后运行保留集；不在保留集上继续调参。最终单 Agent 51/120（42.50%），V3 45/120（37.50%），V3 未证明优于单 Agent。
- [x] 单独运行自建可靠性与故障恢复集，输出成功、违规、越权、未确认写入、重复写入、恢复、延迟、Token 和成本指标。
- [x] 已执行的开发集、可靠性与保留集任务逐项写入 `reports/results.csv` 和被忽略的脱敏原始轨迹；官方任务自定义 Judge 与自建结果使用不同命名空间（保留集 240 行）。

#### 5B 完成记录（2026-11-21）

已实现单/多 Agent τ-bench 适配器、共享 Guard 和固定工具/Token 预算。自建可靠性轨道真实运行 **10/10 通过**；开发集单 Agent **22/30（73.33%）**，V3 **24/30（80.00%）**。冻结后完成同一 test 保留集 40 项 × 3 次 × 2 架构共 240 次：单 Agent **51/120（42.50%）**，V3 **45/120（37.50%）**，差值 −5 个百分点；McNemar 精确双侧 `p=0.238`，近似配对 95% 区间为 −11.9 至 +1.9 个百分点。V3 没有证明优于单 Agent，但 5 个百分点差距也不足以证明确定劣势。开发集优势未泛化，禁止继续使用本 holdout 调参或同版本重跑。完整事故与统计限制见 `docs/PHASE5B_HOLDOUT_REPORT.md` 和 `reports/phase5b_holdout_comparison.json`。

### 阶段 5C：结果分析与求职交付

- [x] 汇总规则流程、单 Agent、多 Agent 和恢复增强组；报告样本量、版本、重复次数、不确定性、收益与代价。
- [x] 编写失败分类、复现步骤、根因和回归证据，不因结果不符合预期而删除失败案例。
- [x] 完成最终 README、架构/评测图、演示脚本、`reports/summary.md` 和阶段 5 验收报告。

#### 5C 与阶段 5 完成记录（2026-11-22）

新增只读 `scripts.build_phase5c_report`，从冻结的开发集、保留集、逐次 CSV、可靠性结果和本地原始轨迹重算 120 对配对统计、延迟、117 对完整 usage 子集及失败双轴分类；输入 SHA256 和机器可读结果写入 `reports/phase5c_analysis.json`。四组只按证据边界汇总：规则流程 10 个自建场景、单 Agent 120 次、V3 120 次、恢复增强 `REL-008` 1 次；没有把不可比证据伪装成四臂排名。

最终结论保持不利结果：单 Agent **51/120（42.50%）**，V3 **45/120（37.50%）**，配对差值 −5.00 个百分点，近似 95% 区间 −11.9 至 +1.9，McNemar 精确双侧 `p=0.238`；开发集优势未泛化。可靠性 **10/10** 只代表每场景一次的确定性断言通过，不称为 100% 生产可靠率。

验收实测：5C 专项 **5 passed**；带现有 PostgreSQL 16 容器与随机隔离 schema 的完整后端 **269 passed、0 failed、0 skipped（101.68s）**；Ruff 通过；报告 `--check` 与只读演示通过；测试后 `phase*` schema 残留 **0**。首次受限沙箱运行卡在 asyncio loopback socket；沙箱外未设置 `TEST_DATABASE_URL` 的诊断运行得到 **254 passed、3 failed、12 skipped**，3 个失败均为测试明确拒绝缺失数据库配置。设置现有本地数据库连接后完整重跑全通过。5C 外部 LLM 调用 **0**、holdout 重跑 **0**、业务 API 变更 **0**。详见 `docs/PHASE5_REPORT.md` 和 `reports/summary.md`。

## 阶段 5.5：商家知识库管理（2026-11-23）

- [x] 新增服务端绑定商家身份的知识文档、生命周期审计和草稿/发布/归档状态；客户端不能提交 `merchant_id`。
- [x] 商家后台新增知识库工作区，支持物流、FAQ、商品说明、服务公告的 Markdown 录入、编辑草稿、发布、撤下和检索预览。
- [x] 发布内容复用 H2/H3 聚合切分和现有 PostgreSQL `policy_documents` / `policy_chunks`；向量 Provider 可用时同步写入 pgvector。
- [x] 关键词与向量检索在数据库检索层按来源前缀隔离商家；商家说明不能成为取消/退货写操作的权威授权依据。
- [x] 顾客端识别无订单号的快递/通常发货地问题，返回商家发布内容和来源；具体订单承运商、运单号、实际发货仓仍读取业务数据库。
- [x] 完成 SQLite、FastAPI、真实 PostgreSQL/pgvector 随机 schema、租户隔离、不可变发布、归档撤下、前端交互和全量回归测试；更新 README、RAG 文档与阶段报告。

#### 阶段 5.5 完成记录

商家知识库形成可运行闭环：操作员创建的内容默认是草稿，发布后进入同一带来源 RAG 索引，已发布版本不可原地覆盖，归档后关键词与向量记录同时撤下；全部生命周期操作留有审计。当前演示认证绑定一个服务端配置的商家身份，但检索实现已按商家来源前缀过滤，测试证明两个商家不能互相召回内容。

真实 PostgreSQL/pgvector 测试在随机 `phase6_knowledge_*` schema 中使用 FastEmbed 多语言 MiniLM 384 维输出索引 3 个片段并完成向量查询，随后清理 schema。最终后端完整回归 **273 passed、0 failed、0 skipped（140.03s）**，Ruff 通过；前端 **8 files、44 passed**，ESLint、TypeScript 与生产构建通过。外部 LLM 调用 **0**。详见 `docs/PHASE5_5_REPORT.md`。

## 阶段 5.6：顾客修改收货地址（实现完成，待人工验收）

- [x] 将既有确定性地址修改规则接入顾客多 Agent 会话，支持意图识别、多轮补充和订单线程绑定。
- [x] 顾客只需提供国家、省/州、城市和详细地址，地址补充可选，不要求邮编；支持常见中国地址和带字段标签的输入。
- [x] 地址写入复用具体方案、客户明确确认、执行前订单版本与状态重检、事务、幂等键及审计日志。
- [x] 顾客确认面板展示中文新地址，成功结果明确显示“收货地址已修改”。
- [ ] 按用户要求本轮不运行自动化测试；由用户在浏览器手动验证后补记结果并完成本阶段验收。

建议人工路径：从一笔本人 `pending` 订单打开客服，发送“把收货地址修改为广东省深圳市南山区示例路 1 号”，核对待确认面板；确认前订单地址应不变，回复“确认”后刷新订单，地址应更新。再用非 `pending` 订单验证服务端拒绝写入。

## 可选阶段 6：模型微调（不阻塞主项目）

- [ ] 仅从允许的训练集及有来源的成功轨迹构造 SFT/LoRA 数据。
- [ ] 隔离测试集，去除评分答案、敏感字段；记录许可证与数据谱系。
- [ ] 与未微调模型在统一测试下对比，并报告成本和效果。
