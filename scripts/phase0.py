"""One command: verify/inspect, import twice, test, and lint. Fails on any failing step."""

import os
import subprocess
import sys

from app.config import Settings

from scripts.fetch_tau_retail import ROOT


def main() -> None:
    environment = dict(os.environ)
    environment.setdefault("TEST_DATABASE_URL", Settings().database_url)
    for command in (
        [sys.executable, "-m", "scripts.fetch_tau_retail"],
        [
            sys.executable,
            "-m",
            "scripts.inspect_tau_retail",
            "--output",
            "data/processed/structure_report.json",
        ],
        [sys.executable, "-m", "scripts.seed_database"],
        [sys.executable, "-m", "scripts.seed_database"],
        [sys.executable, "-m", "pytest", "-q"],
        [sys.executable, "-m", "ruff", "check", "backend", "scripts", "tests"],
    ):
        subprocess.run(command, cwd=ROOT, check=True, env=environment)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(f"Phase 0 incomplete: a validation step exited with status {exc.returncode}")
        raise SystemExit(exc.returncode) from None
