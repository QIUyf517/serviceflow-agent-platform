"""Inspect field names/types and counts, never record values or evaluation answers."""

import argparse
import json
from pathlib import Path

from app.retail import load

from scripts.fetch_tau_retail import COMMIT, ROOT, verify

RAW = ROOT / "data/raw/tau2" / COMMIT


def inspect(directory: Path) -> dict:
    manifest = verify(directory)
    db = load(directory / "db.json")
    raw = json.loads((directory / "db.json").read_text(encoding="utf-8"))
    policy = (directory / "policy.md").read_text(encoding="utf-8")
    return {
        "commit": manifest["commit"],
        "collections": {
            name: {
                "count": len(rows),
                "type": type(rows).__name__,
                "fields": {
                    field: sorted(
                        {type(row[field]).__name__ for row in rows.values() if field in row}
                    )
                    for field in sorted({f for row in rows.values() for f in row})
                },
            }
            for name, rows in raw.items()
        },
        "variants": sum(len(p.variants) for p in db.products.values()),
        "order_items": sum(len(o.items) for o in db.orders.values()),
        "policy": {
            "bytes": len(policy.encode()),
            "headings": [line for line in policy.splitlines() if line.startswith("#")],
        },
        "relationships": "validated: IDs, user/order ownership, item/product/variant references",
        "evaluation_files": "hash checked only; no task contents loaded into business runtime",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=RAW)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = json.dumps(inspect(args.raw_dir), indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report + "\n", encoding="utf-8")
    print(report)
