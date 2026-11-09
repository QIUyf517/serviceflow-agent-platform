"""Product-side single coordinator sharing the trusted phase-2 execution boundary."""

from __future__ import annotations

from time import perf_counter
from uuid import uuid4

from app.multi_agent.conversation import CONFIRM_WORDS, REJECT_WORDS
from app.multi_agent.execution import ExecutionService
from app.multi_agent.models import (
    EligibilityResult,
    EvidenceReference,
    ResolutionProposal,
    TaskPlan,
)
from app.multi_agent.order_agent import DeterministicOrderSelector
from app.multi_agent.order_tools import OrderToolCall, execute_order_tool
from app.multi_agent.policy_agent import POLICY_SOURCE, PolicyAgent
from app.multi_agent.resolution_agent import DeterministicResolutionGenerator, ResolutionDraft
from app.multi_agent.triage import MockTriage
from app.service import Action, BusinessError, RetailService


def run_controlled_single_agent(
    service: RetailService,
    execution: ExecutionService,
    policy: PolicyAgent,
    sid: str,
    message: str,
    *,
    request_id: str | None = None,
) -> dict:
    """One deterministic coordinator; it cannot write except through ExecutionService."""
    began = perf_counter()
    trace_id = uuid4().hex
    normalized = message.strip().casefold()
    if request_id:
        request = execution.get_request(sid, request_id)
        confirm_text, _ = execution.confirmation_phrases(sid, request_id)
        if normalized in CONFIRM_WORDS or message.strip() == confirm_text:
            execution.record_decision(
                sid,
                request_id,
                decision="confirm",
                confirmation_text=confirm_text,
            )
            result = execution.execute_action(
                sid,
                request_id,
                idempotency_key=request.idempotency_key,
            )
            return _result(
                trace_id,
                began,
                "executed",
                [{"node": "single_agent", "tool": f"execute_{request.action_type}_controlled"}],
                execution_result=result.model_dump(),
                final_response=(
                    f"Database status is {result.after_status}. "
                    + (
                        "The return request is registered; no real refund was disbursed."
                        if result.action_type == "return"
                        else "The order cancellation is complete."
                    )
                ),
            )
        if normalized in REJECT_WORDS:
            execution.record_decision(
                sid,
                request_id,
                decision="reject",
                confirmation_text=confirm_text,
            )
            return _result(
                trace_id,
                began,
                "confirmation_rejected",
                [{"node": "single_agent", "tool": "confirmation_gate"}],
                final_response="The operation was rejected and no order change was made.",
            )
        raise BusinessError("explicit_confirmation_required", 409)

    triage = MockTriage().classify(message)
    if triage.needs_clarification:
        return _result(
            trace_id,
            began,
            "needs_clarification",
            [{"node": "single_agent", "tool": "triage"}],
            final_response="Please provide: " + ", ".join(triage.missing_information),
        )
    intent = next(
        (item for item in triage.intents if item in {"cancel_order", "return_order"}),
        None,
    )
    if intent is None:
        task = TaskPlan(
            task_id="single-query",
            intent="order_query",
            target_agent="order",
            status="ready",
        )
        choice = DeterministicOrderSelector().select(task, triage)
        query = execute_order_tool(service, sid, OrderToolCall.model_validate(choice))
        return _result(
            trace_id,
            began,
            "queried",
            [{"node": "single_agent", "tool": choice["name"]}],
            order_result=query.model_dump(),
            final_response="Read-only order query completed from the business database.",
        )

    order_result = execute_order_tool(
        service,
        sid,
        OrderToolCall(name="get_order_details", order_id=triage.order_id),
    )
    evidence = policy.keyword.search(message, top_k=5)
    official = [hit for hit in evidence.hits if hit.source == POLICY_SOURCE.as_posix()]
    if not official:
        raise BusinessError("authoritative_policy_evidence_missing", 409)
    task = TaskPlan(
        task_id=f"single-{intent}",
        intent=intent,
        target_agent="resolution",
        status="ready",
    )
    draft = ResolutionDraft.model_validate(
        DeterministicResolutionGenerator().generate(
            task,
            triage,
            order_result.order.status,
            [hit.section for hit in official],
        ),
        strict=True,
    )
    if draft.missing_information:
        return _result(
            trace_id,
            began,
            "needs_clarification",
            [
                {"node": "single_agent", "tool": "get_order_details"},
                {"node": "single_agent", "tool": "policy_keyword_search"},
            ],
            final_response="Please provide: " + ", ".join(draft.missing_information),
        )
    action = Action.model_validate(
        {"kind": draft.action_type, "order_id": triage.order_id, **draft.proposed_parameters},
        strict=True,
    )
    validation = service.validate_action(sid, action)
    eligibility = EligibilityResult(
        status="eligible" if validation.eligible else "ineligible",
        validated=True,
        rule_code=validation.code,
        checked_order_status=validation.order_status,
        explanation="Deterministic business-rule result.",
    )
    references = [
        EvidenceReference(
            evidence_type="policy",
            source=hit.source,
            reference=hit.chunk_id,
            detail=f"{hit.section} ({hit.version})",
        )
        for hit in official
    ]
    proposal = ResolutionProposal(
        proposal_id="single-resolution-" + uuid4().hex,
        task_id=task.task_id,
        action_type=draft.action_type,
        order_id=triage.order_id,
        proposed_parameters=draft.proposed_parameters,
        supporting_evidence=[
            EvidenceReference(
                evidence_type="order",
                source="business_database",
                reference=triage.order_id or "unknown",
                detail=f"current status={validation.order_status}",
            ),
            *references,
        ],
        policy_references=references,
        missing_information=[],
        requires_user_confirmation=validation.eligible,
        requires_human_review=False,
        eligibility_status=eligibility.status,
        risk_flags=[],
        status="pending_confirmation" if validation.eligible else "ineligible",
        explanation="Single coordinator proposal; authority remains in deterministic services.",
        validated=True,
    )
    if not validation.eligible:
        return _result(
            trace_id,
            began,
            "ineligible",
            [{"node": "single_agent", "tool": "validate_action_readonly"}],
            proposal=proposal.model_dump(),
            final_response=f"Operation rejected by hard rule: {validation.code}.",
        )
    request = execution.prepare_action(
        sid,
        proposal,
        eligibility,
        "single-" + uuid4().hex,
    )
    return _result(
        trace_id,
        began,
        "pending_confirmation",
        [
            {"node": "single_agent", "tool": "get_order_details"},
            {"node": "single_agent", "tool": "policy_keyword_search"},
            {"node": "single_agent", "tool": "validate_action_readonly"},
        ],
        request=request.model_dump(),
        proposal=proposal.model_dump(),
        final_response=f"Pending explicit confirmation: {request.summary}",
    )


def _result(trace_id: str, began: float, status: str, tools: list[dict], **values) -> dict:
    elapsed = max(0.0, (perf_counter() - began) * 1000)
    trace = [
        {
            **item,
            "trace_id": trace_id,
            "status": status,
            "elapsed_ms": elapsed,
        }
        for item in tools
    ]
    return {
        "architecture": "single_agent_controlled",
        "trace_id": trace_id,
        "task_status": status,
        "trace": trace,
        "metrics": {
            "elapsed_ms": elapsed,
            "tool_calls": len(tools),
            "provider": "mock_local",
            "model": "deterministic-v1",
            "token_usage": None,
        },
        **values,
    }
