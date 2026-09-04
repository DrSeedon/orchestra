"""Frozen Phase-2 acceptance oracle for #466.

This file stays under the task boundary. Production code must make it green; the
oracle itself is immutable after the RED commit.
"""

from __future__ import annotations

import importlib
import json
import sqlite3
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest


BASE_REVIEW_RECEIPT_COLUMNS = {
    "receipt_id", "schema_version", "runtime", "reviewer_model", "model_source",
    "session_id", "worker_name", "scope", "task_id", "task_source",
    "artifact_path", "mode", "round", "job_id", "usage_event_id", "requested_at",
    "completed_at", "status", "return_code", "failure_code", "artifact_exists",
    "artifact_bytes", "artifact_sha256", "verdict_present", "verdict_value",
    "jsonl_response_present", "recovery_source", "author_outcome", "outcome_source",
    "outcome_evidence_ref", "notification_event_id", "subject_kind", "target_sha",
    "worker_head", "production_snapshot_sha256", "production_paths_json",
    "coverage_outcome", "policy_ref", "decision_actor",
}
APPROVED_TASK_RUN_COLUMNS = {
    "task_stable_id", "task_snapshot_ref", "prompt_template_start",
    "prompt_template_end", "terminal_operation_id",
}


def _isolated_db(tmp_path, monkeypatch):
    import app.db as db

    path = tmp_path / "run-receipt-466.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(path))
    db.init_db()
    return db, path


def _review_receipt(receipt_id: str, *, requested_at: str, author_outcome: str):
    return {
        "receipt_id": receipt_id,
        "schema_version": 1,
        "runtime": "codex",
        "reviewer_model": "gpt-5.6-luna",
        "model_source": "direct",
        "session_id": "session-466",
        "worker_name": "worker-466",
        "scope": "/scope",
        "task_id": "466",
        "task_source": "session_lookup",
        "artifact_path": "/scope/.orchestra/tasks/466/review.md",
        "mode": "implementation",
        "round": None,
        "job_id": "bg-466",
        "usage_event_id": f"usage:{receipt_id}",
        "requested_at": requested_at,
        "completed_at": requested_at,
        "status": "completed",
        "return_code": 0,
        "failure_code": "",
        "artifact_exists": 1,
        "artifact_bytes": 10,
        "artifact_sha256": "a" * 64,
        "verdict_present": 1,
        "verdict_value": "needs work",
        "jsonl_response_present": 1,
        "recovery_source": "",
        "author_outcome": author_outcome,
        "outcome_source": "direct" if author_outcome != "unknown" else "unknown",
        "outcome_evidence_ref": "" if author_outcome == "unknown" else "review.md#resolution",
        "notification_event_id": "",
        "subject_kind": "implementation",
        "target_sha": "1" * 40,
        "worker_head": "2" * 40,
        "production_snapshot_sha256": "3" * 64,
        "production_paths_json": '["app/example.py"]',
        "coverage_outcome": "reviewed",
        "policy_ref": "",
        "decision_actor": "",
    }


def _decision():
    from app.review_coverage import coverage_decision

    return coverage_decision(
        scope="/scope",
        session_id="session-466",
        task_id="466",
        target_sha="1" * 40,
        worker_head="2" * 40,
        production_paths=["app/example.py"],
        production_snapshot_sha256="3" * 64,
        active=True,
        before="2026-09-03T01:00:00+00:00",
    )


def test_t1_newest_review_requires_direct_author_outcome(tmp_path, monkeypatch):
    db, _path = _isolated_db(tmp_path, monkeypatch)
    older = _review_receipt(
        "review-466-older",
        requested_at="2026-09-03T00:00:00+00:00",
        author_outcome="accepted",
    )
    newer = _review_receipt(
        "review-466-newer",
        requested_at="2026-09-03T00:01:00+00:00",
        author_outcome="unknown",
    )
    assert db.review_receipt_create(older) is True
    assert db.review_receipt_create(newer) is True

    blocked = _decision()
    assert blocked["status"] == "blocked", (
        "T1 missing behavior: the newest real review passes without author_outcome"
    )
    assert blocked["reason"] == "author_outcome_missing"
    assert blocked["receipt_id"] == newer["receipt_id"]

    db.review_receipt_set_outcome(
        newer["receipt_id"], "accepted", "review.md#resolution",
    )
    satisfied = _decision()
    assert satisfied["status"] == "satisfied"
    assert satisfied["receipt_id"] == newer["receipt_id"]
    assert satisfied["author_outcome"] == "accepted"


def test_t1_skip_and_unavailable_do_not_invent_author_outcome(tmp_path, monkeypatch):
    db, _path = _isolated_db(tmp_path, monkeypatch)
    from app.review_coverage import current_policy_ref

    skip = _review_receipt(
        "review-skip-466",
        requested_at="2026-09-03T00:01:00+00:00",
        author_outcome="unknown",
    )
    skip.update(
        runtime="none",
        reviewer_model="",
        mode="skip",
        status="completed",
        return_code=None,
        artifact_exists=0,
        artifact_bytes=0,
        artifact_sha256="",
        verdict_present=0,
        verdict_value="",
        jsonl_response_present=0,
        coverage_outcome="skipped",
        policy_ref=current_policy_ref(),
        decision_actor="orchestrator",
    )
    assert db.review_receipt_create(skip) is True
    decision = _decision()
    assert decision["status"] == "satisfied"
    assert decision["coverage_outcome"] == "skipped"
    assert decision.get("author_outcome", "unknown") == "unknown"

    unavailable = _review_receipt(
        "review-unavailable-466",
        requested_at="2026-09-03T00:02:00+00:00",
        author_outcome="unknown",
    )
    unavailable.update(
        status="failed",
        return_code=None,
        failure_code="weekly_quota_blocked",
        artifact_exists=0,
        artifact_bytes=0,
        artifact_sha256="",
        verdict_present=0,
        verdict_value="",
        jsonl_response_present=0,
        coverage_outcome="unavailable",
        policy_ref=current_policy_ref(),
    )
    assert db.review_receipt_create(unavailable) is True
    decision = _decision()
    assert decision["status"] == "satisfied"
    assert decision["coverage_outcome"] == "unavailable"
    assert decision.get("author_outcome", "unknown") == "unknown"


@pytest.mark.asyncio
async def test_t1_merge_admission_returns_actionable_author_outcome_error(
    tmp_path, monkeypatch,
):
    db, _path = _isolated_db(tmp_path, monkeypatch)
    import app.merge_operations as operations

    operations._runner_tasks.clear()
    db.save_session(_session("session-466", "466"))
    accepted = {
        "session_id": "session-466",
        "name": "session-466",
        "scope": "/scope",
        "base_branch": "main",
        "worker_branch": "task-466/worker",
        "worker_head": "b" * 40,
        "task_id": "466",
        "needs_switch": False,
        "worktree_path": "/worktree",
    }
    admission = {
        "target": {"branch": "main", "sha": "a" * 40},
        "oracle": {"source": "none", "task_id": "466", "required": False},
        "review_coverage": {
            "required": True,
            "status": "blocked",
            "reason": "author_outcome_missing",
            "receipt_id": "review-466-newest",
            "coverage_outcome": "reviewed",
            "author_outcome": "unknown",
            "production_paths": ["app/example.py"],
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
        name="session-466",
        scope="/scope",
        target="main",
    )

    assert status == 409
    assert result["error"]["code"] == "REVIEW_AUTHOR_OUTCOME_MISSING", (
        "T1 missing behavior: merge admission maps missing author outcome as generic coverage"
    )
    assert result["error"]["details"]["receipt_id"] == "review-466-newest"
    assert result["next_action"]["code"] == "RECORD_AUTHOR_OUTCOME_THEN_NEW_OPERATION"
    with db._conn() as connection:
        assert connection.execute(
            "SELECT count(*) FROM merge_operations"
        ).fetchone()[0] == 0


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=False,
    )
    assert done.returncode == 0, done.stderr or done.stdout
    return done.stdout.strip()


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "app").mkdir()
    (repo / "app/example.py").write_text("before = 1\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "base")
    target_sha = _git(repo, "rev-parse", "HEAD")
    _git(repo, "switch", "-c", "task-466/worker")
    (repo / "app/example.py").write_text("after = 2\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "worker")
    return repo, target_sha, _git(repo, "rev-parse", "HEAD")


@pytest.mark.asyncio
async def test_t1_execution_revalidates_pinned_pre_t1_review(tmp_path, monkeypatch):
    db, _path = _isolated_db(tmp_path, monkeypatch)
    import app.merge_operations as operations
    import app.merge_test_gate as test_gate

    repo, target_sha, worker_head = _repo(tmp_path)
    operations._runner_tasks.clear()
    saved = _session("session-466-pre-t1", "466")
    saved.update(
        name="worker-466",
        scope=str(repo),
        cwd=str(repo),
        worktree_path=str(repo),
        branch="task-466/worker",
    )
    db.save_session(saved)
    admission = {
        "target": {"branch": "main", "sha": target_sha},
        "oracle": {"source": "none", "task_id": "466", "required": False},
        "review_coverage": {
            "required": True,
            "status": "satisfied",
            "reason": "",
            "receipt_id": "review-466-pre-t1",
            "coverage_outcome": "reviewed",
            "author_outcome": "unknown",
            "production_paths": ["app/example.py"],
            "production_snapshot_sha256": "c" * 64,
        },
    }
    accepted = {
        "session_id": "session-466-pre-t1",
        "name": "worker-466",
        "scope": str(repo),
        "base_branch": "main",
        "worker_branch": "task-466/worker",
        "worker_head": worker_head,
        "task_id": "466",
        "needs_switch": False,
        "worktree_path": str(repo),
        "admission": admission,
    }
    operation_id = str(uuid.uuid4())
    operations.accept_operation_snapshot(
        operation_id=operation_id,
        request=operations.normalize_request(
            name="worker-466", scope=str(repo), target="main",
        ),
        accepted=accepted,
    )
    blocked = {
        **admission["review_coverage"],
        "status": "blocked",
        "reason": "author_outcome_missing",
    }
    monkeypatch.setattr(
        operations, "_verify_accepted_snapshot", lambda _record: (accepted, ""),
    )
    monkeypatch.setattr(operations, "review_coverage_policy_active", lambda: True)
    monkeypatch.setattr(
        operations, "_revalidate_review_coverage", lambda *_args, **_kwargs: blocked,
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
        "worker_branch": "task-466/worker",
        "worker_head": worker_head,
        "error": "executor must not run",
    })
    monkeypatch.setattr("app.routes.sessions.execute_merge_session", executor)

    await operations._run_operation(operation_id)

    assert executor.await_count == 0, (
        "T1 missing behavior: pinned pre-T1 review was not revalidated before executor"
    )
    result = operations.get_operation_result(operation_id)
    assert result["operation_state"] == "FAILED"
    assert result["error"]["code"] == "REVIEW_AUTHOR_OUTCOME_MISSING"
    assert result["error"]["details"]["receipt_id"] == "review-466-pre-t1"


def _seed_project_and_task(db, *, par_number: int):
    from app import tm

    with tm._conn() as connection:
        tm.ensure_project(connection, "project", scope="/scope")
        task = tm.create_task(
            connection, "project", f"Task {par_number}", par_number=par_number,
        )
    return task


def _session(session_id: str, task_id: str):
    return {
        "id": session_id,
        "name": session_id,
        "scope": "/scope",
        "cwd": "/worktree",
        "model": "gpt-5.6-sol",
        "system_prompt": "prompt",
        "status": "idle",
        "session_id": None,
        "cost_usd": 0.0,
        "worktree_path": "/worktree",
        "branch": f"task-{task_id}/{session_id}",
        "base_branch": "main",
        "needs_switch": 0,
        "task_id": task_id,
        "is_orchestrator": False,
        "parent_name": "orchestrator",
        "color": "",
        "template_hash": "prompt-template-start-466",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    }


def test_t2_task_acceptance_and_terminal_owners_bound_one_run(tmp_path, monkeypatch):
    db, _path = _isolated_db(tmp_path, monkeypatch)
    from app import tm

    expected_columns = APPROVED_TASK_RUN_COLUMNS
    with db._conn() as connection:
        columns = {
            row[1] for row in connection.execute(
                "PRAGMA table_info(review_receipts)"
            ).fetchall()
        }
    assert expected_columns <= columns, (
        "T2 missing behavior: task-run reference columns are absent: "
        f"{sorted(expected_columns - columns)}"
    )

    task = _seed_project_and_task(db, par_number=466)
    identity = {
        "id": task["id"],
        "project_id": task["project_id"],
        "par_number": task["par_number"],
        "sync_revision": task["sync_revision"],
        "stable_id": "46646646-6466-4466-8466-466466466466",
        "canonical_head": "sha256:" + "4" * 64,
    }
    db.publish_ready_session(_session("session-466-run", "466"), identity)
    with db._conn() as connection:
        runs = [
            dict(row) for row in connection.execute(
                "SELECT * FROM review_receipts WHERE subject_kind='task_run'"
            ).fetchall()
        ]
    assert len(runs) == 1, (
        "T2 missing behavior: successful task acceptance opened no task_run receipt"
    )
    run = runs[0]
    assert run["task_stable_id"] == identity["stable_id"]
    assert run["task_snapshot_ref"].endswith(identity["canonical_head"])
    assert run["prompt_template_start"] == "prompt-template-start-466"
    assert run["status"] == "requested" and run["completed_at"] is None

    monkeypatch.setattr(tm, "_ia_context", lambda: None)
    tm.finalize_merge_outcome(
        {
            "project_id": task["project_id"],
            "task": {
                "project_id": task["project_id"],
                "task_id": task["id"],
                "par_number": task["par_number"],
            },
            "commits": {},
            "outcome": "complete",
            "next_task": None,
            "reservation_id": "operation-466",
            "operation_id": "operation-466",
            "session_id": "session-466-run",
        }
    )
    with db._conn() as connection:
        finished = dict(connection.execute(
            "SELECT * FROM review_receipts WHERE receipt_id=?",
            (run["receipt_id"],),
        ).fetchone())
    assert finished["status"] == "completed"
    assert finished["completed_at"]
    assert finished["terminal_operation_id"] == "operation-466"
    assert finished["prompt_template_end"] == "prompt-template-start-466"


def test_t2_trace_is_derived_from_owner_rows_not_stored_counters(tmp_path, monkeypatch):
    db, path = _isolated_db(tmp_path, monkeypatch)
    additions = {
        "task_stable_id": "TEXT NOT NULL DEFAULT ''",
        "task_snapshot_ref": "TEXT NOT NULL DEFAULT ''",
        "prompt_template_start": "TEXT NOT NULL DEFAULT ''",
        "prompt_template_end": "TEXT NOT NULL DEFAULT ''",
        "terminal_operation_id": "TEXT NOT NULL DEFAULT ''",
    }
    with sqlite3.connect(path) as connection:
        existing = {
            row[1] for row in connection.execute(
                "PRAGMA table_info(review_receipts)"
            ).fetchall()
        }
        for column, declaration in additions.items():
            if column not in existing:
                connection.execute(
                    f"ALTER TABLE review_receipts ADD COLUMN {column} {declaration}"
                )
        connection.execute(
            """INSERT INTO review_receipts (
                   receipt_id,schema_version,runtime,reviewer_model,model_source,
                   session_id,worker_name,scope,task_id,task_source,artifact_path,
                   mode,round,job_id,usage_event_id,requested_at,completed_at,status,
                   failure_code,artifact_sha256,verdict_value,recovery_source,
                   author_outcome,outcome_source,outcome_evidence_ref,
                   notification_event_id,subject_kind,target_sha,worker_head,
                   production_snapshot_sha256,production_paths_json,
                   coverage_outcome,policy_ref,decision_actor,task_stable_id,
                   task_snapshot_ref,prompt_template_start,prompt_template_end,
                   terminal_operation_id)
               VALUES (
                   'task-run-466',2,'','','unknown','session-trace-466',
                   'worker-trace-466','/scope','466','canonical','','task_run',NULL,
                   '','','2026-09-03T00:00:00+00:00','2026-09-03T01:00:00+00:00',
                   'completed','','','','','unknown','unknown','','','task_run',
                   '','','','[]','unknown','','',
                   '46646646-6466-4466-8466-466466466466',
                   'orch://project/project/tasks/466@sha256:4444',
                   'prompt-a','prompt-a','operation-trace-466')"""
        )
        connection.execute(
            """INSERT INTO merge_operations (
                   operation_id,session_id,scope,worker_name,request_json,
                   request_hash,dedupe_fingerprint,accepted_worker_branch,
                   accepted_worker_head,accepted_base_branch,accepted_task_id,
                   accepted_admission_json,state,result_json,result_hash,
                   created_at,updated_at,finished_at)
               VALUES ('operation-trace-466','session-trace-466','/scope',
                   'worker-trace-466','{}','request-hash','fingerprint','task-466',
                   'worker-head','main','466','{}','SUCCEEDED',
                   '{"git":{"target_before":"before-sha","target_after":"after-sha"}}',
                   'result-hash','2026-09-03T00:50:00+00:00',
                   '2026-09-03T00:51:00+00:00','2026-09-03T00:51:00+00:00')"""
        )

    db.save_session(_session("session-trace-466", "466"))
    from app.events import MessageProvenance

    db.add_log(
        "session-trace-466",
        datetime.fromisoformat("2026-09-03T00:10:00+00:00"),
        "user_message",
        "correction",
        provenance=MessageProvenance(
            origin="user", senders=("user",), subtype="direct_message",
        ),
    )
    db.add_log(
        "session-trace-466",
        datetime.fromisoformat("2026-09-03T00:11:00+00:00"),
        "tool",
        "Bash: rg -n anchor app",
        tool_use_id="tool-466",
        tool_name="Bash",
    )
    db.turn_usage_add(
        event_id="turn-466",
        session_id="session-trace-466",
        scope="/scope",
        task_id="466",
        runtime="codex",
        model="gpt-5.6-sol",
        ok=False,
        stop_reason="error",
        cost_usd=1.25,
        input_tokens=100,
        output_tokens=10,
        cache_read_tokens=50,
        cache_create_tokens=0,
        ts="2026-09-03T00:20:00+00:00",
    )

    module = importlib.import_module("app.run_receipts") if importlib.util.find_spec(
        "app.run_receipts"
    ) else None
    build = getattr(module, "build_task_run_trace", None) if module else None
    assert callable(build), "T2 missing behavior: derived task-run trace API is absent"
    trace = build("task-run-466")
    assert trace["run"]["task_stable_id"] == (
        "46646646-6466-4466-8466-466466466466"
    )
    assert trace["usage"]["turns"] == 1
    assert trace["usage"]["failed_turns"] == 1
    assert trace["usage"]["cost_usd"] == 1.25
    assert trace["usage"]["models"] == [
        {"runtime": "codex", "model": "gpt-5.6-sol", "turns": 1}
    ]
    assert trace["tools"] == [{"tool_name": "Bash", "calls": 1}]
    assert trace["messages"]["direct_user"] == 1
    assert trace["terminal_operation"] == {
        "operation_id": "operation-trace-466",
        "target_before": "before-sha",
        "target_after": "after-sha",
    }

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE review_receipts SET completed_at=NULL,status='requested',"
            "terminal_operation_id='' WHERE receipt_id='task-run-466'"
        )
    db.add_log(
        "session-trace-466",
        datetime.fromisoformat("2026-09-03T00:40:00+00:00"),
        "tool",
        "LaterTool: must be excluded by as_of",
        tool_use_id="tool-later-466",
        tool_name="LaterTool",
    )
    db.turn_usage_add(
        event_id="turn-later-466",
        session_id="session-trace-466",
        scope="/scope",
        task_id="466",
        runtime="codex",
        model="gpt-5.6-luna",
        ok=True,
        stop_reason="end_turn",
        cost_usd=9.0,
        input_tokens=900,
        output_tokens=90,
        cache_read_tokens=450,
        cache_create_tokens=0,
        ts="2026-09-03T00:40:00+00:00",
    )
    live = build("task-run-466", as_of="2026-09-03T00:30:00+00:00")
    assert live["run"]["live"] is True
    assert live["run"]["completed_at"] is None
    assert live["run"]["effective_end"] == "2026-09-03T00:30:00+00:00"
    assert live["usage"]["turns"] == 1
    assert live["usage"]["cost_usd"] == 1.25
    assert live["tools"] == [{"tool_name": "Bash", "calls": 1}]
    assert live["terminal_operation"] is None

    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE review_receipts SET task_source='legacy_inflight',"
            "task_snapshot_ref='',prompt_template_start='' "
            "WHERE receipt_id='task-run-466'"
        )
    adopted = build("task-run-466", as_of="2026-09-03T00:30:00+00:00")
    assert "acceptance_before_receipt" in adopted["gaps"]

    with sqlite3.connect(path) as connection:
        columns = {
            row[1] for row in connection.execute(
                "PRAGMA table_info(review_receipts)"
            ).fetchall()
        }
    assert columns == BASE_REVIEW_RECEIPT_COLUMNS | APPROVED_TASK_RUN_COLUMNS, (
        "T2 receipt schema must equal the #462 baseline plus exactly five references; "
        f"extra={sorted(columns - BASE_REVIEW_RECEIPT_COLUMNS - APPROVED_TASK_RUN_COLUMNS)}, "
        f"missing={sorted((BASE_REVIEW_RECEIPT_COLUMNS | APPROVED_TASK_RUN_COLUMNS) - columns)}"
    )
