"""Real Retail snapshot in disposable PostgreSQL schema, with scripted model calls."""

import os
from pathlib import Path
from uuid import uuid4

import pytest
from app.database import Base, engine_for, seed
from app.live_agent import live_chat
from app.llm import ModelReply, ModelToolCall
from app.retail import load
from app.service import RetailService

from scripts.fetch_tau_retail import COMMIT, verify

RAW = Path("data/raw/tau2") / COMMIT


class ScriptedProvider:
    def __init__(self, *replies):
        self.replies = iter(replies)

    def complete(self, messages, tools):
        return next(self.replies)


def call(name, args):
    return ModelReply(
        tool_calls=[ModelToolCall(id=uuid4().hex, name=name, arguments=args)],
        usage={"prompt_tokens": 8, "completion_tokens": 3},
    )


@pytest.mark.postgres
def test_real_snapshot_query_cancel_modify_return():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required")
    verify(RAW)
    source = load(RAW / "db.json")
    engine = engine_for(url)
    schema = "phase15_" + uuid4().hex
    with engine.begin() as db:
        db.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    isolated = engine.execution_options(schema_translate_map={None: schema})
    try:
        seed(isolated, source, "phase15")
        service = RetailService(isolated)
        pending = [o for o in source.orders.values() if o.status == "pending"]
        delivered = next(
            o for o in source.orders.values() if o.status == "delivered" and o.payment_history
        )
        assert len(pending) >= 2
        first = pending[0]
        sid = service.start()
        email = source.users[first.user_id].email
        verifier = ScriptedProvider(
            call("find_user_id_by_email", {"email": email}),
            ModelReply(content="Identity verified."),
        )
        live_chat(service, sid, f"My email is {email}", None, verifier)
        query = ScriptedProvider(
            call("get_order_details", {"order_id": first.order_id}),
            ModelReply(content="This order is pending."),
        )
        answer = live_chat(service, sid, f"Check order {first.order_id}", None, query)
        assert answer["response"]["message"] == "This order is pending."
        cancel = ScriptedProvider(
            call(
                "propose_cancel_order",
                {"order_id": first.order_id, "reason": "no longer needed"},
            )
        )
        proposal = live_chat(service, sid, f"Cancel order {first.order_id}", None, cancel)[
            "response"
        ]
        assert service.order(sid, first.order_id)["status"] == "pending"
        done = live_chat(service, sid, "yes", proposal["proposal_id"], ScriptedProvider())[
            "response"
        ]
        assert done["operation"]["order_status"] == "cancelled"

        second = next(o for o in pending[1:] if o.order_id != first.order_id)
        sid2 = service.start()
        service.verify(sid2, email=source.users[second.user_id].email)
        address = dict(second.address)
        address["address1"] = "Stage 1.5 isolated test address"
        modify = ScriptedProvider(
            call(
                "propose_modify_address",
                {"order_id": second.order_id, "address": address},
            )
        )
        proposal2 = live_chat(service, sid2, "Change my shipping address", None, modify)["response"]
        live_chat(service, sid2, "yes", proposal2["proposal_id"], ScriptedProvider())
        assert service.order(sid2, second.order_id)["address"]["address1"] == address["address1"]

        sid3 = service.start()
        service.verify(sid3, email=source.users[delivered.user_id].email)
        return_call = ScriptedProvider(
            call(
                "propose_return_order",
                {
                    "order_id": delivered.order_id,
                    "item_ids": [delivered.items[0].item_id],
                    "payment_method_id": delivered.payment_history[0]["payment_method_id"],
                },
            )
        )
        proposal3 = live_chat(service, sid3, "Return one delivered item", None, return_call)[
            "response"
        ]
        assert service.order(sid3, delivered.order_id)["status"] == "delivered"
        live_chat(service, sid3, "yes", proposal3["proposal_id"], ScriptedProvider())
        assert service.order(sid3, delivered.order_id)["status"] == "return requested"
    finally:
        Base.metadata.drop_all(isolated)
        with engine.begin() as db:
            db.exec_driver_sql(f'DROP SCHEMA "{schema}"')
        engine.dispose()
