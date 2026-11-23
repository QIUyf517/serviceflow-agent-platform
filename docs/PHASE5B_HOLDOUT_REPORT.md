# 阶段 5B：V3 与单 Agent 保留集对照报告

报告日期：2026-11-21（Asia/Shanghai）
执行完成：2026-11-20 16:06（Asia/Shanghai）

## 结论

阶段 5B 的保留集对照已经完成，但结果不支持“V3 优于单 Agent”。在相同 40 个 τ-bench Retail test 任务、每任务 3 次、相同种子、模型、温度、工具、Guard、步数和单并发条件下：

| 架构 | 成功 / 运行 | 成功率 |
| --- | ---: | ---: |
| 单 Agent | 51 / 120 | 42.50% |
| 多 Agent V3 | 45 / 120 | 37.50% |
| V3 − 单 Agent | −6 | −5.00 个百分点 |

配对结果为：双方都成功 39 次、仅单 Agent 成功 12 次、仅 V3 成功 6 次、双方都失败 63 次。McNemar 精确双侧检验 `p=0.238`；配对差值的近似 95% 区间为 −11.9 到 +1.9 个百分点。因此，V3 没有证明优于单 Agent，但本次样本也不足以把 5 个百分点差距解释为确定的劣势。

开发集结论没有泛化：单 Agent 从 73.33% 降到 42.50%，V3 从 80.00% 降到 37.50%，开发集上 V3 的 +6.67 个百分点优势在保留集反转为 −5.00 个百分点。V3 的路由修复仍有确定性回归证据，但不能再把开发集分数当作模型效果优势。

本结果使用官方任务和原始评分 Prompt，但语义 Judge 替换为 DeepSeek，因此 `official_score_eligible=false`，不能称为官方默认 τ-bench 分数。

## 固定条件

- 上游 commit：`da0835f6c67baef58bdda18f2a3b037dfb3a1754`
- 任务：test split 固定 40 项，每项 3 次，共 240 次对照运行
- 被测模型与顾客模拟器：DeepSeek Flash
- 温度 0、任务种子 42、最多 40 步、6 次工具调用、1024 输出 token、120000 累计 token、单并发
- 两臂使用同一原版工具库存与共享确定性 Guard
- V3 适配器哈希：`fd41dc31514e688c46129713519fe2a7387c099ab4d09de33347997b505923ab`
- 单 Agent 适配器哈希：`9ccd17b03f71c00d953cf4a1d4a86804c94d957feab886be2d9a9be0e854db8d`

120 对配对 trial 的任务 ID、trial 与 seed 全部一致，seed mismatch 为 0。

## 成本与 Token

可恢复记录包含约 **2036.38 万 token**。按执行器记录的 DeepSeek 峰值费率估算：单 Agent 117 次为 `$0.8917`，V3 120 次为 `$0.9068`，合计 `$1.7985`；按项目采用的保守 7.2 元/美元预算换算约 `¥12.95`，低于 `$2.70`（20 元预算内的保守美元上限）。

这个金额不是 Provider 最终账单。它不含单 Agent 任务 5 的 3 次不可恢复 token、语义 Judge 调用和未持久化的失败请求，因此最终实际费用必须以 DeepSeek 账单为准，不能把 `$1.7985` 当作精确消费。

## 基础设施事故与处理

### 1. Windows GBK 检查点损坏

单 Agent 完成任务 5 的三次运行后，τ-bench 扩展 JSON 检查点时使用 Windows 默认 GBK，遇到 Unicode 字符后将文件截断为 0 字节。控制台已明确输出三次奖励：成功、失败（max_steps）、成功，即 2/3。

为避免“丢掉失败后重跑”造成选择偏差，任务 5 没有重跑。后续只执行其余 39 个任务，最终把原始 2/3 合并为单 Agent 51/120。三次运行的完整轨迹与精确 token 已丢失，`results.csv` 中对应行明确使用 `console_recovery_after_checkpoint_corruption` 证据标识。

### 2. NL assertions 默认指向 OpenAI

开发集没有触发 `nl_assertions`，保留集任务 38 首次触发后发现上游该评分路径仍使用默认 OpenAI 模型，产生一条无奖励 `infrastructure_error`。修复仅把未修改的上游 NL 评分 Prompt 路由到 DeepSeek，与已配置的 `communicate_info` Judge 保持一致；没有修改 Agent、Prompt、Guard、工具或任务。

上游检查点策略移除无奖励基础设施错误并重试。最终两臂各 120 条计分记录中均无 infrastructure_error。

## 验收决定

阶段 5B 的公平对照与指标采集已完成，可以进入 5C。V3 不获得“优于单 Agent”结论，也不再使用本 holdout 做任何调参、路由修改或同版本重跑。后续 5C 只做结果分析、失败分类和求职交付；如果未来开发 V4，必须建立新的开发证据与独立未见评测集。

最终验证：完整后端与真实 PostgreSQL 随机 schema 回归 **264 passed、0 failed、0 skipped（95.64s）**；阶段 5B 预算、Judge 和恢复专项测试 **8 passed**；Ruff、CSV/JSON 一致性和 Git 差异检查通过。外部模型不参与上述本地回归。

结构化结果见 `reports/phase5b_holdout_comparison.json`，基础设施事故见 `reports/phase5b_holdout_incident_20261120.json`，逐次结果见 `reports/results.csv`。
