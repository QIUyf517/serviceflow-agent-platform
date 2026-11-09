"""Acceptance tests for the repeatable Phase 3 failure injector."""

import os

import pytest
from app.database import ExecutionAuditRow, OrderRow
from app.multi_agent.execution import ExecutionService
from app.service import BusinessError
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from scripts.inject_phase3_failures import (
    _safe_llm_timeout,
    cancellation,
    run_postgres_failure_injection,
)


def test_sqlite_timeout_is_normalized_and_tool_retry_writes_once(service):
    assert _safe_llm_timeout() == "model_request_failed"
    sid = service.start()
    service.verify(sid, email="test@example.invalid")
    proposal, eligibility = cancellation("o")
    execution = ExecutionService(service.engine)
    request = execution.prepare_cancel(
        sid,
        proposal,
        eligibility,
        "phase3-sqlite-timeout-key",
    )
    execution.record_decision(
        sid,
        request.request_id,
        decision="confirm",
        confirmation_text=request.confirmation_text,
    )
    calls = []

    def timeout_once(_: str) -> None:
        calls.append("timeout")
        if len(calls) == 1:
            raise OperationalError("UPDATE orders", {}, TimeoutError("tool timeout"))

    recovered = ExecutionService(
        service.engine,
        fault_injector=timeout_once,
        sleeper=lambda _: None,
        max_retries=1,
        retry_base_seconds=0,
        retry_max_seconds=0,
    ).execute_cancel(
        sid,
        request.request_id,
        idempotency_key=request.idempotency_key,
    )
    assert recovered.status == "succeeded" and recovered.row_version == 2
    with Session(service.engine) as db:
        assert db.get(OrderRow, "o").row_version == 2
        assert db.scalar(
            select(func.count())
            .select_from(ExecutionAuditRow)
            .where(ExecutionAuditRow.event_type == "execution_succeeded")
        ) == 1


def test_sqlite_unconfirmed_request_has_zero_writes_and_explicit_code(service):
    sid = service.start()
    service.verify(sid, email="test@example.invalid")
    proposal, eligibility = cancellation("o")
    execution = ExecutionService(service.engine)
    request = execution.prepare_cancel(
        sid,
        proposal,
        eligibility,
        "phase3-unconfirmed-zero-write",
    )
    with pytest.raises(BusinessError, match="confirmation_required"):
        execution.execute_cancel(
            sid,
            request.request_id,
            idempotency_key=request.idempotency_key,
        )
    with Session(service.engine) as db:
        assert db.get(OrderRow, "o").row_version == 1
        assert db.scalar(
            select(func.count())
            .select_from(ExecutionAuditRow)
            .where(ExecutionAuditRow.event_type == "execution_succeeded")
        ) == 0


@pytest.mark.postgres
def test_postgres_failure_injector_covers_all_scenarios_and_cleans_schema():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail("TEST_DATABASE_URL is required for the phase 3 PostgreSQL acceptance test")
    report = run_postgres_failure_injection(url)
    assert report["timeout"] == {
        "llm_failure_code": "model_request_failed",
        "tool_recovered": True,
        "order_row_version": 2,
    }
    assert report["duplicate_request"]["concurrent_code"] == "execution_in_progress"
    assert report["duplicate_request"]["serial_replay"] is True
    assert report["confirmed_interruption"]["recovered_status"] == "succeeded"
    assert report["order_changed"]["failure_code"] == "order_changed"
    assert report["order_changed"]["reproposal_required"] is True
    assert report["order_changed"]["ticket_completed"] is False
    assert report["assertions"]["unconfirmed_zero_writes"] is True
    assert report["assertions"]["recovery_audit_complete"] is True
    assert report["assertions"]["external_llm_calls"] == 0
    assert report["schema_residual"] == 0
