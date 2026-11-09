"""Phase 3 execution lease, retry, and recovery coverage."""

import os
from copy import deepcopy
from uuid import uuid4

import pytest
from app.database import (
    AuditEventRow,
    Base,
    ExecutionAuditRow,
    ExecutionRequestRow,
    OrderRow,
    engine_for,
    ensure_execution_reliability_schema,
    seed,
)
from app.multi_agent.execution import ExecutionService
from app.multi_agent.models import EligibilityResult, ResolutionProposal
from app.retail import validate
from app.service import BusinessError, RetailService
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session


def verified(service: RetailService) -> str:
    sid = service.start()
    service.verify(sid, email="test@example.invalid")
    return sid


def proposal() -> tuple[ResolutionProposal, EligibilityResult]:
    return (
        ResolutionProposal(
            proposal_id="phase3-recovery-proposal",
            task_id="cancel_order-proposal",
            action_type="cancel",
            order_id="o",
            proposed_parameters={"reason": "ordered by mistake"},
            requires_user_confirmation=True,
            requires_human_review=False,
            eligibility_status="eligible",
            status="pending_confirmation",
            explanation="The pending order is eligible for cancellation.",
            validated=True,
        ),
        EligibilityResult(
            status="eligible",
            validated=True,
            rule_code="cancel_pending_order",
            checked_order_status="pending",
            explanation="The deterministic service rule accepted this request.",
        ),
    )


def confirmed_request(service: RetailService, *, key: str):
    sid = verified(service)
    planned, eligibility = proposal()
    execution = ExecutionService(service.engine)
    request = execution.prepare_cancel(sid, planned, eligibility, key)
    execution.record_decision(
        sid,
        request.request_id,
        decision="confirm",
        confirmation_text=request.confirmation_text,
    )
    return sid, request


def test_expired_execution_lease_recovers_once_after_interruption(service):
    now = [1_000.0]
    sid, request = confirmed_request(service, key="phase3-interruption-recovery")

    def interrupt(stage: str) -> None:
        assert stage == "after_lease_acquired"
        raise RuntimeError("simulated process termination")

    interrupted = ExecutionService(
        service.engine,
        clock=lambda: now[0],
        lease_seconds=10,
        max_retries=0,
        lease_fault_injector=interrupt,
    )
    with pytest.raises(RuntimeError, match="simulated process termination"):
        interrupted.execute_cancel(
            sid,
            request.request_id,
            idempotency_key=request.idempotency_key,
        )

    with Session(service.engine) as db:
        row = db.get(ExecutionRequestRow, request.request_id)
        assert row.status == "executing"
        assert row.attempt_count == 1
        assert db.get(OrderRow, "o").row_version == 1

    active_lease = ExecutionService(
        service.engine,
        clock=lambda: now[0],
        lease_seconds=10,
        max_retries=0,
    )
    with pytest.raises(BusinessError, match="execution_in_progress"):
        active_lease.execute_cancel(
            sid,
            request.request_id,
            idempotency_key=request.idempotency_key,
        )

    now[0] += 11
    recovered = ExecutionService(
        service.engine,
        clock=lambda: now[0],
        lease_seconds=10,
        max_retries=0,
    )
    result = recovered.execute_cancel(
        sid,
        request.request_id,
        idempotency_key=request.idempotency_key,
    )
    replay = recovered.execute_cancel(
        sid,
        request.request_id,
        idempotency_key=request.idempotency_key,
    )

    assert result.after_status == "cancelled"
    assert replay.idempotent_replay is True
    with Session(service.engine) as db:
        row = db.get(ExecutionRequestRow, request.request_id)
        assert row.status == "succeeded" and row.attempt_count == 2
        assert row.lease_owner is None and row.lease_expires_at is None
        assert db.get(OrderRow, "o").row_version == 2
        events = db.scalars(
            select(ExecutionAuditRow).where(
                ExecutionAuditRow.request_id == request.request_id
            )
        ).all()
        event_types = [event.event_type for event in events]
        assert event_types.count("execution_recovery_attempted") == 1
        assert event_types.count("execution_succeeded") == 1
        unified = db.scalars(
            select(AuditEventRow.event_type).where(
                AuditEventRow.request_id == request.request_id
            )
        ).all()
        assert unified.count("recovery_attempted") == 1
        assert unified.count("recovery_succeeded") == 1


def test_retryable_database_error_restarts_from_fresh_state(service):
    sid, request = confirmed_request(service, key="phase3-transient-retry-test")
    calls = []
    sleeps = []

    def fail_once(stage: str) -> None:
        calls.append(stage)
        if len(calls) == 1:
            raise OperationalError("UPDATE orders", {}, Exception("transient"))

    execution = ExecutionService(
        service.engine,
        fault_injector=fail_once,
        sleeper=sleeps.append,
        max_retries=1,
        retry_base_seconds=0.01,
        retry_max_seconds=0.01,
    )
    result = execution.execute_cancel(
        sid,
        request.request_id,
        idempotency_key=request.idempotency_key,
    )

    assert result.after_status == "cancelled"
    assert sleeps == [0.01]
    with Session(service.engine) as db:
        row = db.get(ExecutionRequestRow, request.request_id)
        assert row.status == "succeeded" and row.attempt_count == 2
        assert db.get(OrderRow, "o").row_version == 2
        event_types = db.scalars(
            select(ExecutionAuditRow.event_type).where(
                ExecutionAuditRow.request_id == request.request_id
            )
        ).all()
        assert event_types.count("execution_retry_scheduled") == 1
        assert event_types.count("execution_succeeded") == 1
        assert "execution_failed" not in event_types


def test_order_change_is_not_retried_and_stays_explainable(service):
    sid, request = confirmed_request(service, key="phase3-order-change-test-key")
    with Session(service.engine) as db, db.begin():
        order = db.get(OrderRow, "o")
        changed = deepcopy(order.order_json)
        changed["status"] = "processed"
        order.order_json = changed
        order.status = "processed"
        order.row_version += 1

    sleeps = []
    execution = ExecutionService(
        service.engine,
        sleeper=sleeps.append,
        max_retries=3,
    )
    with pytest.raises(BusinessError, match="order_changed"):
        execution.execute_cancel(
            sid,
            request.request_id,
            idempotency_key=request.idempotency_key,
        )

    assert sleeps == []
    with Session(service.engine) as db:
        order = db.get(OrderRow, "o")
        row = db.get(ExecutionRequestRow, request.request_id)
        assert order.status == "processed" and order.row_version == 2
        assert row.status == "failed" and row.failure_reason == "order_changed"
        assert db.scalar(
            select(func.count())
            .select_from(ExecutionAuditRow)
            .where(
                ExecutionAuditRow.request_id == request.request_id,
                ExecutionAuditRow.event_type == "execution_failed",
            )
        ) == 1


def test_existing_execution_table_gets_non_destructive_lease_columns(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE execution_requests (id VARCHAR PRIMARY KEY)"
        )
        connection.exec_driver_sql(
            "INSERT INTO execution_requests (id) VALUES ('existing-request')"
        )

    ensure_execution_reliability_schema(engine)
    ensure_execution_reliability_schema(engine)

    assert {
        "lease_owner",
        "lease_expires_at",
        "attempt_count",
        "last_attempt_at",
    }.issubset({column["name"] for column in inspect(engine).get_columns("execution_requests")})
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT id FROM execution_requests"
        ).scalar_one() == "existing-request"
    engine.dispose()


@pytest.mark.postgres
def test_postgres_expired_lease_recovery_is_exactly_once(sample):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail("TEST_DATABASE_URL is required for the phase 3 PostgreSQL acceptance test")
    engine = engine_for(url)
    schema = "phase3_recovery_" + uuid4().hex
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    isolated = engine.execution_options(schema_translate_map={None: schema})
    try:
        seed(isolated, validate(sample), "phase3-recovery")
        service = RetailService(isolated)
        sid, request = confirmed_request(
            service,
            key="phase3-postgres-recovery-key",
        )
        now = [2_000.0]

        def interrupt(_: str) -> None:
            raise RuntimeError("simulated process termination")

        crashed = ExecutionService(
            isolated,
            clock=lambda: now[0],
            lease_seconds=10,
            max_retries=0,
            lease_fault_injector=interrupt,
        )
        with pytest.raises(RuntimeError, match="simulated process termination"):
            crashed.execute_cancel(
                sid,
                request.request_id,
                idempotency_key=request.idempotency_key,
            )

        now[0] += 11
        recovered = ExecutionService(
            isolated,
            clock=lambda: now[0],
            lease_seconds=10,
            max_retries=0,
        )
        result = recovered.execute_cancel(
            sid,
            request.request_id,
            idempotency_key=request.idempotency_key,
        )
        replay = recovered.execute_cancel(
            sid,
            request.request_id,
            idempotency_key=request.idempotency_key,
        )
        assert result.after_status == "cancelled"
        assert replay.idempotent_replay is True
        with Session(isolated) as db:
            row = db.get(ExecutionRequestRow, request.request_id)
            assert row.status == "succeeded" and row.attempt_count == 2
            assert db.get(OrderRow, "o").row_version == 2
            assert db.scalar(
                select(func.count())
                .select_from(ExecutionAuditRow)
                .where(ExecutionAuditRow.event_type == "execution_succeeded")
            ) == 1
    finally:
        Base.metadata.drop_all(isolated)
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()
