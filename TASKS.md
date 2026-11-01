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

## 阶段 2：多 Agent 与策略检索

- [ ] 用 LangGraph 实现 Triage、Order、Policy、Resolution 四个专业节点，以及确定性 Guard/Executor（可从 2 个 Agent 起步再扩展）。
- [ ] 为 Agent 设置独立工具白名单；跨节点传递结构化 State，不传递完整用户数据库。
- [ ] Policy Agent v1 直接引用 `policy.md` 相关标题段落；记录证据来源。
- [ ] 新增业务FAQ/商品手册文档集，再引入 pgvector Embedding检索，做RAG召回测试。
- [ ] 记录 trace_id、节点耗时、工具调用、Token使用情况（无统计则标为缺失）。
- [ ] 证明相同业务案例在单 Agent 与多 Agent 均能运行。

**验收：** 至少查询、取消、退货三种端到端场景；检索可溯源；无未经授权的数据写入。

## 阶段 3：工单、持久化与人工接管

- [ ] 建立 `tickets`、`conversations`、`messages`、`operation_requests`、`approvals`、`audit_events` 表。
- [ ] 接入 LangGraph checkpointer；跨请求恢复会话、处理中任务及等待确认状态。
- [ ] 为写操作实现幂等键、唯一约束、事务与失败补偿/重试方案。
- [ ] 实现人工接管API；对不支持/高风险任务创建工单而非假装已处理。
- [ ] 注入异常：超时、API重复请求、进程在确认后中断、订单状态变化。

**验收：** 可以复现故障并稳定恢复；重复请求只产生一次业务变更。

## 阶段 4：前端与管理后台

- [ ] React 用户聊天页：消息、业务操作确认、订单卡片、错误展示。
- [ ] 管理后台：工单列表、详情、人工审批/接管、审计日志。
- [ ] 开发者页：Agent轨迹、工具调用、耗时、失败定位。
- [ ] Docker Compose 启动服务；附种子数据和演示账户说明。

**验收：** 浏览器端完成查询 → 取消/退货 → 审计/人工接管的完整演示。

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
