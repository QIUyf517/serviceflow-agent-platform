"""Validate Phase 5A manifests and optionally run the key-free reliability smoke set."""

import argparse
import json
import os
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.evaluation.preparation import load_and_verify_bundle, smoke_test_nodes

ROOT = Path(__file__).resolve().parents[1]


def _report_base() -> dict[str, object]:
    bundle = load_and_verify_bundle(ROOT)
    return {
        "phase": "5A",
        "status": "prepared_not_run",
        "formal_scores_generated": False,
        "official_holdout_executed": False,
        "official_development_tasks": len(bundle.official.development.task_ids),
        "official_holdout_tasks": len(bundle.official.holdout.task_ids),
        "reliability_scenarios": len(bundle.reliability.scenarios),
        "checks": list(bundle.checks),
        "external_llm_calls": 0,
    }


def run_smoke(output: Path) -> tuple[dict[str, object], int]:
    bundle = load_and_verify_bundle(ROOT)
    nodes = smoke_test_nodes(bundle)
    temp_name = f"pytest-phase5a-smoke-{uuid4().hex}"
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        f"--basetemp=.tmp/{temp_name}",
        *nodes,
    ]
    environment = os.environ.copy()
    for key in (
        "AGENT_API_KEY",
        "OPENAI_API_KEY",
        "LLM_API_KEY",
        "POLICY_EMBEDDING_API_KEY",
    ):
        environment.pop(key, None)
    environment["AGENT_PROVIDER"] = "mock"
    environment["POLICY_RETRIEVAL_STRATEGY"] = "keyword"
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
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    report = _report_base()
    report.update(
        {
            "status": "smoke_passed" if completed.returncode == 0 else "smoke_failed",
            "executed_at": datetime.now(UTC).isoformat(),
            "python": platform.python_version(),
            "smoke_scenario_ids": bundle.config.smoke_scenario_ids,
            "smoke_test_nodes": nodes,
            "pytest_exit_code": completed.returncode,
            "pytest_summary": lines[-1] if lines else "no pytest summary",
        }
    )
    if completed.returncode != 0:
        diagnostics = (completed.stdout + "\n" + completed.stderr).splitlines()
        report["pytest_diagnostics"] = diagnostics[-40:]
    output = output if output.is_absolute() else ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report, completed.returncode


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-smoke", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("reports/phase5a_smoke.json"))
    args = parser.parse_args()
    if args.run_smoke:
        report, code = run_smoke(args.output)
    else:
        report, code = _report_base(), 0
    print(json.dumps(report, ensure_ascii=False))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
