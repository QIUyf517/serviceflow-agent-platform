# 阶段 1 验收报告（2026-11-01）

## 实现与边界

依据固定上游 commit `da0835f6c67baef58bdda18f2a3b037dfb3a1754` 的 Retail `policy.md`、`tools.py`、`data_model.py` 和已导入的实际 JSON 字段开发。原始文件未修改。沿用 `users`、`products`、`orders` JSONB 模型；新增会话、操作提案、审计和聊天轨迹表。`seed --reset` 清理这些从属表后再恢复导入数据。

已实现邮箱或姓名+邮编模拟核验、单会话单客户绑定、本人资料/订单及商品查询。写业务包括 pending 取消、地址/支付/商品变体修改，以及 delivered 退货/换货。订单状态、商品归属/可用性、支付方式和余额由服务端检查；不支持任意金额退款。取消/支付修改写入**本地模拟支付历史及礼品卡余额**，不代表外部资金已到账。退货/换货只记录申请状态，不发送真实邮件。严格禁止 `pending (item modified)` 再取消或修改，符合阶段1安全规则；上游工具中部分地址/支付修改采用较宽松的“pending”匹配，正式官方适配器须另行对照。

写入需先产生含订单号、动作和参数的提案，15 分钟内用相同会话、提案 ID 明确确认。执行事务中锁定提案及订单，检查订单版本、重新运行规则，更新订单/客户 JSON、版本、审计。重复确认返回已存结果。数据库插入审计失败时全部回滚。错误采用固定代码，无客户字段写入错误文本。API 会话 ID 相当于本地 bearer 凭据，模拟身份核验不能用于生产环境。

LangGraph 单 Agent 基线有工具选择与执行节点，服务端只执行白名单工具。Mock Selector 支持有限的英文/中文演示语句，并不等同于真实 LLM 自然语言能力。工具选择器不能通过伪造调用绕过聊天确认词和提案 ID。轨迹表记录工具名、错误、耗时；当前模型 Token 数为 null。没有 LLM Key，真实模型质量、Token 和成本均未测试。阶段2多 Agent 未实现。

`scripts/eval_baseline.py` 校验官方任务 ID 并在临时 schema 重放固定原始业务快照，仅以外部输入的模拟消息运行一次 Mock；不把任务参考动作或评分条件传入 Agent。烟测输出调用数、耗时、Token 空值、错误类别和失败原因；`task_completed:null`、`scoring:not_run`。这**不是**官方 τ-bench 评测，尚缺用户模拟器、原版工具协议适配和官方评分。一次真实烟测：任务 ID `0`、Mock、1 次工具调用、14 ms、Token 未知、无工具错误；任务是否完成未评定。此数字只是一次本地烟测，不能用于成功率结论。

## 验证

- `.venv312/Scripts/python -m pytest -q -p no:cacheprovider`：**26 passed**，真实 PostgreSQL 测试未跳过；临时 schema 在结束时清理。测试覆盖身份隔离、非法订单、状态冲突、无确认、重复确认、到期/状态变化、审计失败回滚、退货/换货/修改、Agent 工具错误和 HTTP 闭环。
- `.venv312/Scripts/python -m ruff check backend scripts tests`：通过。
- Uvicorn 在 `127.0.0.1:8765` 启动成功；真实 HTTP `GET /api/v1/health` 返回 200 `{"status":"ok"}`，随后停止服务。
- `scripts.eval_baseline.run` 在 PostgreSQL 独立临时 schema 成功返回脱敏指标，未进行评分。

## 未完成与风险

真实 LLM Provider、完整官方测评适配与成绩未完成；Mock 的意图覆盖有限。尚无生产级登录、会话过期/撤销、并发限流、数据库迁移框架和外部支付/邮件集成；不能把本地演示业务当作生产服务。阶段1只实现运行轨迹和业务审计，跨进程长会话恢复、人工工单与多 Agent 属后续阶段。本阶段没有创建 Git 提交。
