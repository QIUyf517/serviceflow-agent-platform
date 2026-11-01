from copy import deepcopy

import pytest
from app.database import engine_for, seed
from app.retail import validate
from app.service import RetailService


@pytest.fixture
def sample() -> dict:
    """Handwritten synthetic data; no customer or evaluation task copied from upstream."""
    address = {
        "address1": "test",
        "address2": "",
        "city": "test",
        "country": "test",
        "state": "test",
        "zip": "00000",
    }
    return deepcopy(
        {
            "users": {
                "u": {
                    "user_id": "u",
                    "name": {"first_name": "Test", "last_name": "User"},
                    "email": "test@example.invalid",
                    "address": address,
                    "payment_methods": {},
                    "orders": ["o"],
                }
            },
            "products": {
                "p": {
                    "product_id": "p",
                    "name": "Test product",
                    "variants": {
                        "i": {"item_id": "i", "options": {}, "available": True, "price": 12.0}
                    },
                }
            },
            "orders": {
                "o": {
                    "order_id": "o",
                    "user_id": "u",
                    "status": "pending",
                    "address": address,
                    "items": [
                        {
                            "item_id": "i",
                            "product_id": "p",
                            "name": "Test product",
                            "options": {},
                            "price": 10.0,
                        }
                    ],
                    "fulfillments": [],
                    "payment_history": [],
                }
            },
        }
    )


@pytest.fixture
def service(tmp_path, sample):
    sample["users"]["v"] = deepcopy(sample["users"]["u"])
    sample["users"]["v"].update(user_id="v", email="v@example.invalid", orders=[])
    engine = engine_for(f"sqlite:///{(tmp_path / 'test.db').as_posix()}", testing=True)
    seed(engine, validate(sample), "test")
    svc = RetailService(engine)
    yield svc
    engine.dispose()
