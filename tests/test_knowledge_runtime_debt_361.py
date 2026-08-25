"""#361: debt reasons are explicit policy, not one undifferentiated counter."""

from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ia.projections import SQLiteProjectionBackend
from app.ia.runtime import KnowledgeRuntime, KnowledgeRuntimeError


_PROMPT = "\n".join((
    "Use the single `knowledge` tool for canonical knowledge and evidence operations.",
    "Request progressive detail as `summary` < `record` < `evidence`.",
    "Use typed `orch://` identifiers for task, fact, evidence, session, resource, and skill references.",
    "Markdown files, SQLite, FTS, and vector hits are never independent truth.",
    "Historical Markdown and session archives are immutable cold evidence and are never regenerated.",
    "Canonical task, fact, evidence-reference, and session events are structured Git JSON.",
))


def _owner(tmp_path: Path) -> KnowledgeRuntime:
    tmp_path.mkdir(parents=True, exist_ok=True)
    head = "sha256:" + "1" * 64
    current = tmp_path / "current.db"
    SQLiteProjectionBackend(path=current).replace_current(records=[], canonical_head=head)
    legacy = tmp_path / "legacy.db"
    with sqlite3.connect(legacy) as connection:
        connection.execute(
            "CREATE TABLE sessions(id TEXT,session_id TEXT,status TEXT,system_prompt TEXT,prompt_overlay TEXT)"
        )
    vector = tmp_path / "vector.db"
    vector.write_bytes(b"retained")
    owner = object.__new__(KnowledgeRuntime)
    owner.config = SimpleNamespace(
        state_root=tmp_path,
        legacy_db_path=legacy,
        prompt_assembler=lambda _runtime, _role: _PROMPT,
    )
    owner.paths = {
        "canonical_root": tmp_path / "canonical",
        "current_projection": current,
        "task_projection": tmp_path / "task.db",
        "vector_projection": vector,
    }
    owner.state = {
        "canonical_head": head,
        "projection_head": head,
        "indexed_head": "sha256:" + "2" * 64,
        "debt_count": 0,
    }
    owner.task_store = SimpleNamespace(canonical_head="task-head", projection_head="task-head")
    owner.scope_registry = {}
    owner.query_for_scope = lambda _scope, _text, limit=1: {"count": 0}
    owner.parity = lambda: {"mismatch_count": 0, "mismatches": []}
    owner._ensure_vector_projection = lambda: None
    owner._gate_receipt = lambda name, detail: {"status": "verified", "gate": name, **detail}
    owner._connection = lambda: sqlite3.connect(legacy)
    return owner


def _debt(root: Path, name: str, reason: str) -> None:
    debt = root / "debt"
    debt.mkdir(exist_ok=True)
    (debt / f"{name}.json").write_text(json.dumps({"reason": reason}))


def test_t6_debt_reason_policy_keeps_information_visible_and_blocks_unknown_or_unavailable(
    tmp_path,
):
    owner = _owner(tmp_path)
    _debt(tmp_path, "info", "secret_candidate_in_evidence")
    owner.state["debt_count"] = 1

    gates = owner.verify_gates()
    summary = owner.debt_summary()
    assert gates["privacy"]["informational_debt_count"] == 1
    assert summary == {
        "total_count": 1,
        "blocking_count": 0,
        "informational_count": 1,
        "by_reason": {"secret_candidate_in_evidence": 1},
    }

    _debt(tmp_path, "blocking", "git_evidence_source_unavailable")
    owner.state["debt_count"] = 2
    with pytest.raises(KnowledgeRuntimeError, match="blocking runtime debt"):
        owner.verify_gates()

    _debt(tmp_path, "unknown", "future_reason_without_policy")
    with pytest.raises(KnowledgeRuntimeError, match="unknown runtime debt reason"):
        owner.debt_summary()


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def test_t6_scope_evidence_policy_distinguishes_none_broken_git_and_working_git(tmp_path):
    non_git = tmp_path / "media"
    non_git.mkdir()
    owner = _owner(tmp_path / "none")
    owner.scope_registry = {
        str(non_git): {
            "scope": str(non_git),
            "canonical_project_id": "media",
            "repository_root": str(non_git),
            "evidence_mode": "none",
        }
    }
    owner._commit_canonical = lambda _message: None
    owner._save_state = lambda: None
    owner._import_scope_evidence()
    gates = owner.verify_gates()
    assert owner.state["evidence_less_scopes"] == [
        {"scope": str(non_git), "reason": "not_git_backed"}
    ]
    assert gates["projection"]["evidence_less_scopes"] == owner.state["evidence_less_scopes"]

    broken_root = tmp_path / "broken-git"
    broken_root.mkdir()
    broken = _owner(tmp_path / "broken")
    broken.scope_registry = {
        str(broken_root): {
            "scope": str(broken_root),
            "canonical_project_id": "broken",
            "repository_root": str(broken_root),
            "evidence_mode": "git",
        }
    }
    broken._commit_canonical = lambda _message: None
    broken._save_state = lambda: None
    broken._import_scope_evidence()
    assert broken.state["evidence_less_scopes"] == []
    with pytest.raises(KnowledgeRuntimeError, match="blocking runtime debt"):
        broken.verify_gates()

    git_root = tmp_path / "working-git"
    git_root.mkdir()
    subprocess.run(["git", "init", "-q", str(git_root)], check=True)
    _git(git_root, "config", "user.email", "test@example.invalid")
    _git(git_root, "config", "user.name", "Test")
    source = git_root / "README.md"
    source.write_text("# working evidence\n")
    _git(git_root, "add", "README.md")
    _git(git_root, "commit", "-qm", "fixture")
    working = _owner(tmp_path / "working")
    (working.paths["canonical_root"]).mkdir(parents=True)
    working.scope_registry = {
        str(git_root): {
            "scope": str(git_root),
            "canonical_project_id": "working",
            "repository_root": str(git_root),
            "evidence_mode": "git",
        }
    }
    working._commit_canonical = lambda _message: None
    working._save_state = lambda: None
    working._import_scope_evidence()
    records = working.evidence_records()
    assert len(records) == 1
    assert records[0]["source_path"] == "README.md"
    assert records[0]["git_commit"] == _git(git_root, "rev-parse", "HEAD")
    assert working.state["evidence_less_scopes"] == []
