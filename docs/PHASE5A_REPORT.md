# 阶段 5A：评测框架、数据冻结与异常集

执行日期：2026-11-18（Asia/Shanghai）

## 结论

阶段 5A 已完成。仓库现在具有严格、可校验的官方评测 manifest、自建可靠性 manifest、统一实验配置和无密钥准备/烟测入口。该结论只表示评测输入和安全异常集准备完成，不表示单 Agent 或多 Agent 已完成正式评测，也不表示多 Agent 更优。

## 官方数据边界

官方 τ-bench Retail 继续固定在 commit `da0835f6c67baef58bdda18f2a3b037dfb3a1754`，并校验 `db.json`、`policy.md`、`tasks.json`、`split_tasks.json` 的既有 SHA256。`phase5_official_manifest.json` 包含：

- 开发集：既有 10 项 train 样本 `0,1,6,7,8,10,11,13,14,15`。
- 保留集：官方完整 test split，共 40 个任务 ID。
- 开发集与保留集交集为 0。
- 5A 只校验 `tasks.json` 文件字节哈希，不解析或向 Agent 暴露任务正文、参考动作和评分条件。
- 保留集首次允许计分的阶段声明为 5B，5A 执行次数为 0。

上述约束减少评测污染，但不能阻止拥有仓库文件系统权限的人手工打开原始文件；因此报告的是代码路径边界，而不是无法绕过的访问控制。

## 自建可靠性集

`reliability_scenarios_v1.json` 定义 10 个 ServiceFlow 自编场景：身份未核验、跨顾客访问、未确认写入、错误订单状态、确认绑定被篡改、重复提交、执行前状态变化、暂时超时恢复、任意支付退款请求、恶意政策文档注入。

每个场景至少绑定一个真实 pytest 节点。烟测共执行 11 个测试实例，因为“非待处理订单取消”节点包含两个参数化状态。自建 manifest 明确标注不含官方任务正文、不得计入官方 τ-bench 分数。

## 固定配置

`reports/eval_config.json` 固定了阶段 5B 的候选公平条件：

- Provider：OpenAI-compatible；产品模型 `deepseek-v4-flash`，官方适配器别名 `deepseek-flash`，用户模拟器 `deepseek/deepseek-flash`。
- temperature 0；Provider 模型 seed 不可用，记为 `null`；任务 seed 42。
- 每项 3 次，最大 40 步、6 次工具预算、单并发。
- 对照组为规则流程、受控单 Agent、多 Agent、恢复增强多 Agent；规则与恢复增强组只在适用的自建轨道比较。
- 模型价格不在 5A 硬编码，必须在正式运行日期记录实际公开价格和账单/估算口径。

5B 仍需实现统一执行器来强制这些预算。配置存在不等于预算已经在正式实验中执行。

## 实现与验证

新增 `app.evaluation` Pydantic 模型和准备逻辑，验证：

- manifest 自身 SHA256；
- 上游原始文件 SHA256；
- 开发/保留集合互斥；
- 保留集等于官方 test split；
- 自建场景引用的测试文件和函数真实存在；
- 烟测不依赖 PostgreSQL；
- 官方与自建结果目录分离。

实际命令与结果：

| 命令 | 结果 |
| --- | --- |
| `.\.venv_tau\Scripts\python.exe -m scripts.prepare_phase5a --run-smoke` | 10 类场景，**11 passed in 4.95s**；外部 LLM 0；保留集 0；正式分数 0 |
| `.\.venv_tau\Scripts\python.exe -m pytest ...`，真实 PostgreSQL 随机 schema | **239 passed、0 failed、0 skipped，69.26s** |
| `.\.venv_tau\Scripts\python.exe -m ruff check backend scripts tests` | All checks passed |

本轮没有修改前端，因此没有重复运行前端测试。Compose 的 db、api、frontend 在验收时均为 healthy。

## 失败记录与修复

首次烟测复用了固定的 pytest `basetemp`。此前被中断的 Windows 测试进程留下一个仍被占用的 SQLite 文件，pytest 清理目录时返回 `WinError 32`，导致 1 passed、10 setup errors。错误不是业务断言失败。

烟测入口现改为每次创建唯一 `basetemp`，并在失败报告中保存最后 40 行精简诊断。修订后同一 10 类场景全部通过。完整 pytest 在受限进程内还会因 Windows asyncio 本地 socketpair 创建受阻而卡住，因此最终完整回归在获准的非受限本机进程执行；测试内容、数据库和 Provider 配置未改变，外部模型仍被禁用。

## 未完成项

- 单 Agent 与多 Agent 尚未接入统一的阶段 5 正式运行器。
- 没有运行官方保留集，也没有生成 `results.csv`、成功率、违规率、延迟或成本结论。
- 3 次重复、工具预算和四个对照组只是冻结配置，仍需 5B 执行器强制落实。
- 最终架构图、失败案例集、结果摘要和求职演示属于 5C。

下一步只能进入阶段 5B，不应把本报告中的 11 passed 当作模型效果成绩。
