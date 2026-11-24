"""Validated understanding and planning contracts; neither grants business authority."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

Intent = Literal[
    "product_inquiry",
    "order_query",
    "cancel_order",
    "modify_order",
    "return_order",
    "exchange_order",
    "policy_inquiry",
    "complex_request",
    "unknown",
]
TargetAgent = Literal["order", "policy", "guard", "resolution", "confirmation", "executor"]
TaskStatus = Literal["pending", "ready", "blocked", "completed", "failed"]
FlowStatus = Literal[
    "planned",
    "clarification",
    "unsupported",
    "route_limit",
    "triage_error",
    "queried",
    "partial",
    "query_failed",
    "policy_answered",
    "policy_failed",
    "needs_clarification",
    "proposal_ready",
    "ineligible",
    "resolution_failed",
    "pending_confirmation",
    "confirmation_rejected",
    "executed",
    "execution_failed",
    "handoff_created",
]

EligibilityStatus = Literal["eligible", "ineligible", "unknown"]
ResolutionStatus = Literal[
    "needs_clarification",
    "pending_confirmation",
    "ineligible",
    "informational",
]
ActionType = Literal[
    "cancel",
    "modify_address",
    "modify_payment",
    "modify_items",
    "return",
    "exchange",
    "informational",
]


class TriageResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    intent: Intent
    intents: list[Intent] = Field(min_length=1)
    order_id: str | None = None
    product_id: str | None = None
    requested_action: str | None = None
    extracted_parameters: dict[str, str] = Field(default_factory=dict)
    missing_information: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    confidence: float = Field(ge=0, le=1)
    reasoning_summary: str = Field(max_length=240)

    @model_validator(mode="after")
    def consistent_intents(self) -> "TriageResult":
        if len(set(self.intents)) != len(self.intents):
            raise ValueError("duplicate_intents")
        if self.intent == "complex_request":
            if len(self.intents) < 2 or "complex_request" in self.intents:
                raise ValueError("complex_request_requires_multiple_intents")
        elif self.intent not in self.intents or len(self.intents) != 1:
            raise ValueError("primary_intent_mismatch")
        return self


class TaskPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    task_id: str
    intent: Intent
    target_agent: TargetAgent
    required_inputs: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    status: TaskStatus


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    evidence_type: Literal["order", "policy"]
    source: str
    reference: str
    detail: str


class EligibilityResult(BaseModel):
    """Deterministic rule result; model suggestions never set ``validated``."""

    model_config = ConfigDict(extra="forbid", strict=True)

    status: EligibilityStatus
    validated: bool
    rule_code: str | None = None
    checked_order_status: str | None = None
    explanation: str


class ResolutionProposal(BaseModel):
    """Read-only recommendation. It is not an executable business proposal."""

    model_config = ConfigDict(extra="forbid", strict=True)

    proposal_id: str
    task_id: str
    action_type: ActionType
    order_id: str | None = None
    proposed_parameters: dict[str, JsonValue] = Field(default_factory=dict)
    supporting_evidence: list[EvidenceReference] = Field(default_factory=list)
    policy_references: list[EvidenceReference] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    requires_user_confirmation: bool
    requires_human_review: bool
    eligibility_status: EligibilityStatus
    risk_flags: list[str] = Field(default_factory=list)
    status: ResolutionStatus
    explanation: str
    validated: bool = False

    @model_validator(mode="after")
    def safe_status(self) -> "ResolutionProposal":
        if self.status == "pending_confirmation" and (
            not self.validated
            or self.eligibility_status != "eligible"
            or not self.requires_user_confirmation
            or self.action_type == "informational"
        ):
            raise ValueError("pending_confirmation_requires_validated_eligibility")
        if self.validated and self.eligibility_status == "unknown":
            raise ValueError("validated_eligibility_cannot_be_unknown")
        return self


class ExecutionRequestSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    request_id: str
    idempotency_key: str
    task_id: str
    proposal_id: str
    proposal_version: int
    proposal_digest: str
    order_id: str
    action_type: Literal["cancel", "return", "modify_address"]
    proposed_parameters: dict[str, JsonValue]
    summary: str
    status: Literal[
        "pending_confirmation",
        "confirmed",
        "executing",
        "rejected",
        "expired",
        "superseded",
        "succeeded",
        "failed",
    ]
    confirmation_expires_at: int
    confirmation_text: str | None = None


class ConfirmationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    confirmation_id: str
    request_id: str
    proposal_id: str
    proposal_version: int
    proposal_digest: str
    order_id: str
    action_type: Literal["cancel", "return", "modify_address"]
    decision: Literal["confirm", "reject"]
    status: Literal["valid", "rejected", "expired", "consumed", "invalidated"]
    created_at: int
    expires_at: int


class ExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    request_id: str
    proposal_id: str
    confirmation_id: str
    status: Literal["succeeded"]
    action_type: Literal["cancel", "return", "modify_address"]
    order_id: str
    before_status: str
    after_status: str
    row_version: int
    idempotent_replay: bool = False


class OrderSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    order_id: str
    status: str


class OrderItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    item_id: str
    product_id: str
    name: str
    options: dict[str, str]
    price: float


class TrackingInfo(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    item_ids: list[str]
    tracking_id: list[str]


class OrderDetail(OrderSummary):
    items: list[OrderItem]
    fulfillments: list[TrackingInfo]


class ProductVariant(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    item_id: str
    options: dict[str, str]
    available: bool
    price: float


class ProductDetail(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    product_id: str
    name: str
    variants: dict[str, ProductVariant]


class OrderQueryResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["orders", "order", "status", "items", "logistics", "product"]
    source: Literal["business_database"] = "business_database"
    order_id: str | None = None
    orders: list[OrderSummary] | None = None
    order: OrderDetail | None = None
    status: str | None = None
    items: list[OrderItem] | None = None
    fulfillments: list[TrackingInfo] | None = None
    product: ProductDetail | None = None
