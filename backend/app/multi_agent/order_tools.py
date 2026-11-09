"""Read-only, validated adapters around RetailService's business queries."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.multi_agent.models import (
    OrderDetail,
    OrderItem,
    OrderQueryResult,
    OrderSummary,
    ProductDetail,
    TrackingInfo,
)
from app.service import RetailService

OrderToolName = Literal[
    "get_customer_orders",
    "get_order_details",
    "get_order_status",
    "get_order_items",
    "get_order_logistics",
    "get_product_details",
]
ORDER_TOOLS = frozenset(OrderToolName.__args__)


class OrderToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: OrderToolName
    order_id: str | None = Field(default=None, pattern=r"^#?[A-Za-z0-9_-]{1,64}$")
    product_id: str | None = Field(default=None, pattern=r"^#?[A-Za-z0-9_-]{1,64}$")

    @model_validator(mode="after")
    def required_arguments(self) -> "OrderToolCall":
        if self.name == "get_customer_orders":
            if self.order_id is not None or self.product_id is not None:
                raise ValueError("unexpected_query_argument")
        elif self.name == "get_product_details":
            if self.product_id is None or self.order_id is not None:
                raise ValueError("product_id_required")
        elif self.order_id is None or self.product_id is not None:
            raise ValueError("order_id_required")
        return self


def _detail(raw: dict) -> OrderDetail:
    return OrderDetail.model_validate(
        {
            "order_id": raw["order_id"],
            "status": raw["status"],
            "items": [OrderItem.model_validate(item) for item in raw["items"]],
            "fulfillments": [
                TrackingInfo.model_validate(fulfillment) for fulfillment in raw["fulfillments"]
            ],
        }
    )


def execute_order_tool(
    service: RetailService, session_id: str, call: OrderToolCall
) -> OrderQueryResult:
    """No SQL or write surface; service rechecks identity and order ownership."""
    if call.name == "get_customer_orders":
        orders = service.orders(session_id)
        return OrderQueryResult(
            kind="orders",
            orders=[
                OrderSummary.model_validate(
                    {"order_id": order["order_id"], "status": order["status"]}
                )
                for order in orders
            ],
        )
    if call.name == "get_product_details":
        raw = service.product(session_id, call.product_id, public=True)
        return OrderQueryResult(kind="product", product=ProductDetail.model_validate(raw))
    raw = service.order(session_id, call.order_id)
    detail = _detail(raw)
    if call.name == "get_order_details":
        return OrderQueryResult(kind="order", order_id=detail.order_id, order=detail)
    if call.name == "get_order_status":
        return OrderQueryResult(kind="status", order_id=detail.order_id, status=detail.status)
    if call.name == "get_order_items":
        return OrderQueryResult(
            kind="items", order_id=detail.order_id, status=detail.status, items=detail.items
        )
    return OrderQueryResult(
        kind="logistics",
        order_id=detail.order_id,
        status=detail.status,
        fulfillments=detail.fulfillments,
    )
