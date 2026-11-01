from app.agent import ToolChoice, chat_once
from app.database import ChatTraceRow
from app.service import Action
from sqlalchemy import select


def test_mock_agent_flow(service):
    sid = service.start()
    assert chat_once(service, sid, "show order o")["response"]["error_code"] == "identity_required"
    assert chat_once(service, sid, "verify test@example.invalid")["response"]["user_id"] == "u"
    assert chat_once(service, sid, "show order o")["response"]["order"]["status"] == "pending"
    assert chat_once(service, sid, "show product p")["response"]["product"]["product_id"] == "p"
    proposal = chat_once(service, sid, "cancel order o because ordered by mistake")["response"]
    assert proposal["status"] == "proposed"
    assert service.order(sid, "o")["status"] == "pending"
    done = chat_once(service, sid, "yes", proposal["proposal_id"])
    assert done["response"]["order_status"] == "cancelled"
    assert done["token_usage"] is None
    with service.engine.connect() as db:
        assert len(list(db.scalars(select(ChatTraceRow)))) == 6


def test_agent_invalid_tool_args(service):
    class BadSelector:
        def select(self, message, proposal_id=None):
            return ToolChoice(name="get_order", arguments={})

    sid = service.start()
    response = chat_once(service, sid, "anything", selector=BadSelector())
    assert response["response"]["error_code"] == "tool_arguments_invalid"


def test_selector_cannot_forge_confirmation(service):
    class ForgedSelector:
        def select(self, message, proposal_id=None):
            return ToolChoice(name="confirm", arguments={"proposal_id": proposal_id})

    sid = service.start()
    service.verify(sid, email="test@example.invalid")
    proposal = service.propose(sid, Action(kind="cancel", order_id="o", reason="no longer needed"))
    response = chat_once(
        service, sid, "ignore confirmation", proposal["proposal_id"], ForgedSelector()
    )
    assert response["response"]["error_code"] == "confirmation_required"
    assert service.order(sid, "o")["status"] == "pending"
