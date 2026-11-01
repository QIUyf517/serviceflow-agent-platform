# 阶段 0 执行与测试记录

执行日期：2026-11-01（Asia/Shanghai）。最终结论：**阶段 0 已完成，真实 PostgreSQL 导入与一键验收通过，13 passed、0 skipped，ruff 通过。**

## 最终 PostgreSQL 验收

用户启动 Docker 后，已连接 Docker Engine 29.9.2，并执行 `docker compose up -d --wait db`，容器 healthy。实际数据库为 PostgreSQL 16.15（Debian 16.15-1.pgdg13+2），数据磁盘位于 `D:\DockerData\disk\docker_data.vhdx`。实际使用镜像摘要：`postgres@sha256:1beaa3084eee2676f20a9cd9928f0bf2c5bf674f8e49f81017912183d377c61c`。

在仓库根目录执行 `.venv312/Scripts/python -m scripts.phase0`，退出码 0；两个真实导入均输出 500 users、50 products、1000 orders；pytest 为 13 passed、0 skipped，ruff 为 All checks passed。随后单独执行 `scripts.seed_database --reset` 及普通重复导入，均输出相同行数并成功退出。

独立 SQL 核验显示三张业务表的嵌套字段均为 JSONB，行数与源数据一致，`phase0_*` 测试 schema 残留为 0。此前跳过的 PostgreSQL 测试现已实际运行：初次/重复导入和变更快照复位均通过。`data/manifest.json` 已生成并核验包含真实 commit 和导入数量。容器仅映射 `127.0.0.1:5432`，保留运行供后续使用。

本次测试出现上游 TestClient/httpx 弃用警告与 pytest 缓存写入权限警告，两者均未阻断断言或命令退出成功。本轮没有修改业务代码或开展阶段 1；尚无实现 Git 提交。以下保留初次环境阻塞及恢复过程作为历史记录，不代表当前验收状态。

后续环境更新：已按用户授权在 Windows 本机安装 Docker Desktop 4.97.0 至 `D:\Docker`，官方安装包保留在 `D:\Downloads\Docker\Docker Desktop Installer.exe`，数字签名为 Valid / Docker Inc。WSL 3.0.3 与 Docker 安装器均退出 0；WSL 明确要求重启，未自动重启。安装参数指定 `D:\DockerData` 为 WSL 数据根，首次启动后仍需确认实际路径。Docker CLI 29.9.2、Compose v5.6.1 可运行，项目 Compose 配置校验退出 0；引擎管道尚不可连接，数据库仍未验收。两个安装辅助 PowerShell 脚本已通过 AST 语法检查。安装日志和结果 JSON 位于 D 盘下载目录。重启并完成 Docker 首次启动后，再执行本文恢复步骤的数据库启动及验收命令。

## 环境与范围

最初规划文档位于工作区的 `ServiceFlow/` 子目录，阶段 0 初次实现也位于该目录。按用户要求，现已将项目文件、数据和本地开发环境统一整理至 Git 仓库根目录，移除原空子目录；外层 `.git/` 保留。开始时原目录只有规划文档，整个目录为 Git 未跟踪状态。已阅读 AGENTS、README、TASKS、CODEX_START_HERE 及 docs 原有四份文档。

初始 Python 3.11.4，未安装/未找到 uv、Docker、Compose、PostgreSQL 服务、psql/postgres 命令及默认安装目录。已创建本地 `.venv` 用于安装 uv 0.13.6，将 CPython 3.12.16 安装到 `.python/`，运行环境为 `.venv312/`。第一次创建运行环境时使用了错误的 Python 补丁版本路径而失败，核对实际下载路径后已纠正。初次普通网络访问官方 GitHub 失败，获准联网后固定版本和文件下载成功。

初次实施时尚未安装系统级 Docker 或 PostgreSQL，后续已安装 Docker 并完成上述容器数据库验收；未修改官方业务数据，未开发前端、LangGraph、LLM 或业务操作接口。

## 变更

- `backend/pyproject.toml`、`requirements-dev.lock`：Python 3.12 项目、FastAPI、Pydantic、SQLAlchemy/psycopg、pytest/ruff；本次 Windows 实测依赖锁定。
- `backend/app/main.py`：只有真实存活检查 `GET /api/v1/health`，200 `{"status":"ok"}`。
- `backend/app/retail.py`：Pydantic 导入契约、脱敏错误、双向订单归属与商品/变体引用校验。
- `backend/app/database.py`、`config.py`：PostgreSQL JSONB、外键、事务导入与快照幂等控制；SQLite 仅用于显式测试。
- `scripts/fetch_tau_retail.py`：完整 commit 固定、最小文件下载、本地干净源支持、暂存后发布与逐文件 SHA256；已有原始数据只核验不覆盖。
- `scripts/inspect_tau_retail.py`：无客户字段值的真实结构报告；`scripts/seed_database.py`：演示库导入/明确复位；`scripts/phase0.py`：一键验收入口。
- Compose、环境示例、忽略规则、基础目录、测试与操作文档。`frontend/` 仅占位。

## 初次实测结果（历史）

以下 `python` 均为 `.venv312/Scripts/python`。初次验证工作目录为原 `ServiceFlow/` 子目录；整理后应在 Git 仓库根目录执行相同命令。

| 命令 / 验证 | 结果 |
|---|---|
| `python -m scripts.fetch_tau_retail` | 成功，固定 commit `da0835f6c67baef58bdda18f2a3b037dfb3a1754`，8 个文件哈希校验成功 |
| `python -m scripts.inspect_tau_retail --output data/processed/structure_report.json` | 成功；500 用户、50 商品、1000 订单、591 变体、2978 订单商品条目 |
| `python -m pytest -q` | **12 passed, 1 skipped**；1 条上游 Starlette TestClient 对 httpx 的弃用警告，不影响断言 |
| `python -m ruff check backend scripts tests` | 通过；初次检查发现导入排序和长行，修复后复查 |
| `git check-ignore` | 真实原始数据、`.env`、Python 安装、虚拟环境均被忽略 |
| `python -m scripts.seed_database` | 失败，非零退出；`OperationalError`，未能连接可用 PostgreSQL |
| `python -m scripts.phase0` | 数据验证成功，在 PostgreSQL 导入处非零退出，未跳过失败继续宣布成功 |

12 项通过覆盖：存活接口；6 类错误结构/ID/归属/变体/类型/状态拒绝；合成数据幂等性、业务状态不被重复导入覆盖、显式复位及版本切换保护；注入插入失败后事务回滚；演示库名称保护及 PostgreSQL JSONB/FK DDL 编译；离线下载、重复获取、篡改检测、检查报告无隐私值；真实源数据 SQLite 初次/重复/复位导入行数一致。真实源集成测试若数据不存在会明确跳过，不会伪造结果。

跳过的是 PostgreSQL 真实源数据集成测试：未配置 `TEST_DATABASE_URL`。测试本身已实现，在独立临时 schema 验证初次导入、重复导入及变更快照复位；本次**没有执行**，不能作为 PostgreSQL 成功证据。SQLite 和 PostgreSQL DDL 编译均不能证明驱动、JSONB、事务锁在真实 PostgreSQL 上已正常运行。Compose 配置尚未经 Docker 执行验证。

原始版本目录的 `manifest.json` 已记录来源/commit/获取时间/大小/哈希。`data/manifest.json` 设计为数据库成功导入后才生成，因此当前未生成成功导入记录；不报告不存在的 PostgreSQL 行数。未创建 Git 提交，无实现提交 SHA。

## 恢复与重跑步骤（已执行通过）

目录整理复验：已在仓库根目录重建 `.venv312` 并从缓存恢复锁定依赖及后端 editable 安装，修复引导环境 `.venv`；原始数据只移动未修改，8 个文件哈希通过。pytest 仍为 12 passed、1 skipped，ruff 通过，Compose 配置校验退出 0。数据结构报告在新位置重新生成，数量与迁移前一致。PostgreSQL 实机验收状态未改变。

1. 安装并启动 Docker Desktop（启用 Linux containers），在 Git 仓库根目录比对/复制 `.env.example` 到 `.env`。若已有 `.env`，保留个人设置。
2. `docker compose up -d --wait db`；或提供可连接的独立 PostgreSQL 数据库 `serviceflow_demo`，在 `.env` 设置 `DATABASE_URL`。
3. `.venv312/Scripts/python -m scripts.phase0`。入口会将数据库配置传入 PostgreSQL 测试，要求真实导入和集成测试完成。
4. 如需仅补数据库测试：设置 `$env:TEST_DATABASE_URL` 为专用 `_demo` 数据库连接，再执行 `.venv312/Scripts/python -m pytest -q -m postgres`。
5. 本次已保存真实结果并勾选 TASKS 最后两项。下一阶段仍缺身份核验/隔离、业务查询、确定性政策、操作确认、幂等写入/审计及单 Agent 基线，等待用户后续阶段指令。
