import argparse
import json
from pathlib import Path

from app.config import Settings
from app.database import engine_for, seed
from app.retail import load

from scripts.fetch_tau_retail import ROOT, verify
from scripts.inspect_tau_retail import RAW


def run(raw: Path, reset: bool = False) -> dict:
    manifest = verify(raw)
    db = load(raw / "db.json")
    engine = engine_for(Settings().database_url)
    try:
        counts = seed(engine, db, manifest["files"]["db.json"]["sha256"], reset=reset)
    finally:
        engine.dispose()
    manifest["import"] = {"counts": counts, "target": "isolated PostgreSQL demo"}
    (ROOT / "data/manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-dir", type=Path, default=RAW)
    parser.add_argument(
        "--reset", action="store_true", help="Replace demo tables in one transaction"
    )
    args = parser.parse_args()
    try:
        print(json.dumps(run(args.raw_dir, args.reset)))
    except Exception as exc:
        # Driver/Pydantic exceptions may contain parameters; do not leak them to logs.
        print(f"Import failed: {type(exc).__name__}; check DB availability and source validation")
        raise SystemExit(1) from None
