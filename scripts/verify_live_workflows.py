"""Real-provider product workflows in a disposable PostgreSQL schema."""

import argparse
import json
from pathlib import Path
from statistics import mean
from uuid import uuid4

from app.config import Settings
from app.database import Base, ChatTraceRow, engine_for, seed
from app.live_agent import live_chat
from app.llm import OpenAICompatibleProvider
from app.retail import load
from app.service import RetailService
from sqlalchemy.orm import Session

from scripts.fetch_tau_retail import COMMIT, digest, verify

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "tau2" / COMMIT
DEEPSEEK_OFFPEAK_RATES = {
    "cache_hit_input": 0.003,
    "cache_miss_input": 0.15,
    "output": 0.60,
}


def summarize(records: list[dict]) -> dict:
    durations = sorted(
        sum(record.get(f"{phase}_elapsed_ms", 0) or 0 for phase in ("verify", "request", "confirm"))
        / 1000
        for record in records
    )
    usage: dict[str, int] = {}
    for record in records:
        for phase in ("verify", "request", "confirm"):
            for key, value in (record.get(f"{phase}_usage") or {}).items():
                if isinstance(value, int):
                    usage[key] = usage.get(key, 0) + value
    estimated_cost = (
        usage.get("prompt_cache_hit_tokens", 0) * DEEPSEEK_OFFPEAK_RATES["cache_hit_input"]
        + usage.get("prompt_cache_miss_tokens", 0) * DEEPSEEK_OFFPEAK_RATES["cache_miss_input"]
        + usage.get("completion_tokens", 0) * DEEPSEEK_OFFPEAK_RATES["output"]
    ) / 1_000_000 if usage else None
    return {
        "success_rate": sum(bool(record["passed"]) for record in records) / len(records)
        if records else None,
        "total_tool_calls": sum(
            record.get(f"{phase}_tool_calls", 0) or 0
            for record in records for phase in ("verify", "request", "confirm")
        ),
        "average_latency_seconds": mean(durations) if durations else None,
        "p95_latency_seconds": durations[max(0, (95 * len(durations) + 99) // 100 - 1)]
        if durations else None,
        "token_usage": usage or None,
        "estimated_api_cost_usd": estimated_cost,
        "pricing": {
            "source": "https://api-docs.deepseek.com/quick_start/pricing/",
            "rates_usd_per_million": DEEPSEEK_OFFPEAK_RATES,
            "basis": "documented off-peak estimate; not provider invoice",
        },
        "failure_types": [
            record.get("request_error") for record in records if not record["passed"]
        ],
        "business_violations": None,
    }


def run(scenario_filter: str | None = None) -> dict:
    settings = Settings(agent_provider="openai_compatible")
    provider = OpenAICompatibleProvider(settings)
    verify(RAW)
    source = load(RAW / "db.json")
    engine = engine_for(settings.database_url)
    schema = "phase15_live_" + uuid4().hex
    with engine.begin() as db:
        db.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    isolated = engine.execution_options(schema_translate_map={None: schema})
    records = []
    try:
        seed(isolated, source, digest((RAW / "db.json").read_bytes()))
        service = RetailService(isolated)

        def trace_events(trace_id: str) -> list[dict]:
            with Session(isolated) as db:
                return list(db.get(ChatTraceRow, trace_id).events)

        pending = [o for o in source.orders.values() if o.status == "pending"]
        delivered = next(
            o for o in source.orders.values() if o.status == "delivered" and o.payment_history
        )
        scenarios = [
            ("query", pending[0], None),
            (
                "cancel",
                pending[0],
                {"kind": "cancel", "order_id": pending[0].order_id, "reason": "no longer needed"},
            ),
            (
                "modify_address",
                pending[1],
                {"kind": "modify_address", "order_id": pending[1].order_id},
            ),
            (
                "return",
                delivered,
                {
                    "kind": "return",
                    "order_id": delivered.order_id,
                    "item_ids": [delivered.items[0].item_id],
                    "payment_method_id": delivered.payment_history[0]["payment_method_id"],
                },
            ),
        ]
        for name, order, expected in scenarios:
            if scenario_filter and name != scenario_filter:
                continue
            sid = service.start()
            email = source.users[order.user_id].email
            verify_turn = live_chat(
                service,
                sid,
                f"My account email is {email}. Please verify my identity.",
                None,
                provider,
            )
            if service.user(sid)["user_id"] != order.user_id:
                raise RuntimeError("Agent did not bind the intended customer")
            if name == "query":
                message = f"Please check the status and items of my order {order.order_id}."
            elif name == "cancel":
                message = (
                    f"Please cancel my pending order {order.order_id}. "
                    "The reason is no longer needed."
                )
            elif name == "modify_address":
                address = dict(order.address)
                address["address1"] = "Stage 1.5 isolated test address"
                expected["address"] = address
                message = (
                    f"Please change the shipping address of my pending order "
                    f"{order.order_id} to {json.dumps(address)}."
                )
            else:
                message = (
                    f"Please request a return for item {expected['item_ids'][0]} "
                    f"in my delivered order {order.order_id}. Use my original payment "
                    f"method {expected['payment_method_id']} for the refund."
                )
            turn = live_chat(service, sid, message, None, provider)
            actual = turn["response"]
            record = {
                "scenario": name,
                "verified_trace_id": verify_turn["trace_id"],
                "request_trace_id": turn["trace_id"],
                "request_status": actual.get("status"),
                "request_tool_calls": turn["tool_calls"],
                "request_usage": turn["token_usage"],
                "request_elapsed_ms": turn["elapsed_ms"],
                "verify_usage": verify_turn["token_usage"],
                "verify_elapsed_ms": verify_turn["elapsed_ms"],
                "verify_tool_calls": verify_turn["tool_calls"],
                "request_error": actual.get("error_code"),
                "verify_events": trace_events(verify_turn["trace_id"]),
                "request_events": trace_events(turn["trace_id"]),
            }
            if name == "query":
                record["passed"] = (
                    actual.get("status") == "answered"
                    and order.status.casefold() in actual.get("message", "").casefold()
                    and any(
                        event.get("name") == "get_order_details" and not event.get("error")
                        for event in record["request_events"]
                    )
                )
            else:
                action = actual.get("action") or {}
                matches = actual.get("status") == "proposed" and all(
                    action.get(key) == value for key, value in expected.items()
                )
                record["proposal_matches_request"] = matches
                if matches:
                    confirmed = live_chat(service, sid, "yes", actual["proposal_id"], provider)
                    record["confirm_trace_id"] = confirmed["trace_id"]
                    record["confirm_status"] = confirmed["response"].get("status")
                    record["confirm_usage"] = confirmed["token_usage"]
                    record["confirm_elapsed_ms"] = confirmed["elapsed_ms"]
                    record["confirm_tool_calls"] = confirmed["tool_calls"]
                    record["confirm_events"] = trace_events(confirmed["trace_id"])
                    final = service.order(sid, order.order_id)
                    target = {
                        "cancel": "cancelled",
                        "modify_address": "pending",
                        "return": "return requested",
                    }[name]
                    record["passed"] = (
                        confirmed["response"].get("status") == "succeeded"
                        and final["status"] == target
                        and (name != "modify_address" or final["address"] == address)
                    )
                else:
                    record["passed"] = False
            records.append(record)
        return {
            "kind": "product_live",
            "provider": "deepseek",
            "model": provider.model,
            "source_commit": COMMIT,
            "sample_size": len(records),
            "passed": sum(bool(r["passed"]) for r in records),
            "summary": summarize(records),
            "records": records,
        }
    finally:
        Base.metadata.drop_all(isolated)
        with engine.begin() as db:
            db.exec_driver_sql(f'DROP SCHEMA "{schema}"')
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=["query", "cancel", "modify_address", "return"])
    args = parser.parse_args()
    result = run(args.scenario)
    output = ROOT / "reports" / "raw" / "product_live" / "phase15.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "passed": result["passed"],
                "sample_size": result["sample_size"],
                "output": str(output),
            }
        )
    )


if __name__ == "__main__":
    main()
