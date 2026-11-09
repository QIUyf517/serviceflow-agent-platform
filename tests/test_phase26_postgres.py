"""Real pgvector plus return execution in a random disposable PostgreSQL schema."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from app.config import Settings
from app.database import engine_for, seed
from app.multi_agent.conversation import run_after_sales_conversation
from app.multi_agent.execution import ExecutionService
from app.multi_agent.policy_agent import build_policy_agent
from app.multi_agent.workflow import SessionStateStore
from app.retail import load
from app.service import RetailService

from scripts.fetch_tau_retail import COMMIT, verify

RAW = Path("data/raw/tau2") / COMMIT


@pytest.mark.postgres
def test_real_pgvector_return_agent_path_and_audit():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for isolated PostgreSQL test")
    verify(RAW)
    source = load(RAW / "db.json")
    engine = engine_for(url)
    schema = "phase26_" + uuid4().hex
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    isolated = engine.execution_options(schema_translate_map={None: schema})
    try:
        seed(isolated, source, "phase26")
        service = RetailService(isolated)
        execution = ExecutionService(isolated)
        policy = build_policy_agent(
            isolated,
            Settings(
                _env_file=None,
                agent_provider="mock",
                policy_retrieval_strategy="vector",
                policy_top_k=5,
                policy_embedding_provider="fastembed",
                policy_local_embedding_cache=".cache/fastembed",
            ),
        )
        assert policy.vector is not None
        assert policy.vector.index(rebuild=True) == 17
        candidate = next(
            order
            for order in source.orders.values()
            if order.status == "delivered"
            and order.items
            and order.payment_history
            and order.payment_history[0]["payment_method_id"]
            in source.users[order.user_id].payment_methods
        )
        owner = source.users[candidate.user_id]
        item_id = candidate.items[0].item_id
        method = candidate.payment_history[0]["payment_method_id"]
        sid = service.start()
        service.verify(sid, email=owner.email)
        store = SessionStateStore()
        first = run_after_sales_conversation(
            service,
            execution,
            sid,
            (
                f"Please return delivered order {candidate.order_id} under the return policy "
                f"item_quantities={item_id}:1 payment_method_id={method}"
            ),
            store,
            policy,
        )
        assert first["task_status"] == "pending_confirmation"
        assert any(event.get("tool") == "policy_vector_search" for event in first["trace"])
        assert service.order(sid, candidate.order_id)["status"] == "delivered"
        second = run_after_sales_conversation(
            service,
            execution,
            sid,
            "确认退货",
            store,
            policy,
            request_id=first["request_id"],
        )
        assert second["execution_result"]["after_status"] == "return requested"
        events = execution.audit_events(sid, first["request_id"])
        assert {event["event_type"] for event in events} == {
            "proposal_generated",
            "eligibility_validated",
            "user_confirmed",
            "execution_succeeded",
        }
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        engine.dispose()
