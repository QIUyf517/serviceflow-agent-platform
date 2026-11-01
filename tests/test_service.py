import pytest
from app.database import AuditRow, OrderRow, ProposalRow
from app.service import Action, BusinessError
from sqlalchemy import event, select


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
