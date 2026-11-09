"""Real cancel writes and concurrency in a disposable PostgreSQL schema."""

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from app.config import Settings
from app.database import Base, ExecutionAuditRow, OrderRow, engine_for, seed
from app.multi_agent.execution import ExecutionService
from app.multi_agent.models import EligibilityResult, ResolutionProposal
from app.multi_agent.policy_agent import build_policy_agent
from app.multi_agent.triage import MockTriage
from app.multi_agent.workflow import SessionStateStore, run_turn
from app.retail import load
from app.service import BusinessError, RetailService
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from scripts.fetch_tau_retail import COMMIT, verify

RAW = Path("data/raw/tau2") / COMMIT


def plan_cancel(service, sid, order_id):
    policy = build_policy_agent(
        service.engine,
        Settings(
            _env_file=None,
            agent_provider="mock",
            policy_retrieval_strategy="keyword",
            policy_top_k=3,
        ),
    )
    result = run_turn(
        service,
        sid,
        f"Please cancel order {order_id} because ordered by mistake",
        MockTriage(),
        SessionStateStore(),
        policy_agent=policy,
    )
    assert result["task_status"] == "proposal_ready"
    return (
        ResolutionProposal.model_validate(result["resolution_proposal"], strict=True),
        EligibilityResult.model_validate(result["eligibility_result"], strict=True),
    )


@pytest.mark.postgres
def test_postgres_cancel_concurrency_and_unconfirmed_safety():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for isolated PostgreSQL test")
    verify(RAW)
    source = load(RAW / "db.json")
    engine = engine_for(url)
    schema = "phase25b_" + uuid4().hex
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    isolated = engine.execution_options(schema_translate_map={None: schema})
    try:
        seed(isolated, source, "phase25b")
        service = RetailService(isolated)
        pending = [order for order in source.orders.values() if order.status == "pending"]
        first, second = pending[0], pending[1]

        owner = source.users[first.user_id]
        sid_a = service.start()
        sid_b = service.start()
        service.verify(sid_a, email=owner.email)
        service.verify(sid_b, email=owner.email)
        proposal_a, eligibility_a = plan_cancel(service, sid_a, first.order_id)
        proposal_b, eligibility_b = plan_cancel(service, sid_b, first.order_id)
        execution_a = ExecutionService(isolated)
        execution_b = ExecutionService(isolated)
        request_a = execution_a.prepare_cancel(
            sid_a,
            proposal_a,
            eligibility_a,
            "postgres-concurrent-cancel-a",
        )
        request_b = execution_b.prepare_cancel(
            sid_b,
            proposal_b,
            eligibility_b,
            "postgres-concurrent-cancel-b",
        )
        execution_a.record_decision(
            sid_a,
            request_a.request_id,
            decision="confirm",
            confirmation_text=request_a.confirmation_text,
        )
        execution_b.record_decision(
            sid_b,
            request_b.request_id,
            decision="confirm",
            confirmation_text=request_b.confirmation_text,
        )

        def execute(execution, sid, request):
            try:
                result = execution.execute_cancel(
                    sid,
                    request.request_id,
                    idempotency_key=request.idempotency_key,
                )
                return "ok", result.after_status
            except BusinessError as exc:
                return "error", exc.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(
                pool.map(
                    lambda args: execute(*args),
                    [
                        (execution_a, sid_a, request_a),
                        (execution_b, sid_b, request_b),
                    ],
                )
            )
        assert sorted(outcomes) == [("error", "order_changed"), ("ok", "cancelled")]
        with Session(isolated) as db:
            row = db.get(OrderRow, first.order_id)
            assert row.status == "cancelled" and row.row_version == 2
            assert db.scalar(
                select(func.count())
                .select_from(ExecutionAuditRow)
                .where(ExecutionAuditRow.event_type == "execution_succeeded")
            ) == 1
            assert db.scalar(
                select(func.count())
                .select_from(ExecutionAuditRow)
                .where(ExecutionAuditRow.event_type == "execution_failed")
            ) == 1

        second_owner = source.users[second.user_id]
        second_sid = service.start()
        service.verify(second_sid, email=second_owner.email)
        unconfirmed_proposal, unconfirmed_eligibility = plan_cancel(
            service, second_sid, second.order_id
        )
        unconfirmed = ExecutionService(isolated)
        waiting = unconfirmed.prepare_cancel(
            second_sid,
            unconfirmed_proposal,
            unconfirmed_eligibility,
            "postgres-unconfirmed-cancel",
        )
        with pytest.raises(BusinessError, match="confirmation_required"):
            unconfirmed.execute_cancel(
                second_sid,
                waiting.request_id,
                idempotency_key=waiting.idempotency_key,
            )
        assert service.order(second_sid, second.order_id)["status"] == "pending"
    finally:
        Base.metadata.drop_all(isolated)
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}"')
        engine.dispose()
