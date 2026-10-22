"""Core of hub-backed workers (V-1008): what leaves, what returns, who cleans up."""

import io
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

from app import backend_hub, hub_workspace as hw

SECRET = "sekret-value-0123456789abcdef"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                          text=True).stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "STATE_DIR", tmp_path / "state")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "T")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "T")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@example.com")
    root = tmp_path / "wt"
    root.mkdir()
    _git(root, "init", "-q", "-b", "task-V-1/w")
    (root / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (root / "src").mkdir()
    (root / "src" / "keep.txt").write_text("keep\n")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "init")
    return root


def _tar_of(files: dict[str, bytes], tmp_path: Path, extra=None) -> Path:
    path = tmp_path / "snap.tar"
    with tarfile.open(path, "w") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
        for info in extra or []:
            archive.addfile(info)
    return path


# ── what leaves ──────────────────────────────────────────────────────────────────────


def test_upload_excludes_credentials_by_name_and_by_value(repo):
    (repo / ".env").write_text("API_TOKEN=whatever-whatever\n")
    (repo / "deploy.pem").write_text("x")
    (repo / ".mcp.json").write_text("{}")
    (repo / "notes.txt").write_text(f"the token is {SECRET}\n")
    (repo / "shape.txt").write_text("k = ghp_" + "a" * 36 + "\n")
    (repo / "link").symlink_to("/etc/passwd")
    plan = hw.plan_upload(repo, known=[SECRET])
    assert set(plan.manifest) == {"calc.py", "src/keep.txt"}
    skipped = dict(plan.skipped)
    assert {".env", "deploy.pem", ".mcp.json", "notes.txt", "shape.txt", "link"} <= set(skipped)


def test_upload_paths_subset_and_no_escape(repo):
    plan = hw.plan_upload(repo, ["src"], known=[])
    assert set(plan.manifest) == {"src/keep.txt"}
    for bad in ("../etc", "/etc", "src/../../x"):
        with pytest.raises(hw.HubWorkspaceError):
            hw.plan_upload(repo, [bad], known=[])


def test_prompt_with_platform_credential_is_refused():
    with pytest.raises(hw.HubWorkspaceError):
        hw.assert_no_secret(f"use {SECRET} to log in", [SECRET], "the task prompt")
    hw.assert_no_secret("fix the parser", [SECRET], "the task prompt")


def test_known_secret_values_include_secret_files_and_env(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "DATA_DIR", tmp_path)
    (tmp_path / "secrets").mkdir()
    (tmp_path / "secrets" / "tok").write_text("file-secret-value-123456\n")
    monkeypatch.setenv("SOME_API_KEY", "env-secret-value-1234567")
    values = hw.known_secret_values()
    assert "file-secret-value-123456" in values and "env-secret-value-1234567" in values


# ── what returns ─────────────────────────────────────────────────────────────────────


def test_roundtrip_applies_modified_new_and_deleted(repo, tmp_path):
    plan = hw.plan_upload(repo, known=[])
    snap = _tar_of({"calc.py": b"def add(a, b):\n    return a + b\n", "new/file.py": b"x = 1\n"},
                   tmp_path)
    result = hw.apply_changes(snap, repo, plan.manifest, known=[])
    assert sorted(result.changed) == ["calc.py", "new/file.py"]
    assert result.deleted == ["src/keep.txt"]           # absent from the snapshot
    assert (repo / "calc.py").read_text().endswith("a + b\n")
    assert not (repo / "src").exists()                   # emptied directory pruned
    assert "src/keep.txt" not in result.manifest


def test_unchanged_files_are_not_touched(repo, tmp_path):
    plan = hw.plan_upload(repo, known=[])
    before = (repo / "calc.py").stat().st_mtime_ns
    snap = _tar_of({"calc.py": (repo / "calc.py").read_bytes(),
                    "src/keep.txt": b"keep\n"}, tmp_path)
    result = hw.apply_changes(snap, repo, plan.manifest, known=[])
    assert result.changed == [] and result.deleted == [] and not result.conflicts
    assert (repo / "calc.py").stat().st_mtime_ns == before


def test_sync_back_cannot_escape_the_worktree(repo, tmp_path):
    plan = hw.plan_upload(repo, known=[])
    outside = tmp_path / "outside"
    outside.mkdir()
    (repo / "dirlink").symlink_to(outside)               # a link already present in the worktree
    link = tarfile.TarInfo("evil_link")
    link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
    hard = tarfile.TarInfo("evil_hard")
    hard.type, hard.linkname = tarfile.LNKTYPE, "calc.py"
    snap = _tar_of({"../escaped.txt": b"x", "/abs.txt": b"x", "dirlink/pwn.txt": b"x",
                    "a/../../up.txt": b"x"}, tmp_path, extra=[link, hard])
    result = hw.apply_changes(snap, repo, plan.manifest, known=[])
    assert result.changed == []
    assert not (tmp_path / "escaped.txt").exists() and not (outside / "pwn.txt").exists()
    assert not (tmp_path / "up.txt").exists() and not Path("/abs.txt").exists()
    reasons = " ".join(why for _, why in result.rejected)
    assert "escapes" in reasons and "not a regular file" in reasons and "outside" in reasons


def test_sync_back_rejects_credentials_the_hub_produced(repo, tmp_path):
    plan = hw.plan_upload(repo, known=[SECRET])
    snap = _tar_of({".env": b"A=1\n", "id_ed25519": b"k", "leak.txt": SECRET.encode(),
                    "calc.py": b"ok = 1\n", "src/keep.txt": b"keep\n"}, tmp_path)
    result = hw.apply_changes(snap, repo, plan.manifest, known=[SECRET])
    assert result.changed == ["calc.py"]
    assert {p for p, _ in result.rejected} == {".env", "id_ed25519", "leak.txt"}
    assert not (repo / ".env").exists() and not (repo / "leak.txt").exists()


def test_concurrent_local_edit_is_a_conflict_not_an_overwrite(repo, tmp_path):
    plan = hw.plan_upload(repo, known=[])
    (repo / "calc.py").write_text("# edited on the VPS meanwhile\n")
    snap = _tar_of({"calc.py": b"hub version\n", "src/keep.txt": b"keep\n"}, tmp_path)
    result = hw.apply_changes(snap, repo, plan.manifest, known=[])
    assert result.conflicts == ["calc.py"] and result.changed == []
    assert (repo / "calc.py").read_text() == "# edited on the VPS meanwhile\n"


def test_truncated_snapshot_does_not_delete_the_worktree(repo, tmp_path):
    for i in range(30):
        (repo / f"f{i}.txt").write_text(str(i))
    plan = hw.plan_upload(repo, known=[])
    result = hw.apply_changes(_tar_of({}, tmp_path), repo, plan.manifest, known=[])
    assert result.deleted == [] and (repo / "f3.txt").exists()
    assert any(p == "*" for p, _ in result.rejected)


def test_commit_lands_only_imported_paths_on_the_branch(repo):
    (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    (repo / "unrelated.txt").write_text("dirty\n")
    sha = hw.commit_sync(repo, ["calc.py"], [], "#V-1: hub worker turn 1")
    assert sha and _git(repo, "log", "-1", "--format=%s").strip() == "#V-1: hub worker turn 1"
    assert _git(repo, "show", "--name-only", "--format=", "HEAD").split() == ["calc.py"]
    assert "unrelated.txt" in _git(repo, "status", "--porcelain")


# ── remote safety ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_remote_remove_is_confined_to_broker_workspaces():
    ssh = hw.HubSsh("u@h", "/k", "/home/u/orchestra-ws")
    for bad in ("/home/u", "/home/u/orchestra-ws", "/home/u/orchestra-ws/../x/hub-0123456789abcdef",
                "/home/u/other/hub-0123456789abcdef", "/home/u/orchestra-ws/notmine"):
        with pytest.raises(hw.HubWorkspaceError):
            await ssh.remove(bad)
    with pytest.raises(hw.HubWorkspaceError):
        await ssh.dir_for("../../etc")


# ── whole turn with a fake hub, and lifecycle ────────────────────────────────────────


class FakeSsh(hw.HubSsh):
    """The 'hub' is a local directory; put/get run the same tar paths as the real thing."""

    def __init__(self, base: Path):
        super().__init__("u@h", "/k", str(base))
        self.base = base
        self.removed: list[str] = []

    async def root(self):
        return str(self.base)

    async def put(self, remote_dir, tar_path, *, fresh):
        d = Path(remote_dir)
        d.mkdir(parents=True, exist_ok=not fresh)
        with tarfile.open(tar_path) as archive:
            archive.extractall(d, filter="data")

    async def delete_files(self, remote_dir, rels):
        for rel in rels:
            (Path(remote_dir) / rel).unlink(missing_ok=True)

    async def get(self, remote_dir, out):
        with tarfile.open(out, "w") as archive:
            archive.add(remote_dir, arcname=".")

    async def remove(self, remote_dir):
        self.removed.append(remote_dir)
        import shutil
        shutil.rmtree(remote_dir)


class FakeMc:
    _token = "bearer-token-for-the-hub-0123456789"

    def __init__(self, hub_edit):
        self.calls: list[tuple[str, dict]] = []
        self.hub_edit = hub_edit
        self.project_dir = ""

    async def tool_call(self, name, args):
        self.calls.append((name, args))
        if name == "t3_project_create":
            self.project_dir = args["workspaceRoot"]
            return {"id": "proj-1"}
        if name in ("t3_thread_launch", "t3_thread_send"):
            self.hub_edit(Path(self.project_dir))
            return {"threadId": "thr-1", "runId": "run-1"}
        if name == "t3_thread_wait":
            return {"status": "completed", "timedOut": False}
        if name == "t3_thread_read":
            return {"items": [
                {"createdBy": "agent", "type": "assistant_message", "runId": "run-0", "text": "old turn"},
                {"createdBy": "agent", "type": "assistant_message", "runId": "run-1", "text": "fixed it"},
                {"createdBy": "agent", "type": "user_message", "runId": "run-1", "text": "the prompt"},
            ]}
        return {}

    async def __aexit__(self, *_):
        pass


def _backend(repo, tmp_path, monkeypatch, edit):
    ssh = FakeSsh(tmp_path / "hub")
    monkeypatch.setattr(hw.HubSsh, "from_env", classmethod(lambda cls: ssh))
    monkeypatch.setenv("MULTICODE_MCP_BASE", "http://x")
    monkeypatch.setenv("MULTICODE_MCP_TOKEN", FakeMc._token)
    backend = backend_hub.HubBackend("hub-claude-haiku-5-5", str(repo))
    mc = FakeMc(edit)

    async def client():
        return mc
    backend._client = client
    return backend, ssh, mc


async def _turn(backend, text):
    if backend._ssh is None:
        await backend.connect()
    await backend.send(text)
    return [event async for event in backend.events()]


@pytest.mark.asyncio
async def test_turn_uploads_without_credentials_syncs_back_and_commits(repo, tmp_path, monkeypatch):
    (repo / ".env").write_text(f"TOKEN={FakeMc._token}\n")
    (repo / "notes.txt").write_text(f"{FakeMc._token}\n")

    def edit(workdir: Path):
        assert not (workdir / ".env").exists() and not (workdir / "notes.txt").exists()
        assert not any(FakeMc._token in p.read_text() for p in workdir.rglob("*") if p.is_file())
        (workdir / "calc.py").write_text("def add(a, b):\n    return a + b\n")

    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, edit)
    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [FakeMc._token])
    events = await _turn(backend, "fix add()")
    kinds = [e.type for e in events]
    assert kinds[-1] == "turn_end" and events[-1].metadata["ok"] is True
    assert "fixed it" in next(e for e in events if e.type == "text").content
    assert (repo / "calc.py").read_text().endswith("a + b\n")
    assert _git(repo, "log", "-1", "--format=%s").startswith("#V-1: hub worker turn 1")
    launch = next(args for name, args in mc.calls if name == "t3_thread_launch")
    assert launch["runtimeMode"] == "full-access" and launch["projectId"] == "proj-1"
    assert FakeMc._token not in launch["message"]
    # the second turn is a follow-up into the same hub thread, with a delta upload
    (repo / "extra.txt").write_text("new on the VPS\n")
    events = await _turn(backend, "also do more")
    assert any(name == "t3_thread_send" and args["threadId"] == "thr-1" for name, args in mc.calls)
    assert (Path(mc.project_dir) / "extra.txt").read_text() == "new on the VPS\n"


@pytest.mark.asyncio
async def test_prompt_carrying_a_credential_never_reaches_the_hub(repo, tmp_path, monkeypatch):
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda d: None)
    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [FakeMc._token])
    events = await _turn(backend, f"login with {FakeMc._token}")
    assert events[-1].metadata["ok"] is False
    assert not any(name in ("t3_thread_launch", "t3_thread_send") for name, _ in mc.calls)


@pytest.mark.asyncio
async def test_release_removes_hub_project_directory_and_state(repo, tmp_path, monkeypatch):
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda d: None)
    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [])
    await _turn(backend, "noop")
    state = backend._state
    assert state.path().exists() and Path(state.remote_dir).exists()
    await hw.release_workspace(state, ssh, mc)
    assert not Path(state.remote_dir).exists() and not state.path().exists()
    assert ("t3_project_delete", {"projectId": "proj-1", "force": True}) in mc.calls


@pytest.mark.asyncio
async def test_failed_cleanup_keeps_the_record_for_a_retry(repo, tmp_path, monkeypatch):
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda d: None)
    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [])
    await _turn(backend, "noop")
    state = backend._state

    async def boom(_):
        raise hw.HubWorkspaceError("ssh down")
    ssh.remove = boom
    with pytest.raises(hw.HubWorkspaceError):
        await hw.release_workspace(state, ssh, mc)
    assert state.path().exists()
    assert [s.ws_id for s in hw.states_for_worktree(str(repo))] == [state.ws_id]


def test_hub_models_resolve_and_spawn_needs_configuration(monkeypatch):
    from app import models

    models.validate_model_registry()
    assert models.backend_for_model(models.resolve_model("hub")) == "hub"
    for key in ("MULTICODE_MCP_BASE", "MULTICODE_MCP_TOKEN", "MULTICODE_MCP_TOKEN_FILE",
                "MULTICODE_HUB_SSH", "MULTICODE_HUB_SSH_KEY"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValueError, match="MULTICODE_MCP_BASE"):
        models.ensure_spawn_allowed("hub-claude-sonnet-5-5")


@pytest.mark.asyncio
async def test_real_agent_session_drives_a_hub_turn_like_any_runtime(repo, tmp_path, monkeypatch):
    """Session -> registry -> HubBackend -> fake hub: the worker goes IDLE with a commit."""
    import asyncio
    from datetime import datetime, timezone
    from unittest.mock import MagicMock

    from app.events import MessageProvenance
    from app.session import AgentSession, AgentStatus

    monkeypatch.setattr("app.db.get_recent_chat_logs", MagicMock(return_value=[]))
    monkeypatch.setattr("app.session.save_session", MagicMock())
    monkeypatch.setattr("app.session.add_log", MagicMock(return_value=1))
    monkeypatch.setattr("app.bg_jobs.bg_manager", None)
    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [])
    ssh = FakeSsh(tmp_path / "hub")
    monkeypatch.setattr(hw.HubSsh, "from_env", classmethod(lambda cls: ssh))
    monkeypatch.setenv("MULTICODE_MCP_BASE", "http://x")
    monkeypatch.setenv("MULTICODE_MCP_TOKEN", FakeMc._token)

    def edit(workdir: Path):
        (workdir / "calc.py").write_text("def add(a, b):\n    return a + b\n")

    mc = FakeMc(edit)
    monkeypatch.setattr(backend_hub.MultiCodeClient, "from_env", classmethod(lambda cls: _Entering(mc)))

    session = AgentSession(
        id="hub-sess", name="hubw", scope=str(repo), cwd=str(repo),
        model="hub-claude-sonnet-5-5", system_prompt="x", role="worker",
        backend_type="hub", created_at=datetime.now(timezone.utc),
    )
    await session.start("fix add()", provenance=MessageProvenance(origin="user", senders=("user",)))
    for _ in range(200):
        await asyncio.sleep(0.05)
        if session.status == AgentStatus.IDLE and session.session_id:
            break
    assert session.status == AgentStatus.IDLE
    assert session.session_id.startswith("hub-")
    assert _git(repo, "log", "-1", "--format=%s").startswith("#V-1: hub worker turn 1")
    await session._disconnect_backend()


class _Entering:
    def __init__(self, mc):
        self._mc = mc

    async def __aenter__(self):
        return self._mc

    async def __aexit__(self, *_):
        pass

    def __getattr__(self, name):
        return getattr(self._mc, name)


def test_reply_is_the_assistant_message_of_this_run_not_the_prompt_or_an_older_turn():
    from app.multicode_client import _last_assistant_text

    items = {"items": [
        {"createdBy": "agent", "type": "assistant_message", "runId": "r1", "text": "answer one"},
        {"createdBy": "agent", "type": "user_message", "runId": "r2", "text": "prompt two"},
    ]}
    assert _last_assistant_text(items, "r2") is None      # interrupted before any reply
    assert _last_assistant_text(items, "r1") == "answer one"
