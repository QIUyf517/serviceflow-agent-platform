"""Print a read-only portfolio demo of the frozen Phase 5 result and evidence boundaries."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.evaluation.analysis import build_phase5c_analysis

from scripts.build_phase5c_report import write_or_check

ROOT = Path(__file__).resolve().parents[1]


def build_demo() -> dict[str, object]:
    stale = write_or_check(check=True)
    if stale:
        raise RuntimeError(f"phase5c_artifacts_stale:{','.join(stale)}")
    data = build_phase5c_analysis(ROOT)
    single = data.official_holdout["single_agent"]
    multi = data.official_holdout["multi_agent_v3"]
    return {
        "project": "ServiceFlow",
        "phase": "5C",
        "headline": "The multi-agent development advantage did not generalize to holdout.",
        "official_task_custom_judge": {
            "single_agent": f"{single.successes}/{single.runs} ({single.success_rate:.2%})",
            "multi_agent_v3": f"{multi.successes}/{multi.runs} ({multi.success_rate:.2%})",
            "difference_percentage_points": (
                data.paired_comparison.multi_minus_single_percentage_points
            ),
            "mcnemar_p": data.paired_comparison.mcnemar_exact_two_sided_p,
            "official_score_eligible": data.official_score_eligible,
        },
        "reliability": {
            "result": f"{data.reliability.passed}/{data.reliability.scenario_count}",
            "trials_per_scenario": data.reliability.trials_per_scenario,
            "external_llm_calls": data.reliability.external_llm_calls,
            "claim_boundary": (
                "Specific deterministic assertions passed; not a 100% reliability estimate."
            ),
        },
        "architecture_decision": (
            "Keep the single-agent baseline; retain multi-agent engineering benefits without "
            "claiming a task-success uplift."
        ),
        "artifacts": [
            "reports/summary.md",
            "reports/phase5c_analysis.json",
            "reports/failures/phase5c_failure_catalog.md",
            "docs/PHASE5_REPORT.md",
        ],
        "external_llm_calls": 0,
        "holdout_reruns": 0,
    }


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    demo = build_demo()
    if args.json:
        print(json.dumps(demo, ensure_ascii=False, indent=2))
        return
    print("ServiceFlow 阶段 5C｜冻结结果求职演示")
    print("结论：多 Agent 的开发集优势没有在独立保留集泛化。")
    official = demo["official_task_custom_judge"]
    print(f"单 Agent：{official['single_agent']}")
    print(f"多 Agent V3：{official['multi_agent_v3']}")
    print(
        "配对差值："
        f"{official['difference_percentage_points']:+.2f} 个百分点，"
        f"McNemar p={official['mcnemar_p']:.3f}"
    )
    print("可靠性：10/10 个自建确定性场景通过；每场景仅 1 次，不外推为 100% 可靠率。")
    print("边界：DeepSeek 自定义 Judge，非官方默认 τ-bench 分数；未重跑 holdout。")
    print("详情：reports/summary.md")


if __name__ == "__main__":
    main()
