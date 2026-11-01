from copy import deepcopy

import pytest
from app.agent import chat_once
from app.database import OrderRow, ProductRow, UserRow
from app.service import Action, BusinessError
from sqlalchemy.orm import Session


def prepare(service, *, status="delivered"):
    with Session(service.engine) as db, db.begin():
        user = db.get(UserRow, "u")
        profile = dict(user.profile_json)
        profile["payment_methods"] = {
            "card": {"id": "card", "source": "credit_card", "last_four": "1234", "brand": "visa"},
            "gift": {"id": "gift", "source": "gift_card", "balance": 20.0},
        }
        user.profile_json = profile
        order = db.get(OrderRow, "o")
        data = dict(order.order_json)
        data["status"] = status
        data["payment_history"] = [
            {"transaction_type": "payment", "amount": 10.0, "payment_method_id": "card"}
        ]
        order.order_json = data
        order.status = status
        product = db.get(ProductRow, "p")
        product_data = deepcopy(product.product_json)
        product_data["variants"]["j"] = {
            "item_id": "j",
            "options": {"size": "L"},
            "available": True,
            "price": 14.0,
        }
        product.product_json = product_data
    sid = service.start()
    service.verify(sid, email="test@example.invalid")
    return sid


def test_return_and_method_guard(service):
    sid = prepare(service)
    with pytest.raises(BusinessError, match="items_invalid"):
        service.propose(
            sid, Action(kind="return", order_id="o", item_ids=["missing"], payment_method_id="card")
        )
    p = service.propose(
        sid, Action(kind="return", order_id="o", item_ids=["i"], payment_method_id="gift")
    )
    assert (
        service.confirm(sid, p["proposal_id"], confirmed=True)["order_status"] == "return requested"
    )
    assert service.order(sid, "o")["return_items"] == ["i"]


def test_agent_return_proposal(service):
    sid = prepare(service)
    response = chat_once(service, sid, "return order o item i payment gift")["response"]
    assert response["status"] == "proposed"
    assert service.order(sid, "o")["status"] == "delivered"


def test_exchange_and_modify_rules(service):
    sid = prepare(service)
    p = service.propose(
        sid,
        Action(
            kind="exchange",
            order_id="o",
            item_ids=["i"],
            new_item_ids=["j"],
            payment_method_id="gift",
        ),
    )
    assert (
        service.confirm(sid, p["proposal_id"], confirmed=True)["order_status"]
        == "exchange requested"
    )
    with pytest.raises(BusinessError, match="order_status_invalid"):
        service.propose(
            sid, Action(kind="return", order_id="o", item_ids=["i"], payment_method_id="gift")
        )


def test_pending_modification(service):
    sid = prepare(service, status="pending")
    p = service.propose(
        sid,
        Action(
            kind="modify_items",
            order_id="o",
            item_ids=["i"],
            new_item_ids=["j"],
            payment_method_id="gift",
        ),
    )
    service.confirm(sid, p["proposal_id"], confirmed=True)
    assert service.order(sid, "o")["items"][0]["item_id"] == "j"
    assert service.user(sid)["payment_methods"]["gift"]["balance"] == 16.0
    with pytest.raises(BusinessError, match="order_status_invalid"):
        service.propose(sid, Action(kind="modify_address", order_id="o", address={}))
