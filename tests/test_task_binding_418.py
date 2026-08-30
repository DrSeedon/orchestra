"""Regression coverage for canonical task identity resolution (#418)."""

import pytest


def _init_task_db():
    from app.db import init_db

    init_db()
    from app import tm

    with tm._conn() as connection:
        tm.ensure_project(connection, "project", scope="/scope")
        task = tm.create_task(connection, "project", "Healthy task", par_number=42)
    return task


class _TaskStore:
    canonical_head = "store-head"
    projection_head = "store-head"

    def __init__(self, detail):
        self.detail = detail
        self.updated_identity = None

    def task_get(self, ref, project=""):
        return dict(self.detail)

    def task_update_if_current(self, identity, **_kwargs):
        self.updated_identity = dict(identity)
        return {
            "ok": True,
            "stable_id": identity["stable_id"],
            "canonical_head": self.canonical_head,
            "projection_head": self.projection_head,
            "updated": ["status"],
            "par": "42",
            "new_status": "in_progress",
            "sync_revision": 1,
        }


def test_missing_stable_id_is_loud_and_names_task_identity():
    from app import tm

    task = _init_task_db()
    identity = {
        "id": task["id"],
        "project_id": "project",
        "par_number": 42,
        "sync_revision": 0,
    }
    store = _TaskStore({
        "project": "project",
        "par": "42",
        "canonical_head": "store-head",
    })

    with tm.ia_process_task_store_mode(store=store, mode="canonical"):
        with pytest.raises(ValueError, match="stable_id.*project.*42"):
            tm.api_update_task_if_current(identity, status="in_progress")
    assert store.updated_identity is None


def test_healthy_session_has_same_canonical_identity_failure():
    from app import tm
    from app.db import save_session

    task = _init_task_db()
    save_session({
        "id": "healthy-worker",
        "name": "healthy-worker",
        "scope": "/scope",
        "cwd": "/worktree",
        "model": "claude-sonnet-5[1m]",
        "system_prompt": "",
        "status": "idle",
        "session_id": None,
        "cost_usd": 0.0,
        "worktree_path": "/worktree",
        "branch": "task-42/healthy-worker",
        "base_branch": "main",
        "needs_switch": 0,
        "task_id": "42",
        "is_orchestrator": False,
        "parent_name": "orchestrator",
        "color": "",
        "created_at": "2026-08-30T00:00:00+00:00",
        "finished_at": None,
    })
    identity = {
        "id": task["id"],
        "project_id": "project",
        "par_number": 42,
        "sync_revision": 0,
    }
    store = _TaskStore({"project": "project", "par": "42"})

    with tm.ia_process_task_store_mode(store=store, mode="canonical"):
        with pytest.raises(ValueError, match="stable_id.*project.*42"):
            tm.api_update_task_if_current(identity, status="in_progress")


def test_two_readers_must_agree_on_project_and_display_identity():
    from app import tm

    task = _init_task_db()
    identity = {
        "id": task["id"],
        "project_id": "project",
        "par_number": 42,
        "sync_revision": 0,
    }
    mismatched = _TaskStore({
        "project": "project-15ebb64920a9",
        "par": "42",
        "stable_id": "canonical-42",
        "canonical_head": "store-head",
    })
    with tm.ia_process_task_store_mode(store=mismatched, mode="canonical"):
        with pytest.raises(ValueError, match="identity mismatch.*project.*42"):
            tm.api_update_task_if_current(identity, status="in_progress")
    assert mismatched.updated_identity is None

    matching = _TaskStore({
        "project": "project",
        "par": "42",
        "stable_id": "canonical-42",
        "canonical_head": "store-head",
    })
    with tm.ia_process_task_store_mode(store=matching, mode="canonical"):
        result = tm.api_update_task_if_current(identity, status="in_progress")
    assert result["ok"] is True
    assert matching.updated_identity == {
        "id": task["id"],
        "project_id": "project",
        "par_number": 42,
        "sync_revision": 0,
        "stable_id": "canonical-42",
    }


def test_canonical_reader_failure_is_not_downgraded_to_legacy_identity():
    from app import tm

    _init_task_db()

    class BrokenReader(_TaskStore):
        def task_get(self, ref, project=""):
            raise RuntimeError("canonical catalog unavailable")

    store = BrokenReader({})
    with tm.ia_process_task_store_mode(store=store, mode="canonical"):
        with pytest.raises(RuntimeError, match="canonical catalog unavailable"):
            tm.resolve_scoped_task_identity("/scope", "42")
