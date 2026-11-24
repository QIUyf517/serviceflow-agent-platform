"""Bounded multi-agent planning plus controlled non-LLM execution workflows."""

from copy import deepcopy
from threading import RLock
from time import perf_counter
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.database import SessionRow
from app.multi_agent.checkpointing import (
    CheckpointBackend,
    build_checkpoint_backend,
    checkpoint_key,
)
from app.multi_agent.execution import ExecutionService
from app.multi_agent.message_store import MessageStore
from app.multi_agent.models import TaskPlan, TriageResult
from app.multi_agent.order_agent import run_order_agent
from app.multi_agent.policy_agent import PolicyAgent
from app.multi_agent.resolution_agent import ResolutionGenerator, run_resolution_agent
from app.multi_agent.state import (
    AgentState,
    apply_agent_update,
    begin_server_trace,
    bind_server_confirmation,
    bind_session_identity,
    new_agent_state,
    reset_server_confirmation,
    restore_agent_state,
)
from app.multi_agent.supervisor import MAX_ROUTES, safe_target, supervise
from app.multi_agent.triage import TriageError, TriageProvider
from app.service import BusinessError, RetailService


class SessionStateStore:
    """Optional state cache backed by a LangGraph checkpointer per database."""

    def __init__(self) -> None:
        self.lock = RLock()
        self.states: dict[str, AgentState] = {}
        self._backends: dict[str, CheckpointBackend] = {}

    @staticmethod
    def config(thread_key: str) -> dict[str, dict[str, str]]:
        """Create the only accepted graph config: a server-resolved thread key.

        The key is either the support thread ID or, for legacy callers, the session ID.
        """
        return {"configurable": {"thread_id": thread_key}}

    def backend_for(self, engine: Engine) -> CheckpointBackend:
        key = checkpoint_key(engine)
        with self.lock:
            backend = self._backends.get(key)
            if backend is None:
                backend = build_checkpoint_backend(engine)
                self._backends[key] = backend
            return backend

    def load(
        self,
        engine: Engine,
        thread_key: str,
        *,
        user_id: str | None,
        messages: list[Any] | None = None,
        session_id: str | None = None,
    ) -> tuple[AgentState, bool]:
        """Load authoritative checkpoint state and hydrate transient channels."""
        bound_session = session_id or thread_key
        with self.lock:
            cached = self.states.get(thread_key)
            if cached is not None:
                if (
                    cached["thread_id"] != thread_key
                    or cached["session_id"] != bound_session
                    or cached["user_id"] not in (None, user_id)
                ):
                    raise ValueError("checkpoint_identity_mismatch")
                state = deepcopy(cached)
                state["messages"] = deepcopy(messages or state["messages"])
                return state, True
        checkpoint = self.backend_for(engine).saver.get_tuple(self.config(thread_key))
        if checkpoint is None:
            state = new_agent_state(bound_session, user_id=user_id, thread_id=thread_key)
            state["messages"] = deepcopy(messages or [])
            return state, False
        state = restore_agent_state(
            checkpoint.checkpoint.get("channel_values", {}),
            bound_session,
            user_id=user_id,
            messages=messages,
            thread_id=thread_key,
        )
        with self.lock:
            self.states[thread_key] = deepcopy(state)
        return state, True

    def clear_cache(self) -> None:
        with self.lock:
            self.states.clear()

    def update_checkpoint(self, engine: Engine, session_id: str, delta: dict[str, object]) -> None:
        """Persist a server-produced state delta created outside a graph invocation."""
        writer = StateGraph(AgentState)
        writer.add_node("state_writer", lambda _state: {})
        writer.add_edge(START, "state_writer")
        writer.add_edge("state_writer", END)
        compiled = writer.compile(checkpointer=self.backend_for(engine).saver)
        compiled.update_state(
            self.config(session_id),
            deepcopy(delta),
            as_node="state_writer",
        )

    def close(self) -> None:
        with self.lock:
            backends = list(self._backends.values())
            self._backends.clear()
            self.states.clear()
        for backend in backends:
            backend.close()

    def __enter__(self) -> "SessionStateStore":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def __del__(self) -> None:
        """Release psycopg pools for short-lived stores used by tests and scripts."""
        try:
            self.close()
        except Exception:
            # Interpreter shutdown may already have torn down locks or pool modules.
            pass


def _checked_delta(state: AgentState, delta: dict[str, object]) -> dict[str, object]:
    apply_agent_update(state, delta)
    return delta


def _timed_node(name: str, node: Any) -> Any:
    """Attach measured wall time and correlation IDs to every graph-node event."""

    def wrapped(state: AgentState) -> dict[str, object]:
        began = perf_counter()
        delta = node(state)
        elapsed_ms = max(0.0, (perf_counter() - began) * 1000)
        traces = deepcopy(delta.get("trace", []))
        request = state.get("execution_request")
        for event in traces:
            if event.get("node") == name:
                event["elapsed_ms"] = elapsed_ms
            event.setdefault("trace_id", state["trace_id"])
            if state["current_task"]:
                event.setdefault("task_id", state["current_task"])
            if request is not None:
                event.setdefault("request_id", request.request_id)
        delta["trace"] = traces
        return delta

    return wrapped


def _last_user_message(state: AgentState) -> str:
    return next(
        message.content
        for message in reversed(state["messages"])
        if isinstance(message, HumanMessage) and isinstance(message.content, str)
    )


def _refresh_tasks(tasks: list[TaskPlan]) -> None:
    """Promote only dependency-satisfied tasks; blocked inputs stay blocked."""
    completed = {task.task_id for task in tasks if task.status == "completed"}
    for task in tasks:
        if (
            task.status == "pending"
            and not task.required_inputs
            and all(dependency in completed for dependency in task.dependencies)
        ):
            task.status = "ready"


def build_workflow(
    triage_provider: TriageProvider,
    service: RetailService | None = None,
    policy_agent: PolicyAgent | None = None,
    resolution_generator: ResolutionGenerator | None = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
):
    def triage_node(state: AgentState) -> dict[str, object]:
        previous = state["triage_result"]
        if (
            previous is not None
            and state["resolution_proposal"] is not None
            and state["resolution_proposal"].status == "needs_clarification"
        ):
            previous = previous.model_copy(
                update={
                    "needs_clarification": True,
                    "missing_information": state["resolution_proposal"].missing_information,
                }
            )
        try:
            result = triage_provider.classify(_last_user_message(state), previous)
        except TriageError as exc:
            return _checked_delta(
                state,
                {
                    "triage_result": None,
                    "task_status": "triage_error",
                    "errors": [str(exc)],
                    "trace": [{"node": "triage", "status": "error"}],
                },
            )
        changed_order = result.order_id != state["order_id"]
        continuing_resolution = bool(
            not changed_order
            and state["resolution_proposal"] is not None
            and state["resolution_proposal"].status == "needs_clarification"
            and previous is not None
            and set(result.intents) == set(previous.intents)
        )
        return _checked_delta(
            state,
            {
                "triage_result": result,
                "intent": result.intent,
                "order_id": result.order_id,
                "order_context": state["order_context"] if continuing_resolution else None,
                "order_data": state["order_data"] if continuing_resolution else {},
                "policy_context": state["policy_context"] if continuing_resolution else [],
                "policy_retrieval": state["policy_retrieval"] if continuing_resolution else None,
                "final_response": None,
                "pending_action": None,
                "resolution_proposal": (
                    state["resolution_proposal"] if continuing_resolution else None
                ),
                "eligibility_result": None,
                "risk_flags": [],
                "trace": [{"node": "triage", "status": "classified"}],
            },
        )

    def supervisor_node(state: AgentState) -> dict[str, object]:
        triage = state["triage_result"]
        if triage is None:
            limited = state["routing_count"] >= MAX_ROUTES
            return _checked_delta(
                state,
                {
                    "next_agent": "end",
                    "task_plan": [],
                    "missing_information": [],
                    "routing_count": state["routing_count"] + 1,
                    "task_status": "route_limit" if limited else "triage_error",
                    "trace": [
                        {
                            "node": "supervisor",
                            "status": "route_limit" if limited else "triage_error",
                        }
                    ],
                },
            )
        delta = supervise(triage, state)
        tasks = [task.model_copy(deep=True) for task in delta.get("task_plan", [])]
        if state["order_data"] and state["order_context"]:
            for task in tasks:
                if task.task_id == "order-lookup":
                    task.status = "completed"
                    task.required_inputs = []
        if state["policy_context"]:
            for task in tasks:
                if task.target_agent == "policy":
                    task.status = "completed"
        _refresh_tasks(tasks)
        ready = next(
            (
                task
                for task in tasks
                if task.status == "ready" and task.target_agent in {"order", "policy", "resolution"}
            ),
            None,
        )
        if ready is not None and not delta.get("missing_information"):
            delta["next_agent"] = ready.target_agent
            delta["current_task"] = ready.task_id
        delta["task_plan"] = tasks
        return _checked_delta(state, delta)

    def order_node(state: AgentState) -> dict[str, object]:
        if service is None:
            return _checked_delta(
                state,
                {
                    "errors": ["order_service_unavailable"],
                    "trace": [{"node": "order", "status": "error"}],
                },
            )
        return _checked_delta(state, run_order_agent(service, state["session_id"], state))

    def policy_node(state: AgentState) -> dict[str, object]:
        if policy_agent is None:
            return _checked_delta(
                state,
                PolicyAgent._failure(
                    state,
                    _last_user_message(state),
                    "policy_service_unavailable",
                    "keyword",
                ),
            )
        return _checked_delta(state, policy_agent.run(state))

    def resolution_node(state: AgentState) -> dict[str, object]:
        if service is None:
            return _checked_delta(
                state,
                {
                    "task_status": "resolution_failed",
                    "next_agent": "end",
                    "errors": ["resolution_service_unavailable"],
                    "trace": [{"node": "resolution", "status": "error"}],
                },
            )
        return _checked_delta(
            state,
            run_resolution_agent(service, state, generator=resolution_generator),
        )

    def supervisor_result_node(state: AgentState) -> dict[str, object]:
        tasks = [task.model_copy(deep=True) for task in state["task_plan"]]
        _refresh_tasks(tasks)
        if state["task_status"] in {
            "proposal_ready",
            "ineligible",
            "needs_clarification",
            "resolution_failed",
        }:
            return _checked_delta(
                state,
                {
                    "task_plan": tasks,
                    "next_agent": "end",
                    "current_task": next(
                        (task.task_id for task in tasks if task.status != "completed"), None
                    ),
                    "trace": [{"node": "supervisor_result", "status": state["task_status"]}],
                },
            )
        if any(task.target_agent == "policy" and task.status == "failed" for task in tasks):
            status, target = "policy_failed", "end"
        elif any(task.target_agent == "order" and task.status == "failed" for task in tasks):
            status, target = "query_failed", "end"
        elif any(task.target_agent == "order" and task.status == "ready" for task in tasks):
            status, target = "planned", "order"
        elif policy_agent is not None and any(
            task.target_agent == "policy" and task.status == "ready" for task in tasks
        ):
            status, target = "planned", "policy"
        elif any(task.target_agent == "resolution" and task.status == "ready" for task in tasks):
            status, target = "planned", "resolution"
        else:
            remaining = [task for task in tasks if task.status != "completed"]
            target = safe_target(remaining[0].target_agent) if remaining else "end"
            if remaining:
                status = "partial"
            elif any(task.target_agent == "policy" for task in tasks):
                status = "policy_answered"
            else:
                status = "queried"
        current = next(
            (task.task_id for task in tasks if task.status == "ready"),
            next((task.task_id for task in tasks if task.status != "completed"), None),
        )
        return _checked_delta(
            state,
            {
                "task_plan": tasks,
                "task_status": status,
                "next_agent": target,
                "current_task": current,
                "trace": [{"node": "supervisor_result", "status": status}],
            },
        )

    def terminal_node(state: AgentState) -> dict[str, object]:
        status = state["task_status"]
        if status == "clarification":
            response = "Please provide: " + ", ".join(state["missing_information"]) + "."
        elif status == "planned":
            response = (
                f"Plan prepared; next target: {state['next_agent']}. "
                "No order or policy work has been executed."
            )
        elif status == "queried":
            response = "Read-only query completed from the business database."
        elif status in {"partial", "policy_answered"} and state["final_response"]:
            response = state["final_response"]
        elif status == "partial":
            response = "Read-only work completed; remaining planned steps have not been executed."
        elif status == "query_failed":
            response = "The read-only query failed. No business change was made."
        elif status == "policy_failed":
            response = state["final_response"] or (
                "Policy retrieval failed. No unsupported answer or business change was produced."
            )
        elif status == "route_limit":
            response = "Routing limit reached. Please contact a human agent."
        elif status == "triage_error":
            response = "I could not understand this request safely. Please try again."
        elif status == "needs_clarification":
            response = (
                "Please provide: " + ", ".join(state["missing_information"]) + ". "
                "No business change was made."
            )
        elif status == "proposal_ready" and state["resolution_proposal"]:
            proposal = state["resolution_proposal"]
            response = (
                f"Validated read-only recommendation {proposal.proposal_id}: "
                f"{proposal.action_type} for order {proposal.order_id} with "
                f"{proposal.proposed_parameters}. Explicit user confirmation would be required "
                "before a later-stage executor could act. No business change was made."
            )
        elif status == "ineligible" and state["eligibility_result"]:
            response = state["eligibility_result"].explanation + " No business change was made."
        elif status == "resolution_failed":
            response = (
                "A supported proposal could not be produced safely. No business change was made."
            )
        else:
            response = (
                "I could not identify a supported request. Please clarify or contact support."
            )
        return _checked_delta(
            state,
            {
                "final_response": response,
                "messages": [AIMessage(content=response)],
                "trace": [{"node": "terminal", "status": status or "unsupported"}],
            },
        )

    def route(state: AgentState) -> str:
        if state["task_status"] == "planned" and state["next_agent"] == "order":
            return "order"
        if (
            policy_agent is not None
            and state["task_status"] == "planned"
            and state["next_agent"] == "policy"
        ):
            return "policy"
        if state["task_status"] == "planned" and state["next_agent"] == "resolution":
            return "resolution"
        return "terminal"

    graph = StateGraph(AgentState)
    graph.add_node("triage", _timed_node("triage", triage_node))
    graph.add_node("supervisor", _timed_node("supervisor", supervisor_node))
    graph.add_node("order", _timed_node("order", order_node))
    graph.add_node("policy", _timed_node("policy", policy_node))
    graph.add_node("resolution", _timed_node("resolution", resolution_node))
    graph.add_node("supervisor_result", _timed_node("supervisor_result", supervisor_result_node))
    graph.add_node("terminal", _timed_node("terminal", terminal_node))
    graph.add_edge(START, "triage")
    graph.add_edge("triage", "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        route,
        {
            "order": "order",
            "policy": "policy",
            "resolution": "resolution",
            "terminal": "terminal",
        },
    )
    graph.add_edge("order", "supervisor_result")
    graph.add_edge("policy", "supervisor_result")
    graph.add_edge("resolution", "supervisor_result")
    graph.add_conditional_edges(
        "supervisor_result",
        route,
        {
            "order": "order",
            "policy": "policy",
            "resolution": "resolution",
            "terminal": "terminal",
        },
    )
    graph.add_edge("terminal", END)
    return graph.compile(checkpointer=checkpointer)


def run_turn(
    service: RetailService,
    session_id: str,
    message: str,
    triage_provider: TriageProvider,
    store: SessionStateStore,
    policy_agent: PolicyAgent | None = None,
    resolution_generator: ResolutionGenerator | None = None,
    persist_messages: bool = True,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """Validate the server session, then run one bounded read-only graph turn."""
    began = perf_counter()
    thread_key = thread_id or session_id
    if not message.strip():
        raise ValueError("message_required")
    with Session(service.engine) as db:
        session = db.get(SessionRow, session_id)
        if session is None:
            raise BusinessError("session_not_found", 404)
        user_id = session.user_id
    message_store = MessageStore(service.engine)
    if persist_messages:
        message_store.append(
            session_id, "user", message, meta={"source": "api"}, thread_id=thread_id
        )
    messages = message_store.checkpoint_messages(session_id, thread_id=thread_id)
    backend = store.backend_for(service.engine)
    graph = build_workflow(
        triage_provider,
        service,
        policy_agent,
        resolution_generator,
        checkpointer=backend.saver,
    )
    config = store.config(thread_key)
    with store.lock:
        previous, recovered = store.load(
            service.engine,
            thread_key,
            session_id=session_id,
            user_id=user_id,
            messages=messages,
        )
        if previous["user_id"] is None and user_id is not None:
            previous = bind_session_identity(previous, user_id)
        elif previous["user_id"] != user_id:
            raise BusinessError("checkpoint_identity_mismatch", 409)
        previous = begin_server_trace(reset_server_confirmation(previous))
        # The route budget bounds one graph turn, not the lifetime of a customer session.
        previous["routing_count"] = 0
        previous["messages"] = messages
        trace_offset = len(previous["trace"])
        tool_offset = len(previous["tool_results"])
        if recovered:
            # A persisted checkpoint may predate newly added state channels. Send
            # every normalized non-additive value so LangGraph creates missing
            # channels instead of exposing a partial legacy state to a node.
            graph_input = {
                key: deepcopy(value)
                for key, value in previous.items()
                if key not in {"messages", "tool_results", "errors", "trace"}
            }
            graph_input.update(
                {
                    "messages": [] if not persist_messages else [messages[-1]],
                    "tool_results": [],
                    "errors": [],
                    "trace": [],
                }
            )
        else:
            graph_input = deepcopy(previous)
        outcome: AgentState = graph.invoke(graph_input, config=config)
        if outcome["thread_id"] != thread_key:
            raise BusinessError("checkpoint_session_mismatch", 409)
        store.states[thread_key] = deepcopy(outcome)
    triage: TriageResult | None = outcome["triage_result"]
    provider = getattr(triage_provider, "provider", None)
    if provider is None and policy_agent is not None:
        provider = getattr(policy_agent.answerer, "provider", None)
    provider_name = type(provider).__name__ if provider is not None else "mock_local"
    token_usage = getattr(provider, "total_usage", None) or None
    response = {
        "input": message,
        "trace_id": outcome["trace_id"],
        "thread_id": outcome["thread_id"],
        "triage": triage.model_dump() if triage else None,
        "task_plan": [task.model_dump() for task in outcome["task_plan"]],
        "next_agent": safe_target(outcome["next_agent"]),
        "missing_information": outcome["missing_information"],
        "task_status": outcome["task_status"],
        "current_task": outcome["current_task"],
        "trace": outcome["trace"][trace_offset:],
        "full_trace": outcome["trace"],
        "tool_results": outcome["tool_results"][tool_offset:],
        "order_context": outcome["order_context"],
        "order_data": {key: result.model_dump() for key, result in outcome["order_data"].items()},
        "policy_context": outcome["policy_context"],
        "policy_retrieval": (
            outcome["policy_retrieval"].model_dump() if outcome["policy_retrieval"] else None
        ),
        "resolution_proposal": (
            outcome["resolution_proposal"].model_dump() if outcome["resolution_proposal"] else None
        ),
        "eligibility_result": (
            outcome["eligibility_result"].model_dump() if outcome["eligibility_result"] else None
        ),
        "pending_action": outcome["pending_action"],
        "risk_flags": outcome["risk_flags"],
        "errors": outcome["errors"],
        "metrics": {
            "elapsed_ms": max(0.0, (perf_counter() - began) * 1000),
            "node_count": len(outcome["trace"][trace_offset:]),
            "tool_calls": len(outcome["tool_results"][tool_offset:]),
            "provider": provider_name,
            "model": getattr(provider, "last_model", None)
            or getattr(provider, "model", "deterministic-v1"),
            "run_config": {
                "temperature": getattr(provider, "temperature", None),
                "seed": getattr(provider, "seed", None),
            },
            "token_usage": token_usage,
        },
        "state": {
            "identity_verified": outcome["identity_verified"],
            "order_id": outcome["order_id"],
            "order_context": outcome["order_context"],
            "next_agent": outcome["next_agent"],
            "routing_count": outcome["routing_count"],
            "policy_context": outcome["policy_context"],
            "resolution_proposal": (
                outcome["resolution_proposal"].model_dump()
                if outcome["resolution_proposal"]
                else None
            ),
            "eligibility_result": (
                outcome["eligibility_result"].model_dump()
                if outcome["eligibility_result"]
                else None
            ),
        },
        "final_response": outcome["final_response"],
    }
    if persist_messages and outcome["final_response"]:
        message_store.append(
            session_id,
            "assistant",
            outcome["final_response"],
            meta={"task_status": outcome["task_status"]},
            trace_id=outcome["trace_id"],
            thread_id=thread_id,
        )
    return response


def _execution_tasks(existing: list[TaskPlan], task_id: str, action_type: str) -> list[TaskPlan]:
    tasks = [task.model_copy(deep=True) for task in existing]
    if not tasks:
        intent = {
            "return": "return_order",
            "modify_address": "modify_order",
        }.get(action_type, "cancel_order")
        prefix = action_type
        tasks = [
            TaskPlan(
                task_id=task_id,
                intent=intent,
                target_agent="resolution",
                status="completed",
            ),
            TaskPlan(
                task_id=f"{prefix}_order-guard",
                intent=intent,
                target_agent="guard",
                dependencies=[task_id],
                status="completed",
            ),
            TaskPlan(
                task_id=f"{prefix}_order-confirmation",
                intent=intent,
                target_agent="confirmation",
                dependencies=[f"{prefix}_order-guard"],
                status="completed",
            ),
            TaskPlan(
                task_id=f"{prefix}_order-execute",
                intent=intent,
                target_agent="executor",
                dependencies=[f"{prefix}_order-confirmation"],
                status="ready",
            ),
        ]
        return tasks
    for task in tasks:
        if task.target_agent == "confirmation":
            task.status = "completed"
            task.required_inputs = []
        elif task.target_agent == "executor":
            task.status = "ready"
            task.required_inputs = []
    return tasks


def build_execution_workflow(
    execution_service: ExecutionService,
    request_id: str,
    idempotency_key: str,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
):
    """A non-LLM continuation graph containing only the controlled executor."""

    def confirmation_gate_node(state: AgentState) -> dict[str, object]:
        request = state["execution_request"]
        confirmation = state["confirmation_record"]
        if (
            not state["user_confirmed"]
            or request is None
            or confirmation is None
            or confirmation.status not in {"valid", "consumed"}
            or confirmation.request_id != request.request_id
            or confirmation.proposal_digest != request.proposal_digest
        ):
            raise BusinessError("confirmation_binding_invalid", 409)
        return _checked_delta(
            state,
            {
                "tool_results": [{"tool": "confirmation_gate", "status": "ok", "code": None}],
                "trace": [{"node": "confirmation", "status": "confirmed"}],
            },
        )

    def execution_node(state: AgentState) -> dict[str, object]:
        request = state["execution_request"]
        if request is None:
            raise BusinessError("execution_request_missing", 409)
        result = execution_service.execute_action(
            state["session_id"], request_id, idempotency_key=idempotency_key
        )
        tasks = [task.model_copy(deep=True) for task in state["task_plan"]]
        for task in tasks:
            if task.target_agent == "executor":
                task.status = "completed"
                task.required_inputs = []
        confirmation = state["confirmation_record"]
        if confirmation is None:
            raise BusinessError("confirmation_required", 409)
        return _checked_delta(
            state,
            {
                "task_plan": tasks,
                "current_task": None,
                "task_status": "executed",
                "next_agent": "end",
                "order_context": {
                    "order_id": result.order_id,
                    "status": result.after_status,
                },
                "order_data": {},
                "pending_action": None,
                "confirmation_record": confirmation.model_copy(update={"status": "consumed"}),
                "execution_result": result,
                "tool_results": [
                    {
                        "tool": f"execute_{request.action_type}_controlled",
                        "status": "ok",
                        "code": None,
                    }
                ],
                "trace": [
                    {
                        "node": "execution",
                        "status": "completed",
                        "tool": f"execute_{request.action_type}_controlled",
                        "arguments": {"request_id": request_id},
                    }
                ],
            },
        )

    def terminal_node(state: AgentState) -> dict[str, object]:
        result = state["execution_result"]
        if result is None:
            response = "Execution did not produce a verified database result."
        else:
            if result.action_type == "return":
                response = (
                    f"Return request for order {result.order_id} was registered. "
                    f"Database status is {result.after_status}; row version is "
                    f"{result.row_version}. No real-world refund has been disbursed."
                )
            elif result.action_type == "modify_address":
                response = (
                    f"The shipping address for order {result.order_id} was updated successfully. "
                    f"Database status is {result.after_status}; row version is "
                    f"{result.row_version}."
                )
            else:
                response = (
                    f"Order {result.order_id} was cancelled successfully. "
                    f"Database status is {result.after_status}; row version is "
                    f"{result.row_version}."
                )
        return _checked_delta(
            state,
            {
                "final_response": response,
                "messages": [AIMessage(content=response)],
                "trace": [{"node": "terminal", "status": state["task_status"] or "executed"}],
            },
        )

    def supervisor_result_node(state: AgentState) -> dict[str, object]:
        if state["execution_result"] is None:
            raise BusinessError("execution_result_missing", 500)
        return _checked_delta(
            state,
            {
                "task_status": "executed",
                "next_agent": "end",
                "trace": [{"node": "supervisor_result", "status": "executed"}],
            },
        )

    graph = StateGraph(AgentState)
    graph.add_node("confirmation", _timed_node("confirmation", confirmation_gate_node))
    graph.add_node("execution", _timed_node("execution", execution_node))
    graph.add_node("supervisor_result", _timed_node("supervisor_result", supervisor_result_node))
    graph.add_node("terminal", _timed_node("terminal", terminal_node))
    graph.add_edge(START, "confirmation")
    graph.add_edge("confirmation", "execution")
    graph.add_edge("execution", "supervisor_result")
    graph.add_edge("supervisor_result", "terminal")
    graph.add_edge("terminal", END)
    return graph.compile(checkpointer=checkpointer)


def run_execution_turn(
    execution_service: ExecutionService,
    session_id: str,
    request_id: str,
    idempotency_key: str,
    store: SessionStateStore,
    *,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """Resume from a persisted trusted confirmation and run the execution node once."""
    thread_key = thread_id or session_id
    request, proposal, eligibility = execution_service.execution_context(session_id, request_id)
    if request.status not in {"confirmed", "executing", "succeeded"}:
        code = {
            "rejected": "confirmation_rejected",
            "expired": "confirmation_expired",
            "superseded": "execution_request_superseded",
            "failed": "execution_request_failed",
        }.get(request.status, "confirmation_required")
        raise BusinessError(code, 409)
    confirmation = execution_service.get_confirmation(session_id, request_id)
    with Session(execution_service.engine) as db:
        session = db.get(SessionRow, session_id)
        if session is None or session.user_id is None:
            raise BusinessError("identity_required", 403)
        user_id = session.user_id
    message_store = MessageStore(execution_service.engine)
    messages = message_store.checkpoint_messages(session_id, thread_id=thread_id)
    backend = store.backend_for(execution_service.engine)
    config = store.config(thread_key)
    with store.lock:
        previous, recovered = store.load(
            execution_service.engine,
            thread_key,
            session_id=session_id,
            user_id=user_id,
            messages=messages,
        )
        if previous["resolution_proposal"] is not None and (
            previous["resolution_proposal"].proposal_id != proposal.proposal_id
        ):
            previous = new_agent_state(session_id, user_id=user_id, thread_id=thread_key)
            previous["messages"] = messages
            recovered = False
        tasks = _execution_tasks(previous["task_plan"], proposal.task_id, request.action_type)
        trace_offset = len(previous["trace"])
        tool_offset = len(previous["tool_results"])
        state = apply_agent_update(
            begin_server_trace(previous),
            {
                "order_id": proposal.order_id,
                "order_context": {
                    "order_id": proposal.order_id,
                    "status": eligibility.checked_order_status,
                },
                "resolution_proposal": proposal,
                "eligibility_result": eligibility,
                "execution_request": request,
                "task_plan": tasks,
                "current_task": f"{request.action_type}_order-execute",
                "task_status": "pending_confirmation",
                "next_agent": "end",
            },
        )
        state = bind_server_confirmation(state, request, confirmation)
        execution_graph = build_execution_workflow(
            execution_service,
            request_id,
            idempotency_key,
            checkpointer=backend.saver,
        )
        graph_input: dict[str, object] = (
            {
                "messages": [],
                "trace_id": state["trace_id"],
                "order_id": state["order_id"],
                "order_context": state["order_context"],
                "resolution_proposal": state["resolution_proposal"],
                "eligibility_result": state["eligibility_result"],
                "execution_request": state["execution_request"],
                "confirmation_record": state["confirmation_record"],
                "user_confirmed": state["user_confirmed"],
                "task_plan": state["task_plan"],
                "current_task": state["current_task"],
                "task_status": state["task_status"],
                "next_agent": state["next_agent"],
                "order_data": {},
                "policy_context": [],
                "policy_retrieval": None,
            }
            if recovered
            else state
        )
        outcome: AgentState = execution_graph.invoke(graph_input, config=config)
        store.states[thread_key] = deepcopy(outcome)
    result = outcome["execution_result"]
    return {
        "trace_id": outcome["trace_id"],
        "request_id": request_id,
        "task_status": outcome["task_status"],
        "task_plan": [task.model_dump() for task in outcome["task_plan"]],
        "confirmation": outcome["confirmation_record"].model_dump()
        if outcome["confirmation_record"]
        else None,
        "execution_result": result.model_dump() if result else None,
        "order_context": outcome["order_context"],
        "trace": outcome["trace"][trace_offset:],
        "full_trace": outcome["trace"],
        "tool_results": outcome["tool_results"][tool_offset:],
        "final_response": outcome["final_response"],
    }
