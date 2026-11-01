"""Offline V-1069 regression: task reports do not establish project memory."""

import asyncio
import json
import subprocess
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app import orchestra_layout as layout
from app.prompting import load_worker_memory, refresh_worker_memory


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
    ).stdout


@pytest.fixture
def linked_repo(tmp_path):
    base = tmp_path / "source"
    base.mkdir()
    (base / "source.txt").write_text("source\n")
    git(base, "init", "-q", "-b", "main")
    git(base, "config", "user.name", "test")
    git(base, "config", "user.email", "test@example.invalid")
    git(base, "add", "source.txt")
    git(base, "commit", "-qm", "source")
    worktree = tmp_path / "worker"
    git(base, "worktree", "add", "-qb", "task-V-1069/w", str(worktree))
    reports = worktree / ".orchestra/tasks/V-1069"
    reports.mkdir(parents=True)
    for number in (1, 2):
        (reports / f"report-{number}.md").write_text(f"finding {number}\n")
        git(worktree, "add", ".orchestra/tasks")
        git(worktree, "commit", "-qm", f"report {number}")
    (reports / "pending.md").write_text("uncommitted finding\n")
    return base, worktree


def snapshot(repo):
    return (
        git(repo, "show-ref"), git(repo, "status", "--porcelain=v1"),
        git(repo, "worktree", "list", "--porcelain"), git(repo, "stash", "list"),
        {str(p.relative_to(repo)): p.read_bytes() for p in repo.rglob("*")
         if ".git" not in p.relative_to(repo).parts and p.is_file()},
    )


def refresh(base, worktree):
    return refresh_worker_memory(
        "ROLE\n\n<worker-memory>STALE</worker-memory>", "w", "worker",
        str(base), str(worktree), allow_absent_project=True,
    )


def test_reports_only_linked_branch_is_optional_and_untouched(linked_repo):
    base, worktree = linked_repo
    before = snapshot(base), snapshot(worktree)
    assert refresh(base, worktree) == "ROLE"
    assert refresh(base, base) == "ROLE"
    assert not (base / ".orchestra").exists()
    assert not (worktree / ".orchestra/layout.json").exists()
    assert (snapshot(base), snapshot(worktree)) == before
    assert git(worktree, "rev-list", "--count", "main..HEAD").strip() == "2"


def test_reports_only_base_is_optional_too(linked_repo):
    base, worktree = linked_repo
    reports = base / ".orchestra/tasks"
    reports.mkdir(parents=True)
    (reports / "result.md").write_text("base report\n")
    before = snapshot(base), snapshot(worktree)
    assert refresh(base, worktree) == "ROLE"
    assert refresh(base, base) == "ROLE"
    assert (snapshot(base), snapshot(worktree)) == before


@pytest.mark.parametrize("path", [
    "docs/kb", "docs/tasks", "docs/workers", "docs/archive", "pipelines",
    ".orchestra/workers", ".orchestra/kb", ".orchestra/archive",
    ".orchestra/pipelines", ".orchestra/unknown",
])
@pytest.mark.parametrize("checkout", ["base", "worktree"])
def test_managed_or_unknown_state_still_refuses(linked_repo, path, checkout):
    base, worktree = linked_repo
    target = base if checkout == "base" else worktree
    (target / path).mkdir(parents=True)
    (target / path / "keep.md").write_text("keep this data\n")
    before = snapshot(base), snapshot(worktree)
    with pytest.raises(layout.LayoutMigrationError) as caught:
        refresh(base, worktree)
    assert caught.value.code == "ORCHESTRA_LAYOUT_MISSING"
    assert caught.value.repository == base
    assert (snapshot(base), snapshot(worktree)) == before


@pytest.mark.parametrize("entry", ["layout.json", ".layout-migration.json", "tasks"])
def test_partial_markers_and_tasks_file_are_not_ignored(linked_repo, entry):
    base, worktree = linked_repo
    target = base / ".orchestra"
    target.mkdir()
    (target / entry).write_text("{}")
    before = snapshot(base), snapshot(worktree)
    with pytest.raises(layout.LayoutMigrationError):
        refresh(base, worktree)
    assert (snapshot(base), snapshot(worktree)) == before


def test_broken_managed_link_is_not_absence(linked_repo):
    base, worktree = linked_repo
    (worktree / ".orchestra/workers").symlink_to("missing")
    with pytest.raises(layout.LayoutMigrationError):
        refresh(base, worktree)
    assert (worktree / ".orchestra/workers").is_symlink()


def test_authoritative_layout_guards_are_unchanged(linked_repo):
    base, worktree = linked_repo
    before = snapshot(base), snapshot(worktree)
    with pytest.raises(layout.LayoutMigrationError):
        load_worker_memory("w", "worker", str(base), str(worktree))
    with pytest.raises(layout.LayoutMigrationError):
        layout.require_project_layout(worktree)
    with pytest.raises(layout.LayoutMigrationError) as caught:
        layout.migrate_project_layout(base, repair=True)
    assert caught.value.code == "ORCHESTRA_LAYOUT_MISSING"
    assert (snapshot(base), snapshot(worktree)) == before
    assert not (base / ".orchestra/layout.json").exists()


def test_valid_memory_loads_and_refreshes_without_parent_fallback(linked_repo):
    base, worktree = linked_repo
    workers = worktree / ".orchestra/workers"
    workers.mkdir()
    (workers / "w.md").write_text("personal memory")
    (workers / "worker.md").write_text("role memory")
    (worktree / ".orchestra/layout.json").write_text(json.dumps({
        "schema_version": 1, "layout": ".orchestra", "managed_paths": ["tasks", "workers"],
    }))
    layout.require_project_layout(worktree)
    assert "personal memory" in refresh(base, worktree)
    (workers / "w.md").write_text("updated memory")
    assert "updated memory" in refresh(base, worktree)
    (workers / "w.md").unlink()
    assert "role memory" in refresh(base, worktree)
    (workers / "worker.md").unlink()
    parent_workers = base / ".orchestra/workers"
    parent_workers.mkdir(parents=True)
    (parent_workers / "w.md").write_text("wrong checkout")
    assert refresh(base, worktree) == "ROLE"


@pytest.mark.asyncio
@pytest.mark.parametrize("overlay", [None, ""])
@pytest.mark.parametrize("keyed", [False, True])
@pytest.mark.parametrize("native_id", [None, "native-existing"])
async def test_cold_hydrate_then_send_reaches_native_submit(
    linked_repo, monkeypatch, overlay, keyed, native_id,
):
    from app import db, deps, manager as manager_module
    from app.events import MessageProvenance
    from app.manager import SessionManager
    from app.session import AgentSession

    base, worktree = linked_repo
    db.init_db()
    # The hub copy does not include pipeline manifests. Only template/MCP input
    # boundaries are synthetic; hydration, assembly, memory and send are real.
    monkeypatch.setattr(manager_module, "ROLE_SYSTEM_PROMPT", lambda *_: "ROLE")
    monkeypatch.setattr(manager_module, "get_role", lambda *_: None)
    monkeypatch.setattr(manager_module, "_make_mcp_config", lambda *_a, **_k: {})
    monkeypatch.setattr(manager_module, "prompt_template_hash", lambda *_: "test")
    monkeypatch.setattr("app.session.prompt_template_hash", lambda *_: "test")
    monkeypatch.setattr(AgentSession, "_persist", MagicMock())
    mgr = SessionManager()
    monkeypatch.setattr(mgr, "_role_is_orchestrator", lambda *_: False)
    monkeypatch.setattr(deps, "manager", mgr)
    row = {
        "id": "worker", "name": "w", "scope": str(base), "cwd": str(worktree),
        "model": "claude-sonnet-5-5[1m]", "backend_type": "claude",
        "system_prompt": ("OPERATOR" if overlay is None else "ROLE")
                         + "\n\n<worker-memory>STALE</worker-memory>",
        "prompt_overlay": overlay, "status": "idle", "session_id": native_id,
        "cost_usd": 0, "worktree_path": str(worktree), "branch": "task-V-1069/w",
        "base_branch": "main", "task_id": "V-1069", "is_orchestrator": False,
        "role": "worker", "pipeline": "default", "parent_id": "parent",
        "parent_name": "parent", "owned_dirs": '["source.txt"]', "color": "#fff",
        "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
    }
    db.save_session(row)
    before = snapshot(base), snapshot(worktree)
    session = await mgr.ensure_loaded_by_id("worker")
    assert session is not None
    assert "STALE" not in session.system_prompt
    assert session.prompt_overlay == overlay
    assert session is await mgr.ensure_loaded_by_id("worker")
    backend = SimpleNamespace(send=AsyncMock(), resume_failed=False)
    monkeypatch.setattr(session, "_ensure_backend", AsyncMock(return_value=backend))
    monkeypatch.setattr(session, "_apply_manifest_effort", AsyncMock())
    monkeypatch.setattr(session, "_notify_scope_running", AsyncMock())
    monkeypatch.setattr(session, "_turn_event_loop", AsyncMock())
    monkeypatch.setattr(session, "_log", MagicMock())
    delivery = SimpleNamespace(
        before_submit=AsyncMock(), mark_submitted=AsyncMock(), mark_unknown=AsyncMock(),
    ) if keyed else None
    try:
        # Warm re-injection must re-read absence rather than trusting hydration.
        if native_id:
            session._current_prompt += "\n\n<worker-memory>STALE</worker-memory>"
        await session.send(
            "continue existing task", delivery=delivery,
            provenance=MessageProvenance(origin="platform", senders=("platform",)),
        )
        backend.send.assert_awaited_once()
        outbound = backend.send.await_args.args[0]
        assert outbound.endswith("continue existing task")
        assert "STALE" not in outbound
        if native_id:
            assert ("OPERATOR" if overlay is None else "ROLE") in outbound
        if keyed:
            delivery.before_submit.assert_awaited_once()
            delivery.mark_submitted.assert_awaited_once()
            delivery.mark_unknown.assert_not_awaited()
        for key in ("scope", "cwd", "worktree_path", "branch", "base_branch", "task_id",
                    "parent_id", "parent_name", "session_id"):
            assert getattr(session, key) == row[key]
            assert db.get_session("worker")[key] == row[key]
        assert (snapshot(base), snapshot(worktree)) == before
    finally:
        if session._listen_task:
            session._listen_task.cancel()
            await asyncio.gather(session._listen_task, return_exceptions=True)
