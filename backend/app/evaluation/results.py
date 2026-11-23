"""Stable, append-safe CSV contract shared by Phase 5B evaluation tracks."""

import csv
from pathlib import Path
from typing import Any, Iterable

RESULT_COLUMNS = (
    "schema_version",
    "track",
    "namespace",
    "run_id",
    "architecture",
    "case_id",
    "trial",
    "seed",
    "success",
    "official_reward",
    "duration_seconds",
    "tool_calls",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cost_usd",
    "metric_values_json",
    "failure_type",
    "evidence",
)
RESULT_KEY = ("track", "run_id", "architecture", "case_id", "trial")


def _normalized(row: dict[str, Any]) -> dict[str, str]:
    unknown = set(row) - set(RESULT_COLUMNS)
    if unknown:
        raise ValueError(f"unknown_result_columns:{','.join(sorted(unknown))}")
    return {column: str(row.get(column, "")) for column in RESULT_COLUMNS}


def merge_results(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    """Replace rows with the same stable key and preserve every unrelated result."""
    existing: list[dict[str, str]] = []
    if path.is_file():
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != RESULT_COLUMNS:
                raise ValueError("results_csv_schema_mismatch")
            existing.extend(reader)
    additions = [_normalized(row) for row in rows]
    keys = {tuple(row[column] for column in RESULT_KEY) for row in additions}
    merged = [
        row for row in existing if tuple(row[column] for column in RESULT_KEY) not in keys
    ]
    merged.extend(additions)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_COLUMNS)
        writer.writeheader()
        writer.writerows(merged)
