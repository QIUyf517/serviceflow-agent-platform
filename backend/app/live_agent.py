"""Durable single-agent tool loop; all business writes remain in RetailService."""

import json
from time import perf_counter
from typing import Any, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import ChatTraceRow, ConversationRow, SessionRow
from app.llm import ModelProvider, ModelReply, ProviderError
from app.service import Action, BusinessError, RetailService

CONFIRM_WORDS = {"yes", "确认", "是", "同意"}


def _tool(
    name: str, description: str, properties: dict[str, Any], required: list[str]
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


STRING = {"type": "string"}
ORDER_ID = {"type": "string", "description": "Exact order ID including leading #, e.g. #W0000000."}
REASON = {"type": "string", "enum": ["no longer needed", "ordered by mistake"]}
ITEM_IDS = {"type": "array", "items": STRING, "minItems": 1}
ADDRESS = {
    "type": "object",
    "properties": {key: STRING for key in ("address1", "address2", "city", "state", "country")},
    "required": ["address1", "city", "state", "country"],
    "additionalProperties": False,
}
PROPOSALS = {
    "propose_cancel_order": "cancel",
    "propose_modify_address": "modify_address",
    "propose_modify_payment": "modify_payment",
    "propose_modify_items": "modify_items",
    "propose_return_order": "return",
    "propose_exchange_order": "exchange",
}
TOOLS = [
    _tool(
        "find_user_id_by_email",
        "Verify identity using the email supplied by this user.",
        {"email": STRING},
        ["email"],
    ),
    _tool("get_user_details", "Get the verified customer's own profile.", {}, []),
    _tool("get_orders", "List only the verified customer's orders.", {}, []),
    _tool(
        "get_order_details",
        "Get one order owned by the verified customer.",
        {"order_id": ORDER_ID},
        ["order_id"],
    ),
    _tool(
        "get_product_details",
        "Get product and available variants after verification.",
        {"product_id": STRING},
        ["product_id"],
    ),
    _tool(
        "propose_cancel_order",
        "Validate a pending cancellation and create a proposal. "
        "Use the exact reason enum. No change occurs until user confirmation.",
        {"order_id": ORDER_ID, "reason": REASON},
        ["order_id", "reason"],
    ),
    _tool(
        "propose_modify_address",
        "Validate a pending order shipping address change. "
        "Supply country, state, city and address1; address2 is optional and no postal code is "
        "required. This only creates a proposal.",
        {"order_id": ORDER_ID, "address": ADDRESS},
        ["order_id", "address"],
    ),
    _tool(
        "propose_modify_payment",
        "Validate a pending order payment method change.",
        {"order_id": ORDER_ID, "payment_method_id": STRING},
        ["order_id", "payment_method_id"],
    ),
    _tool(
        "propose_modify_items",
        "Validate all pending order item variant changes at once.",
        {
            "order_id": ORDER_ID,
            "item_ids": ITEM_IDS,
            "new_item_ids": ITEM_IDS,
            "payment_method_id": STRING,
        },
        ["order_id", "item_ids", "new_item_ids", "payment_method_id"],
    ),
    _tool(
        "propose_return_order",
        "Validate a delivered item return request. "
        "Use original payment method or an existing gift card.",
        {"order_id": ORDER_ID, "item_ids": ITEM_IDS, "payment_method_id": STRING},
        ["order_id", "item_ids", "payment_method_id"],
    ),
    _tool(
        "propose_exchange_order",
        "Validate all delivered item exchanges at once.",
        {
            "order_id": ORDER_ID,
            "item_ids": ITEM_IDS,
            "new_item_ids": ITEM_IDS,
            "payment_method_id": STRING,
        },
        ["order_id", "item_ids", "new_item_ids", "payment_method_id"],
    ),
]

SYSTEM_PROMPT = """You are the ServiceFlow retail customer support agent.
Authenticate the user with their supplied email before revealing any profile, order or product data.
Serve one verified customer per session. Read order facts from tools; never invent them.
Order IDs start with #. Preserve the leading # exactly in tool arguments.
For a change, collect all required details and call the matching propose_* tool.
Then present its exact summary
and proposal ID. Do not claim it is complete. The server alone handles explicit confirmation.
Calling a propose_* tool only validates and prepares the action; it does not change the order.
Use at most one tool call at a time. If a tool fails, explain the failure without claiming success.
No real payment, refund or email is performed; changes affect only a local simulated database.
"""


class TurnState(TypedDict, total=False):
    messages: list[dict[str, Any]]
    reply: ModelReply
    result: dict[str, Any]
    events: list[dict[str, Any]]
    usage: dict[str, int]
    calls: int
    stop: bool


def _execute(
    service: RetailService, sid: str, name: str, args: dict[str, Any], user_message: str
) -> dict[str, Any]:
    schema = next(
        (tool["function"]["parameters"] for tool in TOOLS if tool["function"]["name"] == name), None
    )
    if schema is None or set(args) - set(schema["properties"]):
        raise BusinessError("tool_arguments_invalid")
    if "order_id" in args and isinstance(args["order_id"], str):
        oid = args["order_id"]
        if not oid.startswith("#") and f"#{oid}" in user_message:
            args = {**args, "order_id": f"#{oid}"}
    if name == "find_user_id_by_email":
        email = args.get("email")
        if not isinstance(email, str) or email.casefold() not in user_message.casefold():
            raise BusinessError("identity_evidence_required")
        return {"user_id": service.verify(sid, email=email)}
    if name == "get_user_details":
        return {"user": service.user(sid)}
    if name == "get_orders":
        return {"orders": service.orders(sid)}
    if name == "get_order_details":
        return {"order": service.order(sid, args["order_id"])}
    if name == "get_product_details":
        return {"product": service.product(sid, args["product_id"])}
    if name in PROPOSALS:
        return service.propose(sid, Action.model_validate({**args, "kind": PROPOSALS[name]}))
    raise BusinessError("tool_not_allowed")


def live_chat(
    service: RetailService,
    sid: str,
    message: str,
    proposal_id: str | None,
    provider: ModelProvider,
    *,
    max_tool_calls: int = 6,
) -> dict[str, Any]:
    began = perf_counter()
    trace_id = uuid4().hex
    with Session(service.engine) as db, db.begin():
        session = db.get(SessionRow, sid)
        if session is None:
            raise BusinessError("session_not_found", 404)
        row = db.scalar(
            select(ConversationRow).where(ConversationRow.session_id == sid).with_for_update()
        )
        history = list(row.messages) if row else []
        pending = row.pending_proposal_id if row else None
        messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
        messages.append({"role": "user", "content": message})
        if message.strip().casefold() in CONFIRM_WORDS:
            if not proposal_id or proposal_id != pending:
                response = {"status": "error", "error_code": "confirmation_mismatch"}
            else:
                try:
                    result = service.confirm(sid, proposal_id, confirmed=True)
                    response = {
                        "status": "succeeded",
                        "operation": result,
                        "message": (
                            f"Simulated order {result['order_id']} is now {result['order_status']}."
                        ),
                    }
                    pending = None
                except BusinessError as exc:
                    response = {"status": "error", "error_code": exc.code}
            messages.append({"role": "assistant", "content": json.dumps(response)})
            events = [{"node": "confirm", "status": response["status"]}]
            usage: dict[str, int] = {}
            calls = 0
        else:
            if pending:
                pending = None

            def model_node(state: TurnState) -> TurnState:
                try:
                    reply = provider.complete(state["messages"], TOOLS)
                except ProviderError as exc:
                    return {
                        "result": {"status": "error", "error_code": str(exc)},
                        "stop": True,
                        "events": state["events"] + [{"node": "model", "error": str(exc)}],
                    }
                usage = dict(state["usage"])
                for key, value in (reply.usage or {}).items():
                    usage[key] = usage.get(key, 0) + value
                if len(reply.tool_calls) > 1:
                    return {
                        "result": {"status": "error", "error_code": "parallel_tools_denied"},
                        "stop": True,
                        "usage": usage,
                        "events": state["events"]
                        + [{"node": "model", "error": "parallel_tools_denied"}],
                    }
                if not reply.tool_calls:
                    return {
                        "reply": reply,
                        "usage": usage,
                        "stop": True,
                        "result": {
                            "status": "answered",
                            "message": reply.content or "",
                            "operation_executed": False,
                        },
                        "messages": state["messages"]
                        + [{"role": "assistant", "content": reply.content or ""}],
                        "events": state["events"] + [{"node": "model", "text": True}],
                    }
                return {
                    "reply": reply,
                    "usage": usage,
                    "events": state["events"]
                    + [{"node": "model", "tool": reply.tool_calls[0].name}],
                }

            def tool_node(state: TurnState) -> TurnState:
                call = state["reply"].tool_calls[0]
                count = state["calls"] + 1
                try:
                    value = _execute(service, sid, call.name, call.arguments, message)
                except (BusinessError, KeyError, ValueError) as exc:
                    code = exc.code if isinstance(exc, BusinessError) else "tool_arguments_invalid"
                    value = {"error_code": code}
                assistant = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(call.arguments),
                            },
                        }
                    ],
                }
                tool_result = {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(value, ensure_ascii=False),
                }
                new_messages = state["messages"] + [assistant, tool_result]
                event = {
                    "node": "tool",
                    "name": call.name,
                    "error": value.get("error_code"),
                    "proposal_id": value.get("proposal_id"),
                }
                if call.name in PROPOSALS and "proposal_id" in value:
                    return {
                        "messages": new_messages
                        + [{"role": "assistant", "content": value["summary"]}],
                        "calls": count,
                        "stop": True,
                        "result": value,
                        "events": state["events"] + [event],
                    }
                if count >= max_tool_calls:
                    failure = {"status": "error", "error_code": "tool_limit_reached"}
                    return {
                        "messages": new_messages,
                        "calls": count,
                        "stop": True,
                        "result": failure,
                        "events": state["events"] + [event],
                    }
                return {
                    "messages": new_messages,
                    "calls": count,
                    "events": state["events"] + [event],
                }

            graph = StateGraph(TurnState)
            graph.add_node("model", model_node)
            graph.add_node("tool", tool_node)
            graph.add_edge(START, "model")
            graph.add_conditional_edges("model", lambda s: END if s.get("stop") else "tool")
            graph.add_conditional_edges("tool", lambda s: END if s.get("stop") else "model")
            state = graph.compile().invoke(
                {"messages": messages, "events": [], "usage": {}, "calls": 0, "stop": False}
            )
            messages = state["messages"]
            response = state["result"]
            events = state["events"]
            usage = state["usage"]
            calls = state["calls"]
            pending = response.get("proposal_id")
        if row is None:
            db.add(
                ConversationRow(session_id=sid, messages=messages[1:], pending_proposal_id=pending)
            )
        else:
            row.messages = messages[1:]
            row.pending_proposal_id = pending
        elapsed_ms = round((perf_counter() - began) * 1000)
        db.add(
            ChatTraceRow(
                id=trace_id,
                session_id=sid,
                events=events,
                elapsed_ms=elapsed_ms,
                token_usage=usage or None,
            )
        )
    return {
        "trace_id": trace_id,
        "provider": "openai_compatible",
        "tool_calls": calls,
        "elapsed_ms": elapsed_ms,
        "token_usage": usage or None,
        "response": response,
    }
