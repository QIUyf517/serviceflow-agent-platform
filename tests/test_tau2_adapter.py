import pytest
from app.llm import ModelReply, ModelToolCall


class ScriptedProvider:
    def __init__(self, replies):
        self.replies = iter(replies)

    def complete(self, messages, tools):
        return next(self.replies)


def call(name, arguments, number):
    return ModelReply(
        tool_calls=[ModelToolCall(id=f"call_{number}", name=name, arguments=arguments)]
    )


def test_official_text_adapter_and_guards():
    pytest.importorskip("tau2")
    from app.integrations.tau2 import ServiceFlowTauAgent, _is_confirmation
    from tau2.data_model.message import AssistantMessage, ToolMessage, UserMessage
    from tau2.runner import build_environment

    env = build_environment("retail")
    pending_order = next(o for o in env.tools.db.orders.values() if o.status == "pending")
    user = env.tools.db.users[pending_order.user_id]
    own_order = pending_order.order_id
    foreign_order = next(
        o.order_id for o in env.tools.db.orders.values() if o.user_id != user.user_id
    )
    provider = ScriptedProvider(
        [
            call("find_user_id_by_email", {"email": user.email}, 1),
            ModelReply(content="Identity verified."),
            call("get_user_details", {"user_id": user.user_id}, 2),
            call("get_order_details", {"order_id": foreign_order}, 3),
            call("cancel_pending_order", {"order_id": own_order, "reason": "no longer needed"}, 4),
            ModelReply(content="Okay, I will not cancel it."),
        ]
    )
    agent = ServiceFlowTauAgent(env.get_tools(), env.get_policy(), provider)
    state = agent.get_init_state()
    answer, state = agent.generate_next_message(
        UserMessage(role="user", content=f"My email is {user.email}"), state
    )
    assert answer.tool_calls[0].name == "find_user_id_by_email"
    result = env.get_response(answer.tool_calls[0])
    assert isinstance(result, ToolMessage) and not result.error
    answer, state = agent.generate_next_message(result, state)
    assert isinstance(answer, AssistantMessage) and state.verified_user_id == user.user_id
    answer, state = agent.generate_next_message(
        UserMessage(role="user", content="Please show my profile"), state
    )
    assert answer.tool_calls[0].name == "get_user_details"
    answer, state = agent.generate_next_message(env.get_response(answer.tool_calls[0]), state)
    assert own_order in state.own_order_ids
    assert "Other" in answer.content or "own" in answer.content
    answer, state = agent.generate_next_message(
        UserMessage(role="user", content=f"Cancel order {own_order}"), state
    )
    assert answer.tool_calls is None
    assert "confirm" in answer.content
    assert state.pending_write is not None
    answer, state = agent.generate_next_message(UserMessage(role="user", content="no"), state)
    assert answer.tool_calls is None
    assert state.pending_write is None
    confirmations = ("Yes.", "Yes, confirmed.", "Yes, go ahead and process it.")
    assert all(_is_confirmation(value) for value in confirmations)
    assert not any(_is_confirmation(value) for value in ("yes, but wait", "I guess yes", "no"))
