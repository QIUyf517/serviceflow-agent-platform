from copy import deepcopy

import pytest
from app.multi_agent.state import (
    AgentState,
    apply_agent_update,
    bind_session_identity,
    new_agent_state,
)
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph


def test_initial_state_has_fresh_defaults():
    state = new_agent_state("session-a")
    assert state["session_id"] == state["thread_id"] == "session-a"
    assert state["user_id"] is None
    assert state["identity_verified"] is False
    assert state["order_context"] is None
    assert state["pending_action"] is None
    assert state["user_confirmed"] is False
    assert state["messages"] == state["policy_context"] == state["errors"] == []
    assert state["routing_count"] == 0


def test_valid_update_does_not_mutate_previous_state():
    initial = new_agent_state("session-a", user_id="u")
    updated = apply_agent_update(
        initial,
        {
            "intent": "order_query",
            "order_id": "o",
            "order_context": {"order_id": "o", "status": "pending"},
        },
    )
    assert updated["identity_verified"] is True
    assert updated["order_context"] == {"order_id": "o", "status": "pending"}
    assert initial["order_context"] is None


def test_messages_append_across_graph_turns():
    graph = StateGraph(AgentState)

    def reply(_state):
        return {"messages": [AIMessage(content="received")]}

    graph.add_node("reply", reply)
    graph.add_edge(START, "reply")
    graph.add_edge("reply", END)
    compiled = graph.compile()
    first = compiled.invoke(
        apply_agent_update(
            new_agent_state("session-a"), {"messages": [HumanMessage(content="hello")]}
        )
    )
    second = compiled.invoke(
        apply_agent_update(first, {"messages": [HumanMessage(content="again")]})
    )
    assert [message.content for message in second["messages"]] == [
        "hello",
        "received",
        "again",
        "received",
    ]


def test_missing_order_is_explicit_and_can_route_for_clarification():
    state = apply_agent_update(
        new_agent_state("session-a"), {"intent": "cancel", "next_agent": "triage"}
    )
    assert state["order_id"] is None
    assert state["order_context"] is None
    assert state["pending_action"] is None


def test_unverified_state_cannot_hold_order_context():
    with pytest.raises(ValueError, match="identity_required"):
        apply_agent_update(
            new_agent_state("session-a"),
            {"order_id": "o", "order_context": {"order_id": "o", "status": "pending"}},
        )


def test_order_context_must_match_selected_order():
    with pytest.raises(ValueError, match="order_context_mismatch"):
        apply_agent_update(
            new_agent_state("session-a", user_id="u"),
            {"order_id": "o", "order_context": {"order_id": "other", "status": "pending"}},
        )


def test_sessions_do_not_share_mutable_state():
    first = new_agent_state("session-a", user_id="u")
    second = new_agent_state("session-b", user_id="v")
    updated = apply_agent_update(
        first, {"messages": [HumanMessage(content="private")], "errors": ["missing_order"]}
    )
    updated["policy_context"].append(
        {"source": "policy.md", "section": "cancel", "version": "v1", "excerpt": "sample"}
    )
    assert second["messages"] == second["errors"] == second["policy_context"] == []
    assert second["user_id"] == "v"
    assert first["messages"] == first["errors"] == first["policy_context"] == []


@pytest.mark.parametrize(
    ("delta", "reason"),
    [
        ({"identity_verified": True}, "protected_state_field"),
        ({"user_id": "other"}, "protected_state_field"),
        ({"user_confirmed": True}, "protected_state_field"),
        ({"session_id": "other"}, "protected_state_field"),
        ({"routing_count": "one"}, "agent_state_invalid"),
        ({"routing_count": -1}, "routing_count_invalid"),
        ({"order_context": {"order_id": "o"}}, "agent_state_invalid"),
        ({"unexpected": "value"}, "agent_state_invalid"),
        ({"messages": [{"role": "user", "content": "text"}]}, "messages_invalid"),
    ],
)
def test_invalid_node_updates_are_rejected(delta, reason):
    with pytest.raises(ValueError, match=reason):
        apply_agent_update(new_agent_state("session-a"), delta)


def test_invalid_session_id_and_identity_rejected():
    with pytest.raises(ValueError, match="session_id_required"):
        new_agent_state(" ")
    with pytest.raises(ValueError, match="user_id_invalid"):
        new_agent_state("session-a", user_id="")


def test_server_identity_binding_preserves_messages_but_rejects_switch():
    pending = apply_agent_update(
        new_agent_state("session-a"), {"messages": [HumanMessage(content="order status")]}
    )
    bound = bind_session_identity(pending, "u")
    assert bound["identity_verified"] is True
    assert bound["messages"][0].content == "order status"
    assert pending["identity_verified"] is False
    with pytest.raises(ValueError, match="session_identity_conflict"):
        bind_session_identity(bound, "v")


def test_existing_single_agent_interface_is_distinct():
    from app.agent import AgentState as BaselineState
    from app.agent import chat_once
    from app.live_agent import live_chat
    from app.multi_agent.state import AgentState as MultiAgentState

    assert BaselineState is not MultiAgentState
    assert callable(chat_once) and callable(live_chat)
    assert deepcopy(new_agent_state("session-a"))["session_id"] == "session-a"
