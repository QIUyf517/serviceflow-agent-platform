import pytest
from app.database import AuditRow, OrderCreationRow, OrderRow, ProposalRow, UserRow
from app.service import Action, BusinessError, CheckoutRequest
from sqlalchemy import event, select
from sqlalchemy.orm import Session


def verified(service):
    sid = service.start()
    assert service.verify(sid, email="test@example.invalid") == "u"
    return sid


def test_query_isolation(service):
    sid = service.start()
    with pytest.raises(BusinessError, match="identity_required"):
        service.order(sid, "o")
    sid = verified(service)
    assert service.order(sid, "o")["status"] == "pending"
    assert len(service.orders(sid)) == 1
    with pytest.raises(BusinessError, match="order_not_found"):
        service.order(sid, "bogus")
    other = service.start()
    service.verify(other, email="v@example.invalid")
    with pytest.raises(BusinessError, match="order_not_found"):
        service.order(other, "o")


def test_public_catalog_uses_a_valid_session_without_exposing_customer_data(service):
    sid = service.start()

    assert service.products(sid) == [
        {
            "product_id": "p",
            "name": "Test product",
            "min_price": 12.0,
            "max_price": 12.0,
            "available_variants": 1,
            "total_variants": 1,
            "option_names": [],
        }
    ]
    assert service.product(sid, "p", public=True)["product_id"] == "p"
    with pytest.raises(BusinessError, match="identity_required"):
        service.orders(sid)


def test_verified_session_cannot_be_rebound_to_another_customer(service):
    sid = verified(service)

    with pytest.raises(BusinessError, match="identity_not_verified"):
        service.verify(sid, email="v@example.invalid")

    assert service.orders(sid)[0]["user_id"] == "u"


def test_checkout_is_identity_bound_transactional_and_idempotent(service):
    with Session(service.engine) as db, db.begin():
        user = db.get(UserRow, "u")
        profile = dict(user.profile_json)
        profile["payment_methods"] = {
            "card-1": {"id": "card-1", "source": "credit_card", "last_four": "1234"}
        }
        user.profile_json = profile

    request = CheckoutRequest(
        items=[{"item_id": "i", "quantity": 2}], payment_method_id="card-1"
    )
    anonymous = service.start()
    with pytest.raises(BusinessError, match="identity_required"):
        service.checkout(anonymous, request, idempotency_key="checkout-anonymous-1")

    sid = verified(service)
    first = service.checkout(sid, request, idempotency_key="checkout-request-0001")
    assert first["idempotent_replay"] is False
    assert first["order"]["status"] == "pending"
    assert len(first["order"]["items"]) == 2
    assert first["order"]["payment_history"][0]["amount"] == 24.0
    assert service.order(sid, first["order"]["order_id"]) == first["order"]

    replay = service.checkout(sid, request, idempotency_key="checkout-request-0001")
    assert replay["order"] == first["order"]
    assert replay["idempotent_replay"] is True
    with Session(service.engine) as db:
        assert len(list(db.scalars(select(OrderCreationRow)))) == 1
        assert len(list(db.scalars(select(OrderRow)))) == 2

    changed = CheckoutRequest(
        items=[{"item_id": "i", "quantity": 1}], payment_method_id="card-1"
    )
    with pytest.raises(BusinessError, match="idempotency_key_conflict"):
        service.checkout(sid, changed, idempotency_key="checkout-request-0001")


def test_confirm_idempotent_and_guard(service):
    sid = verified(service)
    proposal = service.propose(
        sid, Action(kind="cancel", order_id="o", reason="ordered by mistake")
    )
    assert service.order(sid, "o")["status"] == "pending"
    with pytest.raises(BusinessError, match="confirmation_required"):
        service.confirm(sid, proposal["proposal_id"], confirmed=False)
    result = service.confirm(sid, proposal["proposal_id"], confirmed=True)
    assert result == service.confirm(sid, proposal["proposal_id"], confirmed=True)
    assert service.order(sid, "o")["status"] == "cancelled"
    with pytest.raises(BusinessError, match="order_status_invalid"):
        service.propose(sid, Action(kind="cancel", order_id="o", reason="ordered by mistake"))
    with service.engine.connect() as db:
        assert len(list(db.scalars(select(AuditRow)))) == 1


def test_revalidate_and_rollback(service):
    sid = verified(service)
    p = service.propose(sid, Action(kind="cancel", order_id="o", reason="no longer needed"))
    with service.engine.begin() as db:
        db.execute(
            OrderRow.__table__.update().where(OrderRow.source_order_id == "o").values(row_version=2)
        )
    with pytest.raises(BusinessError, match="order_changed"):
        service.confirm(sid, p["proposal_id"], confirmed=True)
    assert service.order(sid, "o")["status"] == "pending"

    def fail_audit(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO operation_audit"):
            raise RuntimeError("injected")

    p = service.propose(sid, Action(kind="cancel", order_id="o", reason="no longer needed"))
    event.listen(service.engine, "before_cursor_execute", fail_audit)
    with pytest.raises(RuntimeError, match="injected"):
        service.confirm(sid, p["proposal_id"], confirmed=True)
    event.remove(service.engine, "before_cursor_execute", fail_audit)
    assert service.order(sid, "o")["status"] == "pending"


def test_expired_proposal(service):
    sid = verified(service)
    p = service.propose(sid, Action(kind="cancel", order_id="o", reason="no longer needed"))
    with service.engine.begin() as db:
        db.execute(
            ProposalRow.__table__.update()
            .where(ProposalRow.id == p["proposal_id"])
            .values(expires_at=0)
        )
    with pytest.raises(BusinessError, match="proposal_expired"):
        service.confirm(sid, p["proposal_id"], confirmed=True)
    assert service.order(sid, "o")["status"] == "pending"
