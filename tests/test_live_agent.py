from app.database import ConversationRow
from app.live_agent import live_chat
from app.llm import ModelReply, ModelToolCall
from sqlalchemy.orm import Session


class ScriptedProvider:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.seen = []

    def complete(self, messages, tools):
        self.seen.append(messages)
        return next(self.replies)


def tool(name, arguments, number=1):
    return ModelReply(
        tool_calls=[ModelToolCall(id=f"call_{number}", name=name, arguments=arguments)],
        usage={"prompt_tokens": 10, "completion_tokens": 4},
    )


def test_live_query_state_and_cancel(service):
    sid = service.start()
    provider = ScriptedProvider(
        [
            tool("find_user_id_by_email", {"email": "test@example.invalid"}),
            ModelReply(content="Identity verified."),
            tool("get_order_details", {"order_id": "o"}),
            ModelReply(content="Order o is pending."),
            tool(
                "propose_cancel_order",
                {"order_id": "o", "reason": "no longer needed"},
            ),
        ]
    )
    assert (
        live_chat(service, sid, "My email is test@example.invalid", None, provider)["response"][
            "status"
        ]
        == "answered"
    )
    result = live_chat(service, sid, "What is the status of order o?", None, provider)
    assert result["response"]["message"] == "Order o is pending."
    assert result["token_usage"]["prompt_tokens"] == 10
    proposal = live_chat(service, sid, "Please cancel order o, no longer needed", None, provider)[
        "response"
    ]
    assert proposal["status"] == "proposed"
    assert service.order(sid, "o")["status"] == "pending"
    denied = live_chat(service, sid, "yes", "wrong-id", provider)["response"]
    assert denied["error_code"] == "confirmation_mismatch"
    done = live_chat(service, sid, "yes", proposal["proposal_id"], provider)["response"]
    assert done["operation"]["order_status"] == "cancelled"
    assert service.order(sid, "o")["status"] == "cancelled"
    with Session(service.engine) as db:
        row = db.get(ConversationRow, sid)
        assert len(row.messages) >= 10
        assert row.pending_proposal_id is None
    assert len(provider.seen) == 5


def test_live_selector_cannot_execute_write_directly(service):
    sid = service.start()
    service.verify(sid, email="test@example.invalid")
    provider = ScriptedProvider(
        [
            tool("confirm_and_execute", {"order_id": "o"}),
            ModelReply(content="I cannot execute that."),
        ]
    )
    result = live_chat(service, sid, "cancel order o", None, provider)
    assert result["response"]["status"] == "answered"
    assert service.order(sid, "o")["status"] == "pending"
