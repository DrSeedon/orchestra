import asyncio
import multiprocessing
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest


def _session_row(session_id: str = "merge-session") -> dict:
    return {
        "id": session_id,
        "name": "worker",
        "scope": "/scope",
        "cwd": "/scope",
        "model": "model",
        "system_prompt": "",
        "status": "idle",
        "session_id": None,
        "cost_usd": 0.0,
        "worktree_path": "/worktree",
        "branch": "task-42/worker",
        "base_branch": "main",
        "is_orchestrator": False,
        "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "task_id": "42",
        "needs_switch": 0,
    }


def _accepted(session_id: str = "merge-session") -> dict:
    return {
        "session_id": session_id,
        "name": "worker",
        "scope": "/scope",
        "base_branch": "main",
        "worker_branch": "task-42/worker",
        "worker_head": "b" * 40,
        "task_id": "42",
        "needs_switch": False,
        "worktree_path": "/worktree",
    }


def _process_arbitrate(db_path, accept_barrier, claim_barrier, queue, operation_id):
    import app.db as dbmod
    import app.merge_operations as operations

    dbmod.DB_PATH = Path(db_path)
    request = operations.normalize_request(name="worker", scope="/scope", target="main")
    accept_barrier.wait()
    result, created, status = operations.accept_operation_snapshot(
        operation_id=operation_id,
        request=request,
        accepted=_accepted(),
    )
    claim_barrier.wait()
    claimed = operations.claim_operation(result["operation_id"], operation_id)
    queue.put((result["operation_id"], created, status, claimed))


@pytest.fixture
def merge_db(tmp_path, monkeypatch):
    import app.db as dbmod
    import app.merge_operations as operations

    db_path = tmp_path / "merge.db"
    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    dbmod.init_db()
    operations._runner_tasks.clear()
    dbmod.save_session(_session_row())
    return db_path


def test_schema_and_cross_process_arbitration_allow_one_owner(merge_db):
    import app.db as dbmod
    import app.merge_operations as operations

    with dbmod._conn() as connection:
        columns = {
            row[1] for row in connection.execute(
                "PRAGMA table_info(merge_operations)"
            ).fetchall()
        }
        indexes = {
            row[1] for row in connection.execute(
                "PRAGMA index_list(merge_operations)"
            ).fetchall()
        }
    assert {
        "operation_id", "request_hash", "dedupe_fingerprint", "result_json",
        "accepted_base_branch", "terminal_worker_head", "terminal_base_branch",
        "resolved_at", "resolution_evidence_hash",
    } <= columns
    assert "idx_merge_operations_active_session" in indexes

    context = multiprocessing.get_context("fork")
    accept_barrier = context.Barrier(2)
    claim_barrier = context.Barrier(2)
    queue = context.Queue()
    operation_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    processes = [
        context.Process(
            target=_process_arbitrate,
            args=(str(merge_db), accept_barrier, claim_barrier, queue, operation_id),
        )
        for operation_id in operation_ids
    ]
    for process in processes:
        process.start()
    rows = [queue.get(timeout=10) for _ in processes]
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0

    assert len({row[0] for row in rows}) == 1
    assert sum(row[1] for row in rows) == 1
    assert sum(row[3] for row in rows) == 1
    record = operations.get_operation_record(rows[0][0])
    assert record["state"] == "RUNNING"


@pytest.mark.asyncio
async def test_concurrent_keys_start_exactly_one_executor_and_survive_request_return(
    merge_db, monkeypatch,
):
    import app.merge_operations as operations

    monkeypatch.setattr(
        "app.workspace.inspect_worktree_identity",
        lambda _path: ("task-42/worker", "b" * 40),
    )
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def fake_execute(**_kwargs):
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return {
            "ok": True,
            "state": "merged",
            "commit_point": "target_committed",
            "target_branch": "main",
            "target_before": "a" * 40,
            "target_after": "c" * 40,
            "worker_branch": "task-42/worker",
            "worker_head": "b" * 40,
            "conflicts": [],
            "commits_merged": 1,
            "lifecycle_status": {"ok": True},
            "rag_backfill_status": "accepted",
        }

    monkeypatch.setattr("app.routes.sessions.execute_merge_session", fake_execute)
    primary = str(uuid.uuid4())
    ids = [primary] * 20 + [str(uuid.uuid4()), str(uuid.uuid4())]
    responses = await asyncio.gather(*[
        operations.accept_merge_operation(
            operation_id=operation_id,
            name="worker",
            scope="/scope/",
            target="main",
        )
        for operation_id in ids
    ])
    await started.wait()

    assert calls == 1
    assert len({response[0]["operation_id"] for response in responses}) == 1
    assert all(response[1] == 202 for response in responses)
    assert operations._runner_tasks

    release.set()
    await asyncio.gather(*list(operations._runner_tasks.values()))
    canonical = responses[0][0]["operation_id"]
    result = operations.get_operation_result(canonical)
    assert result["operation_state"] == "SUCCEEDED"
    assert result["commit_point"] == "REACHED"


def test_same_key_payload_mismatch_is_typed_409_without_second_row(merge_db):
    import app.db as dbmod
    import app.merge_operations as operations

    operation_id = str(uuid.uuid4())
    first, created, status = operations.accept_operation_snapshot(
        operation_id=operation_id,
        request=operations.normalize_request(name="worker", scope="/scope", target="main"),
        accepted=_accepted(),
    )
    second, created_again, second_status = operations.accept_operation_snapshot(
        operation_id=operation_id,
        request=operations.normalize_request(name="worker", scope="/scope", target="release"),
        accepted=_accepted(),
    )

    assert created is True and status == 202
    assert created_again is False and second_status == 409
    assert second["operation_state"] == "FAILED"
    assert second["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert second["error"]["message"]
    with dbmod._conn() as connection:
        assert connection.execute("SELECT COUNT(*) FROM merge_operations").fetchone()[0] == 1
    assert operations.get_operation_result(operation_id) == first


def test_terminal_dedupe_only_for_mutating_equivalent_snapshot(merge_db):
    import app.merge_operations as operations

    request = operations.normalize_request(name="worker", scope="/scope", target="main")
    first_id = str(uuid.uuid4())
    _, created, _ = operations.accept_operation_snapshot(
        operation_id=first_id, request=request, accepted=_accepted(),
    )
    assert created and operations.claim_operation(first_id, "owner")
    success = operations.normalize_merge_result(first_id, {
        "ok": True,
        "state": "merged",
        "commit_point": "target_committed",
        "target_branch": "main",
        "target_before": "a" * 40,
        "target_after": "c" * 40,
        "worker_branch": "task-42/worker",
        "worker_head": "b" * 40,
        "conflicts": [],
        "lifecycle_status": {"ok": True},
        "rag_backfill_status": "accepted",
    }, request)
    terminal = {**_accepted(), "worker_head": "c" * 40, "task_id": "", "needs_switch": True}
    assert operations.finish_operation(first_id, "owner", success, terminal)

    retry_snapshot = {**_accepted(), "worker_head": "c" * 40, "task_id": "", "needs_switch": True}
    retried, created_again, status = operations.accept_operation_snapshot(
        operation_id=str(uuid.uuid4()), request=request, accepted=retry_snapshot,
    )
    assert created_again is False and status == 200
    assert retried["operation_id"] == first_id

    changed_snapshot = {**retry_snapshot, "worker_head": "d" * 40}
    fresh, fresh_created, fresh_status = operations.accept_operation_snapshot(
        operation_id=str(uuid.uuid4()), request=request, accepted=changed_snapshot,
    )
    assert fresh_created is True and fresh_status == 202
    assert fresh["operation_id"] != first_id


def test_failed_not_reached_and_noop_are_not_permanently_deduped(merge_db):
    import app.merge_operations as operations

    request = operations.normalize_request(name="worker", scope="/scope", target="main")
    first_id = str(uuid.uuid4())
    operations.accept_operation_snapshot(
        operation_id=first_id, request=request, accepted=_accepted(),
    )
    assert operations.claim_operation(first_id, "owner")
    failed = operations.normalize_merge_result(first_id, {
        "ok": False,
        "state": "failed",
        "commit_point": "not_reached",
        "error": "target working tree is dirty (1 file(s): BUGS.md) — commit or discard first",
        "target_branch": "main",
        "worker_branch": "task-42/worker",
        "worker_head": "b" * 40,
        "conflicts": [],
    }, request)
    assert failed["error"]["code"] == "TARGET_DIRTY"
    assert "BUGS.md" in failed["error"]["message"]
    assert operations.finish_operation(first_id, "owner", failed, _accepted())

    new_failed_retry, created, _ = operations.accept_operation_snapshot(
        operation_id=str(uuid.uuid4()), request=request, accepted=_accepted(),
    )
    assert created and new_failed_retry["operation_id"] != first_id
    second_id = new_failed_retry["operation_id"]
    assert operations.claim_operation(second_id, "noop-owner")
    noop = operations.normalize_merge_result(second_id, {
        "ok": True,
        "state": "merged",
        "commit_point": "not_reached",
        "target_branch": "main",
        "target_before": "a" * 40,
        "target_after": "a" * 40,
        "worker_branch": "task-42/worker",
        "worker_head": "b" * 40,
        "conflicts": [],
        "commits_merged": 0,
        "lifecycle_status": {"ok": True},
        "rag_backfill_status": "accepted",
    }, request)
    assert operations.finish_operation(second_id, "noop-owner", noop, _accepted())
    after_noop, created_after_noop, status = operations.accept_operation_snapshot(
        operation_id=str(uuid.uuid4()), request=request, accepted=_accepted(),
    )
    assert created_after_noop is True and status == 202
    assert after_noop["operation_id"] != second_id


def test_unresolved_partial_blocks_new_key_even_when_snapshot_drifted(merge_db):
    import app.merge_operations as operations

    request = operations.normalize_request(name="worker", scope="/scope", target="main")
    operation_id = str(uuid.uuid4())
    operations.accept_operation_snapshot(
        operation_id=operation_id, request=request, accepted=_accepted(),
    )
    assert operations.claim_operation(operation_id, "owner")
    partial = operations.normalize_merge_result(operation_id, {
        "ok": True,
        "state": "merged",
        "commit_point": "target_committed",
        "target_branch": "main",
        "target_before": "a" * 40,
        "target_after": "c" * 40,
        "worker_branch": "task-42/worker",
        "worker_head": "b" * 40,
        "conflicts": [],
        "lifecycle_status": {"ok": True},
        "rag_backfill_status": "not_ready",
    }, request)
    assert operations.finish_operation(operation_id, "owner", partial, _accepted())

    drifted = {**_accepted(), "worker_head": "f" * 40, "task_id": "99"}
    canonical, created, status = operations.accept_operation_snapshot(
        operation_id=str(uuid.uuid4()), request=request, accepted=drifted,
    )
    assert created is False and status == 200
    assert canonical["operation_id"] == operation_id
    assert canonical["operation_state"] == "PARTIAL"


def test_recover_orphan_running_is_unknown_but_pending_is_restartable(merge_db):
    import app.merge_operations as operations

    request = operations.normalize_request(name="worker", scope="/scope", target="main")
    pending_id = str(uuid.uuid4())
    operations.accept_operation_snapshot(
        operation_id=pending_id, request=request, accepted=_accepted(),
    )
    assert operations.recover_orphan_operations() == [pending_id]
    assert operations.get_operation_result(pending_id)["operation_state"] == "PENDING"

    assert operations.claim_operation(pending_id, "dead-process")
    assert operations.recover_orphan_operations() == []
    result = operations.get_operation_result(pending_id)
    assert result["operation_state"] == "UNKNOWN"
    assert result["commit_point"] == "UNKNOWN"
    assert result["error"]["code"] == "UNKNOWN_OUTCOME"
    assert result["error"]["message"]
    assert result["error"]["retryable"] is False


@pytest.mark.asyncio
async def test_runner_rejects_session_snapshot_change_before_executor(merge_db, monkeypatch):
    import app.db as dbmod
    import app.merge_operations as operations

    monkeypatch.setattr(
        "app.workspace.inspect_worktree_identity",
        lambda _path: ("task-43/worker", "c" * 40),
    )
    operation_id = str(uuid.uuid4())
    request = operations.normalize_request(name="worker", scope="/scope", target="main")
    operations.accept_operation_snapshot(
        operation_id=operation_id, request=request, accepted=_accepted(),
    )
    with dbmod._conn() as connection:
        connection.execute(
            "UPDATE sessions SET branch='task-43/worker', task_id='43' WHERE id='merge-session'"
        )

    async def forbidden_execute(**_kwargs):
        raise AssertionError("pinned executor must not run for changed identity")

    monkeypatch.setattr("app.routes.sessions.execute_merge_session", forbidden_execute)
    await operations._run_operation(operation_id)
    result = operations.get_operation_result(operation_id)
    assert result["operation_state"] == "FAILED"
    assert result["commit_point"] == "NOT_REACHED"
    assert result["error"]["code"] == "SESSION_IDENTITY_CHANGED"


@pytest.mark.asyncio
async def test_runner_rejects_removed_and_respawned_same_name(merge_db, monkeypatch):
    import app.db as dbmod
    import app.merge_operations as operations

    operation_id = str(uuid.uuid4())
    request = operations.normalize_request(name="worker", scope="/scope", target="main")
    operations.accept_operation_snapshot(
        operation_id=operation_id, request=request, accepted=_accepted(),
    )
    dbmod.delete_session("merge-session")
    dbmod.save_session(_session_row("replacement-session"))
    monkeypatch.setattr(
        "app.workspace.inspect_worktree_identity",
        lambda _path: ("task-42/worker", "b" * 40),
    )

    async def forbidden_execute(**_kwargs):
        raise AssertionError("replacement session must not be merged")

    monkeypatch.setattr("app.routes.sessions.execute_merge_session", forbidden_execute)
    await operations._run_operation(operation_id)

    result = operations.get_operation_result(operation_id)
    assert result["operation_state"] == "FAILED"
    assert result["commit_point"] == "NOT_REACHED"
    assert result["error"]["code"] == "SESSION_IDENTITY_CHANGED"


@pytest.mark.asyncio
async def test_restore_runs_pending_once_after_fingerprint_recheck(merge_db, monkeypatch):
    import app.merge_operations as operations

    monkeypatch.setattr(
        "app.workspace.inspect_worktree_identity",
        lambda _path: ("task-42/worker", "b" * 40),
    )
    operation_id = str(uuid.uuid4())
    request = operations.normalize_request(name="worker", scope="/scope", target="main")
    operations.accept_operation_snapshot(
        operation_id=operation_id, request=request, accepted=_accepted(),
    )
    calls = 0

    async def fake_execute(**_kwargs):
        nonlocal calls
        calls += 1
        return {
            "ok": True, "state": "merged", "commit_point": "not_reached",
            "target_branch": "main", "target_before": "a" * 40,
            "target_after": "a" * 40, "worker_branch": "task-42/worker",
            "worker_head": "b" * 40, "conflicts": [], "commits_merged": 0,
            "lifecycle_status": {"ok": True}, "rag_backfill_status": "accepted",
        }

    monkeypatch.setattr("app.routes.sessions.execute_merge_session", fake_execute)
    await operations.restore_merge_operations()
    await asyncio.gather(*list(operations._runner_tasks.values()))

    assert calls == 1
    assert operations.get_operation_result(operation_id)["operation_state"] == "SUCCEEDED"


@pytest.mark.asyncio
async def test_runner_pins_persisted_base_branch_before_execution(merge_db, monkeypatch):
    import app.db as dbmod
    import app.merge_operations as operations

    monkeypatch.setattr(
        "app.workspace.inspect_worktree_identity",
        lambda _path: ("task-42/worker", "b" * 40),
    )
    operation_id = str(uuid.uuid4())
    request = operations.normalize_request(name="worker", scope="/scope")
    operations.accept_operation_snapshot(
        operation_id=operation_id, request=request, accepted=_accepted(),
    )
    with dbmod._conn() as connection:
        connection.execute(
            "UPDATE sessions SET base_branch='release' WHERE id='merge-session'"
        )

    async def forbidden_execute(**_kwargs):
        raise AssertionError("changed persisted base must fail before executor")

    monkeypatch.setattr("app.routes.sessions.execute_merge_session", forbidden_execute)
    await operations._run_operation(operation_id)

    result = operations.get_operation_result(operation_id)
    assert result["operation_state"] == "FAILED"
    assert result["commit_point"] == "NOT_REACHED"
    assert result["error"]["code"] == "SESSION_IDENTITY_CHANGED"


@pytest.mark.asyncio
async def test_committed_merge_without_terminal_snapshot_is_quarantined(merge_db, monkeypatch):
    import app.merge_operations as operations

    identity_calls = 0

    def inspect_identity(_path):
        nonlocal identity_calls
        identity_calls += 1
        if identity_calls == 1:
            return "task-42/worker", "b" * 40
        raise RuntimeError("identity unavailable")

    monkeypatch.setattr("app.workspace.inspect_worktree_identity", inspect_identity)
    operation_id = str(uuid.uuid4())
    request = operations.normalize_request(name="worker", scope="/scope", target="main")
    operations.accept_operation_snapshot(
        operation_id=operation_id, request=request, accepted=_accepted(),
    )

    async def fake_execute(**_kwargs):
        return {
            "ok": True, "state": "merged", "commit_point": "target_committed",
            "target_branch": "main", "target_before": "a" * 40,
            "target_after": "c" * 40, "worker_branch": "task-42/worker",
            "worker_head": "b" * 40, "conflicts": [], "commits_merged": 1,
            "lifecycle_status": {"ok": True}, "rag_backfill_status": "accepted",
        }

    monkeypatch.setattr("app.routes.sessions.execute_merge_session", fake_execute)
    await operations._run_operation(operation_id)

    result = operations.get_operation_result(operation_id)
    assert result["operation_state"] == "PARTIAL"
    assert result["commit_point"] == "REACHED"
    assert result["error"]["code"] == "TERMINAL_SNAPSHOT_FAILED"
    assert result["error"]["details"]["exception_type"] == "RuntimeError"
    assert result["next_action"]["code"] == "FINALIZE_SAME_OPERATION"


@pytest.mark.parametrize(
    ("raw", "state", "point", "git_status", "code"),
    [
        (
            {
                "ok": False, "state": "conflict", "commit_point": "not_reached",
                "conflicts": ["shared file.txt"], "worker_branch": "task-42/worker",
            },
            "FAILED", "NOT_REACHED", "CONFLICT", "CONFLICT",
        ),
        (
            {
                "ok": False, "state": "partial", "commit_point": "unknown",
                "error": "rollback verification failed", "conflicts": [],
            },
            "UNKNOWN", "UNKNOWN", "UNKNOWN", "ROLLBACK_FAILED",
        ),
        (
            {
                "ok": True, "state": "merged", "commit_point": "target_committed",
                "conflicts": [], "lifecycle_status": {"ok": True},
                "rag_backfill_status": "not_ready",
            },
            "PARTIAL", "REACHED", "SUCCEEDED", "RAG_NOT_READY",
        ),
    ],
)
def test_normalize_merge_outcomes_are_typed(raw, state, point, git_status, code):
    import app.merge_operations as operations

    result = operations.normalize_merge_result(
        "00000000-0000-0000-0000-000000000001",
        raw,
        operations.normalize_request(name="worker", scope="/scope", target="main"),
    )
    assert result["operation_state"] == state
    assert result["commit_point"] == point
    assert result["git"]["status"] == git_status
    assert result["error"]["code"] == code
    assert result["error"]["message"]
    if code == "CONFLICT":
        assert result["git"]["conflicts"] == ["shared file.txt"]
        assert "worker branch" in result["next_action"]["message"]


@pytest.mark.parametrize(
    ("message", "code", "action"),
    [
        ("worker is running — wait for idle before merge", "BUSY", "WAIT_UNTIL_IDLE_THEN_NEW_OPERATION"),
        ("worker is waiting — wait for idle before merge", "WAITING", "FINISH_WAIT_THEN_NEW_OPERATION"),
        (
            "worker working tree is dirty (1 file(s): shared file.txt) — commit or discard first",
            "WORKER_DIRTY",
            "COMMIT_WORKER_THEN_NEW_OPERATION",
        ),
    ],
)
def test_precommit_failures_have_nonempty_typed_actions(message, code, action):
    import app.merge_operations as operations

    result = operations.normalize_merge_result(
        "00000000-0000-0000-0000-000000000009",
        {
            "ok": False, "state": "failed", "commit_point": "not_reached",
            "error": message, "target_branch": "main",
            "worker_branch": "task-42/worker", "worker_head": "b" * 40,
            "conflicts": [], "_http_status": 400,
        },
        operations.normalize_request(name="worker", scope="/scope", target="main"),
    )

    assert result["operation_state"] == "FAILED"
    assert result["retryable"] is False
    assert result["error"]["code"] == code
    assert result["error"]["message"] == message
    assert result["error"]["details"]["normalization"] == "LEGACY_UPSTREAM_ERROR"
    assert result["next_action"]["code"] == action


def test_post_commit_stage_failures_preserve_all_stage_statuses():
    import app.merge_operations as operations

    result = operations.normalize_merge_result(
        "00000000-0000-0000-0000-000000000005",
        {
            "ok": True,
            "state": "merged",
            "commit_point": "target_committed",
            "target_branch": "main",
            "target_before": "a" * 40,
            "target_after": "c" * 40,
            "worker_branch": "task-42/worker",
            "worker_head": "b" * 40,
            "conflicts": [],
            "linked_tasks": {
                "42": {"ok": True, "added": 1},
                "43": {"ok": False, "error": "task not found"},
            },
            "lifecycle_status": {"ok": False, "error": "sqlite unavailable"},
            "rag_backfill_status": "accepted",
            "switch": {"ok": False, "error": "branch busy"},
            "task_status": {"ok": False, "error": "switch skipped"},
        },
        operations.normalize_request(
            name="worker", scope="/scope", target="main", next_task_id="43",
        ),
    )

    assert result["operation_state"] == "PARTIAL"
    assert result["commit_point"] == "REACHED"
    assert result["task_links"]["status"] == "PARTIAL"
    assert result["lifecycle"]["status"] == "FAILED"
    assert result["rag"]["status"] == "ACCEPTED"
    assert result["next_task"]["status"] == "FAILED"
    assert set(result["error"]["details"]["failed_stages"]) == {
        "TASK_LINK_PARTIAL", "LIFECYCLE_FAILED", "NEXT_TASK_FAILED",
    }


def test_disabled_rag_is_explicit_terminal_policy_not_partial():
    import app.merge_operations as operations

    result = operations.normalize_merge_result(
        "00000000-0000-0000-0000-000000000006",
        {
            "ok": True, "state": "merged", "commit_point": "target_committed",
            "target_branch": "main", "target_before": "a" * 40,
            "target_after": "c" * 40, "worker_branch": "task-42/worker",
            "worker_head": "b" * 40, "conflicts": [],
            "lifecycle_status": {"ok": True}, "rag_backfill_status": "not_ready",
        },
        operations.normalize_request(name="worker", scope="/scope", target="main"),
        rag_enabled=False,
    )

    assert result["operation_state"] == "SUCCEEDED"
    assert result["rag"]["status"] == "DISABLED"
    assert result["error"] is None


def test_legacy_http_merge_is_426_and_capability_is_visible(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app

    monkeypatch.delenv("DASHBOARD_USER", raising=False)
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    client = TestClient(app, raise_server_exceptions=False)
    try:
        response = client.post("/api/sessions/worker/merge", json={"scope": "/scope"})
        capability = client.get("/api/merge-operations/capabilities")
    finally:
        client.close()

    assert response.status_code == 426
    assert response.json()["error"]["code"] == "MERGE_OPERATION_REQUIRED"
    assert response.json()["error"]["message"]
    assert response.json()["error"]["outcome_unknown"] is False
    assert capability.status_code == 200
    assert capability.json()["capability"] == "operation-v1"


def test_operation_http_shape_copies_only_failed_or_unknown_error_to_top_level():
    from app.merge_operations import _base_result, _error
    from app.routes.merge_operations import _response

    operation_id = "00000000-0000-0000-0000-000000000012"
    error = _error("BUSY", "worker is running", operation_id=operation_id)
    failed = _base_result(operation_id, "FAILED", error=error)
    partial = _base_result(operation_id, "PARTIAL", error=error)

    failed_payload = bytes(_response(failed).body)
    partial_payload = bytes(_response(partial).body)
    assert b'"error":{"code":"BUSY"' in failed_payload
    assert b'"error":null' in partial_payload
