"""Minimal validated import contract, based on the pinned upstream data_model.py."""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError


class DataError(ValueError):
    """Safe import failure; never include customer values in exception text."""


class Record(BaseModel):
    model_config = ConfigDict(extra="allow", strict=True)


class Variant(Record):
    item_id: str
    options: dict[str, str]
    available: bool
    price: float


class Product(Record):
    product_id: str
    name: str
    variants: dict[str, Variant]


class User(Record):
    user_id: str
    name: dict[str, str]
    email: str
    address: dict[str, str]
    payment_methods: dict[str, dict[str, Any]]
    orders: list[str]


class Item(Record):
    item_id: str
    product_id: str
    name: str
    options: dict[str, str]
    price: float


class Order(Record):
    order_id: str
    user_id: str
    status: str
    address: dict[str, str]
    items: list[Item]
    fulfillments: list[dict[str, Any]]
    payment_history: list[dict[str, Any]]


class Retail(Record):
    users: dict[str, User]
    products: dict[str, Product]
    orders: dict[str, Order]


def validate(data: Any) -> Retail:
    try:
        db = Retail.model_validate(data)
    except ValidationError:
        raise DataError("Invalid Retail structure (customer values suppressed)") from None
    for collection, field in (
        (db.users, "user_id"),
        (db.products, "product_id"),
        (db.orders, "order_id"),
    ):
        if any(key != getattr(row, field) for key, row in collection.items()):
            raise DataError("Collection key/record ID mismatch")
    variants = set()
    for product in db.products.values():
        for key, variant in product.variants.items():
            if key != variant.item_id or key in variants or variant.price < 0:
                raise DataError("Invalid variant identifier or price")
            variants.add(key)
    for order in db.orders.values():
        if order.user_id not in db.users:
            raise DataError("Order references missing user")
        if order.order_id not in db.users[order.user_id].orders:
            raise DataError("Order/user ownership mismatch")
        if order.status not in {
            "pending",
            "processed",
            "delivered",
            "cancelled",
            "pending (item modified)",
            "exchange requested",
            "return requested",
        }:
            raise DataError("Unknown order status")
        for item in order.items:
            product = db.products.get(item.product_id)
            if product is None or item.item_id not in product.variants or item.price < 0:
                raise DataError("Invalid order item product/variant reference or price")
    for user in db.users.values():
        if len(user.orders) != len(set(user.orders)):
            raise DataError("Duplicate user order reference")
        if any(
            oid not in db.orders or db.orders[oid].user_id != user.user_id for oid in user.orders
        ):
            raise DataError("User references missing or foreign order")
    return db


def load(path: Path) -> Retail:
    try:
        return validate(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, UnicodeError):
        raise DataError("Invalid database encoding or JSON") from None
