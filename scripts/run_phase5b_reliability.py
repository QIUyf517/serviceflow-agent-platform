"""Run the ServiceFlow-authored reliability track without external model calls."""

import argparse
import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from app.evaluation.preparation import load_and_verify_bundle
from app.evaluation.results import merge_results

ROOT = Path(__file__).resolve().parents[1]
SECRET_KEYS = (
    "AGENT_API_KEY",
    "OPENAI_API_KEY",
    "LLM_API_KEY",
    "DEEPSEEK_API_KEY",
    "POLICY_EMBEDDING_API_KEY",
)


def run_reliability(run_id: str, results_path: Path) -> tuple[dict[str, object], int]:
    bundle = load_and_verify_bundle(ROOT)
    raw_dir = ROOT / bundle.config.reliability_results_namespace / run_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    for key in SECRET_KEYS:
        environment.pop(key, None)
    environment["AGENT_PROVIDER"] = "mock"
    environment["POLICY_RETRIEVAL_STRATEGY"] = "keyword"
    rows: list[dict[str, object]] = []
    failures = 0
    for scenario in bundle.reliability.scenarios:
        started = perf_counter()
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--basetemp=.tmp/pytest-phase5b-{scenario.id}-{uuid4().hex}",
            *scenario.test_node_ids,
        ]
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        duration = perf_counter() - started
        success = completed.returncode == 0
        failures += int(not success)
        evidence_path = raw_dir / f"{scenario.id}.txt"
        evidence_path.write_text(
            completed.stdout + "\n" + completed.stderr,
            encoding="utf-8",
        )
        rows.append(
            {
                "schema_version": "1.0",
                "track": "reliability",
                "namespace": bundle.config.reliability_results_namespace,
                "run_id": run_id,
                "architecture": "serviceflow_system",
                "case_id": scenario.id,
                "trial": 1,
                "seed": bundle.config.formal.task_seed,
                "success": str(success).lower(),
                "official_reward": "",
                "duration_seconds": f"{duration:.6f}",
                "tool_calls": "",
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "cost_usd": 0,
                "metric_values_json": json.dumps(
                    scenario.expected_metrics if success else {},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "failure_type": "" if success else "pytest_assertion_failed",
                "evidence": f"pytest:{scenario.test_node_ids[0]}",
            }
        )
    target = results_path if results_path.is_absolute() else ROOT / results_path
    merge_results(target, rows)
    report: dict[str, object] = {
        "phase": "5B",
        "track": "serviceflow_reliability",
        "official_score_eligible": False,
        "run_id": run_id,
        "executed_at": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "scenario_count": len(rows),
        "passed": len(rows) - failures,
        "failed": failures,
        "external_llm_calls": 0,
        "official_holdout_executed": False,
        "results_csv": str(target.relative_to(ROOT)),
        "raw_evidence_namespace": str(raw_dir.relative_to(ROOT)),
        "metric_evidence": (
            "Each value is asserted by the bound pytest test; it is not an official score."
        ),
    }
    report_path = ROOT / "reports" / "phase5b_reliability_summary.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return report, failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default="phase5b-initial")
    parser.add_argument("--results", type=Path, default=Path("reports/results.csv"))
    args = parser.parse_args()
    report, failures = run_reliability(args.run_id, args.results)
    print(json.dumps(report, ensure_ascii=False))
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
