"""Minimal OpenAI-compatible Chat Completions tool calling transport."""

import json
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field

from app.config import Settings


class ModelToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class ModelReply(BaseModel):
    content: str | None = None
    tool_calls: list[ModelToolCall] = Field(default_factory=list)
    usage: dict[str, int] | None = None
    model: str | None = None


class ModelProvider(Protocol):
    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> ModelReply: ...


class ProviderError(Exception):
    """Safe provider failure: do not expose credential or raw HTTP response."""


class OpenAICompatibleProvider:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        key = settings.effective_key
        if key is None or not key.get_secret_value():
            raise ProviderError("agent_api_key_missing")
        self.model = settings.effective_model
        base_url = settings.effective_base_url
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.deepseek = "api.deepseek.com" in base_url
        self.key = key.get_secret_value()
        self.timeout = settings.agent_timeout_seconds
        self.transport = transport
        self.temperature = settings.agent_temperature
        self.seed = None if self.deepseek else settings.agent_seed

    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelReply:
        request: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto" if tools else "none",
            "temperature": self.temperature,
        }
        if self.deepseek:
            request["thinking"] = {"type": "disabled"}
        else:
            request["parallel_tool_calls"] = False
        if self.seed is not None:
            request["seed"] = self.seed
        try:
            with httpx.Client(transport=self.transport, timeout=self.timeout) as client:
                response = client.post(
                    self.url, json=request, headers={"Authorization": f"Bearer {self.key}"}
                )
                response.raise_for_status()
                data = response.json()
            message = data["choices"][0]["message"]
            calls = []
            for call in message.get("tool_calls") or []:
                if call.get("type") != "function":
                    raise ProviderError("unsupported_tool_call")
                arguments = json.loads(call["function"]["arguments"])
                if not isinstance(arguments, dict):
                    raise ProviderError("tool_arguments_invalid")
                calls.append(
                    ModelToolCall(id=call["id"], name=call["function"]["name"], arguments=arguments)
                )
            usage = data.get("usage")
            return ModelReply(
                content=message.get("content"),
                tool_calls=calls,
                usage={k: int(v) for k, v in usage.items() if isinstance(v, int)}
                if isinstance(usage, dict)
                else None,
                model=data.get("model"),
            )
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError("model_request_failed") from exc
