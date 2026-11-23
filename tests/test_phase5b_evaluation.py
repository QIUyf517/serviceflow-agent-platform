import csv
import json
from pathlib import Path

import pytest
from app.evaluation.results import RESULT_COLUMNS, merge_results

from scripts.run_phase5b_official import (
    apply_incident_recovery_exclusions,
    build_communicate_scoring,
    build_plan,
    checkpoint_prefix_count,
    configure_deepseek_nl_assertions_judge,
    estimate_holdout_ceiling_usd,
    validate_holdout_budget,
    validate_run_request,
)


def test_phase5b_plan_keeps_fair_budgets_and_frozen_task_ids():
    development = build_plan("development", "test-plan")
    holdout = build_plan("holdout", "test-plan")
    assert development["architectures"] == ["single_agent", "multi_agent"]
    assert development["task_count"] == 10
    assert development["simulation_count"] == 60
    assert holdout["task_count"] == 40
    assert holdout["simulation_count"] == 240
    assert set(development["task_ids"]).isdisjoint(holdout["task_ids"])
    assert development["max_tool_calls"] == 6
    assert development["max_output_tokens"] == 1024
    assert development["max_total_tokens"] == 120000
    assert (
        development["multi_prompt_version"]
        == "tau2-deterministic-supervisor-specialists-v3"
    )
    assert development["official_score_eligible"] is False
    assert development["scoring"]["implementation"] == "upstream_semantic_prompt_custom_model"
    assert development["scoring"]["semantic_judge_provider"] == "deepseek"
    assert development["scoring"]["semantic_judge_model"] == "deepseek/deepseek-flash"
    assert development["scoring"]["communicate_facts_in_development"] == 0
    assert development["scoring"]["openai_key_required_before_run"] is False
    assert holdout["scoring"]["openai_key_required_before_run"] is False
    assert development["pricing"]["rates_usd_per_million"] == {
        "cache_hit_input": 0.006,
        "cache_miss_input": 0.3,
        "output": 1.2,
    }
    assert development["pricing"]["latest_architecture_approved_ceiling_usd"] is None
    assert development["external_llm_calls"] == 0
    scoring = build_communicate_scoring(holdout)
    assert scoring.scorer.value == "semantic"
    assert scoring.judge.model == "deepseek/deepseek-flash"
    assert scoring.judge.model_args["extra_body"] == {"thinking": {"type": "disabled"}}


def test_paid_and_holdout_runs_require_explicit_authorization():
    with pytest.raises(ValueError, match="one_architecture"):
        validate_run_request("development", None, 1.0, False)
    with pytest.raises(ValueError, match="positive_approved_budget"):
        validate_run_request("development", "single_agent", None, False)
    with pytest.raises(ValueError, match="allow_holdout"):
        validate_run_request("holdout", "single_agent", 1.0, False)
    validate_run_request("holdout", "multi_agent", 1.0, True)


@pytest.mark.parametrize(
    ("architecture", "linear_projection", "required_ceiling"),
    [
        ("single_agent", 0.945818832, 1.1349825984),
        ("multi_agent", 0.917644536, 1.1011734432),
    ],
)
def test_holdout_budget_uses_matching_frozen_development_cost(
    architecture: str, linear_projection: float, required_ceiling: float
):
    holdout = build_plan("holdout", "test-plan")
    projection = estimate_holdout_ceiling_usd(holdout, architecture)
    assert projection["reference_runs"] == 30
    assert projection["planned_runs"] == 120
    assert projection["linear_projection_usd"] == pytest.approx(linear_projection)
    assert projection["required_ceiling_usd"] == pytest.approx(required_ceiling)
    with pytest.raises(ValueError, match="approved_budget_below"):
        validate_holdout_budget(holdout, architecture, 1.20)
    validate_holdout_budget(holdout, architecture, 1.35)


def test_incident_recovery_can_exclude_observed_holdout_without_rerun():
    holdout = build_plan("holdout", "incident-recovery")
    apply_incident_recovery_exclusions(holdout, ["5"], True)
    assert holdout["task_count"] == 39
    assert holdout["simulation_count"] == 117
    assert "5" not in holdout["task_ids"]
    assert holdout["incident_recovery"]["excluded_results_must_be_merged_without_rerun"]

    development = build_plan("development", "invalid-recovery")
    with pytest.raises(ValueError, match="requires_incident_recovery"):
        apply_incident_recovery_exclusions(development, ["0"], True)


def test_all_semantic_judges_route_to_deepseek():
    from tau2.evaluator import evaluator_nl_assertions

    holdout = build_plan("holdout", "deepseek-judges")
    configure_deepseek_nl_assertions_judge(holdout)
    assert evaluator_nl_assertions.DEFAULT_LLM_NL_ASSERTIONS == (
        "deepseek/deepseek-flash"
    )
    assert evaluator_nl_assertions.DEFAULT_LLM_NL_ASSERTIONS_ARGS == {
        "temperature": 0.0,
        "extra_body": {"thinking": {"type": "disabled"}},
    }


def test_incremental_checkpoint_resumes_from_registered_task_prefix(tmp_path: Path):
    path = tmp_path / "results.json"
    task_ids = ["5", "9", "12"]
    path.write_text(
        json.dumps({"tasks": [{"id": "5"}, {"id": "9"}]}), encoding="utf-8"
    )
    assert checkpoint_prefix_count(path, task_ids) == 2
    with pytest.raises(RuntimeError, match="prefix_mismatch"):
        checkpoint_prefix_count(path, ["5", "12", "9"])


def test_results_csv_replaces_only_the_same_stable_key(tmp_path: Path):
    path = tmp_path / "results.csv"
    base = {column: "" for column in RESULT_COLUMNS}
    base.update(
        {
            "schema_version": "1.0",
            "track": "reliability",
            "run_id": "r1",
            "architecture": "system",
            "case_id": "REL-001",
            "trial": 1,
            "success": "false",
        }
    )
    merge_results(path, [base])
    merge_results(path, [{**base, "success": "true"}])
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["success"] == "true"
