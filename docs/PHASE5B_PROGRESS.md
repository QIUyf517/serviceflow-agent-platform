# 阶段 5B 进度报告：公平对照与指标采集

执行日期：2026-11-18 至 2026-11-20（Asia/Shanghai）

## 结论

阶段 5B 已完成验收。开发集结果为单 Agent 22/30、多 Agent v1 8/30、v2 15/30、v3 24/30；冻结后执行 test 保留集 40 项 × 3 次 × 2 架构共 240 次，单 Agent **51/120（42.50%）**，V3 **45/120（37.50%）**。配对差值为 −5 个百分点，McNemar 精确双侧 `p=0.238`，近似 95% 区间为 −11.9 至 +1.9 个百分点。V3 没有证明优于单 Agent，但差距也不足以证明确定劣势。因没有 OpenAI 密钥，语义评分统一使用 DeepSeek 自定义 Judge，结果不具备官方默认分数资格。本 holdout 已冻结，禁止继续用于 V3 调参或同版本重跑。

## 已完成

- 单 Agent 与多 Agent 都注册到固定上游 τ-bench Retail 文本接口。
- 两者使用相同 DeepSeek 模型、原版工具库存、共享确定性 Guard、任务、3 次重复、40 步、6 次工具调用、1024 输出 token、120000 累计 token 和单并发。
- 多 Agent 使用确定性 Supervisor 在身份、订单、政策、解决方案和人工转交角色间路由；角色白名单只缩小当轮工具可见范围，所有写动作仍经过共享身份、订单归属和明确确认 Guard。
- `reports/results.csv` 使用固定 schema；相同运行键可安全重跑替换，不删除其他轨道和失败记录。
- 官方任务自定义 Judge 轨迹与自建原始证据分别使用 `reports/raw/official_tasks_custom_judge/phase5` 和 `reports/raw/reliability/phase5`，且均被 Git 忽略。

## 已运行结果

| 轨道 | 样本 | 结果 | 外部 LLM | 官方分数 |
| --- | ---: | --- | ---: | --- |
| ServiceFlow 自建可靠性 | 10 类 | 10/10 通过 | 0 | 否 |
| τ-bench train 初始开发集 | 10 × 3 × 2 = 60 次 | 单 Agent 22/30，多 Agent v1 8/30 | DeepSeek | 自定义 Judge，非官方默认分数 |
| τ-bench train v2 复评 | 10 × 3 = 30 次 | 多 Agent v2 15/30 | DeepSeek | 自定义 Judge，非官方默认分数 |
| τ-bench train v3 复评 | 10 × 3 = 30 次 | 多 Agent v3 24/30 | DeepSeek | 自定义 Judge，非官方默认分数 |
| 阶段 5B 最终完整回归 | 264 项完整测试 | 264/264 通过 | 0 | 工程回归，不是模型分数 |
| τ-bench test 保留集 | 40 × 3 × 2 = 240 次 | 单 Agent 51/120，V3 45/120 | DeepSeek | 自定义 Judge，非官方默认分数 |

可靠性结果的每个指标值由 manifest 绑定的 pytest 断言支持，不是从自然语言日志猜测。墙钟延迟是真实子进程耗时；因为该轨道强制 Mock Provider，模型 token 和成本都为 0。这些数字只能证明工程安全断言通过，不能代替模型基准效果。

阶段 5B 最终完整后端与真实 PostgreSQL 随机 schema 回归为 **264 passed、0 failed、0 skipped（95.64s）**；`ruff check backend scripts tests` 通过。历史 245、253 项回归分别是 V3 付费复评前和单订单边界冻结时的证据，最终验收以本次 264 项为准。完整测试过程中的中间失败与处理见 `docs/PHASE5B_V3_FREEZE_REPORT.md`。

## 开发集 A/B 结果

两臂均使用 10 个相同任务、每任务 3 次、相同随机种子、DeepSeek Flash、temperature 0、最多 40 步、6 次工具调用和单并发。开发任务不含 `communicate_info`，本次没有实际调用语义 Judge；`official_score_eligible=false` 仍保持不变。

| 指标 | 单 Agent | 多 Agent | 多 Agent - 单 Agent |
| --- | ---: | ---: | ---: |
| 成功次数 / 30 | 22 | 8 | -14 |
| 成功率 | 73.33% | 26.67% | -46.67 个百分点 |
| 平均延迟 | 25.53s | 26.30s | +0.77s |
| P95 延迟 | 36.32s | 35.98s | -0.35s |
| 工具调用 | 161 | 161 | 0 |
| Guard 拒绝 | 22 | 47 | +25 |
| 记录内保守估算成本 | $0.2365 | $0.2692 | +$0.0328 |

当前事实不支持“多 Agent 优于单 Agent”；相反，当前多 Agent 在同一开发集上明显更差。上游动作统计显示多 Agent 读动作正确率 97.7%，但写动作正确率仅 18.8%；单 Agent 分别为 89.7% 和 86.2%。轨迹检查确认，22 个多 Agent 失败中至少 7 个出现“用户明确确认后，写调用仍落到只读角色并被角色白名单拒绝”；成功样本中也有 1 个先出现同类拒绝、后续重试才成功。这证明确定性 Guard 在安全停止，但 Supervisor/角色上下文没有稳定保存待执行意图。

## 多 Agent v2 复评

v2 使用相同 10 项任务、3 次重复、模型、种子、步数和工具预算，只修改确认后的角色保持逻辑。结果从 **8/30（26.67%）提升到 15/30（50.00%）**；读动作由 97.7% 提升到 98.2%，写动作由 18.8% 提升到 55.6%，Guard 拒绝由 47 降到 38。用户提前停止失败由 21 降到 10，但最大步数失败由 1 增到 5。

这证明 v2 修复有效，但没有完全解决状态传递：仍有 5 个失败样本出现“明确确认后写调用落到错误角色”，通常是中间补充商品或支付方式后，路由上下文再次退回只读订单角色。部分复杂任务还因重复摘要和确认达到最大步数。v2 仍比单 Agent 少 7 个成功样本（低 23.33 个百分点），不能冻结或进入保留集。

用户为 v2 复评批准 10 元预算，执行上限按中国银行运行时参考牌价折为 $1.40（约 ¥9.36）。已记录 token 的 DeepSeek 峰值保守估算为 **$0.2656（约 ¥1.77）**；一次 `model_request_failed` 自动重试的失败请求 token 未完整持久化，实际费用必须以 Provider 账单为准。

## 多 Agent v3 实现与开发集复评

v3 不训练模型，也不放宽 Guard，而是在 τ-bench 会话状态中增加服务端拥有的写工作流：`idle → gathering → awaiting_confirmation → executing → post_execution/blocked`。工作流保存售后意图、订单号、具体工具名、完整参数、SHA-256 提案指纹和已完成写次数。只要工作流未结束，普通补充消息继续路由至解决方案角色，不再根据最新一句话退回只读订单角色；人工转交和政策咨询仍可显式覆盖当前路由。

模型在参数齐全时被要求直接提出工具调用，适配器拦截调用并展示准确摘要。确认只对当前指纹有效；参数发生任何变化都会使旧确认失效。明确拒绝会清空工作流，成功或失败的工具结果由确定性代码推进阶段，不依赖模型声称“已完成”。专项测试覆盖初始写意图跨身份核验、PayPal 等普通补充消息、提案篡改、确认绑定和流程中止。

当前边界：该工作流存在于 τ-bench 对话状态中，没有为商城业务库新增表，也没有实现跨进程恢复。付费运行前的本地实现验证没有调用外部模型；随后在相同 10 项开发任务、3 次重复和相同模型/预算下完成 30 次复评。完整实现证据见 `reports/phase5b_v3_implementation.json`。

v3 得到 **24/30（80.00%）**，比 v2 的 15/30 高 9 个成功样本（+30 个百分点），比未修改的单 Agent 22/30 高 2 个（+6.67 个百分点）。平均延迟 23.77s、P95 32.43s；读动作 127/135（94.1%），写动作 27/33（81.8%）。Guard 拒绝由 v2 的 38 次降为 0，轨迹中“明确确认后落到错误角色”的固定报错由 5 个失败样本降为 0，说明 v3 针对的路由状态缺陷已被修复。

但 80% 不能等同于所有业务形态都稳定通过。三轮分别成功 9/10、6/10、9/10，Pass³ 只有 60%。6 个失败均为 `user_stop`，没有最大步数失败。逐任务核查确认：任务 11 要求一个会话退两笔订单，3 个失败均为跨订单批处理；任务 14 同样要求两笔订单，其中 1 个失败属于相同范围；任务 6 和 15 各有一轮选择错误商品/订单，最终写动作未完成，仍是真实的适用范围缺陷。

## 单订单线程边界与冻结

产品已经在阶段 4.5D 使用服务端 `support_threads` 隔离订单，本轮进一步固化写边界：订单线程提到其他订单时返回 `order_scope_mismatch`；通用咨询线程提出取消、退货、换货或修改时返回 `order_thread_required`。两类响应均不创建执行请求、不调用业务工具、不改变订单，并把 `task_status` 与 `consultation_route` 持久化到消息元数据。若跨订单改意图前存在未执行提案，服务端将其标记为 `superseded`，避免后续误确认。

同一订单内多个商品不属于跨订单批处理。新增测试验证两件商品绑定一份具体退货提案、一次客户确认和一次事务执行，审计中只有一条 `execution_succeeded`。边界冻结当时完整回归为 253 项；加入预算、Judge 与恢复测试后的阶段 5B 最终完整回归为 **264 passed、0 failed、0 skipped**，Ruff 通过，外部 LLM 不参与本地回归。

开发集原始结果仍是 24/30，不删除失败。事后排除跨订单任务 11、14 后，产品适用范围描述值为 22/24（91.67%）；它不是预注册指标或官方分数，不能替换总体结果。基于明确产品边界和确定性安全回归，V3 现已冻结；后续任何 Prompt、路由、Guard、线程或预算修改都必须建立新版本。冻结证据见 `docs/PHASE5B_V3_FREEZE_REPORT.md` 与 `reports/phase5b_v3_freeze.json`。

用户批准本轮 ¥5。按运行时中国银行美元卖出价参考值 6.6838 元/美元，将执行硬上限设为 $0.70（约 ¥4.68）。已持久化 token 按 DeepSeek 峰值保守价格估算：被测 Agent $0.1083、用户模拟器 $0.1212，合计 **$0.2294（约 ¥1.53）**；控制台未观察到请求失败重试，但准确费用仍必须以 Provider 账单为准。

记录完整的 60 次运行按 DeepSeek 官方峰值价格、缓存命中/未命中分类估算为 **$0.5057**。首次单 Agent 运行因 Windows GBK 无法输出 `✅`，同一任务被上游重试 4 次后停止；这部分 token 未持久化，费用必须查 Provider 账单，不能填 0。控制台已改成 UTF-8，随后 60 次正式运行均完成。总批准预算为 $0.70；记录内估算仍有 $0.1943，但实际余额需扣除上述未记录调用。

## 保留集完成与后续边界

固定上游版本默认使用 OpenAI Judge。本项目没有 OpenAI 密钥，经用户确认将 `communicate_info` 与 `nl_assertions` Judge 显式改为 `deepseek/deepseek-flash`，同时保留上游语义 Prompt 和结构化返回契约。预检只检查允许使用的 train 开发标准；保留集任务正文仅在获批付费运行时由上游执行器加载。

V3 保留集已经执行并冻结。下一步进入 5C，只能做结果分析、失败分类和求职交付；不能使用该保留集继续调参。共享 Guard 始终要求准确操作摘要和明确确认，后续工作不得通过减少安全校验来换取分数。若开发 V4，必须建立新的开发证据与独立未见评测集。

替换 Judge 模型确实改变了官方默认评分条件，因此执行器和结果固定标注 `tau2_semantic_prompt_deepseek_judge` 与 `official_score_eligible=false`，不能称为官方默认分数。τ-bench 自带的 agent/user cost 不含语义 Judge 账单，最终报告必须核对 DeepSeek 实际账单；无法获得的费用必须标为未知，不能填 0。

## 命令

无费用预检与自建可靠性测试：

```powershell
.\.venv_tau\Scripts\python.exe -m scripts.run_phase5b_official --split development
.\.venv_tau\Scripts\python.exe -m scripts.run_phase5b_official --split holdout
.\.venv_tau\Scripts\python.exe -m scripts.run_phase5b_reliability --run-id phase5b-initial
```

用户授权预算并配置 DeepSeek 密钥后，开发集按架构分别运行：

```powershell
.\.venv_tau\Scripts\python.exe -m scripts.run_phase5b_official --split development --run --architecture single_agent --approved-budget-usd <预算>
.\.venv_tau\Scripts\python.exe -m scripts.run_phase5b_official --split development --run --architecture multi_agent --approved-budget-usd <预算>
```

保留集命令额外要求 `--allow-holdout`。该命令必须等开发集结果检查和实现冻结后再执行，本报告不提供可直接复制的保留集付费命令，以降低误跑风险。
