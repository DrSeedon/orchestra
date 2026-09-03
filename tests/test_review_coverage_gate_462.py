import asyncio
import hashlib
import json
import sqlite3
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest


PROJECT_CONTEXT = """PROJECT CONTEXT:
- Scale: production orchestration platform
- Stack: Python, FastAPI, SQLite, Git worktrees
- What matters: review coverage is bound to the exact production snapshot
"""


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
    return proc.stdout.strip()


def _repo(tmp_path: Path, changed_path: str = "app/widget.py") -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "review-coverage@test")
    _git(repo, "config", "user.name", "review coverage")
    (repo / "README.md").write_text("base\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")
    target_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "switch", "-c", "task-462/worker")
    path = repo / changed_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("VALUE = 1\n")
    _git(repo, "add", changed_path)
    _git(repo, "commit", "-m", "production change")
    return repo, target_sha


def _expected_production_snapshot(repo: Path, target_sha: str, worker_head: str) -> str:
    raw = subprocess.run(
        [
            "git", "diff", "--raw", "--full-index", "-z",
            f"{target_sha}...{worker_head}", "--", "app", "scripts",
        ],
        cwd=repo,
        capture_output=True,
        check=True,
    ).stdout
    return hashlib.sha256(
        b"review-coverage-v1\0" + target_sha.encode() + b"\0" + raw
    ).hexdigest()


def _expected_policy_ref() -> str:
    owner = (
        Path(__file__).resolve().parents[1]
        / ".orchestra/pipelines/default/prompts/skills/codex-debate.md"
    )
    return "codex-debate@sha256:" + hashlib.sha256(owner.read_bytes()).hexdigest()


def _session_info(repo: Path) -> dict:
    return {
        "id": "session-462",
        "name": "worker-462",
        "cwd": str(repo),
        "worktree_path": str(repo),
        "scope": str(repo),
        "task_id": "462",
        "base_branch": "main",
    }


def _save_session(db, *, session_id: str, name: str, scope: str, worktree: str,
                  role: str, is_orchestrator: bool) -> None:
    db.save_session({
        "id": session_id,
        "name": name,
        "scope": scope,
        "cwd": scope,
        "model": "gpt-5.6-sol",
        "system_prompt": "",
        "status": "idle",
        "session_id": None,
        "cost_usd": 0.0,
        "worktree_path": worktree,
        "branch": "task-462/worker" if not is_orchestrator else "main",
        "base_branch": "main",
        "is_orchestrator": is_orchestrator,
        "role": role,
        "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "task_id": "462" if not is_orchestrator else "",
        "needs_switch": 0,
    })


def _available() -> dict:
    return {
        "state": "available",
        "model": "gpt-5.6-luna",
        "provider": "codex",
        "utilization": 1,
        "reason": "test",
    }


def _blocked() -> dict:
    return {
        "state": "blocked",
        "model": "gpt-5.6-luna",
        "provider": "codex",
        "provider_label": "Codex",
        "utilization": 99,
        "reason": "test quota block",
    }


def _receipt_payload(**overrides) -> dict:
    payload = {
        "receipt_id": f"review-receipt:{uuid.uuid4()}",
        "schema_version": 1,
        "runtime": "codex",
        "reviewer_model": "gpt-5.6-luna",
        "model_source": "direct",
        "session_id": "session-462",
        "worker_name": "worker-462",
        "scope": "",
        "task_id": "462",
        "task_source": "session_lookup",
        "artifact_path": "/tmp/review.md",
        "mode": "implementation",
        "round": 1,
        "job_id": "bg-462",
        "usage_event_id": "usage-462",
        "requested_at": "2026-09-03T00:00:00+00:00",
        "completed_at": "2026-09-03T00:01:00+00:00",
        "status": "completed",
        "return_code": 0,
        "failure_code": "",
        "artifact_exists": 1,
        "artifact_bytes": 10,
        "artifact_sha256": "a" * 64,
        "verdict_present": 1,
        "verdict_value": "APPROVED",
        "jsonl_response_present": 1,
        "recovery_source": "",
        "author_outcome": "unknown",
        "outcome_source": "unknown",
        "outcome_evidence_ref": "",
        "notification_event_id": "",
        "subject_kind": "implementation",
        "target_sha": "",
        "worker_head": "",
        "production_snapshot_sha256": "",
        "production_paths_json": "[]",
        "coverage_outcome": "reviewed",
        "policy_ref": "",
        "decision_actor": "",
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_t1_implementation_review_receipt_tracks_exact_production_snapshot(
    tmp_path, monkeypatch,
):
    import app.db as db
    import app.mcp_stdio as mcp

    repo, target_sha = _repo(tmp_path)
    db_path = tmp_path / "receipt.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(db_path))
    db.init_db()
    jobs = []

    async def fake_api(method, path, **kwargs):
        if path == "/api/usage/readiness":
            return _available()
        if method == "GET":
            return _session_info(repo)
        jobs.append(kwargs["json"])
        return {"id": f"bg-{len(jobs)}"}

    monkeypatch.setattr(mcp, "_api", fake_api)
    monkeypatch.setattr(mcp, "_codex_bin", lambda: "/usr/bin/codex")
    monkeypatch.setattr(mcp, "WORKER_NAME", "worker-462")
    monkeypatch.setattr(mcp, "SCOPE", str(repo))

    first = await mcp.mcp.call_tool("codex_review", {
        "context": PROJECT_CONTEXT,
        "output": ".orchestra/tasks/462/review-impl.md",
        "mode": "implementation",
        "model": "gpt5.6luna",
    })
    assert first.isError is False, (
        "T1 missing behavior: codex_review has no snapshot-bound implementation mode"
    )
    first_receipt = db.review_receipt_get(jobs[-1]["receipt_id"])
    assert first_receipt["subject_kind"] == "implementation"
    assert first_receipt["target_sha"] == target_sha
    assert len(first_receipt["production_snapshot_sha256"]) == 64
    command = jobs[-1]["config"]["command"]
    assert "git diff --binary --full-index" in command
    assert f"{target_sha}...{_git(repo, 'rev-parse', 'HEAD')}" in command
    assert target_sha in command
    assert _git(repo, "rev-parse", "HEAD") in command

    note = repo / ".orchestra/tasks/462/note.md"
    note.parent.mkdir(parents=True)
    note.write_text("review evidence only\n")
    _git(repo, "add", str(note.relative_to(repo)))
    _git(repo, "commit", "-m", "review evidence")
    await mcp.codex_review(
        context=PROJECT_CONTEXT,
        output=".orchestra/tasks/462/review-impl-2.md",
        mode="implementation",
        model="gpt5.6luna",
    )
    note_receipt = db.review_receipt_get(jobs[-1]["receipt_id"])
    assert (
        note_receipt["production_snapshot_sha256"]
        == first_receipt["production_snapshot_sha256"]
    )

    (repo / "app/widget.py").write_text("VALUE = 2\n")
    _git(repo, "add", "app/widget.py")
    _git(repo, "commit", "-m", "change implementation")
    await mcp.codex_review(
        context=PROJECT_CONTEXT,
        output=".orchestra/tasks/462/review-impl-3.md",
        mode="implementation",
        model="gpt5.6luna",
    )
    changed_receipt = db.review_receipt_get(jobs[-1]["receipt_id"])
    assert (
        changed_receipt["production_snapshot_sha256"]
        != first_receipt["production_snapshot_sha256"]
    )


def test_t1_init_db_upgrades_a_preexisting_436_receipt_schema(tmp_path, monkeypatch):
    import app.db as db

    db_path = tmp_path / "legacy-436.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute("""
            CREATE TABLE review_receipts (
                receipt_id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL DEFAULT 1,
                runtime TEXT NOT NULL, reviewer_model TEXT NOT NULL,
                model_source TEXT NOT NULL, session_id TEXT NOT NULL,
                worker_name TEXT NOT NULL, scope TEXT NOT NULL, task_id TEXT NOT NULL,
                task_source TEXT NOT NULL, artifact_path TEXT NOT NULL, mode TEXT NOT NULL,
                round INTEGER, job_id TEXT NOT NULL, usage_event_id TEXT NOT NULL,
                requested_at TEXT NOT NULL, completed_at TEXT, status TEXT NOT NULL,
                return_code INTEGER, failure_code TEXT NOT NULL DEFAULT '',
                artifact_exists INTEGER, artifact_bytes INTEGER,
                artifact_sha256 TEXT NOT NULL DEFAULT '', verdict_present INTEGER,
                verdict_value TEXT NOT NULL DEFAULT '', jsonl_response_present INTEGER,
                recovery_source TEXT NOT NULL DEFAULT '',
                author_outcome TEXT NOT NULL DEFAULT 'unknown',
                outcome_source TEXT NOT NULL DEFAULT 'unknown',
                outcome_evidence_ref TEXT NOT NULL DEFAULT '',
                notification_event_id TEXT NOT NULL DEFAULT ''
            )
        """)
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(db_path))

    db.init_db()

    with sqlite3.connect(db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(review_receipts)")}
    expected = {
        "subject_kind", "target_sha", "worker_head", "production_snapshot_sha256",
        "production_paths_json", "coverage_outcome", "policy_ref", "decision_actor",
    }
    assert expected <= columns, (
        "T1 missing behavior: init_db does not upgrade the existing #436 receipt schema"
    )


def test_t1_successful_finalizer_publishes_reviewed_coverage_outcome(
    tmp_path, monkeypatch,
):
    import app.codex_review_artifact as artifact
    import app.db as db

    db_path = tmp_path / "terminal.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(db_path))
    db.init_db()
    receipt = _receipt_payload(
        scope=str(tmp_path), target_sha="1" * 40, worker_head="2" * 40,
        production_snapshot_sha256="3" * 64,
        production_paths_json='["app/widget.py"]', coverage_outcome="unknown",
    )
    db.review_receipt_create(receipt)
    output = tmp_path / "review.md"
    output.write_text("## Verdict\nAPPROVED\n")
    jsonl = tmp_path / "review.jsonl"
    jsonl.write_text(json.dumps({
        "type": "item.completed",
        "item": {"type": "agent_message", "text": "reviewed"},
    }) + "\n")

    artifact._record_terminal_receipt(
        receipt_id=receipt["receipt_id"], output=output, jsonl_file=jsonl,
        status="completed", return_code=0,
    )

    saved = db.review_receipt_get(receipt["receipt_id"])
    assert saved.get("coverage_outcome") == "reviewed", (
        "T1 missing behavior: successful finalization does not publish reviewed coverage"
    )


@pytest.mark.asyncio
async def test_t2_quota_unavailable_is_durable_and_distinct_from_failed(
    tmp_path, monkeypatch,
):
    import app.db as db
    import app.mcp_stdio as mcp

    repo, _target_sha = _repo(tmp_path)
    db_path = tmp_path / "unavailable.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(db_path))
    db.init_db()

    async def fake_api(method, path, **_kwargs):
        if path == "/api/usage/readiness":
            return _blocked()
        if method == "GET":
            return _session_info(repo)
        raise AssertionError("quota refusal must not create a background job")

    monkeypatch.setattr(mcp, "_api", fake_api)
    monkeypatch.setattr(mcp, "WORKER_NAME", "worker-462")
    monkeypatch.setattr(mcp, "SCOPE", str(repo))

    result = await mcp.mcp.call_tool("codex_review", {
        "context": PROJECT_CONTEXT,
        "output": ".orchestra/tasks/462/review-impl.md",
        "mode": "implementation",
        "model": "gpt5.6luna",
    })
    assert result.isError is True
    with db._conn() as connection:
        receipts = connection.execute(
            "SELECT * FROM review_receipts ORDER BY requested_at"
        ).fetchall()
    assert len(receipts) == 1, (
        "T2 missing behavior: quota refusal produced no structured receipt"
    )
    receipt = dict(receipts[0])
    assert receipt["status"] == "failed"
    assert receipt["coverage_outcome"] == "unavailable"
    assert receipt["failure_code"] == "weekly_quota_blocked"
    assert len(receipt["production_snapshot_sha256"]) == 64


@pytest.mark.asyncio
async def test_t2_missing_binary_records_machine_unavailable(tmp_path, monkeypatch):
    import app.db as db
    import app.mcp_stdio as mcp

    repo, _target_sha = _repo(tmp_path)
    db_path = tmp_path / "binary-missing.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(db_path))
    db.init_db()

    async def fake_api(method, path, **_kwargs):
        if path == "/api/usage/readiness":
            return _available()
        if method == "GET":
            return _session_info(repo)
        raise AssertionError("missing binary must not create a background job")

    monkeypatch.setattr(mcp, "_api", fake_api)
    monkeypatch.setattr(mcp, "_codex_bin", lambda: None)
    monkeypatch.setattr(mcp, "WORKER_NAME", "worker-462")
    monkeypatch.setattr(mcp, "SCOPE", str(repo))

    await mcp.mcp.call_tool("codex_review", {
        "context": PROJECT_CONTEXT,
        "output": ".orchestra/tasks/462/review-impl.md",
        "mode": "implementation",
        "model": "gpt5.6luna",
    })
    with db._conn() as connection:
        receipt = connection.execute("SELECT * FROM review_receipts").fetchone()
    assert receipt is not None, (
        "T2 missing behavior: absent Codex binary produced no unavailable receipt"
    )
    receipt = dict(receipt)
    assert receipt["status"] == "failed"
    assert receipt["coverage_outcome"] == "unavailable"
    assert receipt["failure_code"] == "codex_binary_missing"


@pytest.mark.asyncio
async def test_t2_orchestrator_records_snapshot_bound_policy_skip(
    tmp_path, monkeypatch,
):
    import app.db as db
    import app.mcp_stdio as mcp

    repo, _target_sha = _repo(tmp_path)
    db_path = tmp_path / "skip.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(db_path))
    db.init_db()

    calls = []

    async def fake_api(method, path, **kwargs):
        calls.append((method, path, kwargs.get("json")))
        assert method == "POST"
        assert path == "/api/merge-operations/review-skip"
        payload = kwargs["json"]
        assert payload["target_worker"] == "worker-462"
        return {"result": {
            **_receipt_payload(
                status="completed", coverage_outcome="skipped",
                decision_actor="Orchestra-orchestrator",
                policy_ref="codex-debate@abc", production_snapshot_sha256="4" * 64,
            )
        }}

    monkeypatch.setattr(mcp, "_api", fake_api)
    monkeypatch.setattr(mcp, "ROLE", "orchestrator")
    monkeypatch.setattr(mcp, "WORKER_NAME", "Orchestra-orchestrator")
    monkeypatch.setattr(mcp, "SCOPE", str(repo))

    recorded = await mcp.mcp.call_tool("record_review_outcome", {
        "receipt_id": "",
        "outcome": "skipped",
        "outcome_evidence_ref": (
            "tests/test_review_coverage_gate_462.py::"
            "test_t2_orchestrator_records_snapshot_bound_policy_skip"
        ),
        "target_worker": "worker-462",
        "decision_id": "decision-462-skip",
    })
    assert recorded.isError is False, (
        "T2 missing behavior: existing outcome tool cannot record a policy skip"
    )
    receipt = recorded.structuredContent["result"]
    assert receipt["status"] == "completed"
    assert receipt["coverage_outcome"] == "skipped"
    assert receipt["decision_actor"] == "Orchestra-orchestrator"
    assert "codex-debate" in receipt["policy_ref"]
    assert len(receipt["production_snapshot_sha256"]) == 64
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_t2_skip_endpoint_requires_proof_and_replays_one_receipt(
    tmp_path, monkeypatch,
):
    from starlette.requests import Request

    import app.db as db
    import app.mcp_proof as proof
    import app.routes.merge_operations as route

    handler = getattr(route, "record_review_skip", None)
    assert callable(handler), (
        "T2 missing behavior: no proof-bound server endpoint owns skip receipts"
    )
    repo, _target_sha = _repo(tmp_path)
    db_path = tmp_path / "skip-route.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(db_path))
    db.init_db()
    _save_session(
        db, session_id="orchestrator-462", name="Orchestra-orchestrator",
        scope=str(repo), worktree=str(repo), role="orchestrator", is_orchestrator=True,
    )
    _save_session(
        db, session_id="session-462", name="worker-462", scope=str(repo),
        worktree=str(repo), role="worker", is_orchestrator=False,
    )
    token = proof.issue_mcp_proof("orchestrator-462")

    def request(session_id: str, presented: str) -> Request:
        return Request({
            "type": "http", "method": "POST", "path": "/api/merge-operations/review-skip",
            "headers": [
                (b"x-orchestra-session-id", session_id.encode()),
                (b"x-orchestra-mcp-proof", presented.encode()),
            ],
        })

    payload = {
        "decision_id": "decision-462-route",
        "target_worker": "worker-462",
        "scope": str(repo),
        "outcome_evidence_ref": "tests/test_review_coverage_gate_462.py::t2",
    }
    first, replay = await asyncio.gather(
        handler(payload, request("orchestrator-462", token)),
        handler(payload, request("orchestrator-462", token)),
    )
    assert first.status_code == replay.status_code == 200
    first_body = json.loads(first.body)
    assert json.loads(replay.body) == first_body
    assert first_body["result"]["coverage_outcome"] == "skipped"
    with db._conn() as connection:
        rows = connection.execute("SELECT * FROM review_receipts").fetchall()
    assert len(rows) == 1
    stored = dict(rows[0])
    worker_head = _git(repo, "rev-parse", "HEAD")
    target_sha = _git(repo, "rev-parse", "main")
    assert stored["session_id"] == "session-462"
    assert stored["worker_name"] == "worker-462"
    assert stored["target_sha"] == target_sha
    assert stored["worker_head"] == worker_head
    assert stored["production_snapshot_sha256"] == _expected_production_snapshot(
        repo, target_sha, worker_head,
    )

    conflict = await handler(
        {**payload, "outcome_evidence_ref": "changed"},
        request("orchestrator-462", token),
    )
    assert conflict.status_code == 409

    worker_token = proof.issue_mcp_proof("session-462")
    denied = await handler(payload, request("session-462", worker_token))
    assert denied.status_code == 403


@pytest.mark.parametrize(
    ("changed_path", "required"),
    [
        ("app/widget.py", True),
        ("scripts/widget.py", True),
        ("tests/test_widget.py", False),
    ],
)
def test_t3_app_and_scripts_are_reviewed_but_tests_only_are_not(
    tmp_path, monkeypatch, changed_path, required,
):
    import app.acceptance as acceptance
    import app.db as db
    import app.merge_operations as operations

    repo, _target_sha = _repo(tmp_path, changed_path)
    db_path = tmp_path / "trigger.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(db_path))
    db.init_db()
    monkeypatch.setattr(acceptance, "task_oracle_for_session", lambda _sid: {})
    monkeypatch.setattr(
        operations, "review_coverage_policy_active", lambda: True, raising=False,
    )
    accepted = {
        "session_id": "session-462",
        "task_id": "462",
        "base_branch": "main",
        "worktree_path": str(repo),
    }

    admission = operations._prepare_admission_snapshot(
        accepted,
        operations.normalize_request(name="worker-462", scope=str(repo), target="main"),
    )
    review = admission.get("review_coverage", {})
    assert review.get("required") is required, (
        "T3 missing behavior: review trigger is not pinned from changed_paths"
    )
    if required:
        assert review["status"] == "blocked"
        assert review["production_paths"] == [changed_path]
    else:
        assert review["status"] == "not_required"


@pytest.mark.parametrize(
    (
        "status", "coverage_outcome", "failure_code",
        "foreign_session", "stale_snapshot", "allowed",
    ),
    [
        ("completed", "reviewed", "", False, False, True),
        ("completed", "skipped", "", False, False, True),
        ("failed", "unavailable", "weekly_quota_blocked", False, False, True),
        ("failed", "unavailable", "codex_binary_missing", False, False, True),
        ("failed", "unavailable", "provider_error", False, False, False),
        ("interrupted", "reviewed", "interrupted", False, False, False),
        ("failed", "reviewed", "process_exit", False, False, False),
        ("timed_out", "reviewed", "timeout", False, False, False),
        ("completed", "reviewed", "", True, False, False),
        ("completed", "reviewed", "", False, True, False),
    ],
)
def test_t3_only_exact_review_skip_or_unavailable_receipt_authorizes(
    tmp_path, monkeypatch, status, coverage_outcome, failure_code,
    foreign_session, stale_snapshot, allowed,
):
    import app.acceptance as acceptance
    import app.db as db
    import app.merge_operations as operations

    repo, target_sha = _repo(tmp_path)
    worker_head = _git(repo, "rev-parse", "HEAD")
    snapshot = _expected_production_snapshot(repo, target_sha, worker_head)
    db_path = tmp_path / "decision.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(db_path))
    db.init_db()
    monkeypatch.setattr(acceptance, "task_oracle_for_session", lambda _sid: {})
    monkeypatch.setattr(
        operations, "review_coverage_policy_active", lambda: True, raising=False,
    )
    policy_ref = _expected_policy_ref()
    receipt = _receipt_payload(
        scope=str(repo),
        session_id="foreign-session" if foreign_session else "session-462",
        target_sha=target_sha,
        worker_head=worker_head,
        production_snapshot_sha256="0" * 64 if stale_snapshot else snapshot,
        production_paths_json='["app/widget.py"]',
        status=status,
        return_code=None if coverage_outcome == "unavailable" else 0,
        failure_code=failure_code,
        coverage_outcome=coverage_outcome,
        policy_ref=policy_ref if coverage_outcome in {"skipped", "unavailable"} else "",
        artifact_exists=1 if coverage_outcome == "reviewed" else 0,
        artifact_bytes=10 if coverage_outcome == "reviewed" else 0,
        jsonl_response_present=1 if coverage_outcome == "reviewed" else 0,
    )
    db.review_receipt_create(receipt)
    accepted = {
        "session_id": "session-462",
        "task_id": "462",
        "base_branch": "main",
        "worker_head": worker_head,
        "worktree_path": str(repo),
    }

    admission = operations._prepare_admission_snapshot(
        accepted,
        operations.normalize_request(name="worker-462", scope=str(repo), target="main"),
    )

    decision = admission.get("review_coverage", {})
    assert (decision.get("status") == "satisfied") is allowed, (
        "T3 missing behavior: receipt outcome/snapshot is not enforced exactly"
    )


@pytest.mark.asyncio
async def test_t3_blocked_review_snapshot_refuses_before_operation_insert(
    tmp_path, monkeypatch,
):
    import app.db as db
    import app.merge_operations as operations

    db_path = tmp_path / "merge.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(db_path))
    db.init_db()
    operations._runner_tasks.clear()
    db.save_session({
        "id": "session-462",
        "name": "worker-462",
        "scope": "/scope",
        "cwd": "/scope",
        "model": "gpt-5.6-sol",
        "system_prompt": "",
        "status": "idle",
        "session_id": None,
        "cost_usd": 0.0,
        "worktree_path": "/worktree",
        "branch": "task-462/worker",
        "base_branch": "main",
        "is_orchestrator": False,
        "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "task_id": "462",
        "needs_switch": 0,
    })
    accepted = {
        "session_id": "session-462",
        "name": "worker-462",
        "scope": "/scope",
        "base_branch": "main",
        "worker_branch": "task-462/worker",
        "worker_head": "b" * 40,
        "task_id": "462",
        "needs_switch": False,
        "worktree_path": "/worktree",
    }
    admission = {
        "target": {"branch": "main", "sha": "a" * 40},
        "oracle": {"source": "none", "task_id": "462", "required": False},
        "review_coverage": {
            "required": True,
            "status": "blocked",
            "reason": "review_receipt_missing",
            "production_paths": ["app/widget.py"],
            "production_snapshot_sha256": "c" * 64,
        },
    }
    monkeypatch.setattr(operations, "_session_snapshot", lambda _sid: accepted)
    monkeypatch.setattr(
        operations, "_prepare_admission_snapshot", lambda _accepted, _request: admission,
    )
    monkeypatch.setattr(operations, "ensure_operation_runner", lambda _operation_id: None)

    result, status = await operations.accept_merge_operation(
        operation_id=str(uuid.uuid4()),
        name="worker-462",
        scope="/scope",
        target="main",
    )

    assert status == 409, (
        "T3 missing behavior: blocked review coverage still creates a merge operation"
    )
    assert result["error"]["code"] == "REVIEW_COVERAGE_MISSING"
    with db._conn() as connection:
        assert connection.execute("SELECT count(*) FROM merge_operations").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_t3_pending_pre_activation_operation_revalidates_before_executor(
    tmp_path, monkeypatch,
):
    import app.db as db
    import app.merge_operations as operations
    import app.merge_test_gate as test_gate

    repo, target_sha = _repo(tmp_path)
    worker_head = _git(repo, "rev-parse", "HEAD")
    db_path = tmp_path / "pending-activation.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(db_path))
    db.init_db()
    operations._runner_tasks.clear()
    _save_session(
        db, session_id="session-462", name="worker-462", scope=str(repo),
        worktree=str(repo), role="worker", is_orchestrator=False,
    )
    admission = {
        "target": {"branch": "main", "sha": target_sha},
        "oracle": {"source": "none", "task_id": "462", "required": False},
        "review_coverage": {
            "required": False,
            "status": "not_active",
            "production_paths": ["app/widget.py"],
            "production_snapshot_sha256": _expected_production_snapshot(
                repo, target_sha, worker_head,
            ),
        },
    }
    accepted = {
        "session_id": "session-462",
        "name": "worker-462",
        "scope": str(repo),
        "base_branch": "main",
        "worker_branch": "task-462/worker",
        "worker_head": worker_head,
        "task_id": "462",
        "needs_switch": False,
        "worktree_path": str(repo),
        "admission": admission,
    }
    operation_id = str(uuid.uuid4())
    operations.accept_operation_snapshot(
        operation_id=operation_id,
        request=operations.normalize_request(
            name="worker-462", scope=str(repo), target="main",
        ),
        accepted=accepted,
    )
    blocked = {
        **admission["review_coverage"],
        "required": True,
        "status": "blocked",
        "reason": "policy_activated_after_admission",
    }
    monkeypatch.setattr(
        operations, "_verify_accepted_snapshot", lambda _record: (accepted, ""),
    )
    monkeypatch.setattr(
        operations, "review_coverage_policy_active", lambda: True, raising=False,
    )
    monkeypatch.setattr(
        operations, "_revalidate_review_coverage", lambda *_args, **_kwargs: blocked,
        raising=False,
    )
    monkeypatch.setattr(test_gate, "evaluate_test_gate", lambda *_args, **_kwargs: {
        "status": "passed", "reason": "", "exit_code": 0, "output": "",
        "tests": [], "mapped_files": [], "target_ref": "main", "target_sha": target_sha,
    })
    executor = AsyncMock(return_value={
        "ok": False,
        "state": "failed",
        "commit_point": "not_reached",
        "target_branch": "main",
        "worker_branch": "task-462/worker",
        "worker_head": worker_head,
        "error": "executor must not run",
    })
    monkeypatch.setattr("app.routes.sessions.execute_merge_session", executor)

    await operations._run_operation(operation_id)

    executor.assert_not_awaited()
    result = operations.get_operation_result(operation_id)
    assert result["operation_state"] == "FAILED"
    assert result["error"]["code"] == "REVIEW_COVERAGE_MISSING"
