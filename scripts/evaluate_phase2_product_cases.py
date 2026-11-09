"""Run the same product cases through controlled single- and multi-agent paths."""

import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

from app.config import Settings
from app.database import engine_for, seed
from app.multi_agent.conversation import run_after_sales_conversation
from app.multi_agent.execution import ExecutionService
from app.multi_agent.policy_agent import build_policy_agent
from app.multi_agent.workflow import SessionStateStore
from app.retail import load
from app.service import RetailService
from app.single_agent_controlled import run_controlled_single_agent

from scripts.fetch_tau_retail import COMMIT, verify

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/tau2" / COMMIT


def _candidates(source):
    cancel = next(order for order in source.orders.values() if order.status == "pending")
    returned = next(
        order
        for order in source.orders.values()
        if order.status == "delivered"
        and order.items
        and order.payment_history
        and order.payment_history[0]["payment_method_id"]
        in source.users[order.user_id].payment_methods
    )
    return {
        "query": (cancel, f"check order {cancel.order_id} status"),
        "cancel": (
            cancel,
            f"Please cancel order {cancel.order_id} because ordered by mistake",
        ),
        "return": (
            returned,
            (
                f"Please return delivered order {returned.order_id} under the return policy "
                f"item_quantities={returned.items[0].item_id}:1 "
                f"payment_method_id={returned.payment_history[0]['payment_method_id']}"
            ),
        ),
    }


def _run_case(base_engine, source, architecture: str, name: str, order, message: str) -> dict:
    schema = f"phase26_compare_{uuid4().hex}"
    with base_engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    isolated = base_engine.execution_options(schema_translate_map={None: schema})
    try:
        seed(isolated, source, f"phase26-{architecture}-{name}")
        service = RetailService(isolated)
        execution = ExecutionService(isolated)
        policy = build_policy_agent(
            isolated,
            Settings(
                _env_file=None,
                agent_provider="mock",
                policy_retrieval_strategy="keyword",
                policy_top_k=5,
            ),
        )
        owner = source.users[order.user_id]
        sid = service.start()
        service.verify(sid, email=owner.email)
        before = service.order(sid, order.order_id)["status"]
        if architecture == "multi_agent":
            store = SessionStateStore()
            first = run_after_sales_conversation(
                service, execution, sid, message, store, policy
            )
            if name == "query":
                final = first
            else:
                final = run_after_sales_conversation(
                    service,
                    execution,
                    sid,
                    "确认",
                    store,
                    policy,
                    request_id=first["request_id"],
                )
        else:
            first = run_controlled_single_agent(
                service, execution, policy, sid, message
            )
            if name == "query":
                final = first
            else:
                final = run_controlled_single_agent(
                    service,
                    execution,
                    policy,
                    sid,
                    "确认",
                    request_id=first["request"]["request_id"],
                )
        after = service.order(sid, order.order_id)["status"]
        request_id = first.get("request_id") or (first.get("request") or {}).get("request_id")
        audit = execution.audit_events(sid, request_id) if request_id else []
        pending = first.get("pending_confirmation") or first.get("request")
        first_metrics = first.get("metrics", {})
        final_metrics = final.get("metrics", {})
        return {
            "architecture": architecture,
            "case": name,
            "input": message,
            "initial_status": before,
            "final_status": after,
            "first_status": first["task_status"],
            "final_task_status": final["task_status"],
            "confirmation_summary": pending.get("summary") if pending else None,
            "trace": first.get("trace", [])
            + ([] if final is first else final.get("trace", [])),
            "tool_calls": first_metrics.get("tool_calls", 0)
            + (0 if final is first else final_metrics.get("tool_calls", 0)),
            "elapsed_ms": first_metrics.get("elapsed_ms", 0)
            + (0 if final is first else final_metrics.get("elapsed_ms", 0)),
            "provider": final_metrics.get("provider"),
            "model": final_metrics.get("model"),
            "token_usage": final_metrics.get("token_usage"),
            "audit_events": [event["event_type"] for event in audit],
            "failure_reason": final.get("failure_reason"),
        }
    finally:
        with base_engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')


def run() -> dict:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        raise RuntimeError("TEST_DATABASE_URL is required")
    verify(RAW)
    source = load(RAW / "db.json")
    engine = engine_for(url)
    try:
        cases = _candidates(source)
        results = [
            _run_case(engine, source, architecture, name, order, message)
            for architecture in ("single_agent", "multi_agent")
            for name, (order, message) in cases.items()
        ]
    finally:
        engine.dispose()
    return {
        "name": "serviceflow-phase2-product-comparison",
        "official_tau_bench_score": None,
        "provider": "mock_local",
        "model": "deterministic-v1",
        "comparable_controls": [
            "same source snapshot",
            "random isolated PostgreSQL schema per run",
            "same verified identity",
            "same deterministic business rules",
            "same trusted confirmation and ExecutionService",
            "same natural-language input per case",
        ],
        "limitations": [
            "Mock orchestration validates engineering behavior, not model quality.",
            "The six runs are functional cases, not an official tau-bench evaluation.",
        ],
        "results": results,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run()
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
