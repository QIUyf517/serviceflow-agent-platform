import json
import os
from copy import deepcopy

import pytest
from app.database import Base, OrderRow, ProductRow, engine_for, seed
from app.main import app
from app.retail import DataError, load, validate
from fastapi.testclient import TestClient
from sqlalchemy import event, select, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from scripts.fetch_tau_retail import COMMIT, FILES, digest, fetch, verify
from scripts.inspect_tau_retail import RAW, inspect


def test_health() -> None:
    response = TestClient(app).get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert TestClient(app).get("/api/v1/orders/o").status_code == 422


@pytest.mark.parametrize("mutation", ["missing", "id", "owner", "variant", "type", "status"])
def test_invalid_data(sample, mutation) -> None:
    if mutation == "missing":
        del sample["users"]
    elif mutation == "id":
        sample["users"]["u"]["user_id"] = "wrong"
    elif mutation == "owner":
        sample["orders"]["o"]["user_id"] = "foreign"
    elif mutation == "variant":
        sample["orders"]["o"]["items"][0]["item_id"] = "absent"
    elif mutation == "type":
        sample["products"]["p"]["variants"]["i"]["available"] = "yes"
    else:
        sample["orders"]["o"]["status"] = "unknown"
    with pytest.raises(DataError) as error:
        validate(sample)
    assert "test@example.invalid" not in str(error.value)


def test_seed_idempotency_reset_and_snapshot_guard(sample) -> None:
    engine = engine_for("sqlite:///:memory:", testing=True)
    db = validate(sample)
    expected = {"users": 1, "products": 1, "orders": 1}
    assert seed(engine, db, "snapshot-a") == expected
    with engine.begin() as conn:
        conn.execute(update(OrderRow).values(status="cancelled"))
    assert seed(engine, db, "snapshot-a") == expected
    with engine.connect() as conn:
        assert conn.scalar(select(OrderRow.status)) == "cancelled"
        assert conn.scalar(select(ProductRow.product_json)) == sample["products"]["p"]
    with pytest.raises(DataError, match="Different source"):
        seed(engine, db, "snapshot-b")
    assert seed(engine, db, "snapshot-b", reset=True) == expected
    with engine.connect() as conn:
        assert conn.scalar(select(OrderRow.status)) == "pending"
    engine.dispose()


def test_reset_rollback_on_insert_failure(sample) -> None:
    engine = engine_for("sqlite:///:memory:", testing=True)
    db = validate(sample)
    seed(engine, db, "a")

    def fail_orders(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO orders"):
            raise RuntimeError("injected failure")

    event.listen(engine, "before_cursor_execute", fail_orders)
    with pytest.raises(RuntimeError, match="injected"):
        seed(engine, db, "b", reset=True)
    event.remove(engine, "before_cursor_execute", fail_orders)
    assert seed(engine, db, "a") == {"users": 1, "products": 1, "orders": 1}
    engine.dispose()


def test_database_target_guard() -> None:
    for url in (
        "sqlite:///:memory:",
        "postgresql+psycopg://localhost/official_benchmark",
        "postgresql+psycopg://localhost/production",
    ):
        with pytest.raises(DataError):
            engine_for(url)
    ddl = str(CreateTable(OrderRow.__table__).compile(dialect=postgresql.dialect()))
    assert "JSONB" in ddl and "FOREIGN KEY" in ddl


def test_fetch_offline_and_tamper_detection(tmp_path, sample) -> None:
    source = tmp_path / "source"
    for name, path in FILES.items():
        destination = source / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        content = (
            json.dumps(sample)
            if name == "db.json"
            else "{}"
            if name.endswith(".json")
            else "test reference"
        )
        destination.write_text(content, encoding="utf-8")
    target = tmp_path / "raw"
    manifest = fetch(COMMIT, target, source)
    assert len(manifest["files"]) == len(FILES)
    assert fetch(COMMIT, target, source) == manifest
    report = inspect(target / COMMIT)
    assert "test@example.invalid" not in json.dumps(report)
    assert "00000" not in json.dumps(report)
    (target / COMMIT / "db.json").write_text("{}")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify(target / COMMIT)


def test_pinned_real_source_sqlite_import(tmp_path) -> None:
    if not RAW.exists():
        pytest.skip("Pinned raw dataset unavailable; fetch it to run this integration test")
    verify(RAW)
    db = load(RAW / "db.json")
    report = inspect(RAW)
    assert {name: stats["count"] for name, stats in report["collections"].items()} == {
        "users": 500,
        "products": 50,
        "orders": 1000,
    }
    engine = engine_for(f"sqlite:///{(tmp_path / 'demo.db').as_posix()}", testing=True)
    checksum = digest((RAW / "db.json").read_bytes())
    expected = {name: len(getattr(db, name)) for name in ("users", "products", "orders")}
    assert seed(engine, db, checksum) == expected
    assert seed(engine, db, checksum) == expected
    assert seed(engine, db, checksum, reset=True) == expected
    engine.dispose()


@pytest.mark.postgres
def test_postgres_real_import() -> None:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured; PostgreSQL integration not verified")
    if not RAW.exists():
        pytest.fail("Pinned raw dataset required for PostgreSQL integration")
    verify(RAW)
    db = load(RAW / "db.json")
    engine = engine_for(url)
    # Test schema is physically separate from the demo tables, even on a shared test DB.
    import uuid

    schema = "phase0_" + uuid.uuid4().hex
    with engine.begin() as conn:
        conn.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    isolated = engine.execution_options(schema_translate_map={None: schema})
    try:
        checksum = digest((RAW / "db.json").read_bytes())
        counts = {"users": 500, "products": 50, "orders": 1000}
        assert seed(isolated, db, checksum) == counts
        assert seed(isolated, db, checksum) == counts
        changed = deepcopy(db)
        changed.orders.pop(next(iter(changed.orders)))
        assert seed(isolated, changed, "changed", reset=True)["orders"] == 999
        assert seed(isolated, db, checksum, reset=True) == counts
    finally:
        Base.metadata.drop_all(isolated)
        with engine.begin() as conn:
            conn.exec_driver_sql(f'DROP SCHEMA "{schema}"')
        engine.dispose()
