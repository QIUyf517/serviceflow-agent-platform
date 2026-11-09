"""Deterministic task planning and route selection."""

from app.multi_agent.models import Intent, TargetAgent, TaskPlan, TriageResult
from app.multi_agent.state import AgentState

MAX_ROUTES = 6
ORDER_INTENTS = {"order_query", "cancel_order", "modify_order", "return_order", "exchange_order"}
WRITE_INTENTS = {"cancel_order", "modify_order", "return_order", "exchange_order"}
ROUTABLE = {"order", "policy", "resolution"}


def safe_target(target: object) -> str:
    """Only planned, known future agents may appear as a next target."""
    return target if isinstance(target, str) and target in ROUTABLE else "end"


def _step(
    task_id: str,
    intent: Intent,
    target: TargetAgent,
    *,
    required: list[str] | None = None,
    dependencies: list[str] | None = None,
) -> TaskPlan:
    required = required or []
    dependencies = dependencies or []
    return TaskPlan(
        task_id=task_id,
        intent=intent,
        target_agent=target,
        required_inputs=required,
        dependencies=dependencies,
        status="blocked" if required else "pending" if dependencies else "ready",
    )


def supervise(
    triage: TriageResult, state: AgentState, *, max_routes: int = MAX_ROUTES
) -> dict[str, object]:
    """Build a dependency plan from validated intent and server-sourced identity."""
    count = state["routing_count"] + 1
    if max_routes < 1 or count > max_routes:
        return {
            "routing_count": count,
            "next_agent": "end",
            "task_status": "route_limit",
            "errors": ["route_limit_reached"],
            "trace": [{"node": "supervisor", "status": "route_limit"}],
        }
    if triage.intent == "unknown" or triage.intents == ["unknown"]:
        return {
            "routing_count": count,
            "task_plan": [],
            "next_agent": "end",
            "task_status": "unsupported",
            "missing_information": [],
            "current_task": None,
            "trace": [{"node": "supervisor", "status": "unsupported"}],
        }

    intents = [intent for intent in triage.intents if intent != "unknown"]
    tasks: list[TaskPlan] = []
    missing = list(dict.fromkeys(triage.missing_information))
    order_needed = any(intent in ORDER_INTENTS for intent in intents)
    product_needed = "product_inquiry" in intents
    if order_needed and not state["identity_verified"]:
        missing.append("identity_verification")
    if order_needed:
        required = []
        if not triage.order_id and triage.requested_action != "list_orders":
            required.append("order_id")
            if "order_id" not in missing:
                missing.append("order_id")
        if not state["identity_verified"]:
            required.append("identity_verification")
        tasks.append(_step("order-lookup", "order_query", "order", required=required))
    if product_needed:
        required = []
        if not triage.product_id:
            required.append("product_id")
            if "product_id" not in missing:
                missing.append("product_id")
        tasks.append(_step("product-lookup", "product_inquiry", "order", required=required))
    if "policy_inquiry" in intents and not any(i in WRITE_INTENTS for i in intents):
        tasks.append(_step("policy-lookup", "policy_inquiry", "policy"))
    for intent in intents:
        if intent not in WRITE_INTENTS:
            continue
        policy_id = f"{intent}-policy"
        proposal_id = f"{intent}-proposal"
        guard_id = f"{intent}-guard"
        confirm_id = f"{intent}-confirmation"
        tasks.extend(
            [
                _step(policy_id, intent, "policy"),
                _step(
                    proposal_id,
                    intent,
                    "resolution",
                    dependencies=["order-lookup", policy_id],
                ),
                _step(guard_id, intent, "guard", dependencies=[proposal_id]),
                _step(confirm_id, intent, "confirmation", dependencies=[guard_id]),
                _step(f"{intent}-execute", intent, "executor", dependencies=[confirm_id]),
            ]
        )
    ready = next((task for task in tasks if task.status == "ready"), None)
    target = safe_target(ready.target_agent if ready and not missing else None)
    status = "clarification" if missing else "planned"
    return {
        "routing_count": count,
        "task_plan": tasks,
        "missing_information": missing,
        "task_status": status,
        "next_agent": target,
        "current_task": (ready or next(iter(tasks), None)).task_id if tasks else None,
        "trace": [{"node": "supervisor", "status": status}],
    }
