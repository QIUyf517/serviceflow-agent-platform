"""Full two-turn cancel conversation in a disposable PostgreSQL schema."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
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


@pytest.mark.postgres
def test_postgres_two_turn_conversation_and_unconfirmed_counterexample():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for isolated PostgreSQL test")
    verify(RAW)
    source = load(RAW / "db.json")
    engine = engine_for(url)
    schema = "phase25c_" + uuid4().hex
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    isolated = engine.execution_options(schema_translate_map={None: schema})
    try:
        seed(isolated, source, "phase25c")
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
        success_order = pending[0]
        owner = source.users[success_order.user_id]
        sid = service.start()
        service.verify(sid, email=owner.email)
        store = SessionStateStore()

        first = run_cancel_conversation(
            service,
            execution,
            sid,
            f"Please cancel order {success_order.order_id} because ordered by mistake",
            store,
            policy,
        )
        assert first["task_status"] == "pending_confirmation"
        assert first["resolution_proposal"]["validated"] is True
        assert first["eligibility_result"]["status"] == "eligible"
        assert service.order(sid, success_order.order_id)["status"] == "pending"

        second = run_cancel_conversation(
            service,
            execution,
            sid,
            "确认",
            store,
            policy,
            request_id=first["request_id"],
        )
        assert second["task_status"] == "executed"
        assert second["execution_result"]["after_status"] == "cancelled"
        assert service.order(sid, success_order.order_id)["status"] == "cancelled"
        events = execution.audit_events(sid, first["request_id"])
        assert {event["event_type"] for event in events} == {
            "proposal_generated",
            "eligibility_validated",
            "user_confirmed",
            "execution_succeeded",
        }

        counterexample = next(
            order
            for order in pending[1:]
            if order.user_id != success_order.user_id
        )
        other_owner = source.users[counterexample.user_id]
        other_sid = service.start()
        service.verify(other_sid, email=other_owner.email)
        unconfirmed = run_cancel_conversation(
            service,
            execution,
            other_sid,
            f"Please cancel order {counterexample.order_id} because ordered by mistake",
            SessionStateStore(),
            policy,
        )
        assert unconfirmed["task_status"] == "pending_confirmation"
        assert service.order(other_sid, counterexample.order_id)["status"] == "pending"
        assert not any(
            event["event_type"] == "execution_succeeded"
            for event in execution.audit_events(other_sid, unconfirmed["request_id"])
        )
    finally:
        Base.metadata.drop_all(isolated)
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}"')
        engine.dispose()
