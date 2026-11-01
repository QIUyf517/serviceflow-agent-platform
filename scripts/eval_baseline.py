"""Isolated stage-1 smoke run keyed to an official task ID; no official score."""

import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

from app.agent import chat_once
from app.database import Base, engine_for, seed
from app.retail import load
from app.service import RetailService

from scripts.fetch_tau_retail import COMMIT, digest, verify

RAW = Path("data/raw/tau2") / COMMIT


def run(task_id: str, email: str, message: str, url: str) -> dict:
    verify(RAW)
    task_ids = {task["id"] for task in json.loads((RAW / "tasks.json").read_text("utf-8"))}
    if task_id not in task_ids:
        raise ValueError("Unknown official task ID")
    source = load(RAW / "db.json")
    engine = engine_for(url)
    schema = "baseline_" + uuid4().hex
    with engine.begin() as db:
        db.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    isolated = engine.execution_options(schema_translate_map={None: schema})
    try:
        seed(isolated, source, digest((RAW / "db.json").read_bytes()))
        service = RetailService(isolated)
        sid = service.start()
        service.verify(sid, email=email)
        result = chat_once(service, sid, message)
        response = result["response"]
        return {
            "task_id": task_id,
            "task_completed": None,
            "scoring": "not_run",
            "tool_calls": result["tool_calls"],
            "elapsed_ms": result["elapsed_ms"],
            "token_usage": result["token_usage"],
            "error_type": response.get("error_code"),
            "failure_reason": response.get("error_code"),
            "provider": result["provider"],
            "source_commit": COMMIT,
            "trace_id": result["trace_id"],
        }
    finally:
        Base.metadata.drop_all(isolated)
        with engine.begin() as db:
            db.exec_driver_sql(f'DROP SCHEMA "{schema}"')
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--message", required=True)
    args = parser.parse_args()
    from app.config import Settings

    url = os.environ.get("TEST_DATABASE_URL", Settings().database_url)
    print(json.dumps(run(args.task_id, args.email, args.message, url)))


if __name__ == "__main__":
    main()
