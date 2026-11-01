"""Single-agent LangGraph baseline with replaceable structured tool selector."""

import re
from time import perf_counter
from typing import Any, Protocol, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import ChatTraceRow, SessionRow
from app.service import Action, BusinessError, RetailService


class ToolChoice(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolSelector(Protocol):
    def select(self, message: str, proposal_id: str | None = None) -> ToolChoice: ...


class MockSelector:
    """Limited deterministic demo parser, not an LLM or benchmark agent."""

    def select(self, message: str, proposal_id: str | None = None) -> ToolChoice:
        phrase = message.strip()
        if proposal_id and phrase.casefold() in {"yes", "确认", "是", "同意"}:
            return ToolChoice(name="confirm", arguments={"proposal_id": proposal_id})
        if phrase.casefold().startswith("verify "):
            return ToolChoice(name="verify", arguments={"email": phrase[7:].strip()})
        product = re.search(r"(?:product|商品)\s+(\S+)", phrase, re.IGNORECASE)
        if product:
            return ToolChoice(name="get_product", arguments={"product_id": product.group(1)})
        if "订单" in phrase or "order" in phrase.casefold():
            oid = re.search(r"#[A-Za-z0-9]+|\bo\b", phrase)
            action = re.search(r"\b(return|exchange)\b|退货|换货", phrase, re.IGNORECASE)
            if action:
                item = re.search(r"(?:item|商品项)\s+(\S+)", phrase, re.IGNORECASE)
                payment = re.search(r"(?:payment|支付方式)\s+(\S+)", phrase, re.IGNORECASE)
                new_item = re.search(r"(?:new item|新商品项)\s+(\S+)", phrase, re.IGNORECASE)
                if not oid or not item or not payment:
                    return ToolChoice(name="unsupported")
                kind = "return" if action.group().casefold() in {"return", "退货"} else "exchange"
                if kind == "exchange" and not new_item:
                    return ToolChoice(name="unsupported")
                return ToolChoice(
                    name="propose",
                    arguments={
                        "kind": kind,
                        "order_id": oid.group(),
                        "item_ids": [item.group(1)],
                        "new_item_ids": [new_item.group(1)] if new_item else [],
                        "payment_method_id": payment.group(1),
                    },
                )
            if "取消" in phrase or "cancel" in phrase.casefold():
                reason = (
                    "ordered by mistake"
                    if "mistake" in phrase.casefold() or "错误" in phrase
                    else "no longer needed"
                )
                if not oid:
                    return ToolChoice(name="unsupported")
                return ToolChoice(
                    name="propose",
                    arguments={"kind": "cancel", "order_id": oid.group(), "reason": reason},
                )
            if oid:
                return ToolChoice(name="get_order", arguments={"order_id": oid.group()})
            return ToolChoice(name="get_orders")
        return ToolChoice(name="unsupported")


class AgentState(TypedDict, total=False):
    message: str
    proposal_id: str | None
    choice: dict[str, Any]
    response: dict[str, Any]
    events: list[dict[str, Any]]


def chat_once(
    service: RetailService,
    sid: str,
    message: str,
    proposal_id: str | None = None,
    selector: ToolSelector | None = None,
) -> dict[str, Any]:
    selector = selector or MockSelector()
    began = perf_counter()

    def decide(state: AgentState) -> AgentState:
        choice = selector.select(state["message"], state.get("proposal_id"))
        return {"choice": choice.model_dump(), "events": [{"node": "decide", "tool": choice.name}]}

    def execute(state: AgentState) -> AgentState:
        choice = ToolChoice.model_validate(state["choice"])
        args = choice.arguments
        try:
            if choice.name == "verify":
                if args["email"].casefold() not in state["message"].casefold():
                    raise BusinessError("identity_evidence_required")
                result = {"user_id": service.verify(sid, email=args["email"])}
            elif choice.name == "get_orders":
                result = {"orders": service.orders(sid)}
            elif choice.name == "get_order":
                result = {"order": service.order(sid, args["order_id"])}
            elif choice.name == "get_product":
                result = {"product": service.product(sid, args["product_id"])}
            elif choice.name == "propose":
                result = service.propose(sid, Action.model_validate(args))
            elif choice.name == "confirm":
                if state["message"].strip().casefold() not in {"yes", "确认", "是", "同意"}:
                    raise BusinessError("confirmation_required")
                if args.get("proposal_id") != state.get("proposal_id"):
                    raise BusinessError("confirmation_mismatch")
                result = service.confirm(sid, args["proposal_id"], confirmed=True)
            else:
                result = {"status": "unsupported", "message": "Please contact a human agent."}
        except (BusinessError, KeyError, ValueError) as exc:
            code = exc.code if isinstance(exc, BusinessError) else "tool_arguments_invalid"
            result = {"status": "error", "error_code": code}
        return {
            "response": result,
            "events": state["events"]
            + [{"node": "execute", "tool": choice.name, "error": result.get("error_code")}],
        }

    graph = StateGraph(AgentState)
    graph.add_node("decide", decide)
    graph.add_node("execute", execute)
    graph.add_edge(START, "decide")
    graph.add_edge("decide", "execute")
    graph.add_edge("execute", END)
    with Session(service.engine) as db:
        if db.get(SessionRow, sid) is None:
            raise BusinessError("session_not_found", 404)
    outcome = graph.compile().invoke({"message": message, "proposal_id": proposal_id, "events": []})
    trace_id = uuid4().hex
    elapsed_ms = round((perf_counter() - began) * 1000)
    with Session(service.engine) as db, db.begin():
        db.add(
            ChatTraceRow(
                id=trace_id,
                session_id=sid,
                events=outcome["events"],
                elapsed_ms=elapsed_ms,
                token_usage=None,
            )
        )
    return {
        "trace_id": trace_id,
        "provider": "mock" if isinstance(selector, MockSelector) else "custom",
        "tool_calls": 1,
        "elapsed_ms": elapsed_ms,
        "token_usage": None,
        "response": outcome["response"],
    }
