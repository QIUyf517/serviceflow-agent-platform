"""Pinned τ-bench text adapter. The official environment owns tools and scoring."""

import json
import re
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from tau2.agent.base_agent import HalfDuplexAgent, ValidAgentInputMessage
from tau2.data_model.message import (
    AssistantMessage,
    Message,
    MultiToolMessage,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from tau2.environment.tool import Tool

from app.config import Settings
from app.llm import ModelProvider, ModelToolCall, OpenAICompatibleProvider

AUTH_TOOLS = {"find_user_id_by_email", "find_user_id_by_name_zip"}
WRITE_TOOLS = {
    "cancel_pending_order",
    "modify_pending_order_address",
    "modify_pending_order_items",
    "modify_pending_order_payment",
    "modify_user_address",
    "return_delivered_order_items",
    "exchange_delivered_order_items",
}
CONFIRM_WORDS = {"yes", "确认", "是", "同意"}


def _is_confirmation(value: str) -> bool:
    message = value.strip().casefold()
    if message in CONFIRM_WORDS:
        return True
    return bool(
        re.fullmatch(
            r"yes[.!]|yes,? (confirmed|go ahead(?: and process it)?|please|i confirm)[.!]?",
            message,
        )
    )


@dataclass
class TauState:
    messages: list[Message] = field(default_factory=list)
    verified_user_id: str | None = None
    own_order_ids: set[str] = field(default_factory=set)
    pending_write: ModelToolCall | None = None
    last_tool_name: str | None = None


def _as_chat(messages: list[Message], policy: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are a retail support agent. Follow this policy exactly. "
                "Use at most one tool per response. Never claim success before a tool succeeds.\n"
                + policy
            ),
        }
    ]
    for message in messages:
        if isinstance(message, UserMessage):
            result.append({"role": "user", "content": message.content or ""})
        elif isinstance(message, AssistantMessage):
            item: dict[str, Any] = {"role": "assistant", "content": message.content}
            if message.tool_calls:
                item["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": json.dumps(call.arguments)},
                    }
                    for call in message.tool_calls
                ]
            result.append(item)
        elif isinstance(message, ToolMessage):
            result.append(
                {"role": "tool", "tool_call_id": message.id, "content": message.content or ""}
            )
        elif isinstance(message, MultiToolMessage):
            for tool_message in message.tool_messages:
                result.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_message.id,
                        "content": tool_message.content or "",
                    }
                )
    return result


class ServiceFlowTauAgent(HalfDuplexAgent[TauState]):
    def __init__(self, tools: list[Tool], domain_policy: str, provider: ModelProvider) -> None:
        super().__init__(tools=tools, domain_policy=domain_policy)
        self.provider = provider
        self.tool_map = {tool.name: tool for tool in tools}

    def get_init_state(self, message_history: list[Message] | None = None) -> TauState:
        state = TauState()
        for message in message_history or []:
            state.messages.append(message)
            if isinstance(message, AssistantMessage) and message.tool_calls:
                state.last_tool_name = message.tool_calls[0].name
            elif isinstance(message, ToolMessage):
                self._consume_tool(state, message)
        return state

    @staticmethod
    def _consume_tool(state: TauState, message: ToolMessage) -> None:
        if message.error:
            state.last_tool_name = None
            return
        if state.last_tool_name in AUTH_TOOLS:
            identity = (message.content or "").strip().strip('"')
            if identity and not identity.startswith("Error"):
                state.verified_user_id = identity
        elif state.last_tool_name == "get_user_details":
            try:
                profile = json.loads(message.content or "{}")
                if profile.get("user_id") == state.verified_user_id:
                    state.own_order_ids = set(profile.get("orders", []))
            except (ValueError, TypeError, AttributeError):
                pass
        state.last_tool_name = None

    def _guard(self, state: TauState, call: ModelToolCall) -> str | None:
        if call.name not in self.tool_map:
            return "Tool not allowed."
        if call.name in AUTH_TOOLS:
            if state.verified_user_id:
                return "This conversation is already bound to one customer."
            evidence = " ".join(
                m.content or "" for m in state.messages if isinstance(m, UserMessage)
            ).casefold()
            fields = (
                [call.arguments.get("email")]
                if call.name.endswith("email")
                else [
                    call.arguments.get("first_name"),
                    call.arguments.get("last_name"),
                    call.arguments.get("zip"),
                ]
            )
            if not all(isinstance(value, str) and value.casefold() in evidence for value in fields):
                return "Please provide your email or name and zip for verification."
            return None
        if not state.verified_user_id:
            return "Please verify your identity first."
        if call.name == "get_user_details":
            if call.arguments.get("user_id") != state.verified_user_id:
                return "Other customer profiles are not available."
        elif call.name in {"get_order_details"} | WRITE_TOOLS:
            if call.name == "modify_user_address":
                if call.arguments.get("user_id") != state.verified_user_id:
                    return "Other customer profiles are not available."
            elif call.arguments.get("order_id") not in state.own_order_ids:
                return "Load your profile and use only an order in your own order list."
        return None

    def generate_next_message(
        self, message: ValidAgentInputMessage, state: TauState
    ) -> tuple[AssistantMessage, TauState]:
        if isinstance(message, MultiToolMessage):
            for item in message.tool_messages:
                state.messages.append(item)
                self._consume_tool(state, item)
        else:
            state.messages.append(message)
            if isinstance(message, ToolMessage):
                self._consume_tool(state, message)
        if state.pending_write:
            if (
                isinstance(message, UserMessage)
                and _is_confirmation(message.content or "")
            ):
                call = state.pending_write
                state.pending_write = None
                rejection = self._guard(state, call)
                if rejection:
                    response = AssistantMessage.text(rejection)
                else:
                    response = AssistantMessage.text(
                        "",
                        tool_calls=[ToolCall(id=call.id, name=call.name, arguments=call.arguments)],
                    )
                    state.last_tool_name = call.name
                state.messages.append(response)
                return response, state
            if isinstance(message, UserMessage):
                state.pending_write = None
        allowed = [
            tool.openai_schema
            for tool in self.tools
            if state.verified_user_id or tool.name in AUTH_TOOLS
        ]
        started = perf_counter()
        reply = self.provider.complete(_as_chat(state.messages, self.domain_policy), allowed)
        elapsed = perf_counter() - started
        if len(reply.tool_calls) > 1:
            response = AssistantMessage.text(
                "I can use only one tool at a time.",
                usage=reply.usage,
                generation_time_seconds=elapsed,
            )
        elif reply.tool_calls:
            call = reply.tool_calls[0]
            rejection = self._guard(state, call)
            if rejection:
                response = AssistantMessage.text(
                    rejection,
                    usage=reply.usage,
                    generation_time_seconds=elapsed,
                    raw_data={"guard_rejection": rejection},
                )
            elif call.name in WRITE_TOOLS:
                state.pending_write = call
                details = json.dumps(call.arguments, ensure_ascii=False, sort_keys=True)
                response = AssistantMessage.text(
                    f"Please confirm this {call.name} action with yes: {details}",
                    usage=reply.usage,
                    generation_time_seconds=elapsed,
                )
            else:
                response = AssistantMessage.text(
                    "",
                    tool_calls=[ToolCall(id=call.id, name=call.name, arguments=call.arguments)],
                    usage=reply.usage,
                    generation_time_seconds=elapsed,
                )
                state.last_tool_name = call.name
        else:
            response = AssistantMessage.text(
                reply.content or "", usage=reply.usage, generation_time_seconds=elapsed
            )
        state.messages.append(response)
        return response, state


def create_serviceflow_tau_agent(
    tools: list[Tool], domain_policy: str, **kwargs: Any
) -> ServiceFlowTauAgent:
    # Deliberately ignore task and evaluation criteria passed by the registry.
    settings = Settings()
    settings = settings.model_copy(update={"agent_model": kwargs.get("llm", settings.agent_model)})
    return ServiceFlowTauAgent(tools, domain_policy, OpenAICompatibleProvider(settings))
