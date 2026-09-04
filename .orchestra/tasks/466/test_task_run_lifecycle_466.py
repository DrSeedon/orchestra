"""Independent lifecycle seams for the frozen #466 T2 oracle."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest


def _isolated(tmp_path, monkeypatch):
    import app.db as db
    from app import tm

    path = tmp_path / "lifecycle-466.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(path))
    db.init_db()
    monkeypatch.setattr(tm, "_ia_context", lambda: None)
    with tm._conn() as connection:
        tm.ensure_project(connection, "project", scope="/scope")
    return db, tm


def _save_worker(db, session_id: str, task_id: str):
    db.save_session(
        {
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
            "branch": f"task-{task_id or 'adhoc'}/{session_id}",
            "base_branch": "main",
            "needs_switch": 0,
            "task_id": task_id,
            "is_orchestrator": False,
            "parent_name": "orchestrator",
            "color": "",
            "template_hash": "prompt-lifecycle-466",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
        }
    )


def _create_task(tm, par_number: int):
    with tm._conn() as connection:
        return tm.create_task(
            connection, "project", f"Task {par_number}", par_number=par_number,
        )


def _task_runs(db, session_id: str):
    with db._conn() as connection:
        return [
            dict(row) for row in connection.execute(
                "SELECT * FROM review_receipts "
                "WHERE subject_kind='task_run' AND session_id=? ORDER BY requested_at",
                (session_id,),
            ).fetchall()
        ]


def _seed_raw_task_run(db, *, session_id: str, task_id: str):
    additions = {
        "task_stable_id": "TEXT NOT NULL DEFAULT ''",
        "task_snapshot_ref": "TEXT NOT NULL DEFAULT ''",
        "prompt_template_start": "TEXT NOT NULL DEFAULT ''",
        "prompt_template_end": "TEXT NOT NULL DEFAULT ''",
        "terminal_operation_id": "TEXT NOT NULL DEFAULT ''",
    }
    with db._conn() as connection:
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
                   mode,round,job_id,usage_event_id,requested_at,status,
                   failure_code,artifact_sha256,verdict_value,recovery_source,
                   author_outcome,outcome_source,outcome_evidence_ref,
                   notification_event_id,subject_kind,target_sha,worker_head,
                   production_snapshot_sha256,production_paths_json,
                   coverage_outcome,policy_ref,decision_actor,task_stable_id,
                   task_snapshot_ref,prompt_template_start,prompt_template_end,
                   terminal_operation_id)
               VALUES (
                   ?,2,'','','unknown',?,?,? ,?,'canonical','','task_run',NULL,
                   '','','2026-09-03T00:00:00+00:00','requested','','','','',
                   'unknown','unknown','','','task_run','','','','[]','unknown','','',
                   '46646646-6466-4466-8466-466466466466',
                   'orch://project/project/tasks/466@sha256:current',
                   'prompt-lifecycle-466','','')""",
            (f"task-run:{session_id}:{task_id}", session_id, session_id, "/scope", task_id),
        )


def _reserve_handoff(tm, current, following, *, operation_id: str, session_id: str):
    now = datetime.now(timezone.utc).isoformat()
    with tm._conn() as connection:
        connection.execute(
            "INSERT INTO tm_task_reservations(task_id,operation_id,kind,session_id,created_at) "
            "VALUES(?,?,?,?,?)",
            (current["id"], operation_id, "complete", session_id, now),
        )
        connection.execute(
            "INSERT INTO tm_task_reservations(task_id,operation_id,kind,session_id,created_at) "
            "VALUES(?,?,?,?,?)",
            (following["id"], operation_id, "assign", session_id, now),
        )


def _handoff_payload(current, following, *, operation_id: str, session_id: str):
    return {
        "project_id": current["project_id"],
        "task": {
            "project_id": current["project_id"],
            "task_id": current["id"],
            "par_number": current["par_number"],
        },
        "next_task": {
            "project_id": following["project_id"],
            "task_id": following["id"],
            "par_number": following["par_number"],
        },
        "commits": {},
        "outcome": "complete",
        "reservation_id": operation_id,
        "operation_id": operation_id,
        "session_id": session_id,
    }


def test_t2_taskless_binding_opens_run_and_archive_interrupts_it(tmp_path, monkeypatch):
    db, tm = _isolated(tmp_path, monkeypatch)
    task = _create_task(tm, 466)
    _save_worker(db, "taskless-466", "")

    tm.bind_task_to_session("/scope", "taskless-466", "466")
    runs = _task_runs(db, "taskless-466")
    assert len(runs) == 1, (
        "T2 missing behavior: binding a taskless worker opened no task_run receipt"
    )
    assert runs[0]["status"] == "requested"

    db.archive_session("taskless-466")
    ended = _task_runs(db, "taskless-466")[0]
    assert ended["status"] == "interrupted"
    assert ended["completed_at"]
    assert ended["failure_code"] == "session_archived"
    with tm._conn() as connection:
        rebound = tm.get_task_by_id(connection, task["id"])
    assert rebound["status"] == "new"


def test_t2_run_insert_failure_aborts_taskless_binding(tmp_path, monkeypatch):
    db, tm = _isolated(tmp_path, monkeypatch)
    task = _create_task(tm, 466)
    _save_worker(db, "atomic-466", "")

    def fail_open(*_args, **_kwargs):
        raise RuntimeError("receipt insert failed")

    monkeypatch.setattr(db, "task_run_receipt_open", fail_open, raising=False)
    monkeypatch.setattr(tm, "task_run_receipt_open", fail_open, raising=False)
    failure = None
    try:
        tm.bind_task_to_session("/scope", "atomic-466", "466")
    except RuntimeError as error:
        failure = error
    assert failure is not None and "receipt insert failed" in str(failure), (
        "T2 taskless atomicity missing behavior: receipt failure did not abort binding"
    )

    with tm._conn() as connection:
        unchanged = tm.get_task_by_id(connection, task["id"])
    assert unchanged["status"] == "new"
    assert unchanged["worker_session_id"] is None
    assert db.get_session("atomic-466")["task_id"] == ""


def test_t2_explicit_task_cancellation_closes_open_run(tmp_path, monkeypatch):
    db, tm = _isolated(tmp_path, monkeypatch)
    task = _create_task(tm, 466)
    _save_worker(db, "cancel-466", "466")
    with tm._conn() as connection:
        connection.execute(
            "UPDATE tm_tasks SET worker_session_id=?,status='in_progress' WHERE id=?",
            ("cancel-466", task["id"]),
        )
    _seed_raw_task_run(db, session_id="cancel-466", task_id="466")

    result = tm.api_update_task("466", status="cancelled", project="project")
    assert result["new_status"] == "cancelled"
    run = _task_runs(db, "cancel-466")[0]
    assert run["status"] == "interrupted", (
        "T2 missing behavior: explicit task cancellation leaves task_run open"
    )
    assert run["completed_at"]
    assert run["failure_code"] == "task_cancelled"


def test_t2_compare_and_swap_cancellation_closes_open_run(tmp_path, monkeypatch):
    db, tm = _isolated(tmp_path, monkeypatch)
    task = _create_task(tm, 466)
    _save_worker(db, "cancel-cas-466", "466")
    with tm._conn() as connection:
        connection.execute(
            "UPDATE tm_tasks SET worker_session_id=?,status='in_progress' WHERE id=?",
            ("cancel-cas-466", task["id"]),
        )
        current = tm.get_task_by_id(connection, task["id"])
    _seed_raw_task_run(db, session_id="cancel-cas-466", task_id="466")
    identity = {
        "id": current["id"],
        "project_id": current["project_id"],
        "par_number": current["par_number"],
        "sync_revision": current["sync_revision"],
    }

    result = tm.api_update_task_if_current(identity, status="cancelled")
    assert result["new_status"] == "cancelled"
    run = _task_runs(db, "cancel-cas-466")[0]
    assert run["status"] == "interrupted", (
        "T2 CAS cancellation missing behavior: api_update_task_if_current left run open"
    )
    assert run["completed_at"]
    assert run["failure_code"] == "task_cancelled"


def test_t2_startup_adopts_inflight_task_without_inventing_acceptance(tmp_path, monkeypatch):
    db, tm = _isolated(tmp_path, monkeypatch)
    task = _create_task(tm, 466)
    _save_worker(db, "legacy-inflight-466", "466")
    with tm._conn() as connection:
        connection.execute(
            "UPDATE tm_tasks SET worker_session_id=?,status='in_progress' WHERE id=?",
            ("legacy-inflight-466", task["id"]),
        )
    completed = _create_task(tm, 467)
    _save_worker(db, "legacy-completed-466", "467")
    with tm._conn() as connection:
        connection.execute(
            "UPDATE tm_tasks SET worker_session_id=?,status='done',completed_at=? WHERE id=?",
            (
                "legacy-completed-466",
                "2026-09-02T00:00:00+00:00",
                completed["id"],
            ),
        )

    adoption_started = datetime.now(timezone.utc)
    db.init_db()
    adoption_finished = datetime.now(timezone.utc)
    db.init_db()

    runs = _task_runs(db, "legacy-inflight-466")
    assert len(runs) == 1, (
        "T2 missing behavior: startup did not adopt an already-bound in-flight task"
    )
    run = runs[0]
    assert run["task_source"] == "legacy_inflight"
    assert run["task_snapshot_ref"] == ""
    assert run["prompt_template_start"] == ""
    assert run["status"] == "requested"
    requested_at = datetime.fromisoformat(run["requested_at"])
    assert adoption_started <= requested_at <= adoption_finished
    assert len(_task_runs(db, "legacy-inflight-466")) == 1
    assert _task_runs(db, "legacy-completed-466") == []


@pytest.mark.asyncio
async def test_t2_explicit_switch_receipt_failure_restores_assignment(tmp_path, monkeypatch):
    db, tm = _isolated(tmp_path, monkeypatch)
    import app.routes.sessions as sessions_route
    from app.manager import SessionManager

    task = _create_task(tm, 466)
    _save_worker(db, "switch-atomic-466", "")
    local_manager = SessionManager()
    found = local_manager.get_by_name("switch-atomic-466", "/scope")
    assert found is not None
    old_branch = found.branch
    monkeypatch.setattr(sessions_route, "manager", local_manager)
    monkeypatch.setattr(sessions_route, "_session_base_branch", lambda *_args: "main")
    monkeypatch.setattr(
        sessions_route,
        "_existing_branch_verdict",
        lambda *_args, **_kwargs: {"recreate_from_base": False, "discard_current": False},
    )
    monkeypatch.setattr(
        "app.workspace.switch_worktree_branch",
        lambda _path, branch, *_args, **_kwargs: {"ok": True, "branch": branch},
    )

    def fail_open(*_args, **_kwargs):
        raise RuntimeError("switch receipt insert failed")

    monkeypatch.setattr(db, "task_run_receipt_open", fail_open, raising=False)
    monkeypatch.setattr(tm, "task_run_receipt_open", fail_open, raising=False)
    result = await sessions_route.switch_branch(
        "switch-atomic-466",
        {"scope": "/scope", "task_id": "466", "force": True},
    )

    assert result.get("ok") is False, (
        "T2 explicit-switch atomicity missing behavior: receipt failure returned success"
    )
    restored = db.get_session("switch-atomic-466")
    assert restored["task_id"] == ""
    assert restored["branch"] == old_branch
    with tm._conn() as connection:
        unchanged = tm.get_task_by_id(connection, task["id"])
    assert unchanged["status"] == "new"
    assert unchanged["worker_session_id"] is None


def test_t2_task_run_open_retry_and_same_snapshot_reopen_are_distinct(
    tmp_path, monkeypatch,
):
    db, tm = _isolated(tmp_path, monkeypatch)
    task = _create_task(tm, 466)
    _save_worker(db, "reopen-466", "466")
    with tm._conn() as connection:
        connection.execute(
            "UPDATE tm_tasks SET worker_session_id=?,status='in_progress' WHERE id=?",
            ("reopen-466", task["id"]),
        )
    opener = getattr(db, "task_run_receipt_open", None)
    assert callable(opener), (
        "T2 retry-reopen missing behavior: task_run_receipt_open API is absent"
    )
    params = {
        "session_id": "reopen-466",
        "worker_name": "reopen-466",
        "scope": "/scope",
        "task_id": "466",
        "task_stable_id": "46646646-6466-4466-8466-466466466466",
        "task_snapshot_ref": "orch://project/project/tasks/466@sha256:same",
        "prompt_template_start": "prompt-lifecycle-466",
    }
    first = opener(**params)
    replay = opener(**params)
    assert replay["receipt_id"] == first["receipt_id"]
    assert len(_task_runs(db, "reopen-466")) == 1

    finisher = getattr(db, "task_run_receipt_finish", None)
    assert callable(finisher), (
        "T2 retry-reopen missing behavior: task_run_receipt_finish API is absent"
    )
    finisher(
        session_id="reopen-466",
        task_id="466",
        status="interrupted",
        prompt_template_end="prompt-lifecycle-466",
        failure_code="binding_released",
    )
    reopened = opener(**params)
    assert reopened["receipt_id"] != first["receipt_id"]
    runs = _task_runs(db, "reopen-466")
    assert len(runs) == 2
    assert runs[0]["status"] == "interrupted"
    assert runs[1]["status"] == "requested"


def test_t2_strict_handoff_receipt_failure_stays_partial(tmp_path, monkeypatch):
    db, tm = _isolated(tmp_path, monkeypatch)
    current = _create_task(tm, 466)
    following = _create_task(tm, 467)
    _save_worker(db, "handoff-failure-466", "466")
    with tm._conn() as connection:
        connection.execute(
            "UPDATE tm_tasks SET worker_session_id=?,status='in_progress' WHERE id=?",
            ("handoff-failure-466", current["id"]),
        )
    _seed_raw_task_run(db, session_id="handoff-failure-466", task_id="466")
    _reserve_handoff(
        tm, current, following,
        operation_id="handoff-failure-operation-466",
        session_id="handoff-failure-466",
    )

    def fail_open(*_args, **_kwargs):
        raise RuntimeError("handoff receipt insert failed")

    monkeypatch.setattr(db, "task_run_receipt_open", fail_open, raising=False)
    monkeypatch.setattr(tm, "task_run_receipt_open", fail_open, raising=False)
    failure = None
    try:
        tm.finalize_merge_outcome(
            _handoff_payload(
                current,
                following,
                operation_id="handoff-failure-operation-466",
                session_id="handoff-failure-466",
            )
        )
    except RuntimeError as error:
        failure = error

    assert failure is not None and "handoff receipt insert failed" in str(failure), (
        "T2 strict-handoff atomicity missing behavior: receipt failure claimed success"
    )
    with tm._conn() as connection:
        next_row = tm.get_task_by_id(connection, following["id"])
    assert next_row["status"] == "new"
    assert next_row["worker_session_id"] is None


def test_t2_complete_then_next_task_closes_and_opens_distinct_runs(tmp_path, monkeypatch):
    db, tm = _isolated(tmp_path, monkeypatch)
    current = _create_task(tm, 466)
    following = _create_task(tm, 467)
    _save_worker(db, "handoff-466", "466")
    with tm._conn() as connection:
        connection.execute(
            "UPDATE tm_tasks SET worker_session_id=?,status='in_progress' WHERE id=?",
            ("handoff-466", current["id"]),
        )
    _seed_raw_task_run(db, session_id="handoff-466", task_id="466")
    _reserve_handoff(
        tm, current, following,
        operation_id="handoff-operation-466", session_id="handoff-466",
    )
    real_open = getattr(db, "task_run_receipt_open", None)
    opened_task_ids = []

    def observe_open(*args, **kwargs):
        opened_task_ids.append(str(kwargs.get("task_id") or ""))
        if real_open is not None:
            return real_open(*args, **kwargs)
        return {"receipt_id": "unpersisted-current-baseline"}

    monkeypatch.setattr(db, "task_run_receipt_open", observe_open, raising=False)
    monkeypatch.setattr(tm, "task_run_receipt_open", observe_open, raising=False)
    tm.finalize_merge_outcome(
        _handoff_payload(
            current,
            following,
            operation_id="handoff-operation-466",
            session_id="handoff-466",
        )
    )
    assert opened_task_ids == ["467"], (
        "T2 handoff wiring missing behavior: next-task finalization did not open its run"
    )
    runs = _task_runs(db, "handoff-466")
    assert len(runs) == 2, (
        "T2 missing behavior: task handoff did not preserve two distinct run intervals"
    )
    assert runs[0]["task_id"] == "466" and runs[0]["status"] == "completed"
    assert runs[0]["terminal_operation_id"] == "handoff-operation-466"
    assert runs[1]["task_id"] == "467" and runs[1]["status"] == "requested"
    assert runs[1]["completed_at"] is None
