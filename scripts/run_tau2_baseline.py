"""Run pinned official Retail text tasks, or prepare a key-free reproducible plan."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from statistics import mean
from typing import Any

from app.config import Settings

from scripts.fetch_tau_retail import COMMIT, verify

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "vendor" / "tau2-bench"
RAW = ROOT / "data" / "raw" / "tau2" / COMMIT
NAMES = ("db.json", "policy.md", "tasks.json", "split_tasks.json")
DEEPSEEK_OFFPEAK_RATES = {
    "cache_hit_input": 0.003,
    "cache_miss_input": 0.15,
    "output": 0.60,
}


def verify_upstream() -> dict[str, str]:
    if not (UPSTREAM / ".git").exists():
        raise RuntimeError("Clone pinned tau2-bench into ignored vendor/tau2-bench first")
    head = subprocess.check_output(
        ["git", "-C", str(UPSTREAM), "rev-parse", "HEAD"], text=True
    ).strip()
    if head != COMMIT:
        raise RuntimeError("Official checkout is not the pinned commit")
    verify(RAW)
    hashes = {}
    for name in NAMES:
        blob = subprocess.check_output(
            ["git", "-C", str(UPSTREAM), "show", f"HEAD:data/tau2/domains/retail/{name}"]
        )
        expected = hashlib.sha256((RAW / name).read_bytes()).hexdigest()
        if hashlib.sha256(blob).hexdigest() != expected:
            raise RuntimeError(f"Official {name} does not match the pinned source")
        hashes[name] = expected
    return hashes


def build_plan(phase: str, settings: Settings) -> dict[str, Any]:
    hashes = verify_upstream()
    from tau2.runner import get_tasks

    count = 2 if phase == "smoke" else 10
    # The pinned default scorer needs an OpenAI semantic judge only for tasks
    # with communicate_info. Keep the original tasks and scorer unchanged.
    tasks = [
        task for task in get_tasks("retail", task_split_name="train")
        if not (task.evaluation_criteria and task.evaluation_criteria.communicate_info)
    ][:count]
    if len(tasks) != count:
        raise RuntimeError("Not enough judge-free official tasks for this fixed sample")
    deepseek = "api.deepseek.com" in settings.effective_base_url
    model = (
        "deepseek-flash"
        if deepseek and settings.effective_model == "deepseek-v4-flash"
        else settings.effective_model
    )
    user_model = os.environ.get(
        "TAU_USER_MODEL", f"deepseek/{model}" if deepseek else model
    )
    user_model_args = (
        {"temperature": 0, "extra_body": {"thinking": {"type": "disabled"}}}
        if deepseek else {"temperature": 0}
    )
    return {
        "kind": "official_tau2_retail_text",
        "phase": phase,
        "upstream_commit": COMMIT,
        "data_sha256": hashes,
        "task_split": "train",
        "task_ids": [task.id for task in tasks],
        "agent": "serviceflow_single",
        "adapter_revision": "confirmation-v2",
        "agent_provider": "openai_compatible",
        "agent_model": model,
        "agent_base_url": settings.effective_base_url,
        "agent_temperature": settings.agent_temperature,
        "agent_seed": None if deepseek else settings.agent_seed,
        "user_model": user_model,
        "user_model_args": user_model_args,
        "task_selection": "first judge-free train tasks in official order",
        "seed": 42,
        "num_trials": 1,
        "max_steps": 40,
        "max_concurrency": 1,
        "scoring": "upstream_default",
        "agent_input_usd_per_million": settings.agent_input_usd_per_million,
        "agent_output_usd_per_million": settings.agent_output_usd_per_million,
        "pricing": {
            "source": "https://api-docs.deepseek.com/quick_start/pricing/",
            "rates_usd_per_million": DEEPSEEK_OFFPEAK_RATES if deepseek else None,
            "basis": "documented off-peak estimate; not provider invoice" if deepseek else None,
        },
    }


def summarize(results: Any, plan: dict[str, Any]) -> dict[str, Any]:
    rates = plan.get("pricing", {}).get("rates_usd_per_million")

    def estimated_cost(usage: dict[str, int]) -> float | None:
        output_tokens = usage.get("completion_tokens")
        if rates and output_tokens is not None:
            cache_hit = usage.get("prompt_cache_hit_tokens", 0)
            cache_miss = usage.get("prompt_cache_miss_tokens")
            if cache_miss is None:
                cache_miss = usage.get("prompt_tokens", 0) - cache_hit
            return (
                cache_hit * rates["cache_hit_input"]
                + cache_miss * rates["cache_miss_input"]
                + output_tokens * rates["output"]
            ) / 1_000_000
        input_tokens = usage.get("prompt_tokens")
        if (
            input_tokens is not None
            and output_tokens is not None
            and plan["agent_input_usd_per_million"] is not None
            and plan["agent_output_usd_per_million"] is not None
        ):
            return (
                input_tokens * plan["agent_input_usd_per_million"]
                + output_tokens * plan["agent_output_usd_per_million"]
            ) / 1_000_000
        return None

    simulations = results.simulations
    rows = []
    for sim in simulations:
        usage: dict[str, int] = {}
        user_usage: dict[str, int] = {}
        tool_calls = 0
        guard_rejections = 0
        tool_errors = 0
        for message in sim.messages or []:
            if getattr(message, "role", None) == "assistant":
                tool_calls += len(getattr(message, "tool_calls", None) or [])
                guard_rejections += int(
                    bool((getattr(message, "raw_data", None) or {}).get("guard_rejection"))
                )
                for key, value in (getattr(message, "usage", None) or {}).items():
                    if isinstance(value, int):
                        usage[key] = usage.get(key, 0) + value
            elif getattr(message, "role", None) == "user":
                for key, value in (getattr(message, "usage", None) or {}).items():
                    if isinstance(value, int):
                        user_usage[key] = user_usage.get(key, 0) + value
            elif getattr(message, "role", None) == "tool":
                tool_errors += int(bool(getattr(message, "error", False)))
        reward = sim.reward_info.reward if sim.reward_info else None
        rows.append(
            {
                "task_id": sim.task_id,
                "simulation_id": sim.id,
                "trial": sim.trial,
                "seed": sim.seed,
                "reward": reward,
                "success": reward == 1 if reward is not None else None,
                "duration_seconds": sim.duration,
                "tool_calls": tool_calls,
                "token_usage": usage or None,
                "user_token_usage": user_usage or None,
                "agent_cost_usd": sim.agent_cost,
                "user_cost_usd": sim.user_cost,
                "estimated_agent_cost_usd": estimated_cost(usage),
                "estimated_user_cost_usd": estimated_cost(user_usage),
                "guard_rejections": guard_rejections,
                "tool_errors": tool_errors,
                "failure_type": None if reward == 1 else str(sim.termination_reason),
                "business_violations": None,
            }
        )
    durations = sorted(row["duration_seconds"] for row in rows)
    successes = [row["success"] for row in rows if row["success"] is not None]
    totals: dict[str, int] = {}
    user_totals: dict[str, int] = {}
    for row in rows:
        for key, value in (row["token_usage"] or {}).items():
            totals[key] = totals.get(key, 0) + value
        for key, value in (row["user_token_usage"] or {}).items():
            user_totals[key] = user_totals.get(key, 0) + value
    cost = estimated_cost(totals)
    estimated_user_cost = estimated_cost(user_totals)
    user_cost = sum(row["user_cost_usd"] or 0 for row in rows)
    return {
        "evaluation": "official_tau2",
        "completed_runs": len(rows),
        "scored_runs": len(successes),
        "success_rate": sum(successes) / len(successes) if successes else None,
        "average_latency_seconds": mean(durations) if durations else None,
        "p95_latency_seconds": durations[max(0, int(0.95 * len(durations) + 0.999) - 1)]
        if durations
        else None,
        "total_tool_calls": sum(row["tool_calls"] for row in rows),
        "token_usage": totals or None,
        "user_simulator_token_usage": user_totals or None,
        "estimated_agent_cost_usd": cost,
        "reported_user_simulator_cost_usd": user_cost,
        "estimated_user_simulator_cost_usd": estimated_user_cost,
        "estimated_total_cost_usd": (
            cost + estimated_user_cost
            if cost is not None and estimated_user_cost is not None
            else None
        ),
        "pricing": plan.get("pricing"),
        "guard_rejections": sum(row["guard_rejections"] for row in rows),
        "business_violations": None,
        "runs": rows,
    }


def main() -> None:
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["smoke", "baseline"], default="smoke")
    parser.add_argument("--run", action="store_true", help="Use paid agent and user models")
    parser.add_argument(
        "--summarize-only", action="store_true", help="Rebuild metrics from saved official results"
    )
    parser.add_argument("--run-id", default="", help="Optional safe suffix for a fresh repeat")
    args = parser.parse_args()
    if args.run and args.summarize_only:
        parser.error("Choose either --run or --summarize-only")
    if args.run_id and not re.fullmatch(r"[A-Za-z0-9_-]+", args.run_id):
        parser.error("--run-id may contain only letters, digits, underscores and hyphens")
    settings = Settings()
    plan = build_plan(args.phase, settings)
    plan["run_id"] = args.run_id or "initial"
    label = f"{args.phase}_{args.run_id}" if args.run_id else args.phase
    config_path = ROOT / "reports" / f"tau2_{label}_config.json"
    config_path.parent.mkdir(exist_ok=True)
    config_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if not args.run and not args.summarize_only:
        print(
            json.dumps(
                {
                    "status": "prepared_not_run",
                    "config": str(config_path),
                    "task_count": len(plan["task_ids"]),
                }
            )
        )
        return
    if args.run:
        key = settings.effective_key
        if key is None or not key.get_secret_value():
            raise RuntimeError("Agent and user simulator API key is required; no run started")
        if "api.deepseek.com" in settings.effective_base_url:
            os.environ["DEEPSEEK_API_KEY"] = key.get_secret_value()
        elif not os.environ.get("OPENAI_API_KEY"):
            os.environ["OPENAI_API_KEY"] = key.get_secret_value()
    from app.integrations.tau2 import create_serviceflow_tau_agent
    from tau2.data_model.simulation import Results, TextRunConfig
    from tau2.registry import registry
    from tau2.runner import run_domain
    from tau2.utils.utils import DATA_DIR

    registry.register_agent_factory(create_serviceflow_tau_agent, "serviceflow_single")
    run_name = f"serviceflow-stage15-{args.phase}-{plan['agent_model']}-confirmation-v2"
    if args.run_id:
        run_name += f"-{args.run_id}"
    config = TextRunConfig(
        domain="retail",
        agent="serviceflow_single",
        llm_agent=plan["agent_model"],
        llm_user=plan["user_model"],
        llm_args_user=plan["user_model_args"],
        task_split_name="train",
        task_ids=plan["task_ids"],
        seed=42,
        num_trials=1,
        max_steps=plan["max_steps"],
        max_concurrency=1,
        auto_resume=True,
        save_to=run_name,
    )
    if args.summarize_only:
        results = Results.load(DATA_DIR / "simulations" / run_name / "results.json")
    else:
        results = run_domain(config)
    summary = summarize(results, plan)
    output_dir = ROOT / "reports" / "raw" / "official" / args.phase
    if args.run_id:
        output_dir /= args.run_id
    output = output_dir / "summary.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "completed",
                "summary": str(output),
                "success_rate": summary["success_rate"],
                "completed_runs": summary["completed_runs"],
            }
        )
    )


if __name__ == "__main__":
    main()
    # The pinned upstream/LiteLLM import leaves non-daemon workers alive on Windows.
    # All output is closed above; bypass their idle wait after a successful run.
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
