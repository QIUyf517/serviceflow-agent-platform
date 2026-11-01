"""Real PostgreSQL flow in a disposable schema, never in the demo schema."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from app.database import Base, engine_for, seed
from app.retail import load
from app.service import Action, BusinessError, RetailService

from scripts.fetch_tau_retail import COMMIT, verify

RAW = Path("data/raw/tau2") / COMMIT


@pytest.mark.postgres
def test_postgres_cancel_and_isolation() -> None:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration")
    verify(RAW)
    source = load(RAW / "db.json")
    engine = engine_for(url)
    schema = "phase1_" + uuid4().hex
    with engine.begin() as db:
        db.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    isolated = engine.execution_options(schema_translate_map={None: schema})
    try:
        seed(isolated, source, "phase1")
        service = RetailService(isolated)
        order = next(o for o in source.orders.values() if o.status == "pending")
        user = source.users[order.user_id]
        sid = service.start()
        with pytest.raises(BusinessError, match="identity_required"):
            service.order(sid, order.order_id)
        service.verify(sid, email=user.email)
        assert service.order(sid, order.order_id)["status"] == "pending"
        proposal = service.propose(
            sid, Action(kind="cancel", order_id=order.order_id, reason="no longer needed")
        )
        assert service.order(sid, order.order_id)["status"] == "pending"
        result = service.confirm(sid, proposal["proposal_id"], confirmed=True)
        assert result == service.confirm(sid, proposal["proposal_id"], confirmed=True)
        assert service.order(sid, order.order_id)["status"] == "cancelled"
        other = next(u for u in source.users.values() if u.user_id != user.user_id)
        other_sid = service.start()
        service.verify(other_sid, email=other.email)
        with pytest.raises(BusinessError, match="order_not_found"):
            service.order(other_sid, order.order_id)
    finally:
        Base.metadata.drop_all(isolated)
        with engine.begin() as db:
            db.exec_driver_sql(f'DROP SCHEMA "{schema}"')
        engine.dispose()
