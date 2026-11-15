"""Typed LangGraph state; business authorization remains in RetailService."""

from collections.abc import Mapping
from copy import deepcopy
from operator import add
from typing import Annotated, Literal, cast
from uuid import uuid4

from langchain_core.messages import AnyMessage, BaseMessage
from langgraph.channels import UntrackedValue
from langgraph.graph.message import add_messages
from pydantic import (
    ConfigDict,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    TypeAdapter,
    ValidationError,
)
from typing_extensions import NotRequired, TypedDict

from app.multi_agent.models import (
    ConfirmationRecord,
    EligibilityResult,
    ExecutionRequestSummary,
    ExecutionResult,
    FlowStatus,
    OrderQueryResult,
    ResolutionProposal,
    TaskPlan,
    TriageResult,
)
from app.multi_agent.policy_knowledge import SearchResult


class OrderContext(TypedDict):
    order_id: StrictStr
    status: StrictStr


class PolicyEvidence(TypedDict):
    source: StrictStr
    section: StrictStr
    version: StrictStr
    excerpt: StrictStr
    chunk_id: NotRequired[StrictStr]
    score: NotRequired[StrictFloat]
    retrieval_method: NotRequired[StrictStr]


class PendingAction(TypedDict):
    proposal_id: StrictStr
    order_id: StrictStr
    action: StrictStr
    summary: StrictStr


class ToolResult(TypedDict):
    tool: StrictStr
    status: Literal["ok", "error"]
    code: StrictStr | None


class TraceEvent(TypedDict):
    node: StrictStr
    status: StrictStr
    trace_id: NotRequired[StrictStr]
    task_id: NotRequired[StrictStr]
    request_id: NotRequired[StrictStr]
    elapsed_ms: NotRequired[StrictFloat]
    tool: NotRequired[StrictStr]
    arguments: NotRequired[dict[StrictStr, StrictStr]]
    code: NotRequired[StrictStr]


class AgentState(TypedDict):
    """One graph invocation/session; no raw customer profile or credentials."""

    __pydantic_config__ = ConfigDict(extra="forbid")

    messages: Annotated[list[AnyMessage], add_messages]
    trace_id: StrictStr
    session_id: StrictStr
    thread_id: StrictStr
    user_id: StrictStr | None
    identity_verified: StrictBool
    intent: StrictStr | None
    current_task: StrictStr | None
    order_id: StrictStr | None
    order_context: OrderContext | None
    policy_context: Annotated[list[PolicyEvidence], UntrackedValue]
    policy_retrieval: Annotated[SearchResult | None, UntrackedValue]
    pending_action: PendingAction | None
    user_confirmed: StrictBool
    tool_results: Annotated[list[ToolResult], add]
    next_agent: Literal["triage", "order", "policy", "resolution", "end"] | None
    routing_count: StrictInt
    errors: Annotated[list[StrictStr], add]
    final_response: StrictStr | None
    triage_result: TriageResult | None
    task_plan: list[TaskPlan]
    missing_information: list[StrictStr]
    task_status: FlowStatus | None
    trace: Annotated[list[TraceEvent], add]
    order_data: Annotated[dict[StrictStr, OrderQueryResult], UntrackedValue]
    resolution_proposal: ResolutionProposal | None
    eligibility_result: EligibilityResult | None
    risk_flags: list[StrictStr]
    execution_request: ExecutionRequestSummary | None
    confirmation_record: ConfirmationRecord | None
    execution_result: ExecutionResult | None


_STATE_ADAPTER = TypeAdapter(AgentState)
_PROTECTED = frozenset(
    {
        "session_id",
        "thread_id",
        "trace_id",
        "user_id",
        "identity_verified",
        "user_confirmed",
    }
)


def new_agent_state(
    session_id: str, *, user_id: str | None = None, thread_id: str | None = None
) -> AgentState:
    """Create fresh state from a server-owned session and verified database identity.

    The caller must read SessionRow.user_id; a supplied user_id is never proof of identity.
    ``thread_id`` is the server-resolved support thread that isolates one order.
    """
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("session_id_required")
    if user_id is not None and (not isinstance(user_id, str) or not user_id.strip()):
        raise ValueError("user_id_invalid")
    if thread_id is not None and (not isinstance(thread_id, str) or not thread_id.strip()):
        raise ValueError("thread_id_invalid")
    return cast(
        AgentState,
        _STATE_ADAPTER.validate_python(
            {
                "messages": [],
                "trace_id": uuid4().hex,
                "session_id": session_id,
                "thread_id": thread_id or session_id,
                "user_id": user_id,
                "identity_verified": user_id is not None,
                "intent": None,
                "current_task": None,
                "order_id": None,
                "order_context": None,
                "policy_context": [],
                "policy_retrieval": None,
                "pending_action": None,
                "user_confirmed": False,
                "tool_results": [],
                "next_agent": None,
                "routing_count": 0,
                "errors": [],
                "final_response": None,
                "triage_result": None,
                "task_plan": [],
                "missing_information": [],
                "task_status": None,
                "trace": [],
                "order_data": {},
                "resolution_proposal": None,
                "eligibility_result": None,
                "risk_flags": [],
                "execution_request": None,
                "confirmation_record": None,
                "execution_result": None,
            },
            strict=True,
        ),
    )


def begin_server_trace(state: AgentState) -> AgentState:
    """Rotate the server-owned correlation ID for one user/API turn."""
    candidate = deepcopy(state)
    candidate["trace_id"] = uuid4().hex
    return cast(AgentState, _STATE_ADAPTER.validate_python(candidate, strict=True))


def restore_agent_state(
    values: Mapping[str, object],
    session_id: str,
    *,
    user_id: str | None,
    messages: list[AnyMessage] | None = None,
    thread_id: str | None = None,
) -> AgentState:
    """Rebuild a full state from a checkpoint while rebinding server identity.

    Untracked values are intentionally absent from PostgreSQL checkpoints and are
    supplied from normalized messages or recomputed from authoritative services.
    """
    expected_thread = thread_id or session_id
    checkpoint_session = values.get("session_id")
    checkpoint_thread = values.get("thread_id")
    checkpoint_user = values.get("user_id")
    if checkpoint_session not in (None, session_id) or checkpoint_thread not in (
        None,
        expected_thread,
    ):
        raise ValueError("checkpoint_session_mismatch")
    if checkpoint_user not in (None, user_id):
        raise ValueError("checkpoint_identity_mismatch")
    candidate = new_agent_state(session_id, user_id=user_id, thread_id=expected_thread)
    for key, value in values.items():
        if key in candidate and key not in {
            "session_id",
            "thread_id",
            "user_id",
            "identity_verified",
        }:
            candidate[key] = deepcopy(value)
    candidate["session_id"] = session_id
    candidate["thread_id"] = expected_thread
    candidate["user_id"] = user_id
    candidate["identity_verified"] = user_id is not None
    if "messages" not in values:
        candidate["messages"] = deepcopy(messages or [])
    candidate["order_data"] = {}
    candidate["policy_context"] = []
    candidate["policy_retrieval"] = None
    try:
        return cast(AgentState, _STATE_ADAPTER.validate_python(candidate, strict=True))
    except ValidationError as exc:
        raise ValueError("checkpoint_state_invalid") from exc


def bind_session_identity(state: AgentState, user_id: str) -> AgentState:
    """Preserve a pending clarification after the server verifies this session."""
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("user_id_invalid")
    if state["user_id"] not in (None, user_id):
        raise ValueError("session_identity_conflict")
    candidate = deepcopy(state)
    candidate["user_id"] = user_id
    candidate["identity_verified"] = True
    return cast(AgentState, _STATE_ADAPTER.validate_python(candidate, strict=True))


def bind_server_confirmation(
    state: AgentState,
    request: ExecutionRequestSummary,
    confirmation: ConfirmationRecord,
) -> AgentState:
    """Bind only a persisted, operation-specific server confirmation to graph state."""
    valid_status_pair = (
        confirmation.status == "valid" and request.status == "confirmed"
    ) or (
        confirmation.status == "consumed" and request.status == "succeeded"
    )
    if (
        confirmation.decision != "confirm"
        or not valid_status_pair
        or confirmation.request_id != request.request_id
        or confirmation.proposal_id != request.proposal_id
        or confirmation.proposal_version != request.proposal_version
        or confirmation.proposal_digest != request.proposal_digest
        or confirmation.order_id != request.order_id
    ):
        raise ValueError("confirmation_binding_invalid")
    candidate = deepcopy(state)
    candidate["user_confirmed"] = True
    candidate["execution_request"] = request
    candidate["confirmation_record"] = confirmation
    return cast(AgentState, _STATE_ADAPTER.validate_python(candidate, strict=True))


def reset_server_confirmation(state: AgentState) -> AgentState:
    """A confirmation never carries over to a newly triaged operation."""
    candidate = deepcopy(state)
    candidate["user_confirmed"] = False
    candidate["execution_request"] = None
    candidate["confirmation_record"] = None
    candidate["execution_result"] = None
    return cast(AgentState, _STATE_ADAPTER.validate_python(candidate, strict=True))


def apply_agent_update(state: AgentState, update: dict[str, object]) -> AgentState:
    """Validate a node delta without allowing it to set server-owned identity/consent."""
    if _PROTECTED.intersection(update):
        raise ValueError("protected_state_field")
    candidate = deepcopy(state)
    for key, value in update.items():
        if key == "messages":
            if not isinstance(value, list) or not all(isinstance(m, BaseMessage) for m in value):
                raise ValueError("messages_invalid")
            candidate["messages"] = add_messages(candidate["messages"], deepcopy(value))
        elif key in {"tool_results", "errors", "trace"}:
            if not isinstance(value, list):
                raise ValueError("append_field_invalid")
            candidate[key] = candidate[key] + deepcopy(value)
        else:
            candidate[key] = deepcopy(value)
    try:
        validated = _STATE_ADAPTER.validate_python(candidate, strict=True)
    except ValidationError as exc:
        raise ValueError("agent_state_invalid") from exc
    if validated["routing_count"] < 0:
        raise ValueError("routing_count_invalid")
    if not validated["identity_verified"] and (
        validated["order_context"] is not None
        or validated["pending_action"] is not None
        or validated["resolution_proposal"] is not None
    ):
        raise ValueError("identity_required")
    if (
        any(result.kind != "product" for result in validated["order_data"].values())
        and not validated["identity_verified"]
    ):
        raise ValueError("identity_required")
    if validated["order_context"] is not None and (
        validated["order_id"] != validated["order_context"]["order_id"]
    ):
        raise ValueError("order_context_mismatch")
    if validated["pending_action"] is not None and (
        validated["order_id"] != validated["pending_action"]["order_id"]
    ):
        raise ValueError("pending_action_mismatch")
    if validated["user_confirmed"]:
        request = validated["execution_request"]
        confirmation = validated["confirmation_record"]
        if (
            request is None
            or confirmation is None
            or confirmation.status not in {"valid", "consumed"}
            or confirmation.request_id != request.request_id
            or confirmation.proposal_digest != request.proposal_digest
        ):
            raise ValueError("confirmation_binding_invalid")
    return cast(AgentState, validated)
