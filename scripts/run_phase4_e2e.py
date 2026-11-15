"""Run Playwright against real FastAPI and a disposable PostgreSQL schema."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.database import engine_for, seed
from app.retail import validate
from sqlalchemy import text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
TMP = ROOT / ".tmp" / "phase4_e2e"
SCHEMA_PREFIX = "phase4_e2e_"


def _source() -> dict[str, Any]:
    address = {
        "address1": "Phase 4 Test Road",
        "address2": "",
        "city": "Test City",
        "country": "US",
        "state": "CA",
        "zip": "00000",
    }
    users: dict[str, Any] = {}
    orders: dict[str, Any] = {}
    cases = [
        ("cancel", "cancel.phase4@example.invalid", "e2e-cancel", "pending"),
        ("return", "return.phase4@example.invalid", "e2e-return", "delivered"),
        ("pending", "pending.phase4@example.invalid", "e2e-no-confirm", "pending"),
        ("human", "human.phase4@example.invalid", "e2e-human", "pending"),
        ("approval", "approval.phase4@example.invalid", "e2e-approval", "pending"),
        ("race", "race.phase4@example.invalid", "e2e-race", "pending"),
    ]
    for label, email, order_id, status in cases:
        user_id = f"phase4-{label}-user"
        users[user_id] = {
            "user_id": user_id,
            "name": {"first_name": "Phase", "last_name": label.title()},
            "email": email,
            "address": address,
            "payment_methods": {
                "e2e-card": {
                    "source": "credit_card",
                    "brand": "visa",
                    "last_four": "0000",
                }
            },
            "orders": [order_id],
        }
        orders[order_id] = {
            "order_id": order_id,
            "user_id": user_id,
            "status": status,
            "address": address,
            "items": [
                {
                    "item_id": "e2e-item",
                    "product_id": "e2e-product",
                    "name": "Phase 4 Test Product",
                    "options": {"color": "test"},
                    "price": 10.0,
                }
            ],
            "fulfillments": (
                [{"item_ids": ["e2e-item"], "tracking_id": ["E2E-TRACKING"]}]
                if status == "delivered"
                else []
            ),
            "payment_history": (
                [
                    {
                        "transaction_type": "payment",
                        "amount": 10.0,
                        "payment_method_id": "e2e-card",
                    }
                ]
                if status == "delivered"
                else []
            ),
        }
    # One customer owns two orders so the browser can prove thread isolation.
    thread_user = "phase4-thread-user"
    users[thread_user] = {
        "user_id": thread_user,
        "name": {"first_name": "Phase", "last_name": "Thread"},
        "email": "thread.phase4@example.invalid",
        "address": address,
        "payment_methods": {},
        "orders": ["e2e-thread-a", "e2e-thread-b"],
    }
    for order_id in ("e2e-thread-a", "e2e-thread-b"):
        orders[order_id] = {
            "order_id": order_id,
            "user_id": thread_user,
            "status": "pending",
            "address": address,
            "items": [
                {
                    "item_id": "e2e-item",
                    "product_id": "e2e-product",
                    "name": "Phase 4 Test Product",
                    "options": {"color": "test"},
                    "price": 10.0,
                }
            ],
            "fulfillments": [],
            "payment_history": [],
        }
    return {
        "users": users,
        "products": {
            "e2e-product": {
                "product_id": "e2e-product",
                "name": "Phase 4 Test Product",
                "variants": {
                    "e2e-item": {
                        "item_id": "e2e-item",
                        "options": {"color": "test"},
                        "available": True,
                        "price": 10.0,
                    }
                },
            }
        },
        "orders": orders,
    }


def _wait(url: str, process: subprocess.Popen[str], timeout: float = 45) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"process exited before {url} became ready")
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError(f"timed out waiting for {url}")


def _stop(process: subprocess.Popen[str] | None) -> None:
    if process is None or process.poll() is not None:
        return
    if platform.system() == "Windows":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            capture_output=True,
            text=True,
        )
    else:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()


def _drop_schemas(engine: Any) -> int:
    with engine.begin() as connection:
        names = connection.execute(
            text("SELECT nspname FROM pg_namespace WHERE nspname LIKE :prefix"),
            {"prefix": f"{SCHEMA_PREFIX}%"},
        ).scalars().all()
        for name in names:
            if not name.startswith(SCHEMA_PREFIX) or not name.replace("_", "").isalnum():
                raise RuntimeError("refusing to drop an unexpected schema name")
            connection.exec_driver_sql(f'DROP SCHEMA "{name}" CASCADE')
        return len(names)


def main() -> int:
    base_url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://serviceflow:serviceflow_local@127.0.0.1:5432/serviceflow_demo",
    )
    engine = engine_for(base_url)
    schema = f"{SCHEMA_PREFIX}{uuid4().hex}"
    api_process: subprocess.Popen[str] | None = None
    vite_process: subprocess.Popen[str] | None = None
    schema_created = False
    result = 1
    TMP.mkdir(parents=True, exist_ok=True)
    try:
        _drop_schemas(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        schema_created = True
        isolated = engine.execution_options(schema_translate_map={None: schema})
        seed(isolated, validate(_source()), "phase4-e2e-synthetic-v1")

        app_url = make_url(base_url).update_query_dict({"options": f"-csearch_path={schema}"})
        environment = os.environ.copy()
        environment.update(
            {
                "DATABASE_URL": app_url.render_as_string(hide_password=False),
                "OPERATOR_DEMO_TOKEN": f"phase4-e2e-{uuid4().hex}",
                "OPERATOR_DEMO_ID": "phase4-browser-operator",
                "AGENT_PROVIDER": "mock",
                "POLICY_RETRIEVAL_STRATEGY": "keyword",
                "VITE_PROXY_TARGET": "http://127.0.0.1:8010",
                "PLAYWRIGHT_BASE_URL": "http://127.0.0.1:5174",
            }
        )
        for key in (
            "AGENT_API_KEY",
            "OPENAI_API_KEY",
            "LLM_API_KEY",
            "POLICY_EMBEDDING_API_KEY",
        ):
            environment.pop(key, None)
        environment["E2E_OPERATOR_TOKEN"] = environment["OPERATOR_DEMO_TOKEN"]

        creation_flags = (
            subprocess.CREATE_NEW_PROCESS_GROUP if platform.system() == "Windows" else 0
        )
        backend_log = (TMP / "backend.log").open("w", encoding="utf-8")
        vite_log = (TMP / "vite.log").open("w", encoding="utf-8")
        api_process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--app-dir",
                "backend",
                "--host",
                "127.0.0.1",
                "--port",
                "8010",
                "--no-access-log",
            ],
            cwd=ROOT,
            env=environment,
            stdout=backend_log,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=creation_flags,
        )
        _wait("http://127.0.0.1:8010/api/v1/health", api_process)

        npm = "npm.cmd" if platform.system() == "Windows" else "npm"
        vite_process = subprocess.Popen(
            [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", "5174"],
            cwd=FRONTEND,
            env=environment,
            stdout=vite_log,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=creation_flags,
        )
        _wait("http://127.0.0.1:5174/support", vite_process)

        npx = "npx.cmd" if platform.system() == "Windows" else "npx"
        completed = subprocess.run(
            [npx, "playwright", "test", "--config", "playwright.config.ts"],
            cwd=FRONTEND,
            env=environment,
            check=False,
        )
        result = completed.returncode
    except Exception as exc:
        print(f"Phase 4 E2E runner failed: {type(exc).__name__}: {exc}", file=sys.stderr)
    finally:
        _stop(vite_process)
        _stop(api_process)
        dropped = 0
        residual: int | None = None
        if schema_created:
            dropped = _drop_schemas(engine)
            with engine.connect() as connection:
                residual = connection.scalar(
                    text("SELECT count(*) FROM pg_namespace WHERE nspname LIKE :prefix"),
                    {"prefix": f"{SCHEMA_PREFIX}%"},
                )
        engine.dispose()
        print(
            json.dumps(
                {"schema": schema, "cleanup_dropped": dropped, "residual_schemas": residual}
            )
        )
        if residual not in {0, None}:
            result = 1
    return result


if __name__ == "__main__":
    raise SystemExit(main())
