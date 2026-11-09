"""Resolution Agent: evidence-bound drafting plus deterministic read-only validation."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from time import perf_counter
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.multi_agent.models import (
    ActionType,
    EligibilityResult,
    EligibilityStatus,
    EvidenceReference,
    ResolutionProposal,
    TaskPlan,
    TriageResult,
)
from app.multi_agent.state import AgentState
from app.service import Action, BusinessError, RetailService

WRITE_ACTIONS: dict[str, set[ActionType]] = {
    "cancel_order": {"cancel"},
    "modify_order": {"modify_address", "modify_payment", "modify_items"},
    "return_order": {"return"},
    "exchange_order": {"exchange"},
}
ALLOWED_PARAMETERS: dict[ActionType, set[str]] = {
    "cancel": {"reason"},
    "modify_address": {"address"},
    "modify_payment": {"payment_method_id"},
    "modify_items": {"item_ids", "new_item_ids", "payment_method_id"},
    "return": {"item_quantities", "payment_method_id"},
    "exchange": {"item_ids", "new_item_ids", "payment_method_id"},
    "informational": set(),
}
REQUIRED_PARAMETERS: dict[ActionType, set[str]] = {
    "cancel": {"reason"},
    "modify_address": {"address"},
    "modify_payment": {"payment_method_id"},
    "modify_items": {"item_ids", "new_item_ids", "payment_method_id"},
    "return": {"item_quantities", "payment_method_id"},
    "exchange": {"item_ids", "new_item_ids", "payment_method_id"},
    "informational": set(),
}


class ResolutionDraft(BaseModel):
    """Untrusted model/local-generator suggestion before server rule validation."""

    model_config = ConfigDict(extra="forbid", strict=True)
    action_type: ActionType
    proposed_parameters: dict[str, JsonValue] = Field(default_factory=dict)
    eligibility_suggestion: EligibilityStatus = "unknown"
    missing_information: list[str] = Field(default_factory=list)
    explanation: str = Field(max_length=500)


class ResolutionGenerator(Protocol):
    def generate(
        self,
        task: TaskPlan,
        triage: TriageResult,
        order_status: str,
        policy_sections: list[str],
    ) -> dict[str, Any]: ...


def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _quantities(value: str | None) -> dict[str, int]:
    """Parse the deliberately explicit ``item_id:quantity`` wire format."""
    if not value:
        return {}
    result: dict[str, int] = {}
    for part in value.split(","):
        item_id, separator, raw_quantity = part.strip().partition(":")
        if not separator or not item_id or not raw_quantity.isdigit():
            return {}
        quantity = int(raw_quantity)
        if quantity < 1 or item_id in result:
            return {}
        result[item_id] = quantity
    return result


def _cancel_reason(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().casefold()
    if normalized in {"ordered by mistake", "mistake", "买错了", "下错单", "误下单"}:
        return "ordered by mistake"
    if normalized in {"no longer needed", "don't need it", "不需要了", "不想要了"}:
        return "no longer needed"
    return value.strip()


class DeterministicResolutionGenerator:
    """Offline generator used until an approved minimal-context LLM path exists."""

    def generate(
        self,
        task: TaskPlan,
        triage: TriageResult,
        order_status: str,
        policy_sections: list[str],
    ) -> dict[str, Any]:
        del policy_sections
        values = triage.extracted_parameters
        action_type: ActionType
        parameters: dict[str, Any]
        if task.intent == "cancel_order":
            action_type = "cancel"
            reason = _cancel_reason(values.get("reason"))
            parameters = {"reason": reason} if reason else {}
        elif task.intent == "return_order":
            action_type = "return"
            quantities = _quantities(values.get("item_quantities"))
            if not quantities and values.get("item_ids"):
                quantities = dict(Counter(_csv(values.get("item_ids"))))
            parameters = {
                "item_quantities": quantities,
                "payment_method_id": values.get("payment_method_id"),
            }
        elif task.intent == "exchange_order":
            action_type = "exchange"
            parameters = {
                "item_ids": _csv(values.get("item_ids")),
                "new_item_ids": _csv(values.get("new_item_ids")),
                "payment_method_id": values.get("payment_method_id"),
            }
        else:
            kind = values.get("modification_type")
            action_type = {
                "address": "modify_address",
                "payment": "modify_payment",
                "items": "modify_items",
            }.get(kind, "modify_items")
            if action_type == "modify_address":
                parameters = {
                    "address": {
                        key: values[key]
                        for key in ("address1", "address2", "city", "state", "country", "zip")
                        if key in values
                    }
                }
            elif action_type == "modify_payment":
                parameters = {"payment_method_id": values.get("payment_method_id")}
            else:
                parameters = {
                    "item_ids": _csv(values.get("item_ids")),
                    "new_item_ids": _csv(values.get("new_item_ids")),
                    "payment_method_id": values.get("payment_method_id"),
                }
        parameters = {
            key: value for key, value in parameters.items() if value not in (None, [], {})
        }
        missing = sorted(REQUIRED_PARAMETERS[action_type] - parameters.keys())
        if task.intent == "modify_order" and "modification_type" not in values:
            missing.insert(0, "modification_type")
        expected = "pending" if action_type in {
            "cancel",
            "modify_address",
            "modify_payment",
            "modify_items",
        } else "delivered"
        suggestion: EligibilityStatus = "eligible" if order_status == expected else "ineligible"
        return {
            "action_type": action_type,
            "proposed_parameters": parameters,
            "eligibility_suggestion": suggestion,
            "missing_information": list(dict.fromkeys(missing)),
            "explanation": (
                "Candidate action assembled from authorized order facts and policy evidence."
            ),
        }


def _proposal_id(state: AgentState, task: TaskPlan, draft: ResolutionDraft) -> str:
    payload = json.dumps(
        {
            "session": state["session_id"],
            "task": task.task_id,
            "order": state["order_id"],
            "action": draft.action_type,
            "parameters": draft.proposed_parameters,
            "policy": [item.get("chunk_id", item["section"]) for item in state["policy_context"]],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "resolution_" + hashlib.sha256(payload.encode()).hexdigest()[:20]


def _references(state: AgentState) -> tuple[list[EvidenceReference], list[EvidenceReference]]:
    order = [
        EvidenceReference(
            evidence_type="order",
            source="business_database",
            reference=state["order_id"] or "unknown",
            detail=f"current status={state['order_context']['status']}",
        )
    ]
    policy = [
        EvidenceReference(
            evidence_type="policy",
            source=item["source"],
            reference=item.get("chunk_id", item["section"]),
            detail=f"{item['section']} (version {item['version']})",
        )
        for item in state["policy_context"]
    ]
    return order + policy, policy


def _set_task_status(
    tasks: list[TaskPlan], task_id: str, status: str, *, missing: list[str] | None = None
) -> None:
    for task in tasks:
        if task.task_id == task_id:
            task.status = status  # type: ignore[assignment]
            task.required_inputs = missing or []


def run_resolution_agent(
    service: RetailService,
    state: AgentState,
    *,
    generator: ResolutionGenerator | None = None,
) -> dict[str, object]:
    """Draft one dependency-ready action and validate it without a write-capable tool."""
    tasks = [task.model_copy(deep=True) for task in state["task_plan"]]
    triage = state["triage_result"]
    task = next(
        (item for item in tasks if item.target_agent == "resolution" and item.status == "ready"),
        None,
    )
    if triage is None or task is None:
        return {
            "errors": ["resolution_agent_invalid_state"],
            "trace": [{"node": "resolution", "status": "error", "code": "invalid_state"}],
        }
    if not state["identity_verified"] or not state["order_id"] or not state["order_context"]:
        return {
            "missing_information": ["identity_verification", "order_data"],
            "task_status": "needs_clarification",
            "next_agent": "end",
            "errors": ["resolution_evidence_missing"],
            "trace": [
                {
                    "node": "resolution",
                    "status": "needs_clarification",
                    "code": "order_evidence_missing",
                }
            ],
        }
    if not state["policy_context"]:
        return {
            "missing_information": ["policy_evidence"],
            "task_status": "needs_clarification",
            "next_agent": "end",
            "errors": ["policy_evidence_insufficient"],
            "trace": [
                {
                    "node": "resolution",
                    "status": "needs_clarification",
                    "code": "policy_evidence_missing",
                }
            ],
        }
    choose = generator or DeterministicResolutionGenerator()
    try:
        raw = choose.generate(
            task,
            triage,
            state["order_context"]["status"],
            [item["section"] for item in state["policy_context"]],
        )
        draft = ResolutionDraft.model_validate(raw, strict=True)
        if draft.action_type not in WRITE_ACTIONS[task.intent]:
            raise ValueError("resolution_action_mismatch")
        if set(draft.proposed_parameters) - ALLOWED_PARAMETERS[draft.action_type]:
            raise ValueError("resolution_parameters_not_allowed")
    except (KeyError, TypeError, ValueError, ValidationError):
        _set_task_status(tasks, task.task_id, "failed")
        return {
            "task_plan": tasks,
            "resolution_proposal": None,
            "eligibility_result": None,
            "task_status": "resolution_failed",
            "next_agent": "end",
            "errors": ["resolution_output_invalid"],
            "tool_results": [
                {
                    "tool": "resolution_schema_validation",
                    "status": "error",
                    "code": "resolution_output_invalid",
                }
            ],
            "trace": [
                {"node": "resolution", "status": "error", "code": "resolution_output_invalid"}
            ],
        }

    missing = list(dict.fromkeys(draft.missing_information))
    missing.extend(
        sorted(REQUIRED_PARAMETERS[draft.action_type] - draft.proposed_parameters.keys())
    )
    missing = list(dict.fromkeys(missing))
    evidence, policies = _references(state)
    proposal_id = _proposal_id(state, task, draft)
    if missing:
        _set_task_status(tasks, task.task_id, "blocked", missing=missing)
        proposal = ResolutionProposal(
            proposal_id=proposal_id,
            task_id=task.task_id,
            action_type=draft.action_type,
            order_id=state["order_id"],
            proposed_parameters=draft.proposed_parameters,
            supporting_evidence=evidence,
            policy_references=policies,
            missing_information=missing,
            requires_user_confirmation=True,
            requires_human_review=False,
            eligibility_status="unknown",
            status="needs_clarification",
            explanation="More information is required before deterministic validation can run.",
            validated=False,
        )
        return {
            "task_plan": tasks,
            "resolution_proposal": proposal,
            "eligibility_result": EligibilityResult(
                status="unknown",
                validated=False,
                rule_code="required_information_missing",
                checked_order_status=state["order_context"]["status"],
                explanation=(
                    "The rule service was not called because required parameters are missing."
                ),
            ),
            "missing_information": missing,
            "risk_flags": [],
            "pending_action": None,
            "task_status": "needs_clarification",
            "next_agent": "end",
            "tool_results": [
                {"tool": "resolution_schema_validation", "status": "ok", "code": None}
            ],
            "trace": [{"node": "resolution", "status": "needs_clarification"}],
        }

    guard_began = perf_counter()
    try:
        action = Action.model_validate(
            {"kind": draft.action_type, "order_id": state["order_id"], **draft.proposed_parameters},
            strict=True,
        )
        validation = service.validate_action(state["session_id"], action)
    except ValidationError:
        code = "resolution_parameters_invalid"
    except BusinessError as exc:
        code = exc.code
    except SQLAlchemyError:
        code = "database_unavailable"
    else:
        code = None
    guard_elapsed_ms = max(0.0, (perf_counter() - guard_began) * 1000)
    if code is not None:
        _set_task_status(tasks, task.task_id, "failed")
        return {
            "task_plan": tasks,
            "resolution_proposal": None,
            "eligibility_result": EligibilityResult(
                status="unknown",
                validated=False,
                rule_code=code,
                checked_order_status=state["order_context"]["status"],
                explanation="The candidate could not be validated safely.",
            ),
            "task_status": "resolution_failed",
            "next_agent": "end",
            "errors": [code],
            "tool_results": [
                {"tool": "validate_action_readonly", "status": "error", "code": code}
            ],
            "trace": [
                {
                    "node": "guard",
                    "status": "error",
                    "code": code,
                    "elapsed_ms": guard_elapsed_ms,
                }
            ],
        }

    deterministic_status: EligibilityStatus = "eligible" if validation.eligible else "ineligible"
    conflict = draft.eligibility_suggestion != deterministic_status
    flags = ["model_rule_conflict"] if conflict else []
    result = EligibilityResult(
        status=deterministic_status,
        validated=True,
        rule_code=validation.code,
        checked_order_status=validation.order_status,
        explanation=(
            "Existing deterministic business rules accepted the candidate."
            if validation.eligible
            else f"Existing deterministic business rules rejected the candidate: {validation.code}."
        ),
    )
    proposal = ResolutionProposal(
        proposal_id=proposal_id,
        task_id=task.task_id,
        action_type=draft.action_type,
        order_id=state["order_id"],
        proposed_parameters=draft.proposed_parameters,
        supporting_evidence=evidence,
        policy_references=policies,
        missing_information=[],
        requires_user_confirmation=validation.eligible,
        requires_human_review=conflict,
        eligibility_status=deterministic_status,
        risk_flags=flags,
        status="pending_confirmation" if validation.eligible else "ineligible",
        explanation=result.explanation,
        validated=True,
    )
    _set_task_status(tasks, task.task_id, "completed")
    guard_id = task.task_id.replace("-proposal", "-guard")
    _set_task_status(tasks, guard_id, "completed")
    confirmation_id = task.task_id.replace("-proposal", "-confirmation")
    if validation.eligible:
        _set_task_status(tasks, confirmation_id, "blocked", missing=["user_confirmation"])
    else:
        _set_task_status(tasks, confirmation_id, "blocked", missing=["eligibility"])
    summary = f"{draft.action_type}: order {state['order_id']}; {draft.proposed_parameters}"
    return {
        "task_plan": tasks,
        "resolution_proposal": proposal,
        "eligibility_result": result,
        "missing_information": [] if validation.eligible else [validation.code or "ineligible"],
        "risk_flags": flags,
        "pending_action": (
            {
                "proposal_id": proposal_id,
                "order_id": state["order_id"],
                "action": draft.action_type,
                "summary": summary,
            }
            if validation.eligible
            else None
        ),
        "task_status": "proposal_ready" if validation.eligible else "ineligible",
        "next_agent": "end",
        "tool_results": [
            {"tool": "validate_action_readonly", "status": "ok", "code": validation.code}
        ],
        "trace": [
            {"node": "resolution", "status": "completed"},
            {
                "node": "guard",
                "status": "eligible" if validation.eligible else "ineligible",
                "tool": "validate_action_readonly",
                "elapsed_ms": guard_elapsed_ms,
                **({"code": validation.code} if validation.code else {}),
            },
        ],
    }
