# ruff: noqa: E501
"""Generate or verify the frozen Phase 5C analysis and portfolio report artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.evaluation.analysis import Phase5CAnalysis, build_phase5c_analysis

ROOT = Path(__file__).resolve().parents[1]


def _percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def _seconds(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.2f} s"


def _render_summary(data: Phase5CAnalysis) -> str:
    single = data.official_holdout["single_agent"]
    multi = data.official_holdout["multi_agent_v3"]
    paired = data.paired_comparison
    usage = data.comparable_usage
    reliability = data.reliability
    single_failure = data.failures["single_agent"]
    multi_failure = data.failures["multi_agent_v3"]
    return f"""# 多 Agent 的开发集优势没有泛化：ServiceFlow 阶段 5 最终评测摘要

> 结果冻结于 2026-11-21；本报告由 `scripts.build_phase5c_report` 从已冻结结果生成，未重跑 holdout，未调用外部模型。

## 执行摘要

- 在 40 个 τ-bench Retail test 任务、每任务 3 次的配对保留集上，单 Agent 为 **{single.successes}/{single.runs}（{_percent(single.success_rate)}）**，多 Agent V3 为 **{multi.successes}/{multi.runs}（{_percent(multi.success_rate)}）**。
- V3 相对单 Agent 为 **{paired.multi_minus_single_percentage_points:.2f} 个百分点**；配对近似 95% 区间为 **{paired.approximate_paired_95_percent_ci_percentage_points[0]:.1f} 至 {paired.approximate_paired_95_percent_ci_percentage_points[1]:.1f} 个百分点**，McNemar 精确双侧 `p={paired.mcnemar_exact_two_sided_p:.3f}`。证据不支持 V3 优越，也不足以证明确定劣势。
- 开发集的单 Agent / V3 为 **{_percent(data.development_rates['single_agent'])} / {_percent(data.development_rates['multi_agent_v3'])}**；到保留集分别下降 **{data.development_to_holdout_change_percentage_points['single_agent']:.2f} / {data.development_to_holdout_change_percentage_points['multi_agent_v3']:.2f} 个百分点**。开发集优势发生反转。
- 自建可靠性轨道为 **{reliability.passed}/{reliability.scenario_count}**，但每个场景只执行 1 次且不用外部 LLM；它只证明列出的确定性断言，不等于“系统可靠率 100%”。

![阶段 5 开发集与保留集成功率](figures/phase5_success_rates.svg)

## 四组证据矩阵

| 组别 | 证据与样本 | 实际结果 | 可与官方保留集直接比较 | 关键限制 |
| --- | --- | --- | --- | --- |
{chr(10).join(f"| `{arm.arm}` | {arm.evidence}；{arm.sample} | {arm.result} | {'是' if arm.directly_comparable_on_official_holdout else '否'} | {arm.limitation} |" for arm in data.evidence_arms)}

`eval_config.json` 预设了四组，但实际没有形成四组同口径正式对照。只有单 Agent 与多 Agent V3 拥有相同任务、trial、seed、模型、工具、Guard 和预算下的 120 对结果；规则流程与恢复增强只能作为自建工程可靠性证据。

## 官方任务对照

| 指标 | 单 Agent | 多 Agent V3 | 解释 |
| --- | ---: | ---: | --- |
| 成功 / 运行 | {single.successes} / {single.runs} | {multi.successes} / {multi.runs} | 120 对 trial，seed mismatch 为 0 |
| 成功率 | {_percent(single.success_rate)} | {_percent(multi.success_rate)} | V3 − 单 Agent = {paired.multi_minus_single_percentage_points:.2f} 个百分点 |
| 延迟 P50 | {_seconds(single.latency_p50_seconds)} | {_seconds(multi.latency_p50_seconds)} | 墙钟时间，含模型与模拟器 |
| 延迟 P95 | {_seconds(single.latency_p95_seconds)} | {_seconds(multi.latency_p95_seconds)} | 不推断并发吞吐；两组均单并发 |
| 工具调用覆盖 | {single.tool_call_coverage}/{single.runs} | {multi.tool_call_coverage}/{multi.runs} | 单 Agent 任务 5 的 3 条完整轨迹丢失 |
| 跟踪 token | {single.tracked_total_tokens:,}（{single.token_coverage} 次） | {multi.tracked_total_tokens:,}（{multi.token_coverage} 次） | 覆盖不同，不能直接用总量判断效率 |
| 跟踪成本 | ${single.tracked_cost_usd:.4f} | ${multi.tracked_cost_usd:.4f} | 均不含 Judge；单 Agent 还缺 3 次 usage |

配对结果：双方成功 {paired.both_success}，仅单 Agent 成功 {paired.single_only_success}，仅 V3 成功 {paired.multi_only_success}，双方失败 {paired.both_fail}。这比只看两个边际成功率更直接：单 Agent 独占成功对数是 V3 的两倍（12 对 6）。

### 可比 token 与成本子集

为避免把单 Agent 任务 5 的缺失 usage 当成 0，两组都排除任务 5，仅比较各 {usage.runs_per_architecture} 次完整记录：

| 指标 | 单 Agent | 多 Agent V3 | V3 相对变化 |
| --- | ---: | ---: | ---: |
| 每次 token | {usage.single_agent_tokens_per_run:,.1f} | {usage.multi_agent_tokens_per_run:,.1f} | {usage.multi_minus_single_tokens_per_run_percent:+.2f}% |
| 每次跟踪成本 | ${usage.single_agent_cost_per_run_usd:.5f} | ${usage.multi_agent_cost_per_run_usd:.5f} | {usage.multi_minus_single_cost_per_run_percent:+.2f}% |

这些仍不是 Provider 最终账单：语义 Judge、未持久化失败请求均未计入。

## 失败分类

失败使用两个互补维度，不把终止原因冒充根因。

### 终止原因

| 架构 | `user_stop` | `max_steps` | 检查点丢失且仅控制台恢复 | 合计 |
| --- | ---: | ---: | ---: | ---: |
| 单 Agent | {single_failure.termination_reason_counts.get('user_stop', 0)} | {single_failure.termination_reason_counts.get('max_steps', 0)} | {single_failure.termination_reason_counts.get('trace_unavailable_checkpoint_loss', 0)} | {single_failure.failures} |
| 多 Agent V3 | {multi_failure.termination_reason_counts.get('user_stop', 0)} | {multi_failure.termination_reason_counts.get('max_steps', 0)} | 0 | {multi_failure.failures} |

### 业务动作结果

| 架构 | 必需动作未执行 | 必需动作执行但评分失败 | 执行了不同动作 | 纯沟通/只读失败 | 轨迹不可用 | 合计 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 单 Agent | {single_failure.action_outcome_counts.get('required_effect_not_executed', 0)} | {single_failure.action_outcome_counts.get('required_effect_executed_but_score_failed', 0)} | {single_failure.action_outcome_counts.get('different_effect_executed', 0)} | {single_failure.action_outcome_counts.get('communication_or_read_only_failure', 0)} | {single_failure.action_outcome_counts.get('trace_unavailable_checkpoint_loss', 0)} | {single_failure.failures} |
| 多 Agent V3 | {multi_failure.action_outcome_counts.get('required_effect_not_executed', 0)} | {multi_failure.action_outcome_counts.get('required_effect_executed_but_score_failed', 0)} | {multi_failure.action_outcome_counts.get('different_effect_executed', 0)} | {multi_failure.action_outcome_counts.get('communication_or_read_only_failure', 0)} | 0 | {multi_failure.failures} |

“必需动作执行但评分失败”只能说明至少调用了同名效果工具；参数、最终数据库状态或沟通信息仍可能不满足评分条件。更细的因果解释需要逐轨迹人工审阅，不能从工具名自动推出。

详细复现、根因边界与回归证据见 [`failures/phase5c_failure_catalog.md`](failures/phase5c_failure_catalog.md)。

## 可靠性轨道

10 个自建场景均通过；断言记录中的越权披露、未确认写入、重复写入、政策违规、提案绑定违规、陈旧写入、不支持写入和提示注入成功次数均为 0。`REL-008` 的超时归一化与幂等重试为 1/1。

这组证据的适当结论是“这些已绑定 pytest 的确定性边界在本次执行中通过”，不是对任意自然语言、未知故障或生产负载的统计可靠率估计。

## 决策

1. 保留多 Agent 架构作为工程能力与可解释分工方案，但不宣称它提升了本次任务成功率。
2. 默认产品路线应把单 Agent 保留为统一基线；任何 V4 都必须在新的开发证据和独立未见测试集上重新比较。
3. 优先处理会话停滞、工具预算耗尽和多工具调用被拒后的循环，因为它们与大量 `user_stop` / `max_steps` 失败一致；这是一项待验证假设，不是由终止标签直接证明的根因。
4. 继续把身份、归属、确认、规则、事务和幂等放在服务端确定性层，不以 benchmark 分数替代安全回归。

## 可复现命令

```powershell
# 只读取冻结结果并检查生成物，无外部模型调用、无数据库写入
.\\.venv_tau\\Scripts\\python.exe -m scripts.build_phase5c_report --check

# 求职演示摘要（同样只读）
.\\.venv_tau\\Scripts\\python.exe -m scripts.demo_phase5c
```

结构化分析见 [`phase5c_analysis.json`](phase5c_analysis.json)。原始逐次轨迹位于被 Git 忽略的 `reports/raw/`，避免提交模拟客户明细；可提交结果只包含聚合统计、任务 ID 和去标识化复现说明。
"""


def _render_failure_catalog(data: Phase5CAnalysis) -> str:
    single = data.failures["single_agent"]
    multi = data.failures["multi_agent_v3"]
    return f"""# 阶段 5C 失败目录

本目录保留失败，不按结果筛选。自动统计来自 `reports/results.csv` 和本地 `reports/raw/` 冻结轨迹；报告不复制模拟客户姓名、地址、支付信息、任务正文或评分参考动作。

## 复现总入口

```powershell
.\\.venv_tau\\Scripts\\python.exe -m scripts.build_phase5c_report --check
.\\.venv_tau\\Scripts\\python.exe -m pytest -q tests/test_phase5c_analysis.py -p no:cacheprovider --basetemp=.tmp/pytest-phase5c
```

`--check` 会重新计算配对统计、usage 可比子集与失败双轴分类，并校验 Markdown、JSON 和 SVG 是否与冻结输入一致；不会执行 τ-bench、调用模型或修改数据库。

## 失败总体

- 单 Agent：{single.failures} 次失败；`user_stop` {single.termination_reason_counts.get('user_stop', 0)}，`max_steps` {single.termination_reason_counts.get('max_steps', 0)}，检查点丢失 1。
- 多 Agent V3：{multi.failures} 次失败；`user_stop` {multi.termination_reason_counts.get('user_stop', 0)}，`max_steps` {multi.termination_reason_counts.get('max_steps', 0)}。
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
"""


def _render_svg(data: Phase5CAnalysis) -> str:
    values = [
        ("开发集", "单 Agent", data.development_rates["single_agent"], "#2559A7"),
        ("开发集", "多 Agent V3", data.development_rates["multi_agent_v3"], "#D18B22"),
        (
            "保留集",
            "单 Agent",
            data.official_holdout["single_agent"].success_rate,
            "#2559A7",
        ),
        (
            "保留集",
            "多 Agent V3",
            data.official_holdout["multi_agent_v3"].success_rate,
            "#D18B22",
        ),
    ]
    bars = []
    x_positions = [170, 300, 530, 660]
    for x, (split, arm, value, color) in zip(x_positions, values, strict=True):
        height = value * 300
        y = 390 - height
        bars.append(
            f'<rect x="{x}" y="{y:.1f}" width="86" height="{height:.1f}" rx="4" fill="{color}"/>'
            f'<text x="{x + 43}" y="{y - 10:.1f}" text-anchor="middle" class="value">{value * 100:.2f}%</text>'
            f'<text x="{x + 43}" y="420" text-anchor="middle" class="label">{arm}</text>'
            f'<text x="{x + 43}" y="444" text-anchor="middle" class="split">{split}</text>'
        )
    grid = []
    for percent in range(0, 101, 20):
        y = 390 - percent * 3
        grid.append(
            f'<line x1="95" y1="{y}" x2="805" y2="{y}" class="grid"/>'
            f'<text x="78" y="{y + 5}" text-anchor="end" class="tick">{percent}%</text>'
        )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="900" height="520" viewBox="0 0 900 520" role="img" aria-labelledby="title desc">
<title id="title">阶段 5 开发集与保留集成功率</title>
<desc id="desc">开发集单 Agent 73.33%，多 Agent V3 80%；保留集单 Agent 42.50%，多 Agent V3 37.50%。</desc>
<style>
  text {{ font-family: "Microsoft YaHei", "Noto Sans CJK SC", sans-serif; fill: #202733; }}
  .title {{ font-size: 24px; font-weight: 700; }} .subtitle {{ font-size: 14px; fill: #596273; }}
  .grid {{ stroke: #D9DEE7; stroke-width: 1; }} .tick {{ font-size: 13px; fill: #667085; }}
  .value {{ font-size: 15px; font-weight: 700; }} .label {{ font-size: 14px; font-weight: 600; }}
  .split {{ font-size: 13px; fill: #667085; }} .note {{ font-size: 13px; fill: #596273; }}
</style>
<rect width="900" height="520" fill="#FFFFFF"/>
<text x="95" y="42" class="title">开发集优势在独立保留集反转</text>
<text x="95" y="68" class="subtitle">成功率；开发集与保留集是不同任务集合，不应纵向解释为同一任务退化</text>
{''.join(grid)}
<line x1="95" y1="90" x2="95" y2="390" stroke="#8892A3"/>
<line x1="95" y1="390" x2="805" y2="390" stroke="#8892A3"/>
{''.join(bars)}
<text x="95" y="486" class="note">保留集：40 项 × 3 次；V3 − 单 Agent = −5.00 个百分点，配对近似 95% CI [−11.9, +1.9]。</text>
</svg>
"""


def render_artifacts(data: Phase5CAnalysis) -> dict[Path, str]:
    return {
        ROOT / "reports/phase5c_analysis.json": (
            json.dumps(data.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
        ),
        ROOT / "reports/summary.md": _render_summary(data),
        ROOT / "reports/failures/phase5c_failure_catalog.md": _render_failure_catalog(data),
        ROOT / "reports/figures/phase5_success_rates.svg": _render_svg(data),
    }


def write_or_check(check: bool) -> list[str]:
    data = build_phase5c_analysis(ROOT)
    stale: list[str] = []
    for path, content in render_artifacts(data).items():
        if check:
            if not path.is_file() or path.read_text(encoding="utf-8") != content:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    return stale


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when committed Phase 5C artifacts do not match the frozen inputs.",
    )
    args = parser.parse_args()
    stale = write_or_check(args.check)
    if stale:
        print(json.dumps({"status": "stale", "files": stale}, ensure_ascii=False))
        raise SystemExit(1)
    print(
        json.dumps(
            {
                "status": "verified" if args.check else "generated",
                "external_llm_calls": 0,
                "holdout_reruns": 0,
                "files": [str(path.relative_to(ROOT)) for path in render_artifacts(build_phase5c_analysis(ROOT))],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
