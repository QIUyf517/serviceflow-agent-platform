"""Phase 4.5A catalog and customer isolation against disposable PostgreSQL."""

import os
from copy import deepcopy
from uuid import uuid4

import pytest
from app.database import Base, engine_for, seed
from app.retail import validate
from app.service import BusinessError, RetailService


@pytest.mark.postgres
def test_store_catalog_and_customer_sessions_share_postgres_without_cross_access(sample) -> None:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for isolated PostgreSQL test")
    sample["users"]["v"] = deepcopy(sample["users"]["u"])
    sample["users"]["v"].update(user_id="v", email="v@example.invalid", orders=[])
    engine = engine_for(url)
    schema = "phase45a_" + uuid4().hex
    with engine.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    isolated = engine.execution_options(schema_translate_map={None: schema})
    try:
        seed(isolated, validate(sample), "phase45a-test")
        service = RetailService(isolated)

        first_session = service.start()
        assert service.products(first_session)[0]["product_id"] == "p"
        assert service.product(first_session, "p", public=True)["variants"]["i"]["price"] == 12.0
        with pytest.raises(BusinessError, match="identity_required"):
            service.orders(first_session)

        service.verify(first_session, email="test@example.invalid")
        assert service.orders(first_session)[0]["order_id"] == "o"
        with pytest.raises(BusinessError, match="identity_not_verified"):
            service.verify(first_session, email="v@example.invalid")

        second_session = service.start()
        service.verify(second_session, email="v@example.invalid")
        assert service.orders(second_session) == []
        with pytest.raises(BusinessError, match="order_not_found"):
            service.order(second_session, "o")
    finally:
        Base.metadata.drop_all(isolated)
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}"')
        engine.dispose()
