"""Authenticated retail operations. All authorization is server side."""

import json
from collections import Counter
from copy import deepcopy
from hashlib import sha256
from time import time
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import (
    AuditRow,
    Base,
    OrderCreationRow,
    OrderRow,
    ProductRow,
    ProposalRow,
    SessionRow,
    UserRow,
)


class BusinessError(Exception):
    def __init__(self, code: str, status: int = 400) -> None:
        self.code = code
        self.status = status
        super().__init__(code)


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal[
        "cancel", "return", "exchange", "modify_address", "modify_payment", "modify_items"
    ]
    order_id: str
    reason: str | None = None
    item_ids: list[str] = Field(default_factory=list)
    item_quantities: dict[str, int] = Field(default_factory=dict)
    new_item_ids: list[str] = Field(default_factory=list)
    payment_method_id: str | None = None
    address: dict[str, str] | None = None


class ActionValidation(BaseModel):
    """Result of applying existing rules to detached copies only."""

    model_config = ConfigDict(extra="forbid", strict=True)
    eligible: bool
    code: str | None
    order_status: str


class CheckoutItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    item_id: str = Field(min_length=1, max_length=128)
    quantity: int = Field(ge=1, le=10)


class CheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    items: list[CheckoutItem] = Field(min_length=1, max_length=20)
    payment_method_id: str = Field(min_length=1, max_length=128)


class RetailService:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        Base.metadata.create_all(engine)

    def start(self) -> str:
        sid = uuid4().hex
        with Session(self.engine) as db, db.begin():
            db.add(SessionRow(id=sid, user_id=None))
        return sid

    @staticmethod
    def _session(db: Session, sid: str, *, verified: bool = True) -> SessionRow:
        row = db.get(SessionRow, sid)
        if row is None:
            raise BusinessError("session_not_found", 404)
        if verified and row.user_id is None:
            raise BusinessError("identity_required", 403)
        return row

    def verify(
        self,
        sid: str,
        *,
        email: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
        zip_code: str | None = None,
    ) -> str:
        if not email and not all((first_name, last_name, zip_code)):
            raise BusinessError("identity_evidence_required")
        with Session(self.engine) as db, db.begin():
            session = self._session(db, sid, verified=False)
            matches = []
            for user in db.scalars(select(UserRow)):
                profile = user.profile_json
                if email and profile["email"].casefold() == email.casefold():
                    matches.append(user.source_user_id)
                elif not email and (
                    profile["name"].get("first_name"),
                    profile["name"].get("last_name"),
                    profile["address"].get("zip"),
                ) == (first_name, last_name, zip_code):
                    matches.append(user.source_user_id)
            if len(matches) != 1 or (session.user_id and session.user_id != matches[0]):
                raise BusinessError("identity_not_verified", 403)
            session.user_id = matches[0]
            return matches[0]

    @staticmethod
    def _own_order(db: Session, user_id: str, oid: str, *, lock: bool = False) -> OrderRow:
        stmt = select(OrderRow).where(OrderRow.source_order_id == oid)
        if lock:
            stmt = stmt.with_for_update()
        row = db.scalar(stmt)
        if row is None or row.source_user_id != user_id:
            raise BusinessError("order_not_found", 404)
        return row

    def orders(self, sid: str) -> list[dict[str, Any]]:
        with Session(self.engine) as db:
            user = self._session(db, sid).user_id
            return [
                deepcopy(o.order_json)
                for o in db.scalars(select(OrderRow).where(OrderRow.source_user_id == user))
            ]

    def order(self, sid: str, oid: str) -> dict[str, Any]:
        with Session(self.engine) as db:
            user = self._session(db, sid).user_id
            return deepcopy(self._own_order(db, user, oid).order_json)

    def user(self, sid: str) -> dict[str, Any]:
        with Session(self.engine) as db:
            user = self._session(db, sid).user_id
            return deepcopy(db.get(UserRow, user).profile_json)

    @staticmethod
    def _checkout_digest(request: CheckoutRequest) -> tuple[str, dict[str, Any]]:
        quantities = Counter[str]()
        for item in request.items:
            quantities[item.item_id] += item.quantity
        if sum(quantities.values()) > 20 or any(quantity > 10 for quantity in quantities.values()):
            raise BusinessError("checkout_quantity_invalid", 422)
        normalized = {
            "items": [
                {"item_id": item_id, "quantity": quantity}
                for item_id, quantity in sorted(quantities.items())
            ],
            "payment_method_id": request.payment_method_id,
        }
        encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return sha256(encoded.encode("utf-8")).hexdigest(), normalized

    @staticmethod
    def _validate_checkout_key(value: str) -> str:
        if not 16 <= len(value) <= 128 or any(char.isspace() for char in value):
            raise BusinessError("idempotency_key_invalid", 422)
        return value

    @staticmethod
    def _checkout_replay(
        row: OrderCreationRow, *, sid: str, user_id: str, digest: str
    ) -> dict[str, Any]:
        if (
            row.session_id != sid
            or row.user_id != user_id
            or row.parameters_digest != digest
        ):
            raise BusinessError("idempotency_key_conflict", 409)
        result = deepcopy(row.result_json)
        result["idempotent_replay"] = True
        return result

    def checkout(
        self, sid: str, request: CheckoutRequest, *, idempotency_key: str
    ) -> dict[str, Any]:
        """Create one simulated order from authoritative catalog and account data."""
        key = self._validate_checkout_key(idempotency_key)
        digest, normalized = self._checkout_digest(request)
        try:
            with Session(self.engine) as db, db.begin():
                session = self._session(db, sid)
                user_id = session.user_id
                existing = db.scalar(
                    select(OrderCreationRow).where(OrderCreationRow.idempotency_key == key)
                )
                if existing is not None:
                    return self._checkout_replay(
                        existing, sid=sid, user_id=user_id, digest=digest
                    )

                user_row = db.get(UserRow, user_id)
                if user_row is None:
                    raise BusinessError("identity_required", 403)
                user = deepcopy(user_row.profile_json)
                payment = self._method(user, request.payment_method_id)

                requested_ids = {item["item_id"] for item in normalized["items"]}
                variants: dict[str, tuple[ProductRow, dict[str, Any]]] = {}
                for product in db.scalars(select(ProductRow)):
                    for item_id, variant in product.product_json["variants"].items():
                        if item_id in requested_ids:
                            variants[item_id] = (product, variant)

                order_items: list[dict[str, Any]] = []
                for requested in normalized["items"]:
                    found = variants.get(requested["item_id"])
                    if found is None or not found[1]["available"]:
                        raise BusinessError("variant_unavailable", 409)
                    product, variant = found
                    for _ in range(requested["quantity"]):
                        order_items.append(
                            {
                                "item_id": variant["item_id"],
                                "product_id": product.source_product_id,
                                "name": product.name,
                                "options": deepcopy(variant["options"]),
                                "price": variant["price"],
                            }
                        )

                total = round(sum(item["price"] for item in order_items), 2)
                if payment["source"] == "gift_card":
                    if payment.get("balance", 0) < total:
                        raise BusinessError("gift_card_insufficient", 409)
                    payment["balance"] = round(payment["balance"] - total, 2)

                order_id = ""
                for _ in range(20):
                    candidate = f"#W{int(uuid4().hex[:8], 16) % 10_000_000:07d}"
                    if db.get(OrderRow, candidate) is None:
                        order_id = candidate
                        break
                if not order_id:
                    raise BusinessError("order_id_generation_failed", 503)

                order = {
                    "order_id": order_id,
                    "user_id": user_id,
                    "address": deepcopy(user["address"]),
                    "items": order_items,
                    "status": "pending",
                    "fulfillments": [],
                    "payment_history": [
                        {
                            "transaction_type": "payment",
                            "amount": total,
                            "payment_method_id": request.payment_method_id,
                        }
                    ],
                }
                now = int(time())
                result = {
                    "order": deepcopy(order),
                    "idempotent_replay": False,
                    "created_at": now,
                }
                db.add(
                    OrderRow(
                        source_order_id=order_id,
                        source_user_id=user_id,
                        status="pending",
                        order_json=order,
                        row_version=1,
                    )
                )
                db.flush()
                user.setdefault("orders", []).append(order_id)
                user_row.profile_json = user
                db.add(
                    OrderCreationRow(
                        id=uuid4().hex,
                        idempotency_key=key,
                        session_id=sid,
                        user_id=user_id,
                        order_id=order_id,
                        parameters_digest=digest,
                        request_json=normalized,
                        result_json=result,
                        created_at=now,
                    )
                )
                db.flush()
                return result
        except IntegrityError as exc:
            with Session(self.engine) as db:
                session = self._session(db, sid)
                existing = db.scalar(
                    select(OrderCreationRow).where(OrderCreationRow.idempotency_key == key)
                )
                if existing is not None:
                    return self._checkout_replay(
                        existing, sid=sid, user_id=session.user_id, digest=digest
                    )
            raise BusinessError("order_creation_conflict", 409) from exc

    def products(self, sid: str) -> list[dict[str, Any]]:
        """Return public catalog summaries after validating the browser session."""
        with Session(self.engine) as db:
            self._session(db, sid, verified=False)
            products = db.scalars(
                select(ProductRow).order_by(ProductRow.name, ProductRow.source_product_id)
            )
            summaries: list[dict[str, Any]] = []
            for row in products:
                variants = list(row.product_json["variants"].values())
                prices = [variant["price"] for variant in variants]
                available = [variant for variant in variants if variant["available"]]
                summaries.append(
                    {
                        "product_id": row.source_product_id,
                        "name": row.name,
                        "min_price": min(prices),
                        "max_price": max(prices),
                        "available_variants": len(available),
                        "total_variants": len(variants),
                        "option_names": sorted(
                            {name for variant in variants for name in variant["options"]}
                        ),
                    }
                )
            return summaries

    def product(self, sid: str, pid: str, *, public: bool = False) -> dict[str, Any]:
        with Session(self.engine) as db:
            self._session(db, sid, verified=not public)
            row = db.get(ProductRow, pid)
            if row is None:
                raise BusinessError("product_not_found", 404)
            return deepcopy(row.product_json)

    @staticmethod
    def _method(user: dict[str, Any], mid: str | None) -> dict[str, Any]:
        method = user["payment_methods"].get(mid) if mid else None
        if method is None:
            raise BusinessError("payment_method_invalid")
        return method

    def _apply(
        self, db: Session, order: dict[str, Any], user: dict[str, Any], action: Action
    ) -> None:
        kind = action.kind
        status = order["status"]
        if (
            kind in {"cancel", "modify_address", "modify_payment", "modify_items"}
            and status != "pending"
        ):
            raise BusinessError("order_status_invalid")
        if kind in {"return", "exchange"} and status != "delivered":
            raise BusinessError("order_status_invalid")
        if kind == "cancel":
            if action.reason not in {"no longer needed", "ordered by mistake"}:
                raise BusinessError("cancel_reason_invalid")
            for payment in list(order["payment_history"]):
                method = self._method(user, payment["payment_method_id"])
                if payment["transaction_type"] != "payment":
                    continue
                order["payment_history"].append(
                    {
                        "transaction_type": "refund",
                        "amount": payment["amount"],
                        "payment_method_id": payment["payment_method_id"],
                    }
                )
                if method["source"] == "gift_card":
                    method["balance"] = round(method["balance"] + payment["amount"], 2)
            order["status"] = "cancelled"
            order["cancel_reason"] = action.reason
        elif kind == "modify_address":
            required_keys = {"address1", "city", "state", "country"}
            optional_keys = {"address2", "zip"}
            if (
                not action.address
                or not required_keys.issubset(action.address)
                or set(action.address) - required_keys - optional_keys
                or not all(isinstance(v, str) for v in action.address.values())
                or any(not action.address[key].strip() for key in required_keys)
            ):
                raise BusinessError("address_invalid")
            order["address"] = {
                "address1": action.address["address1"].strip(),
                "address2": action.address.get("address2", "").strip(),
                "city": action.address["city"].strip(),
                "state": action.address["state"].strip(),
                "country": action.address["country"].strip(),
            }
            if action.address.get("zip", "").strip():
                order["address"]["zip"] = action.address["zip"].strip()
        elif kind == "modify_payment":
            method = self._method(user, action.payment_method_id)
            history = order["payment_history"]
            if len(history) != 1 or history[0]["transaction_type"] != "payment":
                raise BusinessError("payment_history_invalid")
            original = history[0]
            if original["payment_method_id"] == action.payment_method_id:
                raise BusinessError("payment_method_unchanged")
            old = self._method(user, original["payment_method_id"])
            amount = original["amount"]
            if method["source"] == "gift_card" and method["balance"] < amount:
                raise BusinessError("gift_card_insufficient")
            history.extend(
                [
                    {
                        "transaction_type": "payment",
                        "amount": amount,
                        "payment_method_id": action.payment_method_id,
                    },
                    {
                        "transaction_type": "refund",
                        "amount": amount,
                        "payment_method_id": original["payment_method_id"],
                    },
                ]
            )
            if method["source"] == "gift_card":
                method["balance"] = round(method["balance"] - amount, 2)
            if old["source"] == "gift_card":
                old["balance"] = round(old["balance"] + amount, 2)
        else:
            available = Counter(item["item_id"] for item in order["items"])
            requested = (
                Counter(action.item_quantities)
                if action.item_quantities
                else Counter(action.item_ids)
            )
            if any(quantity < 1 for quantity in requested.values()) or not requested:
                raise BusinessError("items_invalid")
            requested = Counter(
                {
                    item_id: action.item_quantities.get(item_id, quantity)
                    for item_id, quantity in requested.items()
                }
            )
            if requested - available:
                raise BusinessError("items_invalid")
            if kind == "return":
                method = self._method(user, action.payment_method_id)
                original = (
                    order["payment_history"][0]["payment_method_id"]
                    if order["payment_history"]
                    else None
                )
                if method["source"] != "gift_card" and action.payment_method_id != original:
                    raise BusinessError("return_method_invalid")
                order.update(
                    status="return requested",
                    return_items=sorted(requested.elements()),
                    return_item_quantities=dict(sorted(requested.items())),
                    return_payment_method_id=action.payment_method_id,
                    return_refund_status="requested_not_disbursed",
                )
            else:
                if len(action.item_ids) != len(action.new_item_ids):
                    raise BusinessError("items_invalid")
                method = self._method(user, action.payment_method_id)
                used: set[int] = set()
                replacements = []
                difference = 0.0
                for old, new in zip(action.item_ids, action.new_item_ids):
                    index = next(
                        (
                            i
                            for i, item in enumerate(order["items"])
                            if item["item_id"] == old and i not in used
                        ),
                        None,
                    )
                    if index is None or old == new:
                        raise BusinessError("items_invalid")
                    used.add(index)
                    item = order["items"][index]
                    product = db.get(ProductRow, item["product_id"])
                    variant = product.product_json["variants"].get(new) if product else None
                    if not variant or not variant["available"]:
                        raise BusinessError("variant_invalid")
                    difference += variant["price"] - item["price"]
                    replacements.append((index, variant))
                difference = round(difference, 2)
                if method["source"] == "gift_card" and method["balance"] < difference:
                    raise BusinessError("gift_card_insufficient")
                if kind == "exchange":
                    order.update(
                        status="exchange requested",
                        exchange_items=sorted(action.item_ids),
                        exchange_new_items=sorted(action.new_item_ids),
                        exchange_payment_method_id=action.payment_method_id,
                        exchange_price_difference=difference,
                    )
                else:
                    for index, variant in replacements:
                        order["items"][index].update(
                            item_id=variant["item_id"],
                            options=variant["options"],
                            price=variant["price"],
                        )
                    order["payment_history"].append(
                        {
                            "transaction_type": "payment" if difference > 0 else "refund",
                            "amount": abs(difference),
                            "payment_method_id": action.payment_method_id,
                        }
                    )
                    if method["source"] == "gift_card":
                        method["balance"] = round(method["balance"] - difference, 2)
                    order["status"] = "pending (item modified)"

    def validate_action(self, sid: str, action: Action) -> ActionValidation:
        """Run the same business rules as execution without persisting any mutation."""
        with Session(self.engine) as db:
            user_id = self._session(db, sid).user_id
            row = self._own_order(db, user_id, action.order_id)
            user = db.get(UserRow, user_id)
            try:
                self._apply(db, deepcopy(row.order_json), deepcopy(user.profile_json), action)
            except BusinessError as exc:
                return ActionValidation(eligible=False, code=exc.code, order_status=row.status)
            return ActionValidation(eligible=True, code=None, order_status=row.status)

    def propose(self, sid: str, action: Action) -> dict[str, Any]:
        with Session(self.engine) as db, db.begin():
            user_id = self._session(db, sid).user_id
            row = self._own_order(db, user_id, action.order_id)
            user = db.get(UserRow, user_id)
            self._apply(db, deepcopy(row.order_json), deepcopy(user.profile_json), action)
            proposal = ProposalRow(
                id=uuid4().hex,
                session_id=sid,
                order_id=action.order_id,
                action=action.kind,
                arguments=action.model_dump(),
                order_version=row.row_version,
                expires_at=int(time()) + 900,
                status="proposed",
                result=None,
            )
            db.add(proposal)
            return {
                "proposal_id": proposal.id,
                "status": "proposed",
                "action": action.model_dump(),
                "summary": (
                    f"{action.kind}: order {action.order_id}; "
                    f"{action.model_dump(exclude_none=True)}"
                ),
            }

    def confirm(self, sid: str, proposal_id: str, *, confirmed: bool) -> dict[str, Any]:
        if not confirmed:
            raise BusinessError("confirmation_required")
        with Session(self.engine) as db, db.begin():
            user_id = self._session(db, sid).user_id
            stmt = select(ProposalRow).where(ProposalRow.id == proposal_id).with_for_update()
            proposal = db.scalar(stmt)
            if proposal is None or proposal.session_id != sid:
                raise BusinessError("proposal_not_found", 404)
            if proposal.status == "succeeded":
                return deepcopy(proposal.result)
            if proposal.status != "proposed":
                raise BusinessError("proposal_invalid")
            if int(time()) > proposal.expires_at:
                raise BusinessError("proposal_expired", 409)
            row = self._own_order(db, user_id, proposal.order_id, lock=True)
            if row.row_version != proposal.order_version:
                raise BusinessError("order_changed", 409)
            user = db.get(UserRow, user_id)
            order_json, user_json = deepcopy(row.order_json), deepcopy(user.profile_json)
            self._apply(db, order_json, user_json, Action.model_validate(proposal.arguments))
            row.order_json, row.status, row.row_version = (
                order_json,
                order_json["status"],
                row.row_version + 1,
            )
            user.profile_json = user_json
            result = {
                "proposal_id": proposal.id,
                "status": "succeeded",
                "order_id": row.source_order_id,
                "order_status": row.status,
                "row_version": row.row_version,
            }
            proposal.status, proposal.result = "succeeded", result
            db.add(
                AuditRow(
                    id=uuid4().hex,
                    proposal_id=proposal.id,
                    session_id=sid,
                    order_id=row.source_order_id,
                    action=proposal.action,
                    result=result,
                )
            )
            return result
