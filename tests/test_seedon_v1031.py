"""V-1031: platform private links and ownership through model changes, offline."""
from __future__ import annotations

import inspect
import json
import logging
import subprocess
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import private_folder


def _git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True,
    ).stdout.strip()


def _repo(root, ignore=""):
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "user.email", "test@example.invalid")
    (root / ".gitignore").write_text(ignore)
    (root / ".orchestra").mkdir()
    (root / ".orchestra" / "keep.md").write_text("project file\n")
    _git(root, "add", "-f", ".gitignore", ".orchestra/keep.md")
    _git(root, "commit", "-qm", "base")
    return root


def _assert_private_clean(tmp_path, ignore):
    repo = _repo(tmp_path / "main", ignore)
    wt = tmp_path / "worker"
    _git(repo, "worktree", "add", "-q", "-b", "worker", str(wt))
    # Demonstrate the actual shared location; info/exclude alone loses to negation.
    common = Path(_git(wt, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    assert common == repo / ".git"
    (common / "info" / "exclude").write_text(private_folder.EXCLUDE_PATTERN + "\n")
    original = (repo / ".gitignore").read_bytes()
    assert private_folder.ensure_private(wt) == repo / ".orchestra" / "private"
    link = wt / private_folder.PRIVATE_REL
    assert link.is_symlink()
    (link / "note.txt").write_text("local only\n")
    assert _git(wt, "status", "--porcelain") == "", "private link dirties worktree"
    assert _git(repo, "status", "--porcelain") == "", "private folder dirties main"
    winner = _git(wt, "check-ignore", "-v", private_folder.PRIVATE_REL)
    assert not winner.split("\t")[0].split(":", 2)[-1].startswith("!")
    if "!.orchestra/**" in ignore:
        assert winner.startswith(".orchestra/.gitignore:")
    assert private_folder.ensure_private(repo) == link.resolve()
    assert _git(repo, "status", "--porcelain") == "", "private folder dirties main"
    for checkout in (repo, wt):
        assert (checkout / ".gitignore").read_bytes() == original
    before = (wt / ".orchestra" / ".gitignore").read_bytes() if (
        wt / ".orchestra" / ".gitignore").exists() else None
    assert private_folder.ensure_private(wt) == link.resolve()
    after = (wt / ".orchestra" / ".gitignore").read_bytes() if (
        wt / ".orchestra" / ".gitignore").exists() else None
    assert after == before


@pytest.mark.parametrize("ignore", ["", ".orchestra/\n", "!.orchestra/**\n"])
def test_private_clean_in_main_and_linked_worktree(tmp_path, ignore):
    _assert_private_clean(tmp_path, ignore)


def test_existing_private_link_is_repaired_without_replacing_it(tmp_path):
    repo = _repo(tmp_path / "main", "!.orchestra/**\n")
    wt = tmp_path / "worker"
    _git(repo, "worktree", "add", "-q", "-b", "worker", str(wt))
    shared = repo / private_folder.PRIVATE_REL
    shared.mkdir()
    (wt / private_folder.PRIVATE_REL).symlink_to(shared, target_is_directory=True)
    ignore = wt / ".orchestra" / ".gitignore"
    ignore.write_text("# custom rules\n/cache")
    private_folder.ensure_private(wt)
    assert ignore.read_text().startswith("# custom rules\n/cache\n")
    assert _git(wt, "status", "--porcelain") == ""
    assert _git(wt, "check-ignore", "-v", private_folder.PRIVATE_REL).startswith(
        ".orchestra/.gitignore:")


@pytest.mark.parametrize("existing", [False, True])
def test_tracked_ignore_warns_and_preserves_private_link(tmp_path, caplog, existing):
    repo = _repo(tmp_path / "main", "!.orchestra/**\n")
    (repo / ".orchestra" / ".gitignore").write_text("/cache\n")
    _git(repo, "add", ".orchestra/.gitignore")
    _git(repo, "commit", "-qm", "project ignores")
    wt = tmp_path / "worker"
    _git(repo, "worktree", "add", "-q", "-b", "worker", str(wt))
    shared = repo / private_folder.PRIVATE_REL
    link = wt / private_folder.PRIVATE_REL
    if existing:
        shared.mkdir()
        link.symlink_to(shared, target_is_directory=True)
    with caplog.at_level(logging.WARNING, logger=private_folder.__name__):
        assert private_folder.ensure_private(wt) == shared
    assert link.is_symlink() and link.resolve() == shared
    (link / "note.txt").write_text("local only\n")
    assert (shared / "note.txt").read_text() == "local only\n"
    warnings = [record for record in caplog.records if record.name == private_folder.__name__]
    assert {record.args[0] for record in warnings} == {shared, link}
    assert all(record.levelno == logging.WARNING and record.args[1] for record in warnings)
    for checkout in (repo, wt):
        assert (checkout / ".orchestra" / ".gitignore").read_text() == "/cache\n"
    assert _git(wt, "status", "--porcelain") == "?? .orchestra/private"
    assert _git(repo, "status", "--porcelain") == "?? .orchestra/private/"


def _assert_worktree_creation_survives_tracked_private_ignore(tmp_path, monkeypatch, caplog):
    from app import workspace

    repo = _repo(tmp_path / "main", "!.orchestra/**\n")
    (repo / ".orchestra" / ".gitignore").write_text("/cache\n")
    _git(repo, "add", ".orchestra/.gitignore")
    _git(repo, "commit", "-qm", "project ignores")
    monkeypatch.setattr(workspace, "WORKTREE_ROOT", tmp_path / "worktrees")
    with caplog.at_level(logging.WARNING, logger=private_folder.__name__):
        worker = workspace.create_worktree(str(repo), "worker", base_branch="main")
    wt = Path(worker.path)
    assert (wt / private_folder.PRIVATE_REL).is_symlink()
    assert _git(wt, "branch", "--show-current") == worker.branch
    warnings = [record for record in caplog.records if record.name == private_folder.__name__]
    assert any(record.args[0] == wt / private_folder.PRIVATE_REL and record.args[1]
               for record in warnings)
    assert (wt / ".orchestra" / ".gitignore").read_text() == "/cache\n"


def test_worktree_creation_survives_tracked_private_ignore(tmp_path, monkeypatch, caplog):
    _assert_worktree_creation_survives_tracked_private_ignore(tmp_path, monkeypatch, caplog)


def test_ignore_exception_mutation_breaks_worktree_creation(tmp_path, monkeypatch, caplog):
    source = textwrap.dedent(inspect.getsource(private_folder._ignore_private))
    warning = 'logger.warning("Could not exclude %s from Git: %s", wt / PRIVATE_REL, error)'
    assert source.count(warning) == 1
    namespace = dict(vars(private_folder))
    exec(compile(source.replace(warning, "raise"), "<private-ignore-mutant>", "exec"), namespace)
    monkeypatch.setattr(private_folder, "_ignore_private", namespace["_ignore_private"])
    with pytest.raises(RuntimeError):
        _assert_worktree_creation_survives_tracked_private_ignore(tmp_path, monkeypatch, caplog)


def test_private_ignore_write_failure_warns_and_keeps_link(tmp_path, monkeypatch, caplog):
    repo = _repo(tmp_path / "main", "!.orchestra/**\n")
    wt = tmp_path / "worker"
    _git(repo, "worktree", "add", "-q", "-b", "worker", str(wt))
    write_text = Path.write_text

    def fail_ignore_write(path, *args, **kwargs):
        if path.name == ".gitignore" and path.parent.name == ".orchestra":
            raise PermissionError("test ignore file is read-only")
        return write_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_ignore_write)
    with caplog.at_level(logging.WARNING, logger=private_folder.__name__):
        shared = private_folder.ensure_private(wt)
    assert shared == repo / private_folder.PRIVATE_REL
    assert shared.is_dir() and (wt / private_folder.PRIVATE_REL).is_symlink()
    warnings = [record for record in caplog.records if record.name == private_folder.__name__]
    assert {record.args[0] for record in warnings} == {shared, wt / private_folder.PRIVATE_REL}
    assert all(isinstance(record.args[1], PermissionError) for record in warnings)


def test_private_ignore_mutation_is_caught(tmp_path, monkeypatch):
    monkeypatch.setattr(private_folder, "_ignore_private", lambda wt: None)
    with pytest.raises(AssertionError, match="private link dirties worktree"):
        _assert_private_clean(tmp_path, "!.orchestra/**\n")


def test_tracked_ignore_that_already_excludes_private_is_preserved(tmp_path):
    repo = _repo(tmp_path / "main", "!.orchestra/**\n")
    content = "/private\n/cache\n"
    (repo / ".orchestra" / ".gitignore").write_text(content)
    _git(repo, "add", ".orchestra/.gitignore")
    _git(repo, "commit", "-qm", "private ignored by project")
    wt = tmp_path / "worker"
    _git(repo, "worktree", "add", "-q", "-b", "worker", str(wt))
    private_folder.ensure_private(wt)
    assert (wt / private_folder.PRIVATE_REL).is_symlink()
    assert (wt / ".orchestra" / ".gitignore").read_text() == content
    assert _git(wt, "status", "--porcelain") == ""


TRANSITIONS = [
    ("gpt-6-luna", "hub-gpt-6.1-sol"),
    ("hub-gpt-6.1-sol", "gpt-6-luna"),
    ("hub-gpt-6.1-sol", "hub-gpt-6-luna"),
    ("hub-gpt-6.1-sol", "hub-claude-haiku-5-5"),
]


async def _assert_owned_survives(tmp_path, monkeypatch, old_model, new_model, owned):
    from app import db, hub_pool, hub_workspace as hw
    from app import manager as manager_module
    from app.backend_hub import HubBackend
    from app.manager import SessionManager
    from app.models import backend_for_model
    from app.session import AgentSession
    from tests.test_hub_workspace import FakeMc, FakeSsh, _turn

    db.init_db()
    repo = _repo(tmp_path / "repo")
    for name in ("owned", "other"):
        (repo / name).mkdir()
        (repo / name / "code.py").write_text(f"NAME = '{name}'\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "source")
    monkeypatch.setattr(hub_pool, "require_hub_capacity", AsyncMock(return_value=None))
    monkeypatch.setattr(hw, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [])
    def scratch():
        path = tmp_path / "scratch"
        path.mkdir(exist_ok=True)
        return path

    monkeypatch.setattr(hw, "local_scratch", scratch)
    monkeypatch.setattr(HubBackend, "_preamble", lambda self: "offline test")
    mc = FakeMc(lambda root: None)
    ssh = FakeSsh(tmp_path / "hub")
    monkeypatch.setattr(hw.HubSsh, "from_env", classmethod(lambda cls: ssh))
    for key, value in {
        "MULTICODE_MCP_BASE": "http://offline.invalid", "MULTICODE_MCP_TOKEN": "test",
        "MULTICODE_HUB_SSH": "offline", "MULTICODE_HUB_SSH_KEY": "unused",
    }.items():
        monkeypatch.setenv(key, value)

    async def client(self):
        return mc

    monkeypatch.setattr(HubBackend, "_client", client)
    # Exercise the public change-model route, real switch, SQLite and backend factory.
    session = AgentSession(
        id="owned-model", name="worker", scope=str(repo), cwd=str(repo),
        model=old_model, backend_type=backend_for_model(old_model),
        system_prompt="test", owned_dirs=list(owned),
    )
    session._log = lambda *args, **kwargs: None
    initial = session._to_db_dict()
    initial["owned_dirs"] = json.dumps(owned)
    db.save_session(initial)
    if session.backend_type == "hub":
        session._backend = session._make_backend()
        await session._backend.connect()
        # For nonempty ownership, include an existing uploaded workspace/thread.
        if owned:
            events = await _turn(session._backend, "before switch")
            assert events[-1].metadata["ok"] is True
            session.session_id = session._backend.session_id
    else:
        session._backend = SimpleNamespace(disconnect=AsyncMock())
    mgr = SessionManager()
    mgr.sessions[session.id] = session
    from app.routes import sessions as routes

    monkeypatch.setattr(routes, "manager", mgr)
    monkeypatch.setattr(routes, "ensure_dashboard_visible", lambda model: None)
    monkeypatch.setattr("app.quota_queue.release_waiting", AsyncMock())
    result = await routes.change_model("worker", {
        "scope": str(repo), "model": new_model,
        "model_reason": "V-1031 offline ownership regression",
    })
    assert isinstance(result, dict) and result.get("ok"), result
    await session._drain_persist()
    assert session.owned_dirs == owned, "live owned_dirs lost on model change"
    row = db.get_session(session.id)
    assert json.loads(row["owned_dirs"] or "[]") == owned, "persisted owned_dirs lost"
    assert row["model"] == new_model

    async def check_upload(backend):
        events = await _turn(backend, "after model change")
        if owned:
            assert events[-1].metadata["ok"] is True, (
                "next hub upload failed: " + "".join(event.content for event in events))
            remote = Path(backend._state.remote_dir)
            assert (remote / "owned" / "code.py").is_file(), "owned_dirs missing from next upload"
            assert not (remote / "other").exists(), "next upload widened owned_dirs"
        else:
            assert events[-1].metadata["ok"] is False
            assert "set_worker_owned_dirs" in "".join(event.content for event in events)

    if session.backend_type == "hub":
        if session._backend is None:
            session._backend = session._make_backend()
        await check_upload(session._backend)
        session.session_id = session._backend.session_id
        session._persist()
        await session._drain_persist()
    # Recovery uses the real full DB loader; only startup/prompt services are stubbed.
    monkeypatch.setattr(AgentSession, "start", AsyncMock())
    monkeypatch.setattr(manager_module, "_make_mcp_config", lambda *a, **kw: {})
    monkeypatch.setattr(manager_module, "prompt_template_hash", lambda role: "test")
    monkeypatch.setattr(mgr, "assemble_prompt", lambda **kw: ("test", ""))
    mgr.sessions.clear()
    recovered = await mgr.ensure_loaded("worker", str(repo))
    assert recovered.owned_dirs == owned, "recovered owned_dirs lost"
    # hub→native must also preserve the selection for a later return to hub.
    if recovered.backend_type != "hub":
        recovered._log = lambda *a, **kw: None
        result = await recovered.change_model("hub-gpt-6.1-sol")
        assert result["ok"] is True
        await recovered._drain_persist()
        assert json.loads(db.get_session(recovered.id)["owned_dirs"] or "[]") == owned
    backend = recovered._make_backend()
    await check_upload(backend)
    await backend.disconnect()
    await session._disconnect_backend()


@pytest.mark.asyncio
@pytest.mark.parametrize("old_model,new_model", TRANSITIONS)
@pytest.mark.parametrize("owned", [["owned"], []])
async def test_owned_dirs_survive_model_change_and_next_upload(
    tmp_path, monkeypatch, old_model, new_model, owned,
):
    await _assert_owned_survives(tmp_path, monkeypatch, old_model, new_model, owned)


@pytest.mark.asyncio
async def test_owned_dirs_serialization_mutation_is_caught(tmp_path, monkeypatch):
    from app import session as module

    original = '"owned_dirs": json.dumps(self.owned_dirs) if self.owned_dirs else "",'
    source = textwrap.dedent(inspect.getsource(module.AgentSession._to_db_dict))
    assert source.count(original) == 1
    namespace = dict(vars(module))
    exec(compile(source.replace(original, '"owned_dirs": "",'), "<owned-dirs-mutant>", "exec"), namespace)
    monkeypatch.setattr(module.AgentSession, "_to_db_dict", namespace["_to_db_dict"])
    with pytest.raises(AssertionError, match="persisted owned_dirs lost"):
        await _assert_owned_survives(tmp_path, monkeypatch, *TRANSITIONS[0], ["owned"])


@pytest.mark.asyncio
async def test_failed_model_switch_preserves_owned_dirs(tmp_path, monkeypatch):
    from app import db, hub_pool
    from app.session import AgentSession

    db.init_db()
    session = AgentSession(
        id="failed-switch", name="worker", scope=str(tmp_path), cwd=str(tmp_path),
        model="gpt-6-luna", backend_type="codex", system_prompt="test",
        owned_dirs=["owned"],
    )
    db.save_session(session._to_db_dict())
    monkeypatch.setattr(hub_pool, "require_hub_capacity", AsyncMock(return_value=None))

    def fail_save(snapshot):
        raise OSError("offline persistence failure")

    monkeypatch.setattr("app.session.save_session", fail_save)
    result = await session.change_model("hub-gpt-6.1-sol")
    assert result["ok"] is False
    assert result["error_code"] == "text_tail_persistence_failed"
    assert session.model == "gpt-6-luna"
    assert session.owned_dirs == ["owned"]
    row = db.get_session(session.id)
    assert row["model"] == "gpt-6-luna"
    assert json.loads(row["owned_dirs"]) == ["owned"]
