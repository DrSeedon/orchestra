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
    # This test owns operation arbitration, not review coverage: with the policy
    # marker live the admission refuses before the executor and started never fires.
    monkeypatch.setattr(operations, "review_coverage_policy_active", lambda: False)
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
    # Bounded on purpose: a regression here must fail loudly, never hang the gate.
    await asyncio.wait_for(started.wait(), timeout=30)

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
    assert operations.claim_operation(operation_id, "owner") is True
    running = operations.get_operation_result(operation_id)
    assert running["next_action"]["code"] == "CHECK_SAME_OPERATION"
    assert "payload" in running["next_action"]["message"].lower()
    assert "original payload" in running["next_action"]["message"].lower()
    assert "payload differs" in running["next_action"]["message"].lower()
    assert created_again is False and second_status == 409
    assert second["operation_state"] == "FAILED"
    assert second["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert second["error"]["message"]
    assert "payload" in second["next_action"]["message"].lower()
    with dbmod._conn() as connection:
        assert connection.execute("SELECT COUNT(*) FROM merge_operations").fetchone()[0] == 1
        stored = operations.get_operation_result(operation_id)
    assert stored["operation_id"] == first["operation_id"]


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


def test_normalize_rejects_zero_commit_noop_even_when_upstream_is_failed():
    import app.merge_operations as operations

    result = operations.normalize_merge_result(
        "noop-operation",
        {
            "ok": False,
            "state": "partial",
            "commit_point": "target_committed",
            "target_branch": "main",
            "target_before": "a" * 40,
            "target_after": "a" * 40,
            "worker_branch": "task-42/worker",
            "worker_head": "b" * 40,
            "commits_merged": 0,
            "error": "post-merge accounting failed",
        },
        operations.normalize_request(name="worker", scope="/scope", target="main"),
    )

    assert result["operation_state"] == "FAILED"
    assert result["commit_point"] == "NOT_REACHED"
    assert result["git"]["status"] == "FAILED"
    assert result["error"]["code"] == "NO_COMMITS_MERGED"


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
        # Первичный провал — именно он и обязан блокировать (инвариант 1).
        "lifecycle_status": {"ok": False, "error": "sqlite unavailable"},
        "rag_backfill_status": "accepted",
    }, request)
    assert partial["operation_state"] == "PARTIAL"
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

    monkeypatch.setattr(operations, "review_coverage_policy_active", lambda: False)
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
    result = operations.get_operation_result(operation_id)
    assert result["operation_state"] == "FAILED"
    assert result["git"]["status"] == "FAILED"
    assert result["git"]["commits_merged"] == 0
    assert result["error"]["code"] == "NO_COMMITS_MERGED"


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

    monkeypatch.setattr(operations, "review_coverage_policy_active", lambda: False)
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
            # ПЕРВИЧНЫЙ провал после коммита: без сохранённой ветки сессия расходится с
            # git. На этом месте до #80 стоял RAG_NOT_READY — он теперь вторичен, см.
            # test_secondary_stage_failures_do_not_block_after_commit.
            {
                "ok": True, "state": "merged", "commit_point": "target_committed",
                "conflicts": [],
                "lifecycle_status": {"ok": False, "error": "sqlite unavailable"},
                "rag_backfill_status": "accepted",
            },
            "PARTIAL", "REACHED", "SUCCEEDED", "LIFECYCLE_FAILED",
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


def test_post_commit_failure_keeps_git_status_succeeded():
    """A later finalization failure cannot repaint an already committed Git stage."""
    import app.merge_operations as operations

    result = operations.normalize_merge_result(
        "00000000-0000-0000-0000-000000000026",
        {
            "ok": False,
            "state": "partial",
            "commit_point": "target_committed",
            "target_branch": "main",
            "target_after": "c" * 40,
            "commits_merged": 5,
            "conflicts": [],
            "error": "merge finalization failed: status stage exploded",
            "finalization": {"stage": "PENDING"},
        },
        operations.normalize_request(name="worker", scope="/scope", target="main"),
    )

    assert result["commit_point"] == "REACHED"
    assert result["git"]["status"] == "SUCCEEDED"


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


def _merged_raw(**overrides):
    """Успешный git-исход: коммит в target состоялся, все первичные стадии прошли."""
    raw = {
        "ok": True, "state": "merged", "commit_point": "target_committed",
        "target_branch": "main", "target_before": "a" * 40, "target_after": "c" * 40,
        "worker_branch": "task-42/worker", "worker_head": "b" * 40, "conflicts": [],
        "commits_merged": 6, "lifecycle_status": {"ok": True},
        "rag_backfill_status": "accepted",
    }
    raw.update(overrides)
    return raw


def test_missing_task_number_is_a_warning_not_a_partial():
    """Инцидент b876ac54: номер лежит в историческом коммите, чинить его нечем."""
    import app.merge_operations as operations

    result = operations.normalize_merge_result(
        "00000000-0000-0000-0000-000000000020",
        _merged_raw(linked_tasks={
            "18": {"ok": False, "added": 0, "reason": "TASK_NOT_FOUND",
                   "error": "task '18' not found"},
        }),
        operations.normalize_request(name="worker", scope="/scope", target="main"),
    )

    assert result["operation_state"] == "SUCCEEDED"
    assert result["commit_point"] == "REACHED"
    assert result["error"] is None
    assert result["task_links"]["status"] == "WARNED"
    assert any("18" in warning["message"] for warning in result["warnings"])


def test_mixed_link_outcomes_keep_applied_links_and_name_only_the_missing_number():
    """Инциденты 6c226777 и b876ac54: часть привязок применилась, одна ссылка не нашлась."""
    import app.merge_operations as operations

    result = operations.normalize_merge_result(
        "00000000-0000-0000-0000-000000000021",
        _merged_raw(linked_tasks={
            "24": {"ok": True, "added": 3, "task_id": "t-24"},
            "25": {"ok": False, "added": 0, "reason": "TASK_NOT_FOUND",
                   "error": "task '25' not found"},
        }),
        operations.normalize_request(name="worker", scope="/scope", target="main"),
    )

    assert result["operation_state"] == "SUCCEEDED"
    assert result["task_links"]["status"] == "WARNED"
    items = result["task_links"]["items"]
    assert items["24"]["ok"] is True and items["24"]["added"] == 3
    assert items["25"]["ok"] is False
    messages = " ".join(warning["message"] for warning in result["warnings"])
    assert "25" in messages and "24:" not in messages


def test_broken_link_is_still_partial_because_state_not_history_failed():
    """БД задач недоступна — номер существует, повтор может помочь: провал остаётся."""
    import app.merge_operations as operations

    result = operations.normalize_merge_result(
        "00000000-0000-0000-0000-000000000022",
        _merged_raw(linked_tasks={
            "24": {"ok": False, "added": 0, "error": "database is locked"},
        }),
        operations.normalize_request(name="worker", scope="/scope", target="main"),
    )

    assert result["operation_state"] == "PARTIAL"
    assert result["task_links"]["status"] == "FAILED"
    assert result["error"]["code"] == "TASK_LINK_PARTIAL"
    assert result["error"]["details"]["failed_stages"] == ["TASK_LINK_PARTIAL"]


def test_missing_task_number_does_not_block_the_next_operation(merge_db, monkeypatch):
    """Сквозной инвариант инцидентов: следующий мерж создаёт НОВУЮ операцию."""
    import app.merge_operations as operations

    monkeypatch.setattr(
        "app.workspace.inspect_worktree_identity",
        lambda _path: ("task-42/worker", "b" * 40),
    )
    request = operations.normalize_request(name="worker", scope="/scope", target="main")
    first_id = str(uuid.uuid4())
    operations.accept_operation_snapshot(
        operation_id=first_id, request=request, accepted=_accepted(),
    )
    assert operations.claim_operation(first_id, "owner")
    result = operations.normalize_merge_result(first_id, _merged_raw(
        target_after="d" * 40,
        linked_tasks={
            "18": {"ok": False, "added": 0, "reason": "TASK_NOT_FOUND",
                   "error": "task '18' not found"},
        },
    ), request)
    assert operations.finish_operation(first_id, "owner", result, _accepted())

    _next, created, status = operations.accept_operation_snapshot(
        operation_id=str(uuid.uuid4()),
        request=operations.normalize_request(
            name="worker", scope="/scope", target="main", next_task_id="81",
        ),
        accepted={**_accepted(), "worker_head": "e" * 40},
    )
    assert created is True and status == 202


def test_task_not_found_marker_comes_from_the_task_manager(tmp_path, monkeypatch):
    """Маркер не выдуман тестом: его ставит сам tm.link_commits_to_task."""
    import app.db as dbmod
    import app.tm as tm

    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "tm.db")
    dbmod.init_db()
    with tm._conn() as conn:
        tm.ensure_project(conn, "project")
    outcome = tm.link_commits_to_task("18", [{"hash": "a" * 40}], "project")
    assert outcome["ok"] is False
    assert outcome["reason"] == "TASK_NOT_FOUND"


def test_secondary_stage_failures_do_not_block_after_commit():
    """REACHED + только вторичные провалы → терминально, предупреждения на месте."""
    import app.merge_operations as operations

    result = operations.normalize_merge_result(
        "00000000-0000-0000-0000-000000000023",
        _merged_raw(
            rag_backfill_status="not_ready",
            switch={"ok": False, "error": "branch busy"},
            task_status={"ok": False, "error": "switch skipped"},
        ),
        operations.normalize_request(
            name="worker", scope="/scope", target="main", next_task_id="81",
        ),
    )

    assert result["operation_state"] == "SUCCEEDED"
    assert result["operation_state"] not in operations.ACTIVE_STATES
    assert result["error"] is None
    assert result["rag"]["status"] == "NOT_READY"
    assert result["next_task"]["status"] == "FAILED"
    codes = {warning["code"] for warning in result["warnings"]}
    assert codes == {"RAG_NOT_READY", "NEXT_TASK_FAILED"}
    assert "branch busy" in result["next_action"]["message"]


def test_primary_stage_failure_after_commit_still_blocks():
    """LIFECYCLE_FAILED первичен: без сохранённой ветки сессия расходится с git."""
    import app.merge_operations as operations

    result = operations.normalize_merge_result(
        "00000000-0000-0000-0000-000000000024",
        _merged_raw(
            lifecycle_status={"ok": False, "error": "sqlite unavailable"},
            rag_backfill_status="not_ready",
        ),
        operations.normalize_request(name="worker", scope="/scope", target="main"),
    )

    assert result["operation_state"] == "PARTIAL"
    assert result["operation_state"] in operations.ACTIVE_STATES
    assert result["error"]["code"] == "LIFECYCLE_FAILED"
    assert set(result["error"]["details"]["failed_stages"]) == {
        "LIFECYCLE_FAILED", "RAG_NOT_READY",
    }
    # Вторичное не исчезает молча даже когда первичное уже держит операцию.
    assert [warning["code"] for warning in result["warnings"]] == ["RAG_NOT_READY"]


def test_unknown_commit_point_is_never_auto_closed_by_secondary_rule():
    """Инвариант 2: неизвестный git-исход не закрывается автоматически никогда."""
    import app.merge_operations as operations

    result = operations.normalize_merge_result(
        "00000000-0000-0000-0000-000000000025",
        _merged_raw(commit_point="unknown", rag_backfill_status="not_ready"),
        operations.normalize_request(name="worker", scope="/scope", target="main"),
    )

    assert result["operation_state"] == "UNKNOWN"
    assert result["operation_state"] in operations.ACTIVE_STATES
    assert result["error"]["outcome_unknown"] is True


def _blocked_partial(operations, request, session_id="merge-session"):
    """Довести операцию до блокирующего PARTIAL (первичный провал после коммита)."""
    operation_id = str(uuid.uuid4())
    operations.accept_operation_snapshot(
        operation_id=operation_id, request=request, accepted=_accepted(session_id),
    )
    assert operations.claim_operation(operation_id, "owner")
    result = operations.normalize_merge_result(operation_id, _merged_raw(
        lifecycle_status={"ok": False, "error": "sqlite unavailable"},
    ), request)
    assert result["operation_state"] == "PARTIAL"
    assert operations.finish_operation(operation_id, "owner", result, _accepted(session_id))
    return operation_id


def test_blocking_next_action_names_the_allowed_action():
    """Инструкция без разрешённого действия не выполняется — её обходят руками."""
    import app.merge_operations as operations

    request = operations.normalize_request(name="worker", scope="/scope", target="main")
    partial = operations.normalize_merge_result(
        "00000000-0000-0000-0000-000000000030",
        _merged_raw(lifecycle_status={"ok": False, "error": "sqlite unavailable"}),
        request,
    )
    unknown = operations.normalize_merge_result(
        "00000000-0000-0000-0000-000000000031",
        _merged_raw(commit_point="unknown"),
        request,
    )

    for result in (partial, unknown):
        assert result["operation_state"] in operations.ACTIVE_STATES
        assert "resolve_merge_operation" in result["next_action"]["message"]
        assert result["operation_id"] in result["next_action"]["message"]


def test_resolved_partial_lets_the_next_operation_start(merge_db, monkeypatch):
    import app.merge_operations as operations

    monkeypatch.setattr(
        "app.workspace.inspect_worktree_identity",
        lambda _path: ("task-42/worker", "b" * 40),
    )
    request = operations.normalize_request(name="worker", scope="/scope", target="main")
    operation_id = _blocked_partial(operations, request)

    blocked, created, status = operations.accept_operation_snapshot(
        operation_id=str(uuid.uuid4()), request=request,
        accepted={**_accepted(), "worker_head": "e" * 40},
    )
    assert created is False and status == 200
    assert "resolve_merge_operation" in blocked["next_action"]["message"]

    resolved, resolve_status = operations.resolve_operation(
        operation_id, reason="checked main: squash commit is in, session row fixed by hand",
    )
    assert resolve_status == 200
    assert resolved["operation_state"] == "PARTIAL"
    assert resolved["resolution"]["reason"].startswith("checked main")

    _after, created_after, status_after = operations.accept_operation_snapshot(
        operation_id=str(uuid.uuid4()), request=request,
        accepted={**_accepted(), "worker_head": "e" * 40},
    )
    assert created_after is True and status_after == 202


def test_resolve_is_idempotent_and_refuses_non_blocking_states(merge_db, monkeypatch):
    import app.merge_operations as operations

    monkeypatch.setattr(
        "app.workspace.inspect_worktree_identity",
        lambda _path: ("task-42/worker", "b" * 40),
    )
    request = operations.normalize_request(name="worker", scope="/scope", target="main")
    operation_id = _blocked_partial(operations, request)
    _first, first_status = operations.resolve_operation(operation_id, reason="reconciled")
    second, second_status = operations.resolve_operation(operation_id, reason="again")
    assert first_status == 200 and second_status == 200
    assert "error" not in _first
    assert _first["resolution"]["previous_error"]["code"]
    assert "error" not in second
    assert second["resolution"]["reason"] == "reconciled"

    missing, missing_status = operations.resolve_operation(
        str(uuid.uuid4()), reason="reconciled",
    )
    assert missing_status == 404 and missing["error"]["code"] == "OPERATION_NOT_FOUND"

    no_reason, no_reason_status = operations.resolve_operation(operation_id, reason="  ")
    assert no_reason_status == 400
    assert no_reason["error"]["code"] == "RESOLUTION_REASON_REQUIRED"

    succeeded_id = str(uuid.uuid4())
    operations.accept_operation_snapshot(
        operation_id=succeeded_id, request=request,
        accepted={**_accepted(), "worker_head": "e" * 40},
    )
    assert operations.claim_operation(succeeded_id, "owner")
    success = operations.normalize_merge_result(succeeded_id, _merged_raw(), request)
    assert operations.finish_operation(succeeded_id, "owner", success, _accepted())
    refused, refused_status = operations.resolve_operation(succeeded_id, reason="nothing to close")
    assert refused_status == 409
    assert refused["error"]["code"] == "OPERATION_NOT_BLOCKING"


def test_unknown_is_closed_only_by_the_explicit_action(merge_db, monkeypatch):
    """Инвариант 2 на живой записи: UNKNOWN держит блокировку до явного закрытия."""
    import app.merge_operations as operations

    monkeypatch.setattr(
        "app.workspace.inspect_worktree_identity",
        lambda _path: ("task-42/worker", "b" * 40),
    )
    request = operations.normalize_request(name="worker", scope="/scope", target="main")
    operation_id = str(uuid.uuid4())
    operations.accept_operation_snapshot(
        operation_id=operation_id, request=request, accepted=_accepted(),
    )
    assert operations.claim_operation(operation_id, "owner")
    unknown = operations.normalize_merge_result(
        operation_id, _merged_raw(commit_point="unknown"), request,
    )
    assert unknown["operation_state"] == "UNKNOWN"
    assert operations.finish_operation(operation_id, "owner", unknown, _accepted())

    # Ни один другой путь UNKNOWN не закрывает: восстановление сирот его не трогает.
    operations.recover_orphan_operations()
    _blocked, created, _status = operations.accept_operation_snapshot(
        operation_id=str(uuid.uuid4()), request=request,
        accepted={**_accepted(), "worker_head": "e" * 40},
    )
    assert created is False

    operations.resolve_operation(operation_id, reason="checked git: nothing landed in main")
    _after, created_after, _status_after = operations.accept_operation_snapshot(
        operation_id=str(uuid.uuid4()), request=request,
        accepted={**_accepted(), "worker_head": "e" * 40},
    )
    assert created_after is True


def test_resolve_http_route_reports_refusal_and_success(merge_db, monkeypatch):
    from fastapi.testclient import TestClient
    import app.merge_operations as operations
    from app.main import app

    monkeypatch.setattr(
        "app.workspace.inspect_worktree_identity",
        lambda _path: ("task-42/worker", "b" * 40),
    )
    monkeypatch.delenv("DASHBOARD_USER", raising=False)
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    request = operations.normalize_request(name="worker", scope="/scope", target="main")
    operation_id = _blocked_partial(operations, request)

    client = TestClient(app, raise_server_exceptions=False)
    try:
        empty = client.post(f"/api/merge-operations/{operation_id}/resolve", json={})
        ok = client.post(
            f"/api/merge-operations/{operation_id}/resolve",
            json={"reason": "reconciled by hand", "actor": "orchestrator"},
        )
    finally:
        client.close()

    assert empty.status_code == 400
    assert empty.json()["error"]["code"] == "RESOLUTION_REASON_REQUIRED"
    assert ok.status_code == 200
    assert ok.json()["result"]["resolution"]["actor"] == "orchestrator"
