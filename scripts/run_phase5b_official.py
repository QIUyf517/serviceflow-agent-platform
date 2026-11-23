"""Prepare or explicitly run the fair Phase 5B official τ-bench comparison."""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

from app.config import Settings
from app.evaluation.preparation import load_and_verify_bundle, sha256_file
from app.evaluation.results import merge_results

from scripts.run_tau2_baseline import summarize, verify_upstream

ROOT = Path(__file__).resolve().parents[1]
ARCHITECTURES = ("single_agent", "multi_agent")
DEEPSEEK_FLASH_PEAK_RATES = {
    "cache_hit_input": 0.006,
    "cache_miss_input": 0.30,
    "output": 1.20,
}
HOLDOUT_COST_SAFETY_FACTOR = 1.20
HOLDOUT_UNTRACKED_COST_RESERVE_USD = 0.15
DEVELOPMENT_REFERENCE_RUN_IDS = {
    "single_agent": "phase5b-initial",
    "multi_agent": "phase5b-v3",
}


def _development_communicate_facts(task_ids: list[str]) -> int:
    """Inspect development criteria only; holdout task bodies remain unopened here."""
    from tau2.runner import get_tasks

    wanted = set(task_ids)
    tasks = [task for task in get_tasks("retail", task_split_name="train") if task.id in wanted]
    if {task.id for task in tasks} != wanted:
        raise ValueError("development_task_ids_missing")
    return sum(
        len(task.evaluation_criteria.communicate_info or [])
        for task in tasks
        if task.evaluation_criteria is not None
    )


def build_plan(split: Literal["development", "holdout"], run_id: str) -> dict[str, Any]:
    bundle = load_and_verify_bundle(ROOT)
    verify_upstream()
    settings = Settings()
    selected = bundle.official.development if split == "development" else bundle.official.holdout
    formal = bundle.config.formal
    communicate_facts: int | None = (
        _development_communicate_facts(selected.task_ids) if split == "development" else None
    )
    return {
        "phase": "5B",
        "status": "prepared_not_run",
        "run_id": run_id,
        "track": "tau2_retail_official_tasks_custom_deepseek_judge",
        "official_score_eligible": False,
        "results_namespace": bundle.config.official_results_namespace,
        "split": split,
        "source_split": selected.source_split,
        "task_ids": selected.task_ids,
        "task_count": len(selected.task_ids),
        "architectures": list(ARCHITECTURES),
        "simulation_count": len(selected.task_ids) * formal.num_trials * len(ARCHITECTURES),
        "upstream_commit": bundle.official.upstream_commit,
        "data_sha256": bundle.official.data_sha256,
        "model": formal.model,
        "agent_model_alias": formal.official_agent_model_alias,
        "user_simulator_model": formal.user_simulator_model,
        "temperature": formal.temperature,
        "agent_seed": formal.seed,
        "task_seed": formal.task_seed,
        "num_trials": formal.num_trials,
        "max_steps": formal.max_steps,
        "max_tool_calls": formal.max_tool_calls,
        "max_output_tokens": formal.max_output_tokens,
        "max_total_tokens": formal.max_total_tokens,
        "max_concurrency": formal.max_concurrency,
        "tool_inventory": "tau2-retail-original",
        "guard": "ServiceFlowTauAgent._guard/shared",
        "single_prompt_version": "tau2-single-confirmation-v3",
        "multi_prompt_version": "tau2-deterministic-supervisor-specialists-v3",
        "adapter_sha256": {
            "single": sha256_file(ROOT / "backend/app/integrations/tau2.py"),
            "multi": sha256_file(ROOT / "backend/app/integrations/tau2_multi.py"),
        },
        "scoring": {
            "implementation": "upstream_semantic_prompt_custom_model",
            "communicate_scorer": "semantic",
            "profile": formal.scoring_profile,
            "semantic_judge_provider": formal.semantic_judge_provider,
            "semantic_judge_model": formal.semantic_judge_model,
            "communicate_facts_in_development": communicate_facts,
            "openai_key_required_before_run": False,
        },
        "pricing": {
            "basis": formal.pricing_basis,
            "latest_architecture_approved_ceiling_usd": None,
            "provider_invoice_reconciliation_required": True,
            "source": "https://api-docs.deepseek.com/quick_start/pricing/",
            "rate_mode": "set_by_run_environment",
            "conservative_agent_input_usd_per_million": (
                settings.agent_input_usd_per_million
            ),
            "agent_output_usd_per_million": settings.agent_output_usd_per_million,
            "rates_usd_per_million": DEEPSEEK_FLASH_PEAK_RATES,
            "rate_schedule": "conservative_peak",
        },
        "agent_input_usd_per_million": settings.agent_input_usd_per_million,
        "agent_output_usd_per_million": settings.agent_output_usd_per_million,
        "official_holdout_executed": False,
        "external_llm_calls": 0,
        "notes": [
            "Development preflight may inspect train criteria; holdout bodies remain unopened.",
            (
                "Official tasks and upstream semantic prompt are preserved; "
                "the judge model is DeepSeek."
            ),
            "This custom-judge result is not an official default τ-bench score.",
            (
                "Agent/user message costs exclude semantic-judge billing; "
                "reconcile the provider invoice."
            ),
        ],
    }


def validate_run_request(
    split: str,
    architecture: str | None,
    approved_budget_usd: float | None,
    allow_holdout: bool,
) -> None:
    if architecture not in ARCHITECTURES:
        raise ValueError("one_architecture_required_for_paid_run")
    if approved_budget_usd is None or approved_budget_usd <= 0:
        raise ValueError("positive_approved_budget_required")
    if split == "holdout" and not allow_holdout:
        raise ValueError("holdout_requires_explicit_allow_holdout")


def estimate_holdout_ceiling_usd(
    plan: dict[str, Any], architecture: str
) -> dict[str, float | int | str]:
    """Project a full holdout run from the matching frozen development evidence."""
    if plan["split"] != "holdout":
        raise ValueError("holdout_plan_required_for_cost_projection")
    reference_run_id = DEVELOPMENT_REFERENCE_RUN_IDS[architecture]
    reference_path = (
        ROOT
        / plan["results_namespace"]
        / "development"
        / reference_run_id
        / f"{architecture}_summary.json"
    )
    if not reference_path.is_file():
        raise ValueError("matching_development_cost_reference_missing")
    reference = json.loads(reference_path.read_text(encoding="utf-8"))
    completed_runs = int(reference.get("completed_runs", 0))
    observed_cost = reference.get("estimated_total_cost_usd")
    if completed_runs <= 0 or not isinstance(observed_cost, (int, float)):
        raise ValueError("matching_development_cost_reference_invalid")
    planned_runs = int(plan["task_count"]) * int(plan["num_trials"])
    observed_per_run = float(observed_cost) / completed_runs
    projected = observed_per_run * planned_runs
    return {
        "reference": reference_path.relative_to(ROOT).as_posix(),
        "reference_runs": completed_runs,
        "reference_estimated_cost_usd": float(observed_cost),
        "planned_runs": planned_runs,
        "linear_projection_usd": projected,
        "safety_factor": HOLDOUT_COST_SAFETY_FACTOR,
        "required_ceiling_usd": projected * HOLDOUT_COST_SAFETY_FACTOR,
        "untracked_cost_reserve_usd": HOLDOUT_UNTRACKED_COST_RESERVE_USD,
    }


def validate_holdout_budget(
    plan: dict[str, Any], architecture: str, approved_budget_usd: float
) -> dict[str, float | int | str]:
    projection = estimate_holdout_ceiling_usd(plan, architecture)
    required = float(projection["required_ceiling_usd"]) + float(
        projection["untracked_cost_reserve_usd"]
    )
    if required > approved_budget_usd:
        raise ValueError(
            "approved_budget_below_projected_holdout_ceiling:"
            f" required={required:.6f} approved={approved_budget_usd:.6f}"
        )
    return projection


def apply_incident_recovery_exclusions(
    plan: dict[str, Any], excluded_task_ids: list[str], incident_recovery: bool
) -> None:
    """Exclude already-observed holdout tasks only for a documented infra recovery."""
    if not excluded_task_ids:
        return
    if plan["split"] != "holdout" or not incident_recovery:
        raise ValueError("holdout_exclusion_requires_incident_recovery")
    excluded = set(excluded_task_ids)
    unknown = excluded.difference(plan["task_ids"])
    if unknown:
        raise ValueError(f"unknown_incident_task_ids:{sorted(unknown)}")
    plan["task_ids"] = [task_id for task_id in plan["task_ids"] if task_id not in excluded]
    plan["task_count"] = len(plan["task_ids"])
    plan["simulation_count"] = plan["task_count"] * plan["num_trials"]
    plan["incident_recovery"] = {
        "excluded_already_observed_task_ids": sorted(excluded),
        "reason": "windows_checkpoint_encoding_failure_after_results_were_observed",
        "excluded_results_must_be_merged_without_rerun": True,
    }


def _set_runtime_environment(plan: dict[str, Any], settings: Settings) -> None:
    key = settings.effective_key
    if key is None or not key.get_secret_value():
        raise RuntimeError("agent_and_user_simulator_key_missing")
    if "api.deepseek.com" not in settings.effective_base_url:
        raise RuntimeError("frozen_phase5b_provider_is_deepseek_compatible")
    os.environ["DEEPSEEK_API_KEY"] = key.get_secret_value()
    os.environ["AGENT_MAX_TOOL_CALLS"] = str(plan["max_tool_calls"])
    os.environ["AGENT_MAX_OUTPUT_TOKENS"] = str(plan["max_output_tokens"])
    os.environ["AGENT_MAX_TOTAL_TOKENS"] = str(plan["max_total_tokens"])


def _result_rows(
    plan: dict[str, Any], architecture: str, summary: dict[str, Any]
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    namespace = f"{plan['results_namespace']}/{plan['split']}/{plan['run_id']}"
    for item in summary["runs"]:
        usage = item["token_usage"] or {}
        cost = item.get("estimated_agent_cost_usd")
        user_cost = item.get("estimated_user_cost_usd")
        estimated_total = "" if cost is None or user_cost is None else cost + user_cost
        rows.append(
            {
                "schema_version": "1.0",
                "track": "official_tasks_custom_judge",
                "namespace": namespace,
                "run_id": plan["run_id"],
                "architecture": architecture,
                "case_id": item["task_id"],
                "trial": item["trial"],
                "seed": item["seed"],
                "success": "" if item["success"] is None else str(item["success"]).lower(),
                "official_reward": "" if item["reward"] is None else item["reward"],
                "duration_seconds": item["duration_seconds"],
                "tool_calls": item["tool_calls"],
                "prompt_tokens": usage.get("prompt_tokens", ""),
                "completion_tokens": usage.get("completion_tokens", ""),
                "total_tokens": usage.get("total_tokens", ""),
                "cost_usd": estimated_total,
                "metric_values_json": "",
                "failure_type": item["failure_type"] or "",
                "evidence": "tau2_semantic_prompt_deepseek_judge",
            }
        )
    return rows


def build_communicate_scoring(plan: dict[str, Any]) -> Any:
    from tau2.data_model.semantic_communication import (
        CommunicateScoring,
        SemanticCommunicateSettings,
    )

    return CommunicateScoring(
        judge=SemanticCommunicateSettings(
            model=plan["scoring"]["semantic_judge_model"],
            model_args={
                "temperature": plan["temperature"],
                "extra_body": {"thinking": {"type": "disabled"}},
            },
        )
    )


def configure_deepseek_nl_assertions_judge(plan: dict[str, Any]) -> None:
    """Preserve the upstream NL prompt while routing its judge to DeepSeek."""
    from tau2.evaluator import evaluator_nl_assertions

    evaluator_nl_assertions.DEFAULT_LLM_NL_ASSERTIONS = plan["scoring"][
        "semantic_judge_model"
    ]
    evaluator_nl_assertions.DEFAULT_LLM_NL_ASSERTIONS_ARGS = {
        "temperature": plan["temperature"],
        "extra_body": {"thinking": {"type": "disabled"}},
    }


def checkpoint_prefix_count(path: Path, task_ids: list[str]) -> int:
    """Return the registered task prefix so interrupted incremental runs resume safely."""
    if not path.is_file() or path.stat().st_size == 0:
        return 1
    checkpoint = json.loads(path.read_text(encoding="utf-8"))
    checkpoint_ids = [str(task["id"]) for task in checkpoint.get("tasks", [])]
    if checkpoint_ids != task_ids[: len(checkpoint_ids)]:
        raise RuntimeError("holdout_checkpoint_task_prefix_mismatch")
    return max(1, len(checkpoint_ids))


def run_official(plan: dict[str, Any], architecture: str, budget: float) -> dict[str, Any]:
    settings = Settings()
    _set_runtime_environment(plan, settings)
    from app.integrations.tau2 import create_serviceflow_tau_agent
    from app.integrations.tau2_multi import create_serviceflow_tau_multi_agent
    from tau2.data_model.simulation import TextRunConfig
    from tau2.registry import registry
    from tau2.runner import run_domain
    from tau2.utils.utils import DATA_DIR

    configure_deepseek_nl_assertions_judge(plan)

    factory = (
        create_serviceflow_tau_agent
        if architecture == "single_agent"
        else create_serviceflow_tau_multi_agent
    )
    registry_name = f"serviceflow_phase5b_{architecture}"
    registry.register_agent_factory(factory, registry_name)
    save_to = f"serviceflow-phase5b-{plan['split']}-{architecture}-{plan['run_id']}"
    source = DATA_DIR / "simulations" / save_to / "results.json"
    def make_config(task_ids: list[str]) -> TextRunConfig:
        return TextRunConfig(
            domain="retail",
            communicate_scoring=build_communicate_scoring(plan),
            agent=registry_name,
            llm_agent=plan["agent_model_alias"],
            llm_user=plan["user_simulator_model"],
            llm_args_user={
                "temperature": plan["temperature"],
                "extra_body": {"thinking": {"type": "disabled"}},
            },
            task_split_name=plan["source_split"],
            task_ids=task_ids,
            seed=plan["task_seed"],
            num_trials=plan["num_trials"],
            max_steps=plan["max_steps"],
            max_concurrency=plan["max_concurrency"],
            auto_resume=True,
            save_to=save_to,
        )

    if plan["split"] == "holdout":
        projection = validate_holdout_budget(plan, architecture, budget)
        tracked_limit = budget - float(projection["untracked_cost_reserve_usd"])
        reference_per_run = float(projection["linear_projection_usd"]) / int(
            projection["planned_runs"]
        )
        results = None
        first_task_count = checkpoint_prefix_count(source, plan["task_ids"])
        for task_index in range(first_task_count, len(plan["task_ids"]) + 1):
            results = run_domain(make_config(plan["task_ids"][:task_index]))
            partial = summarize(results, plan)
            tracked_cost = partial.get("estimated_total_cost_usd")
            completed = int(partial.get("completed_runs", 0))
            if not isinstance(tracked_cost, (int, float)) or completed <= 0:
                raise RuntimeError("holdout_runtime_cost_unavailable")
            if task_index < len(plan["task_ids"]):
                actual_per_run = float(tracked_cost) / completed
                next_task_runs = int(plan["num_trials"])
                projected_next = max(actual_per_run, reference_per_run) * next_task_runs
                if float(tracked_cost) + projected_next > tracked_limit:
                    raise RuntimeError(
                        "holdout_budget_fuse_open:"
                        f" tracked={float(tracked_cost):.6f}"
                        f" next={projected_next:.6f} limit={tracked_limit:.6f}"
                    )
        if results is None:
            raise RuntimeError("holdout_has_no_tasks")
    else:
        results = run_domain(make_config(plan["task_ids"]))
    summary = summarize(results, plan)
    summary.update(
        {
            "phase": "5B",
            "split": plan["split"],
            "architecture": architecture,
            "run_id": plan["run_id"],
            "approved_budget_usd": budget,
            "semantic_judge_cost_included": False,
            "completed_at": datetime.now(UTC).isoformat(),
        }
    )
    raw_dir = ROOT / plan["results_namespace"] / plan["split"] / plan["run_id"]
    raw_dir.mkdir(parents=True, exist_ok=True)
    if source.is_file():
        shutil.copy2(source, raw_dir / f"{architecture}_results.json")
    summary_path = raw_dir / f"{architecture}_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    merge_results(ROOT / "reports" / "results.csv", _result_rows(plan, architecture, summary))
    return summary


def main() -> None:
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["development", "holdout"], default="development")
    parser.add_argument("--run-id", default="phase5b-initial")
    parser.add_argument("--run", action="store_true", help="Launch paid external model calls")
    parser.add_argument("--architecture", choices=ARCHITECTURES)
    parser.add_argument("--approved-budget-usd", type=float)
    parser.add_argument("--allow-holdout", action="store_true")
    parser.add_argument("--exclude-task-id", action="append", default=[])
    parser.add_argument("--incident-recovery", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.run_id):
        parser.error("--run-id may contain only letters, digits, underscores and hyphens")
    plan = build_plan(args.split, args.run_id)
    try:
        apply_incident_recovery_exclusions(
            plan, args.exclude_task_id, args.incident_recovery
        )
    except ValueError as error:
        parser.error(str(error))
    plan_path = ROOT / "reports" / f"phase5b_{args.split}_plan.json"
    plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if not args.run:
        print(
            json.dumps(
                {"status": "prepared_not_run", "plan": str(plan_path)},
                ensure_ascii=False,
            )
        )
        return
    try:
        validate_run_request(
            args.split,
            args.architecture,
            args.approved_budget_usd,
            args.allow_holdout,
        )
    except ValueError as error:
        parser.error(str(error))
    plan["pricing"]["latest_architecture_approved_ceiling_usd"] = (
        args.approved_budget_usd
    )
    if args.split == "holdout":
        try:
            plan["pricing"]["preflight_projection"] = validate_holdout_budget(
                plan, args.architecture, args.approved_budget_usd
            )
        except ValueError as error:
            parser.error(str(error))
    plan_path.write_text(
        json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    summary = run_official(plan, args.architecture, args.approved_budget_usd)
    summary_dir = ROOT / plan["results_namespace"] / plan["split"] / plan["run_id"]
    plan["completed_architectures"] = [
        architecture
        for architecture in ARCHITECTURES
        if (summary_dir / f"{architecture}_summary.json").is_file()
    ]
    plan["architecture_approved_ceilings_usd"] = {}
    plan["external_llm_calls"] = None
    plan["external_simulations"] = 0
    for completed_architecture in plan["completed_architectures"]:
        completed_summary = json.loads(
            (summary_dir / f"{completed_architecture}_summary.json").read_text(
                encoding="utf-8"
            )
        )
        plan["architecture_approved_ceilings_usd"][completed_architecture] = (
            completed_summary.get("approved_budget_usd")
        )
        plan["external_simulations"] += int(
            completed_summary.get("completed_runs", 0)
        )
    if args.split == "development" and set(plan["completed_architectures"]) == set(
        ARCHITECTURES
    ):
        plan["status"] = "development_completed_implementation_not_frozen"
    else:
        plan["status"] = "architecture_completed"
    plan_path.write_text(
        json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": "completed",
                "architecture": args.architecture,
                "completed_runs": summary["completed_runs"],
                "success_rate": summary["success_rate"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
