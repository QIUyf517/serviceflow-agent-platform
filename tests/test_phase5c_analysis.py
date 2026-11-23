import json
import xml.etree.ElementTree as ET

import pytest
from app.evaluation.analysis import build_phase5c_analysis

from scripts.build_phase5c_report import ROOT, render_artifacts, write_or_check
from scripts.demo_phase5c import build_demo


def test_phase5c_recomputes_frozen_paired_result_and_boundaries():
    data = build_phase5c_analysis(ROOT)
    single = data.official_holdout["single_agent"]
    multi = data.official_holdout["multi_agent_v3"]
    assert (single.successes, single.runs, single.success_rate) == (51, 120, 0.425)
    assert (multi.successes, multi.runs, multi.success_rate) == (45, 120, 0.375)
    assert data.paired_comparison.single_only_success == 12
    assert data.paired_comparison.multi_only_success == 6
    assert data.paired_comparison.mcnemar_exact_two_sided_p == pytest.approx(
        0.237884521484375
    )
    assert data.official_score_eligible is False
    assert data.reliability.trials_per_scenario == 1
    assert data.reliability.recovery_scenario_passed is True
    comparable = [
        arm.arm for arm in data.evidence_arms if arm.directly_comparable_on_official_holdout
    ]
    assert comparable == ["single_agent", "multi_agent"]


def test_phase5c_usage_excludes_missing_case_from_both_arms():
    usage = build_phase5c_analysis(ROOT).comparable_usage
    assert usage.excluded_case_ids == ["5"]
    assert usage.runs_per_architecture == 117
    assert usage.single_agent_tokens_per_run > 0
    assert usage.multi_agent_tokens_per_run > 0


def test_phase5c_failure_axes_reconcile_without_leaking_task_bodies():
    data = build_phase5c_analysis(ROOT)
    for failure in data.failures.values():
        assert sum(failure.termination_reason_counts.values()) == failure.failures
        assert sum(failure.action_outcome_counts.values()) == failure.failures
    rendered = "\n".join(render_artifacts(data).values())
    forbidden = ["reason_for_call", "evaluation_criteria", "known_info", "payment_methods"]
    assert not any(value in rendered for value in forbidden)


def test_phase5c_artifacts_are_current_and_svg_is_valid():
    assert write_or_check(check=True) == []
    ET.parse(ROOT / "reports/figures/phase5_success_rates.svg")
    payload = json.loads((ROOT / "reports/phase5c_analysis.json").read_text(encoding="utf-8"))
    assert payload["phase"] == "5C"


def test_phase5c_demo_is_read_only_and_honest():
    demo = build_demo()
    assert demo["external_llm_calls"] == 0
    assert demo["holdout_reruns"] == 0
    assert demo["official_task_custom_judge"]["official_score_eligible"] is False
