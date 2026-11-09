"""Order Agent: deterministic read-only tool selection and result projection."""

from typing import Any, Protocol

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.multi_agent.models import TaskPlan, TriageResult
from app.multi_agent.order_tools import ORDER_TOOLS, OrderToolCall, execute_order_tool
from app.multi_agent.state import AgentState
from app.service import BusinessError, RetailService

MAX_ORDER_TOOL_CALLS = 2
ORDER_READ_ACTIONS = {
    "get_order_details",
    "get_order_status",
    "get_order_items",
    "get_order_logistics",
}
ACTION_ALIASES = {
    "check_status": "get_order_status",
    "query_order_status": "get_order_status",
    "status": "get_order_status",
    "check_items": "get_order_items",
    "check_logistics": "get_order_logistics",
}


class OrderToolSelector(Protocol):
    def select(self, task: TaskPlan, triage: TriageResult) -> dict[str, Any]: ...


class DeterministicOrderSelector:
    def select(self, task: TaskPlan, triage: TriageResult) -> dict[str, Any]:
        if task.task_id == "product-lookup":
            return {"name": "get_product_details", "product_id": triage.product_id}
        if triage.requested_action == "list_orders":
            return {"name": "get_customer_orders"}
        action = ACTION_ALIASES.get(triage.requested_action, triage.requested_action)
        name = action if action in ORDER_READ_ACTIONS else "get_order_details"
        return {"name": name, "order_id": triage.order_id}


def run_order_agent(
    service: RetailService,
    session_id: str,
    state: AgentState,
    *,
    selector: OrderToolSelector | None = None,
    max_calls: int = MAX_ORDER_TOOL_CALLS,
) -> dict[str, object]:
    """Return a validated node delta; never expose raw order/payment/customer objects."""
    triage = state["triage_result"]
    tasks = [task.model_copy(deep=True) for task in state["task_plan"]]
    if triage is None or max_calls < 1 or max_calls > MAX_ORDER_TOOL_CALLS:
        return {
            "errors": ["order_agent_invalid_state"],
            "trace": [{"node": "order", "status": "error"}],
        }
    choose = selector or DeterministicOrderSelector()
    results: dict[str, object] = {}
    tool_results = []
    trace = []
    order_context = None
    calls = 0
    for task in tasks:
        if task.target_agent != "order" or task.status != "ready":
            continue
        if calls >= max_calls:
            break
        calls += 1
        raw_choice = choose.select(task, triage)
        name = raw_choice.get("name") if isinstance(raw_choice, dict) else None
        arguments = (
            {
                key: value
                for key, value in raw_choice.items()
                if key in {"order_id", "product_id"} and isinstance(value, str)
            }
            if isinstance(raw_choice, dict)
            else {}
        )
        try:
            if name not in ORDER_TOOLS:
                raise BusinessError("tool_not_allowed")
            call = OrderToolCall.model_validate(raw_choice)
            expected_name = DeterministicOrderSelector().select(task, triage)["name"]
            if call.name != expected_name:
                raise BusinessError("tool_not_allowed")
            if call.name == "get_product_details":
                if task.task_id != "product-lookup" or call.product_id != triage.product_id:
                    raise BusinessError("tool_arguments_invalid")
            elif task.task_id == "product-lookup":
                raise BusinessError("tool_arguments_invalid")
            elif call.name == "get_customer_orders":
                if triage.requested_action != "list_orders":
                    raise BusinessError("tool_arguments_invalid")
            elif call.order_id != triage.order_id:
                raise BusinessError("tool_arguments_invalid")
            if call.name != "get_product_details" and not state["identity_verified"]:
                raise BusinessError("identity_required", 403)
            result = execute_order_tool(service, session_id, call)
        except BusinessError as exc:
            code = exc.code
        except ValidationError:
            code = "tool_arguments_invalid"
        except (KeyError, ValueError):
            code = "data_shape_invalid"
        except SQLAlchemyError:
            code = "database_unavailable"
        else:
            code = None
            task.status = "completed"
            results[task.task_id] = result
            if result.order_id and result.status:
                order_context = {"order_id": result.order_id, "status": result.status}
            elif result.order is not None:
                order_context = {"order_id": result.order.order_id, "status": result.order.status}
        if code is not None:
            task.status = "failed"
        tool_results.append({"tool": str(name), "status": "error" if code else "ok", "code": code})
        event = {"node": "order", "status": "error" if code else "completed", "tool": str(name)}
        if arguments:
            event["arguments"] = arguments
        if code:
            event["code"] = code
        trace.append(event)
    return {
        "task_plan": tasks,
        "order_data": results,
        "order_context": order_context,
        "tool_results": tool_results,
        "trace": trace,
        "errors": [item["code"] for item in tool_results if item["code"]],
    }
