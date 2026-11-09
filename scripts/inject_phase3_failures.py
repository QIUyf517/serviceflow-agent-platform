"""Repeatable Phase 3 failure injection in one disposable PostgreSQL schema."""

from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import Any
from uuid import uuid4

import httpx
from app.config import Settings
from app.database import (
    AuditEventRow,
    Base,
    ExecutionAuditRow,
    ExecutionRequestRow,
    OrderRow,
    engine_for,
    seed,
)
from app.llm import OpenAICompatibleProvider, ProviderError
from app.multi_agent.execution import ExecutionService
from app.multi_agent.models import EligibilityResult, ResolutionProposal
from app.retail import validate
from app.service import BusinessError, RetailService
from app.ticketing import TicketService, ticket_idempotency_key
from pydantic import SecretStr
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session


def synthetic_source() -> dict[str, Any]:
    """Synthetic-only source; no official task, score, or customer data is read."""
    address = {
        "address1": "test",
        "address2": "",
        "city": "test",
        "country": "test",
        "state": "test",
        "zip": "00000",
    }
    order_ids = ["timeout", "duplicate", "interrupt", "changed", "unconfirmed"]
    return {
        "users": {
            "phase3-user": {
                "user_id": "phase3-user",
                "name": {"first_name": "Phase", "last_name": "Three"},
                "email": "phase3@example.invalid",
                "address": address,
                "payment_methods": {},
                "orders": order_ids,
            }
        },
        "products": {
            "phase3-product": {
                "product_id": "phase3-product",
                "name": "Synthetic product",
                "variants": {
                    "phase3-item": {
                        "item_id": "phase3-item",
                        "options": {},
                        "available": True,
                        "price": 10.0,
                    }
                },
            }
        },
        "orders": {
            order_id: {
                "order_id": order_id,
                "user_id": "phase3-user",
                "status": "pending",
                "address": address,
                "items": [
                    {
                        "item_id": "phase3-item",
                        "product_id": "phase3-product",
                        "name": "Synthetic product",
                        "options": {},
                        "price": 10.0,
                    }
                ],
                "fulfillments": [],
                "payment_history": [],
            }
            for order_id in order_ids
        },
    }


def cancellation(order_id: str) -> tuple[ResolutionProposal, EligibilityResult]:
    return (
        ResolutionProposal(
            proposal_id=f"phase3-{order_id}-proposal",
            task_id="cancel_order-proposal",
            action_type="cancel",
            order_id=order_id,
            proposed_parameters={"reason": "ordered by mistake"},
            requires_user_confirmation=True,
            requires_human_review=False,
            eligibility_status="eligible",
            status="pending_confirmation",
            explanation="Synthetic deterministic cancellation proposal.",
            validated=True,
        ),
        EligibilityResult(
            status="eligible",
            validated=True,
            rule_code="cancel_pending_order",
            checked_order_status="pending",
            explanation="The synthetic order is pending.",
        ),
    )


def prepare(
    execution: ExecutionService,
    sid: str,
    order_id: str,
    *,
    confirm: bool = True,
):
    proposal, eligibility = cancellation(order_id)
    request = execution.prepare_cancel(
        sid,
        proposal,
        eligibility,
        f"phase3-failure-{order_id}-key",
    )
    if confirm:
        execution.record_decision(
            sid,
            request.request_id,
            decision="confirm",
            confirmation_text=request.confirmation_text,
        )
    return request


def _safe_llm_timeout() -> str:
    def timeout(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("injected timeout")

    provider = OpenAICompatibleProvider(
        Settings(
            _env_file=None,
            agent_api_key=SecretStr("synthetic-test-key"),
            agent_base_url="https://example.invalid/v1",
            agent_timeout_seconds=0.01,
        ),
        transport=httpx.MockTransport(timeout),
    )
    try:
        provider.complete([{"role": "user", "content": "test"}], tools=[])
    except ProviderError as exc:
        if str(exc) != "model_request_failed":
            raise AssertionError("LLM timeout leaked a non-normalized error") from exc
        return str(exc)
    raise AssertionError("injected LLM timeout unexpectedly succeeded")


def run_scenarios(engine) -> dict[str, Any]:
    service = RetailService(engine)
    sid = service.start()
    service.verify(sid, email="phase3@example.invalid")
    report: dict[str, Any] = {}

    llm_code = _safe_llm_timeout()
    timeout_request = prepare(ExecutionService(engine), sid, "timeout")
    calls = []

    def timeout_once(stage: str) -> None:
        calls.append(stage)
        if len(calls) == 1:
            raise OperationalError("UPDATE orders", {}, TimeoutError("tool timeout"))

    timeout_execution = ExecutionService(
        engine,
        fault_injector=timeout_once,
        sleeper=lambda _: None,
        max_retries=1,
        retry_base_seconds=0,
        retry_max_seconds=0,
    )
    timeout_result = timeout_execution.execute_cancel(
        sid,
        timeout_request.request_id,
        idempotency_key=timeout_request.idempotency_key,
    )
    report["timeout"] = {
        "llm_failure_code": llm_code,
        "tool_recovered": timeout_result.status == "succeeded",
        "order_row_version": timeout_result.row_version,
    }

    duplicate_execution = ExecutionService(engine)
    duplicate_request = prepare(duplicate_execution, sid, "duplicate")
    lease_acquired = Event()
    release_execution = Event()

    def pause_after_lease(_: str) -> None:
        lease_acquired.set()
        if not release_execution.wait(timeout=10):
            raise AssertionError("concurrent duplicate synchronization timed out")

    first_execution = ExecutionService(
        engine,
        lease_fault_injector=pause_after_lease,
        max_retries=0,
    )

    def first_call():
        return first_execution.execute_cancel(
            sid,
            duplicate_request.request_id,
            idempotency_key=duplicate_request.idempotency_key,
        )

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(first_call)
        if not lease_acquired.wait(timeout=10):
            raise AssertionError("execution lease was not acquired")
        try:
            duplicate_execution.execute_cancel(
                sid,
                duplicate_request.request_id,
                idempotency_key=duplicate_request.idempotency_key,
            )
        except BusinessError as exc:
            if exc.code != "execution_in_progress":
                raise
            concurrent_code = exc.code
        else:
            raise AssertionError("concurrent duplicate bypassed the execution lease")
        finally:
            release_execution.set()
        first_result = pending.result(timeout=10)
    replay = duplicate_execution.execute_cancel(
        sid,
        duplicate_request.request_id,
        idempotency_key=duplicate_request.idempotency_key,
    )
    report["duplicate_request"] = {
        "concurrent_code": concurrent_code,
        "first_status": first_result.status,
        "serial_replay": replay.idempotent_replay,
        "order_row_version": replay.row_version,
    }

    now = [1_000.0]
    interrupt_request = prepare(ExecutionService(engine), sid, "interrupt")

    def terminate(_: str) -> None:
        raise RuntimeError("simulated process termination")

    interrupted = ExecutionService(
        engine,
        clock=lambda: now[0],
        lease_seconds=10,
        max_retries=0,
        lease_fault_injector=terminate,
    )
    try:
        interrupted.execute_cancel(
            sid,
            interrupt_request.request_id,
            idempotency_key=interrupt_request.idempotency_key,
        )
    except RuntimeError as exc:
        if str(exc) != "simulated process termination":
            raise
    else:
        raise AssertionError("process interruption was not injected")
    with Session(engine) as db:
        interrupted_row = db.get(ExecutionRequestRow, interrupt_request.request_id)
        if interrupted_row.status != "executing":
            raise AssertionError("interrupted request did not retain recoverable state")
        if db.get(OrderRow, "interrupt").row_version != 1:
            raise AssertionError("interruption caused a partial business write")
    now[0] += 11
    recovery = ExecutionService(
        engine,
        clock=lambda: now[0],
        lease_seconds=10,
        max_retries=0,
    ).execute_cancel(
        sid,
        interrupt_request.request_id,
        idempotency_key=interrupt_request.idempotency_key,
    )
    report["confirmed_interruption"] = {
        "recovered_status": recovery.status,
        "order_row_version": recovery.row_version,
    }

    changed_execution = ExecutionService(engine)
    changed_request = prepare(changed_execution, sid, "changed")
    with Session(engine) as db, db.begin():
        order = db.get(OrderRow, "changed")
        payload = dict(order.order_json)
        payload["status"] = "processed"
        order.order_json = payload
        order.status = "processed"
        order.row_version += 1
    try:
        changed_execution.execute_cancel(
            sid,
            changed_request.request_id,
            idempotency_key=changed_request.idempotency_key,
        )
    except BusinessError as exc:
        if exc.code != "order_changed":
            raise
        changed_code = exc.code
    else:
        raise AssertionError("changed order was incorrectly executed")
    ticket = TicketService(engine).create(
        sid,
        category="execution_failed",
        severity="high",
        priority=2,
        reason_code="order_changed",
        summary="Order state changed; a new proposal is required.",
        requested_action={"action": "repropose", "order_id": "changed"},
        idempotency_key=ticket_idempotency_key(
            sid,
            "execution_failed",
            "order_changed",
            request_id=changed_request.request_id,
        ),
        actor="system",
        order_id="changed",
        request_id=changed_request.request_id,
    )
    report["order_changed"] = {
        "failure_code": changed_code,
        "reproposal_required": True,
        "ticket_status": ticket["status"],
        "ticket_completed": False,
    }

    unconfirmed_execution = ExecutionService(engine)
    unconfirmed = prepare(
        unconfirmed_execution,
        sid,
        "unconfirmed",
        confirm=False,
    )
    try:
        unconfirmed_execution.execute_cancel(
            sid,
            unconfirmed.request_id,
            idempotency_key=unconfirmed.idempotency_key,
        )
    except BusinessError as exc:
        if exc.code != "confirmation_required":
            raise
    else:
        raise AssertionError("unconfirmed request performed a business write")

    with Session(engine) as db:
        versions = {
            order_id: db.get(OrderRow, order_id).row_version
            for order_id in (
                "timeout",
                "duplicate",
                "interrupt",
                "changed",
                "unconfirmed",
            )
        }
        success_counts = {
            request_id: db.scalar(
                select(func.count())
                .select_from(ExecutionAuditRow)
                .where(
                    ExecutionAuditRow.request_id == request_id,
                    ExecutionAuditRow.event_type == "execution_succeeded",
                )
            )
            for request_id in (
                timeout_request.request_id,
                duplicate_request.request_id,
                interrupt_request.request_id,
            )
        }
        recovery_events = db.scalars(
            select(AuditEventRow.event_type).where(
                AuditEventRow.request_id == interrupt_request.request_id
            )
        ).all()
        changed_row = db.get(ExecutionRequestRow, changed_request.request_id)
    if versions != {
        "timeout": 2,
        "duplicate": 2,
        "interrupt": 2,
        "changed": 2,
        "unconfirmed": 1,
    }:
        raise AssertionError(f"unexpected row versions: {versions}")
    if any(count != 1 for count in success_counts.values()):
        raise AssertionError(f"business write was not exactly once: {success_counts}")
    if recovery_events.count("recovery_attempted") != 1 or recovery_events.count(
        "recovery_succeeded"
    ) != 1:
        raise AssertionError("unified recovery audit is incomplete")
    if changed_row.status != "failed" or changed_row.failure_reason != "order_changed":
        raise AssertionError("order change did not persist an explicit failure code")
    report["assertions"] = {
        "order_versions": versions,
        "success_event_counts": success_counts,
        "unconfirmed_zero_writes": versions["unconfirmed"] == 1,
        "recovery_audit_complete": True,
        "external_llm_calls": 0,
    }
    return report


def run_postgres_failure_injection(url: str) -> dict[str, Any]:
    engine = engine_for(url)
    schema = "phase3_failures_" + uuid4().hex
    isolated = engine.execution_options(schema_translate_map={None: schema})
    report: dict[str, Any] | None = None
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        seed(isolated, validate(synthetic_source()), "phase3-failure-injection")
        report = run_scenarios(isolated)
    finally:
        try:
            Base.metadata.drop_all(isolated)
        finally:
            with engine.begin() as connection:
                connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    with engine.connect() as connection:
        residual = connection.execute(
            text("SELECT count(1) FROM pg_namespace WHERE nspname = :schema"),
            {"schema": schema},
        ).scalar_one()
    engine.dispose()
    if report is None:
        raise AssertionError("failure injection did not produce a report")
    report["schema"] = schema
    report["schema_residual"] = residual
    if residual != 0:
        raise AssertionError(f"failure schema was not removed: {schema}")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database-url",
        default=os.environ.get("TEST_DATABASE_URL"),
        help="Dedicated PostgreSQL database ending in _demo (or TEST_DATABASE_URL).",
    )
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("TEST_DATABASE_URL or --database-url is required")
    print(json.dumps(run_postgres_failure_injection(args.database_url), indent=2))


if __name__ == "__main__":
    main()
