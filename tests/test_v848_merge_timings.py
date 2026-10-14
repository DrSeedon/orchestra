import asyncio
import time
import uuid
from types import SimpleNamespace

import pytest


@pytest.fixture
def merge_db(tmp_path, monkeypatch):
    import app.db as db
    import app.merge_operations as operations
    from tests.test_merge_operations import _session_row

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "merge.db")
    db.init_db()
    operations._runner_tasks.clear()
    db.save_session(_session_row())


@pytest.mark.asyncio
async def test_active_merge_conflict_is_rejected_before_snapshot_and_admission(
    merge_db, monkeypatch,
):
    import app.merge_operations as operations
    from tests.test_merge_operations import _accepted

    active_id = str(uuid.uuid4())
    request = operations.normalize_request(name="worker", scope="/scope", target="main")
    operations.accept_operation_snapshot(
        operation_id=active_id, request=request, accepted=_accepted(),
    )
    calls = []

    def slow_snapshot(_session_id):
        calls.append("snapshot")
        time.sleep(0.05)
        return _accepted()

    def slow_admission(*_args):
        calls.append("admission")
        time.sleep(0.05)
        return {
            "target": {"branch": "main", "sha": "target-sha"},
            "oracle": {"source": "none", "required": False},
        }

    monkeypatch.setattr(operations, "_session_snapshot", slow_snapshot)
    monkeypatch.setattr(operations, "_prepare_admission_snapshot", slow_admission)
    started = time.perf_counter()
    result, status = await operations.accept_merge_operation(
        operation_id=str(uuid.uuid4()),
        name="worker",
        scope="/scope",
        target="main",
    )
    elapsed = time.perf_counter() - started
    print(f"active-conflict-preoperation={elapsed:.3f}s calls={calls}")

    assert status == 202
    assert result["operation_id"] == active_id
    assert calls == []


@pytest.mark.asyncio
async def test_busy_worker_is_rejected_without_waiting_for_its_turn():
    from app.routes.sessions import _merge_worker_is_idle

    calls = []

    async def slow_completion_wait():
        calls.append("wait")
        await asyncio.sleep(0.05)
        return False

    session = SimpleNamespace(
        status=SimpleNamespace(value="running"),
        loaded=True,
        wait_for_turn_completion=slow_completion_wait,
    )
    started = time.perf_counter()
    idle = _merge_worker_is_idle(session)
    elapsed = time.perf_counter() - started
    print(f"busy-worker-refusal={elapsed:.3f}s calls={calls}")

    assert idle is False
    assert calls == []


@pytest.mark.asyncio
async def test_busy_worker_is_rejected_before_snapshot_and_operation_creation(
    merge_db, monkeypatch,
):
    import app.merge_operations as operations
    import app.db as db

    with db._conn() as connection:
        connection.execute(
            "UPDATE sessions SET status='running' WHERE id='merge-session'",
        )
    monkeypatch.setattr("app.deps.manager.get", lambda _session_id: None)
    monkeypatch.setattr(
        operations, "_session_snapshot",
        lambda _session_id: pytest.fail("busy admission must not read Git"),
    )
    monkeypatch.setattr(
        operations, "_prepare_admission_snapshot",
        lambda *_args: pytest.fail("busy admission must not prepare acceptance"),
    )

    result, status = await operations.accept_merge_operation(
        operation_id=str(uuid.uuid4()), name="worker", scope="/scope",
    )

    assert status == 409
    assert result["error"]["code"] == "WORKER_BUSY"
    with db._conn() as connection:
        assert connection.execute("SELECT count(*) FROM merge_operations").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_running_worker_that_finishes_within_budget_is_accepted(
    merge_db, monkeypatch,
):
    import app.merge_operations as operations
    from tests.test_merge_operations import _accepted

    status = SimpleNamespace(value="running")
    wait_calls = []

    class Session:
        pass

    session = Session()
    session.status = status

    async def finish_turn():
        wait_calls.append("wait")
        await asyncio.sleep(0.02)
        status.value = "idle"
        return True

    session.wait_for_turn_completion = finish_turn
    monkeypatch.setattr("app.deps.manager.get", lambda _session_id: session)
    monkeypatch.setattr(operations, "_session_snapshot", lambda _sid: _accepted())
    monkeypatch.setattr(
        operations,
        "_prepare_admission_snapshot",
        lambda *_args: {
            "target": {"branch": "main", "sha": "target-sha"},
            "oracle": {"source": "none", "required": False},
        },
    )
    monkeypatch.setattr(operations, "MERGE_BUSY_WAIT_SECONDS", 0.2)
    scheduled = []
    monkeypatch.setattr(operations, "ensure_operation_runner", scheduled.append)

    result, status_code = await operations.accept_merge_operation(
        operation_id=str(uuid.uuid4()), name="worker", scope="/scope", target="main",
    )

    assert status_code == 202
    assert result["operation_state"] == "PENDING"
    assert wait_calls == ["wait"]
    assert scheduled == [result["operation_id"]]


@pytest.mark.asyncio
async def test_running_worker_past_budget_returns_busy_without_snapshot_or_operation(
    merge_db, monkeypatch,
):
    import app.db as db
    import app.merge_operations as operations

    status = SimpleNamespace(value="running")

    class Session:
        pass

    session = Session()
    session.status = status

    async def turn_never_finishes():
        await asyncio.Event().wait()

    session.wait_for_turn_completion = turn_never_finishes
    monkeypatch.setattr("app.deps.manager.get", lambda _session_id: session)
    monkeypatch.setattr(operations, "MERGE_BUSY_WAIT_SECONDS", 0.05)
    monkeypatch.setattr(
        operations, "_session_snapshot",
        lambda _sid: pytest.fail("timed-out worker must not be snapshotted"),
    )
    monkeypatch.setattr(
        operations, "_prepare_admission_snapshot",
        lambda *_args: pytest.fail("timed-out worker must not be admitted"),
    )
    started = time.perf_counter()
    result, status_code = await operations.accept_merge_operation(
        operation_id=str(uuid.uuid4()), name="worker", scope="/scope", target="main",
    )
    elapsed = time.perf_counter() - started

    assert elapsed < 0.5
    assert status_code == 409
    assert result["error"]["code"] == "WORKER_BUSY"
    assert "idle" in result["error"]["message"]
    with db._conn() as connection:
        assert connection.execute("SELECT count(*) FROM merge_operations").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_accepted_operation_exposes_snapshot_admission_and_total_preoperation_time(
    merge_db, monkeypatch,
):
    import app.merge_operations as operations
    from tests.test_merge_operations import _accepted

    def slow_snapshot(_session_id):
        time.sleep(0.01)
        return _accepted()

    def slow_admission(*_args):
        time.sleep(0.01)
        return {
            "target": {"branch": "main", "sha": "target-sha"},
            "oracle": {"source": "none", "required": False},
        }

    monkeypatch.setattr("app.deps.manager.get", lambda _session_id: None)
    monkeypatch.setattr(operations, "_session_snapshot", slow_snapshot)
    monkeypatch.setattr(operations, "_prepare_admission_snapshot", slow_admission)
    monkeypatch.setattr(operations, "ensure_operation_runner", lambda _operation_id: None)
    result, status = await operations.accept_merge_operation(
        operation_id=str(uuid.uuid4()), name="worker", scope="/scope", target="main",
    )

    assert status == 202
    assert result["phase_durations_ms"]["snapshot"] >= 5
    assert result["phase_durations_ms"]["admission"] >= 5
    assert result["phase_durations_ms"]["pre_operation"] >= 15


@pytest.mark.asyncio
async def test_executed_session_merge_reports_git_and_finalization_durations(
    monkeypatch, tmp_path,
):
    import app.routes.sessions as sessions_route
    import app.workspace as workspace
    from app import tm
    from tests.test_task_tracker_integration import (
        _commit_file,
        _init_db,
        _make_git_scope,
        _prepare_merge,
        _save_worker,
    )
    from tests.task_seeds import create_task as seed_task

    _init_db()
    repo = _make_git_scope(monkeypatch, tmp_path)
    scope = str(repo)
    name = "timed-merge-worker"
    with tm._conn() as connection:
        tm.ensure_project(connection, "project", scope=scope)
        task = seed_task(connection, "project", "Timed merge", par_number=848)
    task_ref = tm.public_task_ref(task)
    worktree = workspace.create_worktree(scope, name, task_id=task_ref)
    _save_worker(
        session_id=name, task_id=task_ref, scope=scope,
        worktree_path=worktree.path, branch=worktree.branch,
    )
    tm.bind_task_to_session(scope, name, task_ref)
    head = _commit_file(worktree.path, "timed.txt", "measure merge phases")
    found = _prepare_merge(monkeypatch, session_id=name, scope=scope)
    monkeypatch.setattr(
        "app.ia.merge_receipts.merge_receipt_configured", lambda: False,
    )
    monkeypatch.setattr(
        "app.workspace.merge_worktree_to_main",
        lambda *_args, **_kwargs: {
            "ok": True,
            "commits_merged": 1,
            "branch": found.branch,
            "merged_commits": {
                task_ref: [{"hash": "v848abc", "message": "#848: timed"}],
            },
        },
    )

    result = await sessions_route.execute_merge_session(
        session_id=name,
        expected_name=name,
        expected_scope=scope,
        expected_branch=worktree.branch,
        expected_head=head,
        req={
            "scope": scope,
            "task_outcome": "complete",
            "merge_schema_version": 2,
            "expected_head": head,
        },
    )

    assert result["ok"] is True, result
    assert result["phase_durations_ms"]["git"] >= 0
    assert result["phase_durations_ms"]["finalization"] >= 0


def test_phase_durations_are_stored_in_the_operation_result(merge_db):
    import json

    import app.db as db
    import app.merge_operations as operations
    from tests.test_merge_operations import _accepted, _merged_raw

    operation_id = str(uuid.uuid4())
    request = operations.normalize_request(name="worker", scope="/scope", target="main")
    _pending, created, _status = operations.accept_operation_snapshot(
        operation_id=operation_id,
        request=request,
        accepted={
            **_accepted(),
            "phase_durations_ms": {"snapshot": 3, "admission": 5, "pre_operation": 9},
        },
    )
    assert created is True
    assert operations.claim_operation(operation_id, "owner") is True
    operations.record_phase_duration(operation_id, "acceptance", 11)
    operations.record_phase_duration(operation_id, "test_gate", 13)
    operations.record_phase_duration(operation_id, "mutation_gate", 17)
    operations.record_phase_duration(operation_id, "git", 19)
    operations.record_phase_duration(operation_id, "finalization", 23)
    result = operations.normalize_merge_result(
        operation_id, _merged_raw(), request,
    )
    assert operations.finish_operation(
        operation_id, "owner", result, _accepted(),
    ) is True

    stored = operations.get_operation_result(operation_id)
    phases = stored["phase_durations_ms"]
    assert phases["snapshot"] == 3
    assert phases["admission"] == 5
    assert phases["pre_operation"] == 9
    assert phases["queue"] >= 0
    assert phases["acceptance"] == 11
    assert phases["test_gate"] == 13
    assert phases["mutation_gate"] == 17
    assert phases["git"] == 19
    assert phases["finalization"] == 23
    with db._conn() as connection:
        result_json = connection.execute(
            "SELECT result_json FROM merge_operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()[0]
    assert json.loads(result_json)["phase_durations_ms"] == phases


def test_test_gate_reports_gate_duration_without_inventing_skipped_mutation_time(
    tmp_path, monkeypatch,
):
    from app.merge_test_gate import evaluate_test_gate

    monkeypatch.setattr("app.merge_test_gate.changed_paths", lambda *_a, **_kw: None)
    result = evaluate_test_gate(str(tmp_path), target_ref="main", target_sha="head")

    assert result["status"] == "skipped"
    assert result["phase_durations_ms"]["test_gate"] >= 0
    assert "mutation_gate" not in result["phase_durations_ms"]


def test_test_and_mutation_gate_durations_are_measured_separately(
    tmp_path, monkeypatch,
):
    from app.merge_test_gate import PASSED, evaluate_test_gate

    monkeypatch.setattr("app.merge_test_gate.changed_paths", lambda *_a, **_kw: ["app/x.py"])
    monkeypatch.setattr("app.merge_test_gate.select_tests", lambda *_a, **_kw: ["tests/test_x.py"])
    monkeypatch.setattr("app.merge_test_gate.changed_test_paths", lambda _changed: [])
    monkeypatch.setattr(
        "app.merge_test_gate.changed_source_paths", lambda _changed: ["app/x.py"],
    )
    monkeypatch.setattr("app.merge_test_gate._pytest_interpreter", lambda _worktree: "python")
    monkeypatch.setattr(
        "app.merge_test_gate.run_pytest",
        lambda _worktree, tests: {
            "status": PASSED, "exit_code": 0, "output": "", "tests": tests,
        },
    )
    monkeypatch.setattr(
        "app.merge_test_gate.evaluate_mutation_gate",
        lambda *_a, **_kw: {"status": PASSED, "tests": []},
    )

    result = evaluate_test_gate(str(tmp_path), target_ref="main", target_sha="head")

    assert result["phase_durations_ms"]["test_gate"] >= 0
    assert result["phase_durations_ms"]["mutation_gate"] >= 0
