"""Adds the order-thread columns and binds legacy rows in one re-runnable step."""

import argparse
import json

from app.config import Settings
from app.database import engine_for
from app.support_threads import ensure_support_thread_schema


def run() -> dict[str, int]:
    engine = engine_for(Settings().database_url)
    try:
        return ensure_support_thread_schema(engine)
    finally:
        engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Backfill support_threads for legacy tickets and messages."
    )
    parser.parse_args()
    try:
        print(json.dumps(run(), ensure_ascii=False))
    except Exception as exc:
        # Driver exceptions may contain connection parameters; keep the log generic.
        print(f"Migration failed: {type(exc).__name__}; check database availability")
        raise SystemExit(1) from None
