"""Reproducible Phase 5C analysis over frozen Phase 5 evaluation artifacts.

This module is deliberately offline.  It reads scored outputs after a run has
finished; it never imports task criteria into an Agent prompt or runtime state.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.evaluation.results import RESULT_COLUMNS

OFFICIAL_TRACK = "official_tasks_custom_judge"
RELIABILITY_TRACK = "reliability"
SINGLE_HOLDOUT_RUN = "phase5b-final-single-remainder"
MULTI_HOLDOUT_RUN = "phase5b-final-multi"
BUSINESS_EFFECT_TOOLS = {
    "cancel_pending_order",
    "modify_pending_order_address",
    "modify_pending_order_items",
    "modify_pending_order_payment",
    "modify_user_address",
    "return_delivered_order_items",
    "exchange_delivered_order_items",
    "transfer_to_human_agents",
}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceFile(StrictModel):
    path: str
    sha256: str


class OfficialArmSummary(StrictModel):
    architecture: Literal["single_agent", "multi_agent"]
    run_id: str
    runs: int = Field(ge=1)
    successes: int = Field(ge=0)
    failures: int = Field(ge=0)
    success_rate: float = Field(ge=0, le=1)
    duration_coverage: int = Field(ge=0)
    latency_p50_seconds: float | None
    latency_p95_seconds: float | None
    tool_call_coverage: int = Field(ge=0)
    total_tool_calls: int | None
    mean_tool_calls_per_covered_run: float | None
    token_coverage: int = Field(ge=0)
    tracked_total_tokens: int
    cost_coverage: int = Field(ge=0)
    tracked_cost_usd: float
    excluded_costs: list[str]


class PairedComparison(StrictModel):
    pairs: int = Field(ge=1)
    both_success: int = Field(ge=0)
    single_only_success: int = Field(ge=0)
    multi_only_success: int = Field(ge=0)
    both_fail: int = Field(ge=0)
    multi_minus_single_percentage_points: float
    approximate_paired_95_percent_ci_percentage_points: tuple[float, float]
    mcnemar_exact_two_sided_p: float = Field(ge=0, le=1)


class ComparableUsageSummary(StrictModel):
    excluded_case_ids: list[str]
    reason: str
    runs_per_architecture: int = Field(ge=1)
    single_agent_tokens_per_run: float
    multi_agent_tokens_per_run: float
    multi_minus_single_tokens_per_run_percent: float
    single_agent_cost_per_run_usd: float
    multi_agent_cost_per_run_usd: float
    multi_minus_single_cost_per_run_percent: float


class FailureSummary(StrictModel):
    architecture: Literal["single_agent", "multi_agent"]
    failures: int = Field(ge=0)
    termination_reason_counts: dict[str, int]
    action_outcome_counts: dict[str, int]
    raw_trace_failures_classified: int = Field(ge=0)
    raw_trace_failures_unavailable: int = Field(ge=0)


class ReliabilitySummary(StrictModel):
    scenario_count: int = Field(ge=1)
    passed: int = Field(ge=0)
    failed: int = Field(ge=0)
    trials_per_scenario: int = Field(ge=1)
    external_llm_calls: int = Field(ge=0)
    tracked_cost_usd: float = Field(ge=0)
    recovery_scenario_id: str
    recovery_scenario_passed: bool
    zero_count_metrics: dict[str, int]


class EvidenceArm(StrictModel):
    arm: Literal["rules", "single_agent", "multi_agent", "multi_agent_recovery"]
    evidence: str
    sample: str
    result: str
    directly_comparable_on_official_holdout: bool
    limitation: str


class Phase5CAnalysis(StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    phase: Literal["5C"] = "5C"
    generated_from_frozen_results: Literal[True] = True
    official_score_eligible: Literal[False] = False
    sources: list[SourceFile]
    official_holdout: dict[str, OfficialArmSummary]
    paired_comparison: PairedComparison
    comparable_usage: ComparableUsageSummary
    development_rates: dict[str, float]
    development_to_holdout_change_percentage_points: dict[str, float]
    reliability: ReliabilitySummary
    evidence_arms: list[EvidenceArm]
    failures: dict[str, FailureSummary]
    conclusions: list[str]
    limitations: list[str]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"json_object_required:{path}")
    return value


def _read_results(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != RESULT_COLUMNS:
            raise ValueError("results_csv_schema_mismatch")
        return list(reader)


def _float(row: dict[str, str], key: str) -> float | None:
    value = row[key].strip()
    return float(value) if value else None


def _int(row: dict[str, str], key: str) -> int | None:
    value = row[key].strip()
    return int(value) if value else None


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _arm_summary(rows: list[dict[str, str]], architecture: str) -> OfficialArmSummary:
    successes = sum(row["success"].casefold() == "true" for row in rows)
    durations = [value for row in rows if (value := _float(row, "duration_seconds")) is not None]
    tool_calls = [value for row in rows if (value := _int(row, "tool_calls")) is not None]
    tokens = [value for row in rows if (value := _int(row, "total_tokens")) is not None]
    costs = [value for row in rows if (value := _float(row, "cost_usd")) is not None]
    missing_cost_note = []
    if len(costs) != len(rows):
        missing_cost_note.append(
            f"{len(rows) - len(costs)} runs have no persisted token or cost usage"
        )
    missing_cost_note.extend(
        [
            "semantic Judge calls are not included",
            "failed requests without persisted usage are not included",
        ]
    )
    return OfficialArmSummary(
        architecture=architecture,
        run_id=rows[0]["run_id"],
        runs=len(rows),
        successes=successes,
        failures=len(rows) - successes,
        success_rate=successes / len(rows),
        duration_coverage=len(durations),
        latency_p50_seconds=_percentile(durations, 0.5),
        latency_p95_seconds=_percentile(durations, 0.95),
        tool_call_coverage=len(tool_calls),
        total_tool_calls=sum(tool_calls) if tool_calls else None,
        mean_tool_calls_per_covered_run=(sum(tool_calls) / len(tool_calls) if tool_calls else None),
        token_coverage=len(tokens),
        tracked_total_tokens=sum(tokens),
        cost_coverage=len(costs),
        tracked_cost_usd=sum(costs),
        excluded_costs=missing_cost_note,
    )


def _paired_comparison(
    single_rows: list[dict[str, str]], multi_rows: list[dict[str, str]]
) -> PairedComparison:
    def keyed(rows: list[dict[str, str]]) -> dict[tuple[str, str, str], bool]:
        result: dict[tuple[str, str, str], bool] = {}
        for row in rows:
            key = (row["case_id"], row["trial"], row["seed"])
            if key in result:
                raise ValueError(f"duplicate_paired_key:{key}")
            result[key] = row["success"].casefold() == "true"
        return result

    single = keyed(single_rows)
    multi = keyed(multi_rows)
    if single.keys() != multi.keys():
        raise ValueError("holdout_pair_keys_mismatch")
    both_success = single_only = multi_only = both_fail = 0
    for key, single_success in single.items():
        multi_success = multi[key]
        if single_success and multi_success:
            both_success += 1
        elif single_success:
            single_only += 1
        elif multi_success:
            multi_only += 1
        else:
            both_fail += 1
    pairs = len(single)
    difference = (multi_only - single_only) / pairs
    # Sample variance (ddof=1) of paired {-1, 0, +1} outcomes, divided by n.
    # This reproduces the frozen Phase 5B normal-approximation interval.
    variance = (
        ((single_only + multi_only) - pairs * difference**2) / (pairs - 1) / pairs
    )
    margin = 1.96 * math.sqrt(variance)
    discordant = single_only + multi_only
    tail = sum(math.comb(discordant, value) for value in range(min(single_only, multi_only) + 1))
    mcnemar = min(1.0, 2 * tail / (2**discordant)) if discordant else 1.0
    return PairedComparison(
        pairs=pairs,
        both_success=both_success,
        single_only_success=single_only,
        multi_only_success=multi_only,
        both_fail=both_fail,
        multi_minus_single_percentage_points=difference * 100,
        approximate_paired_95_percent_ci_percentage_points=(
            (difference - margin) * 100,
            (difference + margin) * 100,
        ),
        mcnemar_exact_two_sided_p=mcnemar,
    )


def _comparable_usage(
    single_rows: list[dict[str, str]], multi_rows: list[dict[str, str]]
) -> ComparableUsageSummary:
    def complete(rows: list[dict[str, str]]) -> list[dict[str, str]]:
        return [
            row
            for row in rows
            if row["case_id"] != "5"
            and _int(row, "total_tokens") is not None
            and _float(row, "cost_usd") is not None
        ]

    single = complete(single_rows)
    multi = complete(multi_rows)
    if len(single) != 117 or len(multi) != 117:
        raise ValueError("comparable_usage_expected_117_runs_per_architecture")
    single_tokens = sum(int(row["total_tokens"]) for row in single) / len(single)
    multi_tokens = sum(int(row["total_tokens"]) for row in multi) / len(multi)
    single_cost = sum(float(row["cost_usd"]) for row in single) / len(single)
    multi_cost = sum(float(row["cost_usd"]) for row in multi) / len(multi)
    return ComparableUsageSummary(
        excluded_case_ids=["5"],
        reason=(
            "The single-agent checkpoint for case 5 lost three token and cost records; both arms "
            "exclude that case for a like-for-like usage comparison."
        ),
        runs_per_architecture=117,
        single_agent_tokens_per_run=single_tokens,
        multi_agent_tokens_per_run=multi_tokens,
        multi_minus_single_tokens_per_run_percent=(multi_tokens / single_tokens - 1) * 100,
        single_agent_cost_per_run_usd=single_cost,
        multi_agent_cost_per_run_usd=multi_cost,
        multi_minus_single_cost_per_run_percent=(multi_cost / single_cost - 1) * 100,
    )


def _tool_names(message: dict[str, Any]) -> list[str]:
    calls = message.get("tool_calls")
    if isinstance(calls, dict):
        calls = [calls]
    if not isinstance(calls, list):
        return []
    return [call["name"] for call in calls if isinstance(call, dict) and call.get("name")]


def _failure_action_counts(raw_path: Path) -> Counter[str]:
    raw = _read_json(raw_path)
    expected_by_task: dict[str, set[str]] = {}
    for task in raw.get("tasks", []):
        if not isinstance(task, dict):
            continue
        actions = task.get("evaluation_criteria", {}).get("actions", []) or []
        expected_by_task[str(task.get("id"))] = {
            action.get("name")
            for action in actions
            if isinstance(action, dict) and action.get("name") in BUSINESS_EFFECT_TOOLS
        }
    counts: Counter[str] = Counter()
    for simulation in raw.get("simulations", []):
        if not isinstance(simulation, dict):
            continue
        reward = simulation.get("reward_info", {}).get("reward")
        if reward != 0 and reward != 0.0:
            continue
        expected = expected_by_task.get(str(simulation.get("task_id")), set())
        observed = {
            name
            for message in simulation.get("messages", [])
            if isinstance(message, dict)
            for name in _tool_names(message)
            if name in BUSINESS_EFFECT_TOOLS
        }
        if expected and not observed:
            outcome = "required_effect_not_executed"
        elif expected & observed:
            outcome = "required_effect_executed_but_score_failed"
        elif expected and observed:
            outcome = "different_effect_executed"
        elif observed:
            outcome = "unexpected_effect_executed"
        else:
            outcome = "communication_or_read_only_failure"
        counts[outcome] += 1
    return counts


def _termination_reason(value: str) -> str:
    if value == "console_recovery_after_checkpoint_corruption":
        return "trace_unavailable_checkpoint_loss"
    if value.startswith("TerminationReason."):
        return value.removeprefix("TerminationReason.").casefold()
    return value or "unknown"


def _failure_summary(
    rows: list[dict[str, str]], raw_path: Path, architecture: str
) -> FailureSummary:
    failed = [row for row in rows if row["success"].casefold() != "true"]
    termination = Counter(_termination_reason(row["failure_type"]) for row in failed)
    action = _failure_action_counts(raw_path)
    unavailable = len(failed) - sum(action.values())
    if unavailable < 0:
        raise ValueError("raw_failure_count_exceeds_csv")
    if unavailable:
        action["trace_unavailable_checkpoint_loss"] += unavailable
    return FailureSummary(
        architecture=architecture,
        failures=len(failed),
        termination_reason_counts=dict(sorted(termination.items())),
        action_outcome_counts=dict(sorted(action.items())),
        raw_trace_failures_classified=sum(action.values()) - unavailable,
        raw_trace_failures_unavailable=unavailable,
    )


def _reliability_summary(rows: list[dict[str, str]]) -> ReliabilitySummary:
    metrics: Counter[str] = Counter()
    recovery_passed = False
    for row in rows:
        values = json.loads(row["metric_values_json"] or "{}")
        for key, value in values.items():
            if isinstance(value, bool):
                if key == "recovery_success" and row["case_id"] == "REL-008":
                    recovery_passed = value and row["success"].casefold() == "true"
            elif isinstance(value, int):
                metrics[key] += value
    zero_metrics = {
        key: metrics.get(key, 0)
        for key in (
            "unauthorized_disclosure_count",
            "unconfirmed_write_count",
            "duplicate_write_count",
            "policy_violation_count",
            "binding_violation_count",
            "stale_write_count",
            "unsupported_write_count",
            "prompt_injection_success_count",
        )
    }
    return ReliabilitySummary(
        scenario_count=len(rows),
        passed=sum(row["success"].casefold() == "true" for row in rows),
        failed=sum(row["success"].casefold() != "true" for row in rows),
        trials_per_scenario=1,
        external_llm_calls=0,
        tracked_cost_usd=sum(float(row["cost_usd"] or 0) for row in rows),
        recovery_scenario_id="REL-008",
        recovery_scenario_passed=recovery_passed,
        zero_count_metrics=zero_metrics,
    )


def build_phase5c_analysis(root: Path) -> Phase5CAnalysis:
    """Build the analysis from committed summaries, CSV rows and ignored raw traces."""
    results_path = root / "reports" / "results.csv"
    development_path = root / "reports" / "phase5b_v3_development_comparison.json"
    holdout_path = root / "reports" / "phase5b_holdout_comparison.json"
    reliability_path = root / "reports" / "phase5b_reliability_summary.json"
    single_raw = (
        root
        / "reports/raw/official_tasks_custom_judge/phase5/holdout"
        / "phase5b-final-single-remainder/single_agent_results.json"
    )
    multi_raw = (
        root
        / "reports/raw/official_tasks_custom_judge/phase5/holdout"
        / "phase5b-final-multi/multi_agent_results.json"
    )
    required = [
        results_path,
        development_path,
        holdout_path,
        reliability_path,
        single_raw,
        multi_raw,
    ]
    missing = [str(path.relative_to(root)) for path in required if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"phase5c_sources_missing:{','.join(missing)}")

    rows = _read_results(results_path)
    single_rows = [
        row
        for row in rows
        if row["track"] == OFFICIAL_TRACK and row["run_id"] == SINGLE_HOLDOUT_RUN
    ]
    multi_rows = [
        row
        for row in rows
        if row["track"] == OFFICIAL_TRACK and row["run_id"] == MULTI_HOLDOUT_RUN
    ]
    reliability_rows = [row for row in rows if row["track"] == RELIABILITY_TRACK]
    if len(single_rows) != 120 or len(multi_rows) != 120 or len(reliability_rows) != 10:
        raise ValueError("phase5c_expected_120_120_10_rows")

    single = _arm_summary(single_rows, "single_agent")
    multi = _arm_summary(multi_rows, "multi_agent")
    paired = _paired_comparison(single_rows, multi_rows)
    usage = _comparable_usage(single_rows, multi_rows)
    development = _read_json(development_path)
    holdout = _read_json(holdout_path)
    reliability = _reliability_summary(reliability_rows)

    if single.successes != holdout["results"]["single_agent"]["successes"]:
        raise ValueError("single_holdout_summary_mismatch")
    if multi.successes != holdout["results"]["multi_agent_v3"]["successes"]:
        raise ValueError("multi_holdout_summary_mismatch")
    if paired.model_dump() != {
        "pairs": holdout["paired_analysis"]["pairs"],
        "both_success": holdout["paired_analysis"]["both_success"],
        "single_only_success": holdout["paired_analysis"]["single_only_success"],
        "multi_only_success": holdout["paired_analysis"]["multi_only_success"],
        "both_fail": holdout["paired_analysis"]["both_fail"],
        "multi_minus_single_percentage_points": holdout["results"]["multi_minus_single"][
            "percentage_points"
        ],
        "approximate_paired_95_percent_ci_percentage_points": tuple(
            holdout["results"]["multi_minus_single"]
            ["approximate_paired_95_percent_ci_percentage_points"]
        ),
        "mcnemar_exact_two_sided_p": holdout["paired_analysis"][
            "mcnemar_exact_two_sided_p"
        ],
    }:
        raise ValueError("paired_analysis_summary_mismatch")

    development_rates = {
        "single_agent": float(development["single_agent_v1"]["success_rate"]),
        "multi_agent_v3": float(development["multi_agent_v3"]["success_rate"]),
    }
    changes = {
        "single_agent": (single.success_rate - development_rates["single_agent"]) * 100,
        "multi_agent_v3": (multi.success_rate - development_rates["multi_agent_v3"]) * 100,
    }
    sources = [
        SourceFile(path=str(path.relative_to(root)).replace("\\", "/"), sha256=_sha256(path))
        for path in required
    ]
    return Phase5CAnalysis(
        sources=sources,
        official_holdout={"single_agent": single, "multi_agent_v3": multi},
        paired_comparison=paired,
        comparable_usage=usage,
        development_rates=development_rates,
        development_to_holdout_change_percentage_points=changes,
        reliability=reliability,
        evidence_arms=[
            EvidenceArm(
                arm="rules",
                evidence="ServiceFlow 确定性政策与安全路径（自建可靠性轨道）",
                sample="10 个自建场景，每场景执行 1 次 pytest",
                result="10/10 通过；已断言的违规计数均为 0",
                directly_comparable_on_official_holdout=False,
                limitation="不是隔离的官方任务端到端实验臂，且没有重复运行。",
            ),
            EvidenceArm(
                arm="single_agent",
                evidence="冻结的 τ-bench Retail test 任务 + DeepSeek 自定义语义 Judge",
                sample="40 项任务 × 3 次 = 120 次配对运行",
                result=f"{single.successes}/{single.runs} ({single.success_rate:.2%})",
                directly_comparable_on_official_holdout=True,
                limitation="自定义 Judge 结果不是官方默认 τ-bench 分数。",
            ),
            EvidenceArm(
                arm="multi_agent",
                evidence="冻结的 V3 确定性 Supervisor + 专业角色",
                sample="40 项任务 × 3 次 = 120 次配对运行",
                result=f"{multi.successes}/{multi.runs} ({multi.success_rate:.2%})",
                directly_comparable_on_official_holdout=True,
                limitation="V3 的产品边界是一笔订单一个线程。",
            ),
            EvidenceArm(
                arm="multi_agent_recovery",
                evidence="REL-008 超时归一化与幂等重试断言",
                sample="1 个自建恢复场景 × 1 次执行",
                result="1/1 通过" if reliability.recovery_scenario_passed else "0/1 通过",
                directly_comparable_on_official_holdout=False,
                limitation="没有执行完整的恢复增强官方任务实验臂。",
            ),
        ],
        failures={
            "single_agent": _failure_summary(single_rows, single_raw, "single_agent"),
            "multi_agent_v3": _failure_summary(multi_rows, multi_raw, "multi_agent"),
        },
        conclusions=[
            "Multi-agent V3 did not demonstrate superiority on the frozen holdout.",
            "The observed -5.0 percentage-point difference is not statistically decisive at 0.05.",
            (
                "The development advantage reversed on holdout, so the development score did not "
                "generalize."
            ),
            (
                "The reliability track supports specific safety invariants, not a general 100% "
                "reliability claim."
            ),
        ],
        limitations=[
            (
                "Only the single-agent and multi-agent V3 arms are directly comparable on official "
                "tasks."
            ),
            "The semantic Judge uses DeepSeek instead of the upstream default OpenAI model.",
            (
                "The reliability track has one execution per authored scenario and no external LLM "
                "calls."
            ),
            "Three single-agent case-5 token/cost traces were lost in a checkpoint incident.",
            "Tracked costs exclude semantic Judge calls and some failed requests.",
        ],
    )
