"""Ownership uses the worker checkout, independently of its parent routing scope."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
    ).stdout


def init_repo(repo):
    repo.mkdir(parents=True)
    (repo / "source.txt").write_text("synthetic source\n")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Synthetic V1151")
    git(repo, "config", "user.email", "v1151@example.invalid")
    commit(repo)


def commit(repo):
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "synthetic snapshot")


def managed_memory(repo, text):
    workers = repo / ".orchestra/workers"
    workers.mkdir(parents=True, exist_ok=True)
    (workers / "w.md").write_text(text)
    (repo / ".orchestra/layout.json").write_text(json.dumps({
        "schema_version": 1, "layout": ".orchestra", "managed_paths": ["workers"],
    }))


def snapshot(repo):
    common = Path(git(repo, "rev-parse", "--git-common-dir").strip())
    if not common.is_absolute():
        common = repo / common
    exclude = common / "info/exclude"
    return (
        git(repo, "show-ref"), git(repo, "status", "--porcelain=v1"),
        git(repo, "worktree", "list", "--porcelain"), git(repo, "stash", "list"),
        {str(p.relative_to(repo)): ("link", str(p.readlink())) if p.is_symlink()
         else ("file", p.read_bytes()) if p.is_file() else ("directory",)
         for p in repo.rglob("*") if ".git" not in p.relative_to(repo).parts},
        exclude.read_bytes() if exclude.exists() else None,
    )


def durable_state(db):
    with db._conn() as connection:
        return {table: [dict(row) for row in connection.execute(f"SELECT * FROM {table}")]
                for table in ("sessions", "tm_tasks", "tm_task_reservations")}


@pytest.fixture
def env(tmp_path, monkeypatch):
    from app import db, manager as mm, mcp_stdio as m
    from app.main import global_exception_handler
    from app.routes import sessions as routes
    from app.session import AgentSession

    db.init_db()
    parent = tmp_path / "parent"
    init_repo(parent)
    managed_memory(parent, "FOREIGN PARENT MEMORY")
    (parent / ".gitignore").write_text("source/\n")
    commit(parent)
    repo = parent / "source"
    init_repo(repo)
    # Ordinary source skills are not managed Orchestra state.
    (repo / "skills").mkdir()
    (repo / "skills/SKILL.md").write_text("synthetic source skill\n")
    commit(repo)
    mgr = mm.SessionManager()
    monkeypatch.setattr(routes, "manager", mgr)
    monkeypatch.setattr(m, "SCOPE", str(parent))
    start = AsyncMock(side_effect=AssertionError("ownership must not start a provider"))
    monkeypatch.setattr(AgentSession, "start", start)
    app = FastAPI()
    app.include_router(routes.router)
    app.add_exception_handler(Exception, global_exception_handler)

    async def request(dirs):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test.invalid",
        ) as client:
            return await client.post("/api/sessions/w/owned-dirs", json={
                "scope": str(parent), "owned_dirs": dirs,
            })

    async def api(method, path, **kwargs):
        assert (method, path) == ("POST", "/api/sessions/w/owned-dirs")
        response = await request(kwargs["json"]["owned_dirs"])
        if response.status_code >= 400:
            raise m._response_error(method, path, response, response.json(), "synthetic")
        return response.json()

    monkeypatch.setattr(m, "_api", api)

    def worker(loaded, worktree=False):
        checkout = repo
        if worktree:
            checkout = tmp_path / "worker"
            git(repo, "worktree", "add", "-qb", "task-V-1151/w", str(checkout))
        overlay = "\n\nKEEP TASK" + mm.ownership_block(["old"])
        session = AgentSession(
            id="synthetic-w", name="w", scope=str(parent), cwd=str(checkout),
            worktree_path=str(checkout) if worktree else None,
            branch="task-V-1151/w" if worktree else "", model="hubsol",
            role="worker", backend_type="hub", task_id="V-1151", owned_dirs=["old"],
            system_prompt="KEEP ROLE" + overlay + "\n\n<worker-memory>STALE</worker-memory>",
            prompt_overlay=overlay, color="#818cf8",
        )
        session._current_prompt = session.system_prompt
        session._prompt_injected = True
        db.save_session(session._to_db_dict())
        if loaded:
            mgr.sessions[session.id] = session
        else:
            session = mgr.get_by_name("w", str(parent))
            assert not session.loaded
        return session, checkout

    yield SimpleNamespace(
        db=db, parent=parent, repo=repo, mgr=mgr, m=m, request=request,
        worker=worker, start=start,
    )
    start.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded", [False, True], ids=["detached", "loaded"])
@pytest.mark.parametrize("worktree", [False, True], ids=["cwd", "linked"])
@pytest.mark.parametrize("reports", [False, True], ids=["source", "reports"])
@pytest.mark.parametrize("parent_layout", [False, True], ids=["parent-missing", "parent-current"])
async def test_source_ownership_persists_without_parent_memory(
    env, loaded, worktree, reports, parent_layout,
):
    if reports:
        target = env.repo / ".orchestra/tasks/V-1151/report.md"
        target.parent.mkdir(parents=True)
        target.write_text("synthetic report\n")
        commit(env.repo)
    if not parent_layout:
        (env.parent / ".orchestra/layout.json").unlink()
    session, checkout = env.worker(loaded, worktree)
    before = snapshot(env.parent), snapshot(checkout)
    old = durable_state(env.db)
    for dirs in (["source.txt/", "skills"], []):
        await env.m.set_worker_owned_dirs("w", json.dumps(dirs))
        expected = ["source.txt", "skills"] if dirs else []
        row = env.db.get_session_by_name("w", str(env.parent))
        assert json.loads(row["owned_dirs"] or "[]") == expected
        prompt = row["system_prompt"]
        assert "KEEP ROLE" in prompt and "KEEP TASK" in prompt
        assert "FOREIGN" not in prompt and "STALE" not in prompt
        assert "<worker-memory>" not in prompt
        assert "- old/" not in prompt
        assert ("## Directory ownership" in prompt) == bool(dirs)
        assert row["prompt_overlay"].count("## Directory ownership") == bool(dirs)
        for area in expected:
            assert f"- {area}/" in prompt and f"- {area}/" in row["prompt_overlay"]
        if loaded:
            assert session.system_prompt == session._current_prompt == prompt
            assert session.owned_dirs == expected and not session._prompt_injected
        after = durable_state(env.db)
        for key in old["sessions"][0]:
            if key not in {"owned_dirs", "system_prompt", "prompt_overlay"}:
                assert after["sessions"][0][key] == old["sessions"][0][key], key
        assert after["tm_tasks"] == old["tm_tasks"]
        assert after["tm_task_reservations"] == old["tm_task_reservations"]
    assert (snapshot(env.parent), snapshot(checkout)) == before
    assert not (checkout / ".orchestra/layout.json").exists()
    assert not (checkout / ".orchestra/private").exists()
    assert not (checkout / ".orchestra/.gitignore").exists()
    if not reports:
        assert not (checkout / ".orchestra").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded", [False, True], ids=["detached", "loaded"])
@pytest.mark.parametrize("worktree", [False, True], ids=["cwd", "linked"])
async def test_managed_ownership_refreshes_own_memory(env, loaded, worktree):
    managed_memory(env.repo, "OWN MEMORY")
    commit(env.repo)
    session, checkout = env.worker(loaded, worktree)
    (checkout / ".orchestra/workers/w.md").write_text("UPDATED OWN MEMORY")
    before = snapshot(env.parent), snapshot(checkout)
    response = await env.request(["source.txt"])
    assert response.status_code == 200, response.text
    row = env.db.get_session_by_name("w", str(env.parent))
    assert "UPDATED OWN MEMORY" in row["system_prompt"]
    assert "FOREIGN" not in row["system_prompt"] and "STALE" not in row["system_prompt"]
    assert (snapshot(env.parent), snapshot(checkout)) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded", [False, True], ids=["detached", "loaded"])
@pytest.mark.parametrize("worktree", [False, True], ids=["cwd", "linked"])
@pytest.mark.parametrize("path", [
    ".orchestra/workers/w.md", "docs/workers/w.md",
    ".orchestra/.layout-migration.json", ".orchestra/unknown/keep.md",
    ".orchestra/layout.json/broken", ".orchestra/workers",
])
async def test_own_missing_or_damaged_state_refuses_atomically(env, loaded, worktree, path):
    target = env.repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    if path == ".orchestra/workers":
        target.symlink_to("missing-workers")
    else:
        target.write_text("synthetic state\n")
    commit(env.repo)
    session, checkout = env.worker(loaded, worktree)
    before = snapshot(env.parent), snapshot(checkout), durable_state(env.db)
    live_before = (session.system_prompt, session.prompt_overlay, session._current_prompt,
                   session.owned_dirs[:], session._prompt_injected)
    response = await env.request(["source.txt"])
    assert response.status_code == 500, response.text
    error = response.json()["error"]
    assert "ORCHESTRA_LAYOUT_MISSING" in error
    # LayoutMigrationError names the owning main checkout for repair, including
    # errors raised while inspecting a linked worker. It must never name scope.
    assert f"repository={env.repo}; repair:" in error
    assert (snapshot(env.parent), snapshot(checkout), durable_state(env.db)) == before
    assert (session.system_prompt, session.prompt_overlay, session._current_prompt,
            session.owned_dirs, session._prompt_injected) == live_before


def reports_with_private(env, loaded, location):
    """Reported shape: an independent reports-only base and an ordinary private dir."""
    reports = env.repo / ".orchestra/tasks/V-1151"
    reports.mkdir(parents=True)
    (reports / "report.md").write_text("synthetic report\n")
    (env.repo / ".gitignore").write_text("# Synthetic existing rules\n/.orchestra/private\n")
    commit(env.repo)
    session, checkout = env.worker(loaded, location != "main")
    roots = {"worker": [checkout], "base": [env.repo],
             "both": [env.repo, checkout], "main": [env.repo]}[location]
    for root in roots:
        private = root / ".orchestra/private"
        private.mkdir()
        (private / "synthetic.bin").write_bytes(b"synthetic private fixture\x00\xff")
        (private / "source-link").symlink_to("../../source.txt")
    return session, checkout


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded", [False, True], ids=["detached", "loaded"])
@pytest.mark.parametrize("location", ["worker", "base", "both", "main"])
async def test_private_artifact_ownership_updates_without_layout(env, monkeypatch, loaded, location):
    from app import orchestra_layout as layout

    session, checkout = reports_with_private(env, loaded, location)
    if location != "main":
        assert session.worktree_path == session.cwd == str(checkout)
        assert git(checkout, "rev-parse", "--show-toplevel").strip() == str(checkout)
        assert git(checkout, "rev-parse", "--git-common-dir").strip() == str(env.repo / ".git")
    if location == "worker":
        # Exact new reported-path control: no layout, base has tasks only;
        # linked checkout has exactly two ordinary directories, tasks and private.
        assert {p.name for p in (env.repo / ".orchestra").iterdir()} == {"tasks"}
        assert {p.name for p in (checkout / ".orchestra").iterdir()} == {"tasks", "private"}
        assert not (checkout / ".orchestra/private").is_symlink()
    migrate = Mock(side_effect=AssertionError("ownership must not migrate the source project"))
    monkeypatch.setattr(layout, "migrate_project_layout", migrate)
    before = snapshot(env.parent), snapshot(checkout)
    original = durable_state(env.db)
    for dirs in (["source.txt", "skills"], []):
        # _api raises real ApiToolError for HTTP500; do not suppress it or rely
        # on English success prose. Assert the actual stored and active outcome.
        await env.m.set_worker_owned_dirs("w", json.dumps(dirs))
        row = env.db.get_session_by_name("w", str(env.parent))
        assert json.loads(row["owned_dirs"] or "[]") == dirs
        prompt = row["system_prompt"]
        assert "KEEP ROLE" in prompt and "KEEP TASK" in prompt
        assert "FOREIGN" not in prompt and "STALE" not in prompt
        assert "<worker-memory>" not in prompt
        assert ("## Directory ownership" in prompt) == bool(dirs)
        assert ("## Directory ownership" in row["prompt_overlay"]) == bool(dirs)
        for directory in dirs:
            assert f"- {directory}/" in prompt
            assert f"- {directory}/" in row["prompt_overlay"]
        if loaded:
            assert session.system_prompt == session._current_prompt == prompt
            assert session.owned_dirs == dirs and not session._prompt_injected
        after = durable_state(env.db)
        for key in original["sessions"][0]:
            if key not in {"owned_dirs", "system_prompt", "prompt_overlay"}:
                assert after["sessions"][0][key] == original["sessions"][0][key], key
        assert after["tm_tasks"] == original["tm_tasks"]
        assert after["tm_task_reservations"] == original["tm_task_reservations"]
    assert (snapshot(env.parent), snapshot(checkout)) == before
    for root in (env.repo, checkout):
        assert not (root / ".orchestra/layout.json").exists()
        assert not (root / ".orchestra/.gitignore").exists()
    migrate.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("loaded", [False, True], ids=["detached", "loaded"])
@pytest.mark.parametrize("location", ["base", "worker"])
@pytest.mark.parametrize("path", [
    ".orchestra/workers/w.md", "docs/workers/w.md", ".orchestra/kb/topic.md",
    ".orchestra/.layout-migration.json", ".orchestra/unknown/keep.md",
    ".orchestra/layout.json/broken",
])
async def test_private_does_not_hide_managed_state(env, loaded, location, path):
    session, checkout = reports_with_private(env, loaded, "both")
    root = env.repo if location == "base" else checkout
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("synthetic state\n")
    before = snapshot(env.parent), snapshot(checkout), durable_state(env.db)
    active = (session.system_prompt, session.prompt_overlay, session._current_prompt,
              session.owned_dirs[:], session._prompt_injected)
    response = await env.request(["source.txt"])
    assert response.status_code == 500, response.text
    assert "ORCHESTRA_LAYOUT_MISSING" in response.json()["error"]
    assert f"repository={env.repo}; repair:" in response.json()["error"]
    assert (snapshot(env.parent), snapshot(checkout), durable_state(env.db)) == before
    assert (session.system_prompt, session.prompt_overlay, session._current_prompt,
            session.owned_dirs, session._prompt_injected) == active


@pytest.mark.asyncio
@pytest.mark.parametrize("location", ["base", "worker"])
@pytest.mark.parametrize("kind", ["file", "broken-link", "foreign-link"])
async def test_non_directory_private_stays_strict(env, location, kind):
    session, checkout = reports_with_private(env, False, "worker" if location == "base" else "base")
    private = (env.repo if location == "base" else checkout) / ".orchestra/private"
    if kind == "file":
        private.write_text("synthetic private file\n")
    elif kind == "broken-link":
        private.symlink_to("missing-private")
    else:
        private.symlink_to(env.parent / ".orchestra/workers", target_is_directory=True)
    before = snapshot(env.parent), snapshot(checkout), durable_state(env.db)
    response = await env.request(["source.txt"])
    assert response.status_code == 500, response.text
    assert "ORCHESTRA_LAYOUT_MISSING" in response.json()["error"]
    assert (snapshot(env.parent), snapshot(checkout), durable_state(env.db)) == before
