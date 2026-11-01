"""V-1142: the main checkout's plain private folder is ignored despite root negations."""
from __future__ import annotations

import json
import logging
import subprocess
from unittest.mock import AsyncMock

import pytest

from app import orchestra_layout as layout, private_folder

NEGATION = "!.orchestra/\n!.orchestra/**\n*.log\n"


def _git(root, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=check, capture_output=True, text=True,
    ).stdout.strip()


def _repo(root, ignore=NEGATION, managed=True):
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.name", "T")
    _git(root, "config", "user.email", "t@example.invalid")
    (root / ".gitignore").write_text(ignore)
    (root / "src.txt").write_text("x\n")
    if managed:
        (root / ".orchestra" / "kb").mkdir(parents=True)
        (root / ".orchestra" / "kb" / "a.md").write_text("kb\n")
        (root / ".orchestra" / "layout.json").write_text(json.dumps(
            {"schema_version": 1, "layout": ".orchestra", "managed_paths": ["kb"]}))
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    return root


def _write_private(root):
    f = root / ".orchestra" / "private" / "task" / "sample.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("{}\n")


def test_old_behavior_negation_exposes_private(tmp_path):
    repo = _repo(tmp_path / "p")
    _write_private(repo)
    assert "?? .orchestra/private/" in _git(repo, "status", "--short")


def test_main_private_ignored_and_public_tasks_trackable(tmp_path):
    repo = _repo(tmp_path / "p")
    assert private_folder.ensure_main_private(repo) == repo / ".orchestra" / "private"
    _write_private(repo)
    task = repo / ".orchestra" / "tasks" / "V-1" / "report.md"
    task.parent.mkdir(parents=True)
    task.write_text("public\n")
    status = _git(repo, "status", "--short", "--untracked-files=all")
    assert "private" not in status
    assert "tasks/V-1/report.md" in status
    assert _git(repo, "check-ignore", ".orchestra/tasks/V-1/report.md", check=False) == ""
    assert (repo / ".gitignore").read_text() == NEGATION


def test_linked_worker_still_shares_main_folder(tmp_path):
    repo = _repo(tmp_path / "p")
    private_folder.ensure_main_private(repo)
    wt = tmp_path / "w"
    _git(repo, "worktree", "add", "-q", "-b", "w", str(wt))
    private_folder.ensure_private(wt)
    link = wt / ".orchestra" / "private"
    assert link.is_symlink() and link.resolve() == (repo / ".orchestra" / "private").resolve()
    _write_private(wt)
    assert _git(wt, "status", "--short") == ""
    assert _git(repo, "status", "--short") == ""


def test_source_only_and_pre_migration_projects_untouched(tmp_path):
    src = _repo(tmp_path / "s", managed=False)
    assert private_folder.ensure_main_private(src) is None
    assert not (src / ".orchestra").exists()
    # reports only: still source-only
    rep = _repo(tmp_path / "r", managed=False)
    (rep / ".orchestra" / "tasks" / "V-1").mkdir(parents=True)
    (rep / ".orchestra" / "tasks" / "V-1" / "report.md").write_text("r\n")
    assert private_folder.ensure_main_private(rep) is None
    assert not (rep / ".orchestra" / "private").exists()
    # legacy docs/kb without layout.json awaits migration
    old = _repo(tmp_path / "o", managed=False)
    (old / "docs" / "kb").mkdir(parents=True)
    (old / "docs" / "kb" / "a.md").write_text("k\n")
    assert private_folder.ensure_main_private(old) is None
    assert not (old / ".orchestra").exists()
    assert private_folder.ensure_main_private(tmp_path / "missing") is None


def test_tracked_private_and_tracked_ignorefile_preserved(tmp_path, caplog):
    repo = _repo(tmp_path / "t")
    _write_private(repo)
    _git(repo, "add", "-f", ".orchestra/private/task/sample.json")
    _git(repo, "commit", "-qm", "tracked private")
    assert private_folder.ensure_main_private(repo) is None
    assert not (repo / ".orchestra" / ".gitignore").exists()
    (repo / ".orchestra" / "private" / "task" / "sample.json").write_text("{\"a\":1}\n")
    assert "M .orchestra/private/task/sample.json" in _git(repo, "status", "--short")

    other = _repo(tmp_path / "u")
    (other / ".orchestra" / ".gitignore").write_text("# user\n")
    _git(other, "add", "-f", ".orchestra/.gitignore")
    _git(other, "commit", "-qm", "tracked ignore")
    with caplog.at_level(logging.WARNING):
        assert private_folder.ensure_main_private(other) is not None  # no raise
    assert any(r.levelno >= logging.WARNING and str(other) in r.getMessage()
               for r in caplog.records)
    assert (other / ".orchestra" / ".gitignore").read_text() == "# user\n"


def test_existing_untracked_ignore_rules_preserved(tmp_path):
    repo = _repo(tmp_path / "e")
    (repo / ".orchestra" / ".gitignore").write_text("/cache")
    private_folder.ensure_main_private(repo)
    text = (repo / ".orchestra" / ".gitignore").read_text()
    assert text.startswith("/cache\n") and "/private" in text
    private_folder.ensure_main_private(repo)
    assert (repo / ".orchestra" / ".gitignore").read_text() == text


def test_startup_registered_migration_applies_it_and_survives_refusal(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "m")
    res = layout.migrate_registered_projects({"p": repo}, preserve_dirty=True,
                                             live_session_ids=frozenset())
    assert res["p"]["status"] == "already_current"
    _write_private(repo)
    assert _git(repo, "status", "--short") == ""

    bad = _repo(tmp_path / "b")
    monkeypatch.setattr(private_folder, "ensure_private",
                        lambda p: (_ for _ in ()).throw(RuntimeError("boom")))
    res = layout.migrate_registered_projects({"b": bad}, preserve_dirty=True,
                                             live_session_ids=frozenset())
    assert res["b"]["status"] == "already_current"


# --- actual manager entrypoints (provider start stubbed, git/ignore/DB real) ---------------

@pytest.fixture
def mgr(tmp_path, monkeypatch, configured_hub):
    from app import db, manager as mm
    from app.session import AgentSession

    db.init_db()
    monkeypatch.setattr(AgentSession, "start", AsyncMock())
    # Pipeline manifests are not what is under test; keep every other step real.
    monkeypatch.setattr(mm, "get_active_pipeline", lambda *a, **k: "default")
    monkeypatch.setattr(mm.SessionManager, "_role_is_orchestrator", lambda *a, **k: True)
    monkeypatch.setattr(mm, "validate_spawn", lambda *a, **k: None)
    monkeypatch.setattr(mm, "get_role", lambda *a, **k: None)
    monkeypatch.setattr(mm, "_scaffold_role_docs", lambda *a, **k: None)
    monkeypatch.setattr(mm.SessionManager, "assemble_prompt",
                        lambda self, **k: ("prompt", ""))
    monkeypatch.setattr(mm, "prompt_template_hash", lambda *a, **k: "h")
    return mm.SessionManager()


def _assert_private_hidden_public_visible(repo):
    _write_private(repo)
    task = repo / ".orchestra" / "tasks" / "V-1" / "report.md"
    task.parent.mkdir(parents=True, exist_ok=True)
    task.write_text("public\n")
    status = _git(repo, "status", "--short", "--untracked-files=all")
    assert "private" not in status
    assert "tasks/V-1/report.md" in status


@pytest.mark.asyncio
async def test_manager_create_main_session_prepares_private(mgr, tmp_path):
    repo = _repo(tmp_path / "p")
    await mgr.create_session(
        name="main", scope=str(repo), cwd=str(repo), model="hubsol", is_orchestrator=True,
        model_reason="Synthetic model check",
    )
    _assert_private_hidden_public_visible(repo)


@pytest.mark.asyncio
async def test_manager_create_source_only_stays_source_only(mgr, tmp_path):
    repo = _repo(tmp_path / "s", managed=False)
    await mgr.create_session(
        name="main", scope=str(repo), cwd=str(repo), model="hubsol", is_orchestrator=True,
        model_reason="Synthetic model check",
    )
    assert not (repo / ".orchestra").exists()
    assert _git(repo, "status", "--short") == ""


@pytest.mark.asyncio
async def test_manager_db_reload_prepares_private(mgr, tmp_path):
    from app import db

    repo = _repo(tmp_path / "p")
    created = await mgr.create_session(
        name="main", scope=str(repo), cwd=str(repo), model="hubsol", is_orchestrator=True,
        model_reason="Synthetic model check",
    )
    # Simulate a project that was managed before this fix: no ignore metadata yet.
    ignore = repo / ".orchestra" / ".gitignore"
    ignore.unlink(missing_ok=True)
    if (repo / ".orchestra" / "private").exists():
        (repo / ".orchestra" / "private").rmdir()
    mgr.sessions.clear()
    row = next(r for r in db.get_all_sessions(str(repo)) if r["id"] == created.id)
    await mgr._load_from_db(row)
    assert ignore.is_file()
    _assert_private_hidden_public_visible(repo)


@pytest.mark.asyncio
async def test_manager_db_reload_source_only_untouched(mgr, tmp_path):
    from app import db

    repo = _repo(tmp_path / "s", managed=False)
    created = await mgr.create_session(
        name="main", scope=str(repo), cwd=str(repo), model="hubsol", is_orchestrator=True,
        model_reason="Synthetic model check",
    )
    mgr.sessions.clear()
    row = next(r for r in db.get_all_sessions(str(repo)) if r["id"] == created.id)
    await mgr._load_from_db(row)
    assert not (repo / ".orchestra").exists()
