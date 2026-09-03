#!/usr/bin/env python3
"""Freeze protocol inputs before the first model call."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCK = ROOT / "prereg-lock.json"
FILES = ["protocol.json", "capsules.md", "handoff_corpus.json", "answer_keys.json", "run_pilot.py", "score_blind.py", "analyze.py"]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if LOCK.exists():
        raise SystemExit("prereg-lock.json already exists; refusing to overwrite")
    missing = [name for name in FILES if not (ROOT / name).is_file()]
    if missing:
        raise SystemExit(f"missing prereg files: {missing}")
    protocol = json.loads((ROOT / "protocol.json").read_text())
    lock = {
        "task_id": 292,
        "locked_at": "2026-08-16T12:00:00Z",
        "first_model_call": False,
        "protocol_sha256": sha(ROOT / "protocol.json"),
        "files": {name: sha(ROOT / name) for name in FILES},
        "cases": protocol["cases"],
        "arms": protocol["arms"],
        "seed": protocol["randomization"]["seed"],
        "pass_fail": protocol["pass_fail"],
        "aggregation": protocol["noise"],
    }
    LOCK.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"lock": str(LOCK), "sha256": lock["protocol_sha256"], "files": len(FILES)}))


if __name__ == "__main__":
    main()
