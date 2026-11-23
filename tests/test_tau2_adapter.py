import pytest
from app.llm import ModelReply, ModelToolCall


class ScriptedProvider:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []

    def complete(self, messages, tools):
        self.requests.append({"messages": messages, "tools": tools})
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


def test_official_multi_agent_routes_and_reuses_the_same_guard():
    pytest.importorskip("tau2")
    from app.integrations.tau2_multi import ServiceFlowTauMultiAgent
    from tau2.data_model.message import ToolMessage, UserMessage
    from tau2.runner import build_environment

    env = build_environment("retail")
    order = next(item for item in env.tools.db.orders.values() if item.status == "pending")
    user = env.tools.db.users[order.user_id]
    provider = ScriptedProvider(
        [
            call("find_user_id_by_email", {"email": user.email}, 1),
            call("get_user_details", {"user_id": user.user_id}, 2),
            ModelReply(content="Your profile is loaded."),
            ModelReply(content="Please confirm that you want me to cancel this order."),
            ModelReply(content="The saved PayPal account will be used if needed."),
            call(
                "cancel_pending_order",
                {"order_id": order.order_id, "reason": "no longer needed"},
                3,
            ),
            ModelReply(content="The cancellation was completed."),
        ]
    )
    agent = ServiceFlowTauMultiAgent(env.get_tools(), env.get_policy(), provider)
    state = agent.get_init_state()

    answer, state = agent.generate_next_message(
        UserMessage(
            role="user",
            content=f"Cancel order {order.order_id}. My email is {user.email}",
        ),
        state,
    )
    assert state.route_history[-1] == "identity_specialist"
    assert state.workflow.intent == "cancel"
    assert state.workflow.stage == "gathering"
    assert {item["function"]["name"] for item in provider.requests[0]["tools"]} == {
        "find_user_id_by_email",
        "find_user_id_by_name_zip",
    }
    identity = env.get_response(answer.tool_calls[0])
    assert isinstance(identity, ToolMessage)

    answer, state = agent.generate_next_message(identity, state)
    assert state.route_history[-1] == "order_specialist"
    assert answer.tool_calls[0].name == "get_user_details"
    profile = env.get_response(answer.tool_calls[0])
    answer, state = agent.generate_next_message(profile, state)
    assert state.profile_loaded

    answer, state = agent.generate_next_message(
        UserMessage(role="user", content=f"Cancel order {order.order_id}"), state
    )
    assert state.route_history[-1] == "resolution_specialist"
    assert state.workflow.intent == "cancel"
    assert state.workflow.stage == "gathering"
    assert answer.tool_calls is None
    assert "confirm" in answer.content
    answer, state = agent.generate_next_message(
        UserMessage(role="user", content="Yes, use PayPal."), state
    )
    assert state.route_history[-1] == "resolution_specialist"
    assert answer.tool_calls is None
    assert state.workflow.stage == "gathering"
    answer, state = agent.generate_next_message(
        UserMessage(role="user", content="Yes, go ahead."), state
    )
    assert state.route_history[-1] == "resolution_specialist"
    assert state.pending_write is not None
    assert state.workflow.stage == "awaiting_confirmation"
    assert state.workflow.proposal_name == "cancel_pending_order"
    assert state.workflow.proposal_fingerprint is not None
    assert len(state.workflow.proposal_fingerprint) == 64
    assert "confirm" in answer.content
    answer, state = agent.generate_next_message(UserMessage(role="user", content="yes"), state)
    assert answer.tool_calls[0].name == "cancel_pending_order"
    assert state.workflow.stage == "executing"
    result = env.get_response(answer.tool_calls[0])
    answer, state = agent.generate_next_message(result, state)
    assert answer.content == "The cancellation was completed."
    assert state.workflow.stage == "post_execution"
    assert state.workflow.completed_writes == 1


def test_multi_agent_v3_binds_confirmation_to_exact_proposal_and_supports_abort():
    pytest.importorskip("tau2")
    from app.integrations.tau2_multi import ServiceFlowTauMultiAgent
    from tau2.data_model.message import UserMessage
    from tau2.runner import build_environment

    env = build_environment("retail")
    order = next(item for item in env.tools.db.orders.values() if item.status == "pending")
    user = env.tools.db.users[order.user_id]
    provider = ScriptedProvider(
        [
            call(
                "cancel_pending_order",
                {"order_id": order.order_id, "reason": "no longer needed"},
                1,
            ),
            ModelReply(content="Okay, no action was taken."),
        ]
    )
    agent = ServiceFlowTauMultiAgent(env.get_tools(), env.get_policy(), provider)
    state = agent.get_init_state()
    state.verified_user_id = user.user_id
    state.profile_loaded = True
    state.own_order_ids = {order.order_id}

    answer, state = agent.generate_next_message(
        UserMessage(role="user", content=f"Cancel order {order.order_id}"), state
    )
    assert answer.tool_calls is None
    assert state.pending_write is not None
    assert state.workflow.stage == "awaiting_confirmation"
    state.pending_write.arguments["reason"] = "changed after summary"

    answer, state = agent.generate_next_message(UserMessage(role="user", content="yes"), state)
    assert answer.tool_calls is None
    assert answer.raw_data["guard_rejection"] == "proposal_fingerprint_mismatch"
    assert state.pending_write is None
    assert state.workflow.stage == "gathering"

    answer, state = agent.generate_next_message(UserMessage(role="user", content="no"), state)
    assert answer.content == "Okay, no action was taken."
    assert state.workflow.stage == "idle"
    assert state.workflow.intent is None
    assert state.pending_write is None


def test_official_adapter_enforces_fixed_tool_and_token_budgets():
    pytest.importorskip("tau2")
    from app.integrations.tau2 import ServiceFlowTauAgent
    from tau2.data_model.message import UserMessage
    from tau2.runner import build_environment

    env = build_environment("retail")
    provider = ScriptedProvider(
        [
            call("find_user_id_by_email", {"email": "nobody@example.com"}, 1),
            call("find_user_id_by_email", {"email": "nobody@example.com"}, 2),
        ]
    )
    agent = ServiceFlowTauAgent(
        env.get_tools(), env.get_policy(), provider, max_tool_calls=1, max_total_tokens=100
    )
    state = agent.get_init_state()
    answer, state = agent.generate_next_message(
        UserMessage(role="user", content="My email is nobody@example.com"), state
    )
    assert answer.tool_calls and state.tool_calls_used == 1
    answer, state = agent.generate_next_message(
        UserMessage(role="user", content="Please try again"), state
    )
    assert answer.tool_calls is None
    assert answer.raw_data["budget_rejection"] == "tool_call_budget_exhausted"

    token_provider = ScriptedProvider(
        [ModelReply(content="too long", usage={"total_tokens": 101})]
    )
    token_agent = ServiceFlowTauAgent(
        env.get_tools(), env.get_policy(), token_provider, max_total_tokens=100
    )
    answer, state = token_agent.generate_next_message(
        UserMessage(role="user", content="hello"), token_agent.get_init_state()
    )
    assert answer.raw_data["budget_rejection"] == "token_budget_exhausted"
    assert state.total_tokens_used == 101
