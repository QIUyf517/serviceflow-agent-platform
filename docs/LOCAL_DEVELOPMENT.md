# ServiceFlow 本地开发指南

## 前置条件

- Python 3.12
- Docker Desktop 与 Docker Compose
- Node.js 20+（仅前端开发、测试或重新生成截图时需要）

所有命令默认在仓库根目录执行。Windows 示例使用 PowerShell。

## 首次启动

1. 复制配置模板并替换 `<local-demo-database-password>`、`<local-demo-operator-token>`。不要提交生成的文件。

   ```powershell
   Copy-Item .env.example .env.phase4
   ```

2. 下载固定 commit 的最小 τ-bench Retail 文件。脚本会验证 JSON 和 SHA256，已有目录只校验、不覆盖。

   ```powershell
   python -m scripts.fetch_tau_retail
   ```

3. 启动 PostgreSQL，导入模拟快照，再启动 API 与前端。

   ```powershell
   docker compose config
   docker compose up -d --build db
   docker compose --profile tools run --rm seed
   docker compose up -d --build api frontend
   docker compose ps
   ```

普通 `docker compose up` 不会自动复位数据库。同一来源重复 seed 是幂等的；只有明确接受丢弃本地业务修改时才使用种子脚本的 `--reset` 参数。

## 本地入口

| 页面 | 地址 |
|---|---|
| 模拟商城与顾客客服 | <http://127.0.0.1:5173/store> |
| 管理后台 | <http://127.0.0.1:5173/admin> |
| 开发者追踪 | <http://127.0.0.1:5173/developer> |
| OpenAPI | <http://127.0.0.1:8000/docs> |

本地模拟账户来自下载的固定业务快照。不要把账户邮箱、姓名、邮编、地址或订单内容复制到 README、Issue、截图或提交记录。

## 最小 API 流程

创建会话：

```http
POST /api/v1/sessions
```

使用模拟邮箱核验；邮箱必须来自用户本次明确提供的输入：

```http
POST /api/v1/sessions/<session-id>/verify
Content-Type: application/json

{"email":"<local-simulated-account-email>"}
```

读取本人订单：

```http
GET /api/v1/orders
X-Session-Id: <verified-session-id>
```

请求取消时只生成待确认提案：

```http
POST /api/v1/multi-agent/chat
X-Session-Id: <verified-session-id>
Content-Type: application/json

{"message":"这个订单不要了","order_id":"<owned-order-id>"}
```

## 后端开发与验证

仓库保留锁定依赖文件；现有 Windows 开发环境使用 `.venv_tau`。新环境可创建 Python 3.12 虚拟环境并安装后端开发依赖，然后设置测试数据库：

```powershell
python -m venv .venv_tau
.\.venv_tau\Scripts\python.exe -m pip install -r requirements-dev.lock
$env:TEST_DATABASE_URL = 'postgresql+psycopg://serviceflow:<password>@127.0.0.1:5432/serviceflow_demo'
.\.venv_tau\Scripts\python.exe -m pytest -q -rs -p no:cacheprovider --basetemp=.tmp/pytest-full
.\.venv_tau\Scripts\python.exe -m ruff check backend scripts tests
```

PostgreSQL 测试使用随机隔离 schema 并在结束后清理。没有 `TEST_DATABASE_URL` 时，不能把跳过的数据库测试报告成完整验收。

## 前端验证

```powershell
Set-Location frontend
npm ci
npm run lint
npm run typecheck
npm run test -- --run
npm run build
npm run test:e2e
Set-Location ..
```

真实浏览器 E2E 会启动隔离的 FastAPI 和 PostgreSQL schema，注入合成测试数据，结束后清理。

## 重新生成作品集截图

先确保本地 `/store` 正常运行，再执行：

```powershell
Set-Location frontend
npm run capture:portfolio
Set-Location ..
```

脚本只截取公开商品目录和商品详情，不登录模拟顾客账户。

## 停止与清理

保留数据库卷：

```powershell
docker compose down
```

删除本项目 Compose 创建的数据库卷（不可恢复）：

```powershell
docker compose down --volumes
```

不要对不确定来源的 Docker volume 或非演示数据库执行删除、复位操作。
