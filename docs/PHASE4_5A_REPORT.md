# 阶段 4.5A：模拟商店与顾客身份验收报告

日期：2026-11-13

## 1. 范围与结论

本轮只完成 4.5A：中文模拟商城、商品目录/详情、购物车、事务化模拟下单、顾客身份与服务端 session 绑定、本人订单，以及从订单打开的智能客服对话框。没有开始 4.5B 内容安全与咨询分流，没有开始 4.5C 全量中文化与人工回复，也没有勾选阶段 4.5 收尾。

4.5A 三项验收全部通过：商品、订单和客服读取同一业务数据库；未核验不请求/不展示订单与个人资料；跨顾客订单查询在服务端返回安全 404；切换顾客会使用新 session 并重新核验。运行时没有静态商品数据、假 API 或外部 LLM 调用。

## 2. 实现闭环

### 后端与数据边界

- `GET /api/v1/products`：从 `products` 表返回排序后的商品摘要，包含价格范围、可用/全部规格数与选项名。
- `GET /api/v1/products/{pid}`：从同一表返回完整规格。
- `POST /api/v1/orders`：只接受规格 ID、数量和账户支付方式 ID；服务端从已核验 session、商品表和顾客表重读权威价格、可用性、地址和支付方式，在一个事务中创建订单并写入 `order_creations` 幂等审计。
- 下单不接受前端 `user_id`、价格或配送地址；未核验返回 403，规格不可用或礼品卡不足安全停止。同一幂等键和请求返回原订单，键与身份或内容冲突返回 409。
- 两个公开商品接口仍要求服务端存在的 session，但不要求顾客身份；它们不返回客户字段。
- `GET /users/me`、`GET /orders`、`GET /orders/{oid}` 继续要求已核验 session。订单归属从 `service_sessions.user_id` 取得，不接受前端 `user_id`。
- 已绑定 session 尝试使用另一顾客证据会返回 `identity_not_verified` 403；其他顾客查询非本人订单返回 `order_not_found` 404，不泄露订单是否存在。

### 前端

- `/store` 为主入口；`/` 重定向至 `/store`，旧 `/support` 保留兼容跳转。
- 商城采用中文电商的搜索、分类、商品卡片和侧栏购物车结构；去掉了商城上方重复的全局项目导航，商品详情改为打开即见的居中对话框，规格较多时只在对话框内部滚动，移动端呈现底部抽屉。详情内可把可用规格加入购物车。展示层确定性翻译固定快照的 50 个商品名、全部规格字段和实际规格值；商品 ID 和上游数据不变。
- 顾客专区在核验前只显示身份门，订单和顾客 Query 保持 disabled；核验后可结算并查看本人订单。每笔订单内有“联系商家客服”，点击打开绑定该订单上下文的页面内对话框。
- “切换模拟顾客”请求新 session，清除购物车、订单缓存、当前订单、对话、任务、结算/工单幂等键和内存 trace，再回到身份门。
- 响应式布局、语义标题、表格表头、键盘焦点和 reduced-motion 规则均保留。

## 3. API 示例

```http
POST /api/v1/sessions

HTTP/1.1 200
{"session_id":"<random-server-session>"}
```

```http
GET /api/v1/products
X-Session-Id: <random-server-session>

HTTP/1.1 200
[
  {
    "product_id":"9523456873",
    "name":"T-Shirt",
    "min_price":46.66,
    "max_price":54.84,
    "available_variants":10,
    "total_variants":12,
    "option_names":["color","material","size","style"]
  }
]
```

上述数值是固定上游快照中该商品的示例；运行时返回当前业务库内的实际值。

```http
GET /api/v1/orders
X-Session-Id: <unverified-session>

HTTP/1.1 403
{"error":{"code":"identity_required"}}
```

```http
POST /api/v1/orders
X-Session-Id: <verified-session>
Idempotency-Key: checkout-<unique-key>
Content-Type: application/json

{"items":[{"item_id":"9612497925","quantity":1}],"payment_method_id":"<account-method-id>"}

HTTP/1.1 200
{"order":{"order_id":"#W<generated>","status":"pending","items":[...]},"idempotent_replay":false,"created_at":<unix-time>}
```

## 4. 验收结果

| 检查 | 结果 |
|---|---|
| 完整后端 pytest（含真实 PostgreSQL 随机 schema） | 208 passed，0 failed，0 skipped |
| Ruff | 通过 |
| 前端 Vitest | 8 files，38 passed，0 failed |
| ESLint / TypeScript / 生产构建 | 全部通过 |
| Chromium + 真实 FastAPI + 真实 PostgreSQL | 7 passed，0 failed |
| E2E schema 清理 | 创建 1，清理 1，残留 0 |
| Docker Compose | db/api/frontend 均 healthy |
| 外部 LLM 调用 | 0 |

主要命令：

```powershell
$env:TEST_DATABASE_URL = '<isolated PostgreSQL demo URL>'
.venv_tau/Scripts/python -m pytest -q -rs -p no:cacheprovider
.venv_tau/Scripts/python -m ruff check backend scripts tests

Set-Location frontend
npm run lint
npm run typecheck
npm run test -- --run
npm run build
npm run test:e2e
```

## 5. 未完成项与边界

- 4.5B 的内容安全、FAQ/商品/订单分流、中文追问和咨询转人工尚未实现。
- 4.5C 的全部顾客文案中文化、商家新工单提醒与人工回复尚未实现。现有 Agent 回复仍可能包含英文技术文案，不应声称阶段 4.5 已完成。
- “切换顾客”通过换用新随机 session 实现隔离；旧 session 作为 bearer 凭据仍由服务端保留，本阶段没有实现账户系统级的注销/撤销机制。这是模拟登录的已知边界，不能当作生产 IAM。
