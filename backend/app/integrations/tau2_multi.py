"""Role-separated τ-bench adapter sharing the single adapter's deterministic guard."""

import hashlib
import json
from time import perf_counter
from typing import Any

from tau2.agent.base_agent import ValidAgentInputMessage
from tau2.data_model.message import (
    AssistantMessage,
    MultiToolMessage,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from tau2.environment.tool import Tool

from app.config import Settings
from app.integrations.tau2 import (
    AUTH_TOOLS,
    WRITE_TOOLS,
    ServiceFlowTauAgent,
    TauState,
    _as_chat,
    _is_confirmation,
)
from app.llm import ModelProvider, ModelToolCall, OpenAICompatibleProvider

READ_TOOLS = {
    "calculate",
    "get_order_details",
    "get_product_details",
    "get_item_details",
    "get_user_details",
    "list_all_product_types",
}
HUMAN_TOOLS = {"transfer_to_human_agents"}
WRITE_INTENT_TERMS = {
    "exchange": ("exchange", "swap", "换货"),
    "return": ("return", "refund", "退货", "退款"),
    "cancel": ("cancel", "cancellation", "取消订单"),
    "modify": (
        "modify",
        "change",
        "update",
        "address",
        "payment",
        "修改",
        "更改",
        "地址",
        "支付",
    ),
}
WORKFLOW_ABORT_MESSAGES = {
    "no",
    "no.",
    "never mind",
    "nevermind",
    "stop",
    "算了",
    "不用了",
    "不要了",
    "停止",
}


class ServiceFlowTauMultiAgent(ServiceFlowTauAgent):
    """Deterministic supervisor plus role-specific tools and prompts."""

    def __init__(
        self,
        tools: list[Tool],
        domain_policy: str,
        provider: ModelProvider,
        *,
        max_tool_calls: int = 6,
        max_total_tokens: int = 120_000,
    ) -> None:
        super().__init__(
            tools,
            domain_policy,
            provider,
            max_tool_calls=max_tool_calls,
            max_total_tokens=max_total_tokens,
        )

    @staticmethod
    def _latest_user_text(state: TauState) -> str:
        return next(
            (
                message.content or ""
                for message in reversed(state.messages)
                if isinstance(message, UserMessage)
            ),
            "",
        )

    @staticmethod
    def _requested_route(text: str) -> str:
        lowered = text.casefold()
        if any(word in lowered for word in ("human", "representative", "人工")):
            return "human_specialist"
        if any(
            word in lowered
            for word in (
                "cancel",
                "modify",
                "return",
                "exchange",
                "refund",
                "address",
                "payment",
                "取消",
                "修改",
                "退货",
                "换货",
            )
        ):
            return "resolution_specialist"
        if any(word in lowered for word in ("policy", "rule", "eligible", "政策", "规则")):
            return "policy_specialist"
        return "order_specialist"

    @staticmethod
    def _write_intent(text: str) -> str | None:
        lowered = text.casefold()
        return next(
            (
                intent
                for intent, terms in WRITE_INTENT_TERMS.items()
                if any(term in lowered for term in terms)
            ),
            None,
        )

    @staticmethod
    def _is_workflow_abort(text: str) -> bool:
        return text.strip().casefold() in WORKFLOW_ABORT_MESSAGES

    @staticmethod
    def _proposal_fingerprint(name: str, arguments: dict[str, Any]) -> str:
        canonical = json.dumps(
            {"name": name, "arguments": arguments},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _update_workflow_from_user(self, state: TauState, text: str) -> None:
        if self._is_workflow_abort(text):
            state.pending_write = None
            state.workflow.clear()
            return
        intent = self._write_intent(text)
        if intent is None:
            return
        if state.workflow.intent != intent:
            state.pending_write = None
            state.workflow.clear_proposal()
        state.workflow.intent = intent
        if state.workflow.stage not in {"awaiting_confirmation", "executing"}:
            state.workflow.stage = "gathering"

    @staticmethod
    def _invalidate_proposal(state: TauState) -> None:
        state.pending_write = None
        state.workflow.clear_proposal()
        if state.workflow.intent is not None:
            state.workflow.stage = "gathering"

    def _record_proposal(self, state: TauState, call: ModelToolCall) -> str:
        fingerprint = self._proposal_fingerprint(call.name, call.arguments)
        state.pending_write = call
        state.workflow.intent = state.workflow.intent or call.name
        state.workflow.stage = "awaiting_confirmation"
        state.workflow.order_id = call.arguments.get("order_id")
        state.workflow.proposal_name = call.name
        state.workflow.proposal_arguments = dict(call.arguments)
        state.workflow.proposal_fingerprint = fingerprint
        return fingerprint

    def _consume_and_update_workflow(
        self, state: TauState, message: ToolMessage
    ) -> None:
        completed_tool = state.last_tool_name
        self._consume_tool(state, message)
        if message.error:
            if completed_tool in WRITE_TOOLS:
                state.workflow.stage = "blocked"
            return
        if completed_tool in WRITE_TOOLS:
            state.workflow.completed_writes += 1
            state.workflow.stage = "post_execution"
            state.workflow.clear_proposal()
        elif completed_tool in HUMAN_TOOLS:
            state.workflow.clear()

    def _route(self, state: TauState) -> str:
        if not state.verified_user_id:
            return "identity_specialist"
        if not state.profile_loaded:
            return "order_specialist"
        requested_route = self._requested_route(self._latest_user_text(state))
        if requested_route in {"human_specialist", "policy_specialist"}:
            return requested_route
        if state.workflow.active:
            return "resolution_specialist"
        return requested_route

    @staticmethod
    def _role_instruction(route: str) -> str:
        return {
            "identity_specialist": (
                "The deterministic supervisor selected the identity specialist. Verify only "
                "identity evidence explicitly present in the conversation."
            ),
            "order_specialist": (
                "The deterministic supervisor selected the read-only order and product specialist. "
                "Retrieve only the verified customer's data and do not propose writes."
            ),
            "policy_specialist": (
                "The deterministic supervisor selected the policy specialist. Explain the supplied "
                "official policy without performing a business write."
            ),
            "resolution_specialist": (
                "The deterministic supervisor selected the resolution specialist. Gather current "
                "facts and propose at most one allowed action. When every required argument is "
                "known, emit the write tool call immediately; do not ask for confirmation in "
                "prose. The adapter will intercept the call, show the exact arguments, and require "
                "explicit confirmation before execution."
            ),
            "human_specialist": (
                "The deterministic supervisor selected human handoff. Use only the handoff tool "
                "when appropriate."
            ),
        }[route]

    @staticmethod
    def _allowed_names(route: str) -> set[str]:
        if route == "identity_specialist":
            return AUTH_TOOLS
        if route == "order_specialist":
            return READ_TOOLS
        if route == "policy_specialist":
            return set()
        if route == "human_specialist":
            return HUMAN_TOOLS
        return READ_TOOLS | WRITE_TOOLS | HUMAN_TOOLS

    def generate_next_message(
        self, message: ValidAgentInputMessage, state: TauState
    ) -> tuple[AssistantMessage, TauState]:
        if isinstance(message, MultiToolMessage):
            for item in message.tool_messages:
                state.messages.append(item)
                self._consume_and_update_workflow(state, item)
        else:
            state.messages.append(message)
            if isinstance(message, ToolMessage):
                self._consume_and_update_workflow(state, message)
            elif isinstance(message, UserMessage):
                self._update_workflow_from_user(state, message.content or "")

        if state.pending_write:
            if isinstance(message, UserMessage) and _is_confirmation(message.content or ""):
                call = state.pending_write
                actual_fingerprint = self._proposal_fingerprint(call.name, call.arguments)
                if actual_fingerprint != state.workflow.proposal_fingerprint:
                    self._invalidate_proposal(state)
                    response = AssistantMessage.text(
                        "The proposed action changed. I need to show a new exact summary before "
                        "you can confirm it.",
                        raw_data={"guard_rejection": "proposal_fingerprint_mismatch"},
                    )
                    state.messages.append(response)
                    return response, state
                state.pending_write = None
                rejection = self._guard(state, call)
                if rejection:
                    state.workflow.stage = "blocked"
                    response = AssistantMessage.text(rejection)
                else:
                    response = self._emit_tool_call(state, call)
                    state.workflow.stage = (
                        "executing" if response.tool_calls else "blocked"
                    )
                state.messages.append(response)
                return response, state
            if isinstance(message, UserMessage):
                self._invalidate_proposal(state)

        route = self._route(state)
        state.route_history.append(route)
        allowed_names = self._allowed_names(route)
        allowed = [tool.openai_schema for tool in self.tools if tool.name in allowed_names]
        chat = _as_chat(state.messages, self.domain_policy)
        chat.insert(1, {"role": "system", "content": self._role_instruction(route)})
        started = perf_counter()
        reply = self.provider.complete(chat, allowed)
        elapsed = perf_counter() - started
        self._record_usage(state, reply.usage)

        if state.total_tokens_used > self.max_total_tokens:
            response = AssistantMessage.text(
                "I cannot safely continue because this task reached its fixed token budget.",
                usage=reply.usage,
                generation_time_seconds=elapsed,
                raw_data={"budget_rejection": "token_budget_exhausted"},
            )
        elif len(reply.tool_calls) > 1:
            response = AssistantMessage.text(
                "I can use only one tool at a time.",
                usage=reply.usage,
                generation_time_seconds=elapsed,
            )
        elif reply.tool_calls:
            call = reply.tool_calls[0]
            rejection = self._guard(state, call)
            if call.name not in allowed_names:
                rejection = "Tool not allowed for the selected specialist."
            if rejection:
                response = AssistantMessage.text(
                    rejection,
                    usage=reply.usage,
                    generation_time_seconds=elapsed,
                    raw_data={"guard_rejection": rejection, "route": route},
                )
            elif call.name in WRITE_TOOLS:
                fingerprint = self._record_proposal(state, call)
                details = json.dumps(call.arguments, ensure_ascii=False, sort_keys=True)
                response = AssistantMessage.text(
                    f"Please confirm this {call.name} action with yes: {details}",
                    usage=reply.usage,
                    generation_time_seconds=elapsed,
                    raw_data={
                        "route": route,
                        "workflow_intent": state.workflow.intent,
                        "proposal_fingerprint": fingerprint,
                    },
                )
            else:
                budget_rejection = self._budget_rejection(state)
                if budget_rejection is not None:
                    response = budget_rejection
                else:
                    state.tool_calls_used += 1
                    state.last_tool_name = call.name
                    response = AssistantMessage.text(
                        "",
                        tool_calls=[ToolCall(id=call.id, name=call.name, arguments=call.arguments)],
                        usage=reply.usage,
                        generation_time_seconds=elapsed,
                        raw_data={"route": route},
                    )
        else:
            response = AssistantMessage.text(
                reply.content or "",
                usage=reply.usage,
                generation_time_seconds=elapsed,
                raw_data={"route": route},
            )
        state.messages.append(response)
        return response, state


def create_serviceflow_tau_multi_agent(
    tools: list[Tool], domain_policy: str, **kwargs: Any
) -> ServiceFlowTauMultiAgent:
    # Deliberately ignore task and evaluation criteria passed by the registry.
    settings = Settings()
    settings = settings.model_copy(update={"agent_model": kwargs.get("llm", settings.agent_model)})
    return ServiceFlowTauMultiAgent(
        tools,
        domain_policy,
        OpenAICompatibleProvider(settings),
        max_tool_calls=settings.agent_max_tool_calls,
        max_total_tokens=settings.agent_max_total_tokens,
    )
