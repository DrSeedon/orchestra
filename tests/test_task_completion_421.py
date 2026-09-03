"""Regression coverage for two-owner merge completion (#421)."""

from contextlib import contextmanager

import pytest


def _task_state():
    from app import tm

    from app.db import init_db

    init_db()
    with tm._conn() as connection:
        tm.ensure_project(connection, "project", scope="/scope")
        task = tm.create_task(
            connection, "project", "Finish task", par_number=42,
            status="in_progress",
        )
        connection.execute(
            "UPDATE tm_tasks SET worker_session_id=? WHERE id=?",
            ("worker-421", task["id"]),
        )
    return task


def _finalization(task, *, outcome="complete"):
    return {
        "project_id": "project",
        "task": {
            "project_id": "project",
            "task_id": task["id"],
            "par_number": 42,
        },
        "commits": {},
        "outcome": outcome,
        "reservation_id": "operation-421",
        "session_id": "worker-421",
    }


@contextmanager
def _shadow_store(tmp_path):
    from app import tm

    with tm.ia_task_store_mode(
        mode="shadow",
        canonical_root=tmp_path / "canonical",
        projection_path=tmp_path / "task.db",
        cutoff="2026-08-30T00:00:00+00:00",
        source_head="source-421",
    ) as store:
        yield store


def test_complete_finalization_updates_canonical_status_and_completion_time(tmp_path):
    from app import tm

    task = _task_state()
    payload = _finalization(task)
    with _shadow_store(tmp_path) as store:
        result = tm.finalize_merge_outcome(payload)
        with tm._conn() as connection:
            legacy = tm.get_task_by_id(connection, task["id"])
        canonical = store.task_get("42", project="project")

    assert result["ok"] is True
    assert legacy["status"] == "done"
    assert legacy["completed_at"]
    assert canonical["status"] == "done"
    assert canonical["completed_at"]


def test_continue_finalization_does_not_close_either_store(tmp_path):
    from app import tm

    task = _task_state()
    payload = _finalization(task, outcome="continue")
    with _shadow_store(tmp_path) as store:
        result = tm.finalize_merge_outcome(payload)
        with tm._conn() as connection:
            legacy = tm.get_task_by_id(connection, task["id"])
        canonical = store.task_get("42", project="project")

    assert result["ok"] is True
    assert legacy["status"] == "in_progress"
    assert canonical["status"] == "in_progress"
    assert canonical["completed_at"] is None


def test_canonical_completion_failure_is_visible_after_git_commit(tmp_path, monkeypatch):
    from app import tm

    task = _task_state()
    payload = _finalization(task)
    with _shadow_store(tmp_path) as store:
        monkeypatch.setattr(
            store,
            "task_update_if_current",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("canonical write unavailable")
            ),
        )
        with pytest.raises(RuntimeError, match="canonical"):
            tm.finalize_merge_outcome(payload)

    assert payload["task_status"]["ok"] is False
    assert "canonical write unavailable" in payload["task_status"]["error"]


def test_canonical_completion_failure_replays_to_both_stores(tmp_path, monkeypatch):
    from app import tm

    task = _task_state()
    payload = _finalization(task)
    with _shadow_store(tmp_path) as store:
        original = store.task_update_if_current
        calls = 0

        def fail_once(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("canonical write unavailable")
            return original(*args, **kwargs)

        monkeypatch.setattr(store, "task_update_if_current", fail_once)
        with pytest.raises(RuntimeError, match="canonical"):
            tm.finalize_merge_outcome(payload)

        with tm._conn() as connection:
            connection.execute(
                "UPDATE tm_tasks SET status='done', completed_at=?, "
                "sync_revision=sync_revision+1 WHERE id=?",
                ("2026-08-30T00:00:01+00:00", task["id"]),
            )
        replayed = tm.finalize_merge_outcome(payload)
        canonical = store.task_get("42", project="project")
        with tm._conn() as connection:
            legacy = tm.get_task_by_id(connection, task["id"])

    assert replayed["ok"] is True
    assert legacy["status"] == "done"
    assert legacy["completed_at"]
    assert canonical["status"] == "done"
    assert canonical["completed_at"]


def test_sync_revision_debt_does_not_fail_completion(tmp_path, monkeypatch):
    from app import tm

    task = _task_state()
    payload = _finalization(task)
    monkeypatch.setattr(
        tm,
        "api_update_task_if_current",
        lambda *_args, **_kwargs: {
            "ok": True,
            "new_status": "done",
            "updated": ["status"],
            "shadow_match": False,
            "projection_debt": {
                "mismatches": {
                    "sync_revision": {"canonical": 2, "legacy": 3},
                },
            },
        },
    )

    with _shadow_store(tmp_path):
        result = tm.finalize_merge_outcome(payload)

    assert result["ok"] is True
    assert payload["task_status"]["ok"] is True


def test_finalization_failure_describes_projection_mismatch(tmp_path, monkeypatch):
    from app import tm

    task = _task_state()
    payload = _finalization(task)
    monkeypatch.setattr(
        tm,
        "api_update_task_if_current",
        lambda *_args, **_kwargs: {
            "ok": True,
            "new_status": "done",
            "updated": ["status"],
            "shadow_match": False,
            "projection_debt": {
                "mismatches": {
                    "status": {"canonical": "in_progress", "legacy": "done"},
                },
            },
        },
    )

    with _shadow_store(tmp_path), pytest.raises(RuntimeError) as raised:
        tm.finalize_merge_outcome(payload)

    detail = str(raised.value)
    assert "status" in detail
    assert "canonical" in detail
    assert "in_progress" in detail
    assert "legacy" in detail
    assert "done" in detail
