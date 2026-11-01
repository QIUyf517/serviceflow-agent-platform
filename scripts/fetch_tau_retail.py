"""Fetch only pinned Retail inputs and reference/license files; never overwrite raw data."""

import argparse
import hashlib
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "da0835f6c67baef58bdda18f2a3b037dfb3a1754"
REPO = "https://github.com/sierra-research/tau2-bench"
FILES = {
    name: f"data/tau2/domains/retail/{name}"
    for name in ("db.json", "policy.md", "tasks.json", "split_tasks.json")
}
FILES.update(
    {
        "LICENSE": "LICENSE",
        "data_model.py": "src/tau2/domains/retail/data_model.py",
        "tools.py": "src/tau2/domains/retail/tools.py",
        "upstream_pyproject.toml": "pyproject.toml",
    }
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch(commit: str, destination: Path, local: Path | None = None) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("A full immutable commit SHA is required")
    target = destination / commit
    if target.exists():
        return verify(target)
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination) as staging:
        stage = Path(staging)
        records = {}
        for name, source in FILES.items():
            url = f"https://raw.githubusercontent.com/sierra-research/tau2-bench/{commit}/{source}"
            if local:
                content = (local / source).read_bytes()
            else:
                with urlopen(url, timeout=60) as response:
                    content = response.read()
            if name.endswith(".json"):
                json.loads(content)
            (stage / name).write_bytes(content)
            records[name] = {"source": url, "sha256": digest(content), "bytes": len(content)}
        manifest = {
            "repository": REPO,
            "commit": commit,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "license_file": "LICENSE",
            "files": records,
            "purpose": "simulation only; tasks/splits are evaluation-only",
        }
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        stage.rename(target)
    return verify(target)


def verify(directory: Path) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest["commit"] != directory.name:
        raise ValueError("Manifest commit/path mismatch")
    if set(manifest["files"]) != set(FILES):
        raise ValueError("Incomplete source manifest")
    for name, record in manifest["files"].items():
        if digest((directory / name).read_bytes()) != record["sha256"]:
            raise ValueError(f"Source hash mismatch: {name}")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", default=COMMIT)
    parser.add_argument("--destination", type=Path, default=ROOT / "data/raw/tau2")
    parser.add_argument("--local-repository", type=Path)
    args = parser.parse_args()
    if args.local_repository:
        import subprocess

        actual = subprocess.check_output(
            ["git", "-C", str(args.local_repository), "rev-parse", "HEAD"], text=True
        ).strip()
        dirty = subprocess.check_output(
            ["git", "-C", str(args.local_repository), "status", "--porcelain"], text=True
        )
        if actual != args.commit or dirty:
            parser.error("Local source must be clean and checked out at the requested commit")
    result = fetch(args.commit, args.destination, args.local_repository)
    print(json.dumps({"commit": result["commit"], "verified_files": len(result["files"])}))
