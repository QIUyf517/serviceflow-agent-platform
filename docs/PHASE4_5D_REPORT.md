# 阶段 4.5D 报告：订单独立会话线程（串话修复）

日期：2026-11-15
范围：P0（阻断串话）→ 验收 → P1（正式订单会话模型）→ P2（界面调整）

## 1. 问题与根因

人工复核发现同一顾客的两笔订单会在商家后台混在同一个人工聊天窗口。

- 根因在服务端：`TicketService.detail()` 按 `session_id` 读取最近 20 条消息（`backend/app/ticketing.py`），
  一条会话包含这位顾客所有订单的对话。
- 前端另有一处放大问题：找不到订单工单时会退化为“任意未绑定工单”，把通用咨询工单显示在某笔订单窗口里。
- 检查结论：没有证据表明会串到其他顾客；已确认会在同一顾客不同订单之间串话，可能导致客服理解错订单。

## 2. 设计决策

1. 线程是隔离边界：`support_threads` 一行代表一次会话上下文，`kind='order'` 绑一笔订单，`kind='general'` 为该会话的通用咨询。
2. 线程只能由服务端解析：客户端只提交 `order_id`，服务端核验会话身份与订单归属后创建或恢复线程；客户端不能提交 `thread_id` 读取他人数据。
3. 不使用“从消息文字里搜索订单号”作为过滤依据：订单线程内提到其他订单会被确定性拒绝，提示用户从对应订单重新打开客服。
4. 状态隔离：`messages`、`tickets` 与 LangGraph 检查点都按线程落库；待确认请求只从本线程检查点恢复，切换线程不携带上一订单的确认状态。
5. `ticket_id` 仍表示该线程中的一次人工接管；同一订单重复“转人工”按线程幂等复用同一工单。
6. 旧数据不猜测：只根据工单已有的 `order_id`、消息的 `ticket_id` 绑定；无法判断的进入“通用咨询”。

## 3. 代码变更

### 数据模型与迁移

- `backend/app/database.py`：新增 `SupportThreadRow`；`MessageRow.thread_id`、`TicketRow.thread_id` 与索引；两条部分唯一索引保证
  `(session_id, order_id)` 与 `(session_id, order_id IS NULL)` 唯一。
- `backend/app/support_threads.py`：
  - `get_or_create_thread()`：统一线程创建入口，冲突时回落到已存在线程。
  - `SupportThreadService.resolve()`：核验会话；订单线程要求已核验身份且订单归属本顾客，否则 403/404。
  - `ensure_support_thread_schema()`：`create_all` 建新表、就地 `ALTER TABLE` 补列与索引，再执行回填；进程内按引擎缓存避免每请求重复迁移。
  - `_backfill_threads()`：回填并返回计数（`order_threads_created`、`general_threads_created`、`tickets_bound`、
    `tickets_with_order_conflict`、`messages_bound_to_ticket`、`messages_bound_to_general`）。
- `scripts/migrate_support_threads.py`：独立运行迁移并输出上述计数，便于人工复核。

### 工单与消息

- `TicketService.create()`：接受 `thread_id`，校验线程归属；线程绑定订单时强制使用该订单；未指定线程时按工单订单自动落到对应线程（无订单则通用线程）。
- `TicketService.detail()`：只读取本线程消息；新增 `thread` 投影与 `related_tickets`（同单历史、其他订单数量）。
- `customer_tickets()`：返回 `thread_id` 与 `thread_kind`。
- `customer_reply()` / `reply()`：写入的 `MessageRow` 带上工单线程。
- `ticket_idempotency_key()`：加入 `thread_id`，避免同一会话两笔订单的“转人工”互相幂等覆盖。
- `MessageStore.append/rows/langchain_messages/checkpoint_messages`：支持 `thread_id` 过滤与写入。

### Agent 状态

- `AgentState`：`new_agent_state()`/`restore_agent_state()` 接受 `thread_id`，检查点线程键不再等于会话 ID。
- `SessionStateStore.load()`：以线程键读取，同时校验会话 ID 与身份，防止跨会话恢复。
- `run_turn()` / `run_execution_turn()`：可传入 `thread_id`，消息读写、检查点与响应均按线程。
- `conversation.run_after_sales_conversation()`：接受服务端解析后的线程；待确认请求只从本线程检查点恢复；转人工工单绑定线程与订单；
  订单线程内的跨订单请求直接返回 `order_scope_mismatch`（中文说明）。
- `triage.ThreadScopedTriage`：把服务端线程订单绑定到分类结果，避免要求顾客在每条消息里重复订单号。

### API

- 新增 `POST /api/v1/support/threads`（`{"order_id": "..."}` 或 `{}`）。
- `POST /api/v1/multi-agent/chat` 接受 `order_id`，响应新增 `thread_id`、`thread_order_id`、`thread_kind`。
- `GET /api/v1/multi-agent/tasks/current?order_id=`、`GET /api/v1/customer/conversation?order_id=`。
- 旧接口（`/debug/plan`、cancel/return requests）统一按会话的通用线程解析，行为与升级前一致。

### 前端

- 顾客端：按订单解析线程；标题固定“正在咨询订单 #…”；切换订单即清空消息与确认面板；新增“通用咨询”入口；
  刷新后按上次打开的订单窗口恢复线程；工单只按 `thread_id` 过滤，删除未绑定工单兜底。
- 商家端：工单列表新增订单列（“通用咨询”显式标注）；案件卷宗顶部固定订单与线程说明；同单历史折叠，其他订单显示数量且默认不展开。

## 4. 迁移实测

本机演示库（真实 PostgreSQL 16，public schema）：

```
{"order_threads_created": 2, "general_threads_created": 8, "tickets_bound": 7,
 "tickets_with_order_conflict": 0, "messages_bound_to_ticket": 2, "messages_bound_to_general": 57}
```

重复运行输出全 0，说明迁移幂等。新增 PostgreSQL 测试会先删除线程列与索引构造“旧库”，再执行迁移并断言绑定结果与冲突计数。

## 5. 验证结果

| 项目 | 结果 |
| --- | --- |
| 后端 pytest（含真实 PostgreSQL 随机 schema） | 235 passed, 0 failed, 0 skipped |
| `ruff check backend scripts tests` | 通过 |
| 前端 vitest | 8 files, 43 passed |
| ESLint / TypeScript / 生产构建 | 通过 |
| Chromium + 真实 FastAPI + PostgreSQL | 11 passed |
| E2E 随机 schema 残留 | 0 |
| 外部 LLM 调用 | 0 |

新增测试：`tests/test_phase45d_threads.py`（7 项 API 隔离用例）、`tests/test_phase45d_postgres.py`（旧库升级与回填）、
`frontend/e2e/phase45d.spec.ts`（真实浏览器双订单隔离与刷新恢复）、前端单测“只显示当前订单会话”。

## 6. 验收标准对照

1. 同一顾客两个订单、两个聊天窗口完全隔离：`test_two_orders_get_distinct_threads_and_isolated_messages` + e2e 双订单用例。
2. 订单 A 的人工回复只出现在订单 A：`test_operator_console_and_customer_window_share_one_order_thread`。
3. 刷新后仍恢复正确订单线程：前端 `support_context` 提示 + 服务端线程解析，e2e 刷新断言。
4. 通用咨询不会自动进入订单线程：`test_general_consultation_never_enters_an_order_thread`。
5. 跨顾客访问继续返回 404：`test_cross_customer_thread_access_is_rejected`。
6. 切换线程不携带上一订单确认状态：`test_switching_threads_does_not_carry_a_pending_confirmation`。
7. 人工回复不能替代客户明确确认：`test_operator_reply_never_substitutes_customer_confirmation`（含内部审批）。

## 7. 已知边界

- 旧工单若创建前没有工单关联的聊天记录，只能进入“通用咨询”，不会出现在订单窗口；这是为避免错误绑定而接受的取舍。
- 检查点按线程隔离后，跨线程的“历史待确认请求”不会自动迁移；旧检查点仍按原会话线程键读取，升级后新对话进入新线程。
- 线程仅支持 `open`/`closed` 两种状态；关闭语义本轮未实现业务动作，仅保留字段。
- 迁移在服务启动时执行；大量历史数据的首次回填耗时会高于后续请求。
- 本报告中的测评数字均为本地实测，不构成官方 τ-bench 结论。
