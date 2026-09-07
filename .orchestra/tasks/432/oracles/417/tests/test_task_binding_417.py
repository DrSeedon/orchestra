"""Regression coverage for split task/session bindings (#417)."""

from datetime import datetime, timezone

import pytest


def _init_db():
    from app.db import init_db

    init_db()


def _seed_project(scope: str = "/scope") -> None:
    from app import tm

    with tm._conn() as connection:
        tm.ensure_project(connection, "project", scope=scope)


def _save_worker(*, session_id: str, task_id: str, branch: str = "") -> None:
    from app.db import save_session

    save_session(
        {
            "id": session_id,
            "name": session_id,
            "scope": "/scope",
            "cwd": "/worktree",
            "model": "claude-sonnet-5[1m]",
            "system_prompt": "",
            "status": "idle",
            "session_id": None,
            "cost_usd": 0.0,
            "worktree_path": "/worktree",
            "branch": branch or f"task-adhoc/{session_id}",
            "base_branch": "main",
            "needs_switch": 0,
            "task_id": task_id,
            "is_orchestrator": False,
            "parent_name": "orchestrator",
            "color": "",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
        }
    )


def test_bind_task_repairs_split_session_binding():
    """A session-side binding must be completed on the task side."""
    from app import tm
    from app.db import get_session

    _init_db()
    _seed_project()
    with tm._conn() as connection:
        task = tm.create_task(connection, "project", "Switch target", par_number=42)
    _save_worker(session_id="split-worker", task_id="42")

    result = tm.bind_task_to_session("/scope", "split-worker", "42")

    assert result["worker_session_id"] == "split-worker"
    with tm._conn() as connection:
        bound = tm.get_task_by_id(connection, task["id"])
    assert bound["worker_session_id"] == "split-worker"
    assert get_session("split-worker")["task_id"] == "42"


@pytest.mark.asyncio
async def test_switch_assignment_binds_session_and_task(monkeypatch):
    """A successful branch switch publishes both durable ownership links."""
    import app.routes.sessions as sessions_route
    from app import tm
    from app.db import get_session
    from app.manager import SessionManager

    _init_db()
    _seed_project()
    with tm._conn() as connection:
        task = tm.create_task(connection, "project", "Switch target", par_number=42)
    _save_worker(session_id="switch-worker", task_id="")
    local_manager = SessionManager()
    found = local_manager.get_by_name("switch-worker", "/scope")
    monkeypatch.setattr(sessions_route, "manager", local_manager)
    monkeypatch.setattr(sessions_route, "_session_base_branch", lambda *_args: "main")
    monkeypatch.setattr(
        sessions_route,
        "_existing_branch_verdict",
        lambda *_args, **_kwargs: {"recreate_from_base": False, "discard_current": False},
    )
    monkeypatch.setattr(
        "app.workspace.switch_worktree_branch",
        lambda _path, branch, **_kwargs: {"ok": True, "branch": branch},
    )

    result = await sessions_route.switch_branch(
        "switch-worker",
        {"scope": "/scope", "task_id": "42", "force": True},
    )

    assert result["ok"] is True
    assert get_session(found.id)["task_id"] == "42"
    with tm._conn() as connection:
        bound = tm.get_task_by_id(connection, task["id"])
    assert bound["worker_session_id"] == found.id


@pytest.mark.asyncio
async def test_switch_assignment_failure_restores_both_binding_sides(monkeypatch):
    """An exception between lifecycle and task writes cannot strand the worker."""
    import app.routes.sessions as sessions_route
    from app import tm
    from app.db import get_session
    from app.manager import SessionManager

    _init_db()
    _seed_project()
    with tm._conn() as connection:
        task = tm.create_task(connection, "project", "Switch target", par_number=42)
    _save_worker(session_id="atomic-switch", task_id="")
    local_manager = SessionManager()
    found = local_manager.get_by_name("atomic-switch", "/scope")
    monkeypatch.setattr(sessions_route, "manager", local_manager)
    monkeypatch.setattr(sessions_route, "_session_base_branch", lambda *_args: "main")
    monkeypatch.setattr(
        sessions_route,
        "_existing_branch_verdict",
        lambda *_args, **_kwargs: {"recreate_from_base": False, "discard_current": False},
    )
    monkeypatch.setattr(
        "app.workspace.switch_worktree_branch",
        lambda _path, branch, **_kwargs: {"ok": True, "branch": branch},
    )
    monkeypatch.setattr(
        tm,
        "api_update_task_if_current",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("injected task binding failure")
        ),
    )

    result = await sessions_route.switch_branch(
        "atomic-switch",
        {"scope": "/scope", "task_id": "42", "force": True},
    )

    assert result["ok"] is False
    assert result["state"] == "task_assignment_failed"
    assert result["rollback"]["ok"] is True
    assert get_session(found.id)["task_id"] == ""
    with tm._conn() as connection:
        row = tm.get_task_by_id(connection, task["id"])
    assert row["worker_session_id"] is None


def test_bind_task_rejects_session_bound_to_another_task():
    """Existing ownership protection must remain loud and specific."""
    from app import tm

    _init_db()
    _seed_project()
    with tm._conn() as connection:
        current = tm.create_task(connection, "project", "Current", par_number=41)
        target = tm.create_task(connection, "project", "Target", par_number=42)
    _save_worker(session_id="conflicting-worker", task_id="41")

    with pytest.raises(ValueError, match="already bound to another task"):
        tm.bind_task_to_session("/scope", "conflicting-worker", "42")

    with tm._conn() as connection:
        assert tm.get_task_by_id(connection, current["id"])["worker_session_id"] is None
        assert tm.get_task_by_id(connection, target["id"])["worker_session_id"] is None


def test_inferred_binding_rejects_owner_changed_before_task_write(monkeypatch):
    """A session rollback after inference must not write a stale task owner."""
    from app import tm

    _init_db()
    _seed_project()
    with tm._conn() as connection:
        task = tm.create_task(connection, "project", "Switch target", par_number=42)
    _save_worker(session_id="stale-owner", task_id="42")
    identity = tm.resolve_scoped_task_identity("/scope", "42")

    def infer_then_rollback(*_args, **_kwargs):
        with tm._conn() as connection:
            connection.execute(
                "UPDATE sessions SET task_id='' WHERE id=?", ("stale-owner",)
            )
        return "stale-owner"

    monkeypatch.setattr(tm, "_infer_task_worker_session", infer_then_rollback)

    with pytest.raises(ValueError, match="session binding changed"):
        tm.api_update_task_if_current(identity, status="in_progress")
    with tm._conn() as connection:
        assert tm.get_task_by_id(connection, task["id"])["worker_session_id"] is None
