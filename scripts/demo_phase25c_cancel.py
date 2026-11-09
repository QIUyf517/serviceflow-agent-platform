"""Run the Phase 2.5C cancel workflow in a disposable PostgreSQL schema."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.config import Settings
from app.database import Base, engine_for, seed
from app.multi_agent.conversation import run_cancel_conversation
from app.multi_agent.execution import ExecutionService
from app.multi_agent.policy_agent import build_policy_agent
from app.multi_agent.workflow import SessionStateStore
from app.retail import load
from app.service import RetailService

from scripts.fetch_tau_retail import COMMIT, verify

RAW = Path("data/raw/tau2") / COMMIT


def _turn_view(turn: dict[str, Any]) -> dict[str, Any]:
    proposal = turn.get("resolution_proposal")
    return {
        "task_status": turn["task_status"],
        "request_id": turn.get("request_id"),
        "proposal": proposal,
        "eligibility": turn.get("eligibility_result"),
        "pending_confirmation": turn.get("pending_confirmation"),
        "execution_result": turn.get("execution_result"),
        "trace": turn["trace"],
        "tool_results": turn["tool_results"],
        "final_response": turn["final_response"],
        "metrics": turn["metrics"],
    }


def run_demo(database_url: str) -> dict[str, Any]:
    """Use only a random schema; always remove it before returning."""
    verify(RAW)
    source = load(RAW / "db.json")
    engine = engine_for(database_url)
    schema = "phase25c_demo_" + uuid4().hex
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    isolated = engine.execution_options(schema_translate_map={None: schema})
    try:
        seed(isolated, source, "phase25c-demo")
        service = RetailService(isolated)
        execution = ExecutionService(isolated)
        policy = build_policy_agent(
            isolated,
            Settings(
                _env_file=None,
                agent_provider="mock",
                policy_retrieval_strategy="keyword",
                policy_top_k=3,
                policy_embedding_api_key=None,
            ),
        )
        pending = [order for order in source.orders.values() if order.status == "pending"]
        successful = pending[0]
        owner = source.users[successful.user_id]
        sid = service.start()
        service.verify(sid, email=owner.email)
        store = SessionStateStore()
        before = service.order(sid, successful.order_id)["status"]
        first = run_cancel_conversation(
            service,
            execution,
            sid,
            f"Please cancel order {successful.order_id} because ordered by mistake",
            store,
            policy,
        )
        waiting_status = service.order(sid, successful.order_id)["status"]
        second = run_cancel_conversation(
            service,
            execution,
            sid,
            "确认",
            store,
            policy,
            request_id=first["request_id"],
        )
        after = service.order(sid, successful.order_id)["status"]

        counterexample = next(
            order for order in pending[1:] if order.user_id != successful.user_id
        )
        counter_owner = source.users[counterexample.user_id]
        counter_sid = service.start()
        service.verify(counter_sid, email=counter_owner.email)
        denied = run_cancel_conversation(
            service,
            execution,
            counter_sid,
            f"Please cancel order {counterexample.order_id} because ordered by mistake",
            SessionStateStore(),
            policy,
        )
        denied_status = service.order(counter_sid, counterexample.order_id)["status"]
        return {
            "mode": "mock_triage_keyword_policy_local_resolution",
            "external_llm_called": False,
            "schema_was_disposable": True,
            "success_case": {
                "order_id": successful.order_id,
                "database_status": {
                    "before": before,
                    "before_confirmation": waiting_status,
                    "after_confirmation": after,
                },
                "first_turn": _turn_view(first),
                "second_turn": _turn_view(second),
                "audit": execution.audit_events(sid, first["request_id"]),
            },
            "unconfirmed_counterexample": {
                "order_id": counterexample.order_id,
                "database_status": denied_status,
                "turn": _turn_view(denied),
                "audit": execution.audit_events(counter_sid, denied["request_id"]),
            },
        }
    finally:
        Base.metadata.drop_all(isolated)
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}"')
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Phase 2.5C isolated PostgreSQL cancel demonstration"
    )
    parser.add_argument(
        "--database-url",
        default=Settings().database_url,
        help="PostgreSQL database used only as a host for a random disposable schema",
    )
    parser.add_argument("--output", type=Path, help="Optional JSON output path")
    args = parser.parse_args()
    result = run_demo(args.database_url)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
