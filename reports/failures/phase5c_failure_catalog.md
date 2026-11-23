# 阶段 5C 失败目录

本目录保留失败，不按结果筛选。自动统计来自 `reports/results.csv` 和本地 `reports/raw/` 冻结轨迹；报告不复制模拟客户姓名、地址、支付信息、任务正文或评分参考动作。

## 复现总入口

```powershell
.\.venv_tau\Scripts\python.exe -m scripts.build_phase5c_report --check
.\.venv_tau\Scripts\python.exe -m pytest -q tests/test_phase5c_analysis.py -p no:cacheprovider --basetemp=.tmp/pytest-phase5c
```

`--check` 会重新计算配对统计、usage 可比子集与失败双轴分类，并校验 Markdown、JSON 和 SVG 是否与冻结输入一致；不会执行 τ-bench、调用模型或修改数据库。

## 失败总体

- 单 Agent：69 次失败；`user_stop` 49，`max_steps` 19，检查点丢失 1。
- 多 Agent V3：75 次失败；`user_stop` 57，`max_steps` 18。
- 自动动作分类只回答“是否执行了评分任务要求的同名业务效果工具”，不自动判断参数是否正确，也不把终止原因当作根因。

## 代表性失败与修复证据

| 案例 | 已核实事实 | 根因判断 | 复现证据 | 回归证据 / 状态 |
| --- | --- | --- | --- | --- |
| 开发集 V1 确认后角色丢失 | V1 有 7 次、V2 有 5 次该类失败，V3 为 0 | 已核实为 Supervisor 在确认后选错专业角色；V3 固化待执行角色 | `reports/phase5b_development_comparison.json`、`reports/phase5b_v2_development_comparison.json`、`reports/phase5b_v3_development_comparison.json` | `tests/test_tau2_adapter.py` 中 V3 确认后执行回归；开发集改善，不代表 holdout 泛化 |
| 开发集跨订单任务 11/14 | 原始 V3 仍保留 6 个相关 run，其中 4 个失败；产品定义是一订单一线程 | benchmark 任务要求与产品边界不一致；这是适用范围差异，不是删除失败的理由 | `reports/phase5b_v3_development_comparison.json` 的 `failure_audit` | `tests/test_phase45d_threads.py` 验证跨订单零部分执行；完整 24/30 仍是主结果 |
| holdout 多 Agent 任务 5 trial 2 | 轨迹中多次出现多工具调用被单工具 Guard 拒绝，最终在最后一次写操作前耗尽固定预算 | “Guard 拒绝—模型重复—预算耗尽”是该轨迹的直接机制；不能外推到全部 `max_steps` | 本地忽略文件 `reports/raw/official_tasks_custom_judge/phase5/holdout/phase5b-final-multi/multi_agent_results.json`，筛选 `task_id=5, trial=2` | 尚未修复；V3 与 holdout 已冻结。未来 V4 应在新开发集增加“拒绝后恢复”测试 |
| 单 Agent 任务 5 检查点损坏 | 3 次 reward 在控制台保留为 2 成功/1 失败，但完整轨迹和 usage 丢失 | Windows 默认 GBK 追加 JSON 遇 Unicode 后破坏检查点 | `reports/phase5b_holdout_incident_20261120.json` | 不重跑该任务，避免选择偏差；最终报告把 3 次 usage 标为缺失 |
| NL assertions 默认 Judge | 首次任务 38 评分误走 OpenAI，产生无 reward 基础设施错误 | 上游另一评分路径未继承 DeepSeek Judge 配置 | `docs/PHASE5B_HOLDOUT_REPORT.md` 的事故记录 | `tests/test_phase5b_evaluation.py::test_all_semantic_judges_route_to_deepseek`；最终计分集无 infrastructure error |
| holdout 优势反转 | 开发集 V3 比单 Agent高 6.67 个百分点，holdout 低 5.00 个百分点 | 已核实结论是“开发优势未泛化”；样本不足以识别单一因果根因 | `reports/phase5b_holdout_comparison.json` | 冻结结果，禁止用 holdout 调参；未来 V4 使用新开发证据和独立未见集 |

## 不能从现有证据推出的结论

- `user_stop` 不等于“用户不满意”的唯一原因，可能包括任务自然结束、模型停滞或模拟器策略。
- `max_steps` 说明预算耗尽，不自动证明是路由、Prompt、模型或 Guard 的单一缺陷。
- 同名写工具被调用但 reward 为 0，不自动说明服务端违规；也可能是参数、目标对象、最终状态或沟通评分不符。
- 10/10 自建场景不是生产环境 100% 可靠率，也不能与 42.50% / 37.50% 的官方任务成功率合并。
