# 阶段 5 最终验收报告：结果不支持多 Agent 优越性

日期：2026-11-22（Asia/Shanghai）

## 结论

阶段 5A、5B、5C 已形成从数据冻结、公平对照到失败分析和求职交付的闭环。结果不支持预设的“多 Agent 优于单 Agent”：独立保留集上，单 Agent 为 **51/120（42.50%）**，多 Agent V3 为 **45/120（37.50%）**，差值 −5.00 个百分点；配对近似 95% 区间为 −11.9 至 +1.9 个百分点，McNemar 精确双侧 `p=0.238`。

这意味着 V3 没有证明优越，本次差距也不足以证明确定劣势。开发集上的 +6.67 个百分点优势没有泛化，holdout 已冻结且禁止继续用于 V3 调参或同版本重跑。

## 交付范围

- `backend/app/evaluation/analysis.py`：严格 Pydantic 输出模型、配对统计、usage 可比子集、可靠性聚合及冻结轨迹失败分类。
- `scripts/build_phase5c_report.py`：生成或 `--check` 校验结构化 JSON、Markdown 报告、失败目录与 SVG；只读、零外部模型调用。
- `scripts/demo_phase5c.py`：面向求职演示的一页真实结果摘要，不启动付费评测。
- `reports/summary.md`：最终指标、四组证据矩阵、收益/代价、失败分类与决策。
- `reports/failures/phase5c_failure_catalog.md`：代表性失败、复现入口、根因边界和回归证据；不删除不利结果。
- `reports/phase5c_analysis.json`：机器可读指标、输入路径及 SHA256。
- `reports/figures/phase5_success_rates.svg`：开发集与保留集成功率对照，明确两者是不同任务集合。

README 和 `docs/ARCHITECTURE.md` 已补充实际安全架构与冻结评测管线。5C 不新增或修改业务 API；既有 API 输入/输出示例和安全约束保持有效。

## 四组证据边界

| 组别 | 实际证据 | 可与官方任务保留集直接比较 | 限制 |
| --- | --- | --- | --- |
| 规则流程 | 10 个自建确定性场景 10/10 | 否 | 每场景 1 次，且不是隔离的完整官方任务臂 |
| 单 Agent | 40 项 × 3 次，51/120 | 是 | DeepSeek 自定义 Judge，非官方默认分数 |
| 多 Agent V3 | 同一 120 对 trial，45/120 | 是 | 一订单一线程产品边界 |
| 恢复增强 | `REL-008` 1/1 | 否 | 没有运行完整 recovery-enhanced 官方任务臂 |

因此，阶段任务中的“四组汇总”已完成，但没有把不可比证据包装成四臂排名。

## 收益与代价

V3 的工程收益是专业角色工具白名单、确定性路由状态和确认后角色恢复；开发集确认后角色错误从 V1 的 7 次、V2 的 5 次降为 V3 的 0 次。它没有转化为保留集成功率优势。

在双方都排除任务 5、各 117 次完整 usage 的可比子集上，V3 每次 token 比单 Agent 低约 10.47%，跟踪成本低约 1.80%；但保留集 P50 / P95 延迟从单 Agent 的 27.21 / 37.79 秒变为 V3 的 27.84 / 40.48 秒。成本均不含语义 Judge 和未持久化失败请求，不能当作最终账单。

## 失败与事故

- 单 Agent 69 次失败：49 次 `user_stop`、19 次 `max_steps`、1 次检查点丢失后仅从控制台恢复。
- V3 75 次失败：57 次 `user_stop`、18 次 `max_steps`。
- 动作轴显示单 Agent / V3 分别有 37 / 42 次未执行任务要求的业务效果，3 / 10 次执行不同业务效果；这只是可复现分类，不自动等同于单一根因。
- Windows GBK 检查点事故保留 2/3 控制台 reward，未重跑任务 5，避免选择偏差；三次 usage 明确记为缺失。
- `nl_assertions` 默认 OpenAI Judge 路径已固定到 DeepSeek，并由专项测试覆盖；最终计分集无基础设施错误。

完整失败目录见 `reports/failures/phase5c_failure_catalog.md`。

## 验收命令

```powershell
.\.venv_tau\Scripts\python.exe -m scripts.build_phase5c_report --check
.\.venv_tau\Scripts\python.exe -m scripts.demo_phase5c --json
.\.venv_tau\Scripts\python.exe -m pytest -q tests/test_phase5c_analysis.py -p no:cacheprovider --basetemp=.tmp/pytest-phase5c
.\.venv_tau\Scripts\python.exe -m pytest -q -p no:cacheprovider --basetemp=.tmp/pytest-phase5c-full
.\.venv_tau\Scripts\python.exe -m ruff check backend scripts tests
```

最终实测：5C 专项 **5 passed**；带现有 PostgreSQL 16 容器和随机隔离 schema 的完整后端 **269 passed、0 failed、0 skipped（101.68s）**；Ruff、报告 `--check` 和只读演示通过；测试后 `phase*` schema 残留 **0**。完整回归只有一条上游 `audioop` 弃用警告。

首次受限沙箱运行卡在 asyncio loopback socket，属于已知本地执行限制；沙箱外首次诊断又因未设置 `TEST_DATABASE_URL` 得到 **254 passed、3 failed、12 skipped**，三个失败均是阶段 3 PostgreSQL 验收测试主动拒绝缺失配置。随后从现有本地配置设置测试连接，完整重跑 269 项全通过。中间失败与跳过均保留在记录中，没有只报告选择性重跑。

## 未完成项

阶段 5 无必需项未完成。可选阶段 6 的微调不是主项目验收条件。未来如开发 V4，必须建立新的开发证据与独立未见评测集，不能复用本 holdout 调参后再声称独立验证。
