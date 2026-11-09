"""Real Retail snapshot in an isolated PostgreSQL schema; no demo table writes."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from app.database import AuditRow, Base, OrderRow, ProposalRow, engine_for, seed
from app.multi_agent.triage import MockTriage
from app.multi_agent.workflow import SessionStateStore, run_turn
from app.retail import load
from app.service import RetailService
from sqlalchemy import select
from sqlalchemy.orm import Session

from scripts.fetch_tau_retail import COMMIT, verify

RAW = Path("data/raw/tau2") / COMMIT


@pytest.mark.postgres
def test_real_postgres_order_agent_readonly_scenarios():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for isolated PostgreSQL test")
    verify(RAW)
    source = load(RAW / "db.json")
    engine = engine_for(url)
    schema = "phase23_" + uuid4().hex
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    isolated = engine.execution_options(schema_translate_map={None: schema})
    try:
        seed(isolated, source, "phase23")
        service = RetailService(isolated)
        selected = next(order for order in source.orders.values() if order.status == "delivered")
        owner = source.users[selected.user_id]
        sid = service.start()
        denied = run_turn(
            service, sid, f"查询订单{selected.order_id}详情", MockTriage(), SessionStateStore()
        )
        assert denied["task_status"] == "clarification"
        assert denied["order_data"] == {}

        service.verify(sid, email=owner.email)
        own = run_turn(
            service, sid, f"查询订单{selected.order_id}详情", MockTriage(), SessionStateStore()
        )
        detail = own["order_data"]["order-lookup"]["order"]
        assert own["task_status"] == "queried"
        assert detail["order_id"] == selected.order_id
        assert detail["status"] == selected.status
        assert detail["fulfillments"] == [
            {"item_ids": f["item_ids"], "tracking_id": f["tracking_id"]}
            for f in selected.fulfillments
        ]
        assert "address" not in detail and "payment_history" not in detail

        other = next(user for user in source.users.values() if user.user_id != owner.user_id)
        other_sid = service.start()
        service.verify(other_sid, email=other.email)
        foreign = run_turn(
            service,
            other_sid,
            f"查询订单{selected.order_id}详情",
            MockTriage(),
            SessionStateStore(),
        )
        assert foreign["task_status"] == "query_failed"
        assert foreign["tool_results"][0]["code"] == "order_not_found"

        multi = SessionStateStore()
        first = run_turn(service, sid, "查询订单状态", MockTriage(), multi)
        assert first["task_status"] == "clarification"
        second = run_turn(service, sid, selected.order_id, MockTriage(), multi)
        assert second["task_status"] == "queried"
        assert second["order_data"]["order-lookup"]["status"] == selected.status

        with Session(isolated) as db:
            assert db.get(OrderRow, selected.order_id).row_version == 1
            assert db.scalar(select(ProposalRow)) is None
            assert db.scalar(select(AuditRow)) is None
    finally:
        Base.metadata.drop_all(isolated)
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}"')
        engine.dispose()
