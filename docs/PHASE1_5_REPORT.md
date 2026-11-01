# 阶段 1.5：真实 LLM 单 Agent 与 τ-bench 评估接入

执行日期：2026-11-01（Asia/Shanghai）。本轮仅覆盖阶段 1.5，未实施多 Agent。

## 代码与安全边界

- 阶段 1 原代码先经 26 项测试核对，检查 Git 忽略项和敏感文件后建立本地提交 `94c1c492611e8da53bbad7e115569ef1281b98b7`；未推送。
- 保留 Mock 模式。真实模式新增可配置 OpenAI 兼容 Chat Completions Provider，并以 LangGraph 执行单 Agent 工具循环。当前从被 Git 忽略的 `.env` 读取 DeepSeek 密钥，仓库没有密钥值。
- 客户身份、订单归属、政策校验、明确确认、幂等和事务写入仍由确定性业务服务执行。Agent 只能调用结构化工具。确认要携带提案 ID；确认时重新读取业务状态。对话消息和工具轨迹存 PostgreSQL，按会话权限读取。
- 适配器按官方 `HalfDuplexAgent` 接口接入原版文本环境；直接使用上游的政策、工具、用户模拟器、任务和评分器。任务参考动作、断言和评分条件不传给 Agent。

## 固定数据与运行方式

上游仓库：`sierra-research/tau2-bench`，commit `da0835f6c67baef58bdda18f2a3b037dfb3a1754`。运行入口每次核对 Git HEAD 和原始 `db.json`、`policy.md`、`tasks.json`、`split_tasks.json` 的 SHA256；项目 `data/raw/tau2/<commit>/manifest.json` 保留文件来源、获取日期和全部哈希。官方仓库置于被忽略的 `vendor/tau2-bench`，官方环境与本项目 PostgreSQL 物理隔离。

官方实验配置位于 `reports/tau2_smoke_config.json` 和 `reports/tau2_baseline_config.json`：Retail `train`，固定按官方顺序选出前 10 个无需 `communicate_info` 语义裁判的原始任务，ID 为 `0,1,6,7,8,10,11,13,14,15`；烟测取 `0,1`。Agent 为 `deepseek-flash`，官方用户模拟器为 `deepseek/deepseek-flash`，temperature 0，seed 42，1 次重复，最大 40 步，单并发。DeepSeek 不支持的模型级随机 seed 记为 `null`；随机性仍可能造成重跑差异。上游默认评分器未改。任务样本因缺少上游默认 OpenAI 语义裁判密钥而缩小，不能代表完整 Retail 分数，也不能与官方排行榜直接比较。

产品侧脚本从固定公开 `db.json` 导入一次性 PostgreSQL schema，结束删除。所有验证数据来自公开 Retail 快照；正式演示表未读写。产品报告与官方报告分别保存在被忽略的 `reports/raw/product_live/` 和 `reports/raw/official/`，不会把客户衍生数据提交 Git。

## A. 产品 PostgreSQL + 业务 API 基线

真实 DeepSeek 运行四项自然语言场景：订单查询、待处理订单取消、待处理订单地址修改、已交付订单退货。每项先由邮箱核验身份；查询需调用订单工具，三项写入均先提出含参数的操作摘要、得到明确 `yes` 和提案 ID，再由业务服务写入并从 PostgreSQL 复查状态。4/4 通过；该结果只证明这四个被选案例，不是总体成功率。

| 指标 | 实测 |
|---|---:|
| 场景成功率 | 4/4（100%，1 次） |
| 工具调用 | 8 次（含 4 次身份查询） |
| 平均 / P95 端到端耗时 | 3.936 / 5.358 秒 |
| Token | 输入 21,395；输出 815；总 22,210 |
| DeepSeek API 费用 | 约 $0.000898（估算，非账单） |
| 已观测失败类型 | 无 |
| 自动化业务违规率 | 未建立独立裁判，记为未知；测试断言覆盖确认及最终状态 |

费用按 [DeepSeek 官方价格表](https://api-docs.deepseek.com/quick_start/pricing/) 的非高峰缓存命中输入 $0.003、缓存未命中输入 $0.15、输出 $0.60 / 百万 Token 与 API usage 估算。价格、计费时段和账单可能变化，不能视为真实扣费金额。产品逐场景轨迹和 usage 保存在 `reports/raw/product_live/phase15.json`。

## B. 官方 τ-bench Retail 原始文本环境

烟测真实运行 2 项：1/2 通过。任务 1 的官方 reward=1，包含身份/订单/商品查询及换货工具写入，官方 DB 和动作检查均通过；任务 0 已调用换货工具，但达到 40 步限制，官方 reward=0。保留该失败轨迹，不将已执行工具等同于任务完成。烟测结果路径：`reports/raw/official/smoke/summary.json`；上游原始轨迹在忽略目录 `vendor/tau2-bench/data/simulations/`。

同一固定配置重新运行 10 项样本，**10/10 获官方 reward=1**；样本量小、只跑 1 次，不能推断完整 Retail 成功率。烟测与基线有两个重叠任务，它们是两次独立的模拟运行，不能合并成 12 个独立任务。尤其任务 0 在烟测中 40 步耗尽，在基线重跑时通过且耗时 177.19 秒，显示模型和用户模拟器仍有变异与长尾延迟。

| 指标 | 10 项固定基线实测 |
|---|---:|
| 官方任务成功率 | 10/10（100%，1 次） |
| 工具调用 | 58 次 |
| 平均 / P95 任务耗时 | 40.619 / 177.189 秒 |
| Agent Token | 输入 792,693；输出 14,619；总 807,312 |
| Agent API 费用 | 约 $0.018091（按 DeepSeek 公开非高峰价估算） |
| 官方用户模拟器费用 | $0.009823（上游运行对象报告） |
| 合计 | 约 $0.027914；估计值与报告值相加，非账单 |
| Guard 拒绝 | 4 次，均未放行被拒绝的调用 |
| 任务失败类型 | 本次 10 项无；烟测任务 0 为 `max_steps` |
| 独立业务违规率 | 未评定；上游 10 项 DB 匹配均通过，不等于已通过所有安全审计 |

报告 `reports/raw/official/baseline/summary.json` 保留逐任务 reward、耗时、工具次数、Token、费用和终止原因；上游原始 `results.json` 含逐轮工具轨迹。典型成功例为基线任务 `0`（换货，官方 DB/动作检查通过），失败例为烟测任务 `0`（工具已执行但超步，reward=0）。官方评估的用户模拟器、环境和评分均不同于产品四场景，两个成功率不能合并。按同一保存路径再次运行会恢复既有官方结果；增加 `--run-id <标识>` 可保存新的独立重复实验。

## 验证与限制

- `.venv_tau/Scripts/python -m pytest -q -p no:cacheprovider` 配合 `TEST_DATABASE_URL`：**35 passed**，含保留的阶段 1 测试、Mock/脚本化 Provider 测试、真实 PostgreSQL 临时 schema 测试、官方适配器在官方环境上的测试；测试没有调用付费模型。
- `.venv312/Scripts/python -m ruff check backend scripts tests`：通过。
- 真实 DeepSeek 与官方烟测已运行；DeepSeek 使用 `.env` 中现有密钥。其他 Provider 的真实网络运行未执行。
- API 聊天与轨迹读取的会话权限，以及真实 Provider 分支，已有脚本化自动测试；付费真实模型主要通过 `live_chat` 入口和隔离库验证，没有将正式演示表用于写入测试。
- 身份核验使用 Retail 模拟邮箱或姓名+邮编，不能视为生产级客户认证。官方默认评分未单独提供业务违规裁判，违规指标保留未知。

启动、API 示例和复现命令见 [README](../README.md)。
