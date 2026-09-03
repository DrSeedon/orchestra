"""Delivery check binding the final prompt rollout to a real project-local agent call."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
RECEIPT = ROOT / "docs/tasks/412/live-owner-receipt.json"
MANIFEST = ROOT / "docs/tasks/412/distribution-manifest.json"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_t6_live_owner_receipt_binds_real_session_and_nonempty_io():
    from app.db import DB_PATH

    assert RECEIPT.is_file(), "T6 live project-local owner receipt missing"
    assert MANIFEST.is_file(), "T6 distribution manifest missing"
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert receipt["status"] == "verified"
    assert receipt["source"] == "project-local"
    assert receipt["project_id"] == "orchestra"
    assert receipt["distribution_manifest_sha256"] == hashlib.sha256(
        MANIFEST.read_bytes()
    ).hexdigest()
    assert receipt["reads"] and receipt["writes"]

    db_path = Path(DB_PATH).resolve()
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as connection:
        row = connection.execute(
            "SELECT scope,role FROM sessions WHERE id=?",
            (receipt["agent_session_id"],),
        ).fetchone()
    assert row is not None, "T6 receipt agent_session_id is not a real session"
    assert Path(row[0]).resolve() == Path(receipt["repository_root"]).resolve()
    assert row[1] in {"orchestrator", "sub-orchestrator", "full-cycle", "worker"}

    repo = Path(receipt["repository_root"])
    commit = receipt["target_commit"]
    assert _git(repo, "rev-parse", f"{commit}^{{commit}}") == commit
    assert {item["operation"] for item in receipt["reads"]} >= {"query"}
    assert {item["operation"] for item in receipt["writes"]} >= {"promote"}
    for item in receipt["reads"] + receipt["writes"]:
        assert Path(item["path"]).parts[:2] == ("docs", "kb")
        payload = subprocess.run(
            ["git", "-C", str(repo), "show", f"{commit}:{item['path']}"],
            check=True,
            capture_output=True,
        ).stdout
        assert hashlib.sha256(payload).hexdigest() == item["sha256"]
