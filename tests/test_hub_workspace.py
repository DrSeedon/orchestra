"""Core of hub-backed workers (V-1008): what leaves, what returns, who cleans up."""

import io
import json
import os
import shlex as _shlex
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
    assert set(plan.manifest) == {"src/keep.txt", "calc.py"}      # the subset plus repo-level files
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
    sha, failed = hw.commit_sync(repo, ["calc.py"], [], "#V-1: hub worker turn 1")
    assert not failed
    assert sha and _git(repo, "log", "-1", "--format=%s").strip() == "#V-1: hub worker turn 1"
    assert _git(repo, "show", "--name-only", "--format=", "HEAD").split() == ["calc.py"]
    assert "unrelated.txt" in _git(repo, "status", "--porcelain")


# ── remote safety ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_remote_remove_is_confined_to_broker_workspaces(monkeypatch):
    ssh = hw.HubSsh("u@h", "/k", "/home/u/orchestra-ws")

    async def must_not_run(self, remote, **kw):
        raise AssertionError(f"a refused removal reached the hub: {remote}")
    monkeypatch.setattr(hw.HubSsh, "run", must_not_run)
    for bad in ("/home/u", "/home/u/orchestra-ws", "/home/u/orchestra-ws/../x/hub-0123456789abcdef",
                "/home/u/other/hub-0123456789abcdef", "/home/u/orchestra-ws/notmine",
                "/home/u/orchestra-ws/proj-0123456789ab"):      # the persistent warm copy of a project
        with pytest.raises(hw.HubWorkspaceError):
            await ssh.remove(bad)
    with pytest.raises(hw.HubWorkspaceError):
        await ssh.dir_for("../../etc")


# ── whole turn with a fake hub, and lifecycle ────────────────────────────────────────


def shlex_split(command):
    return _shlex.split(command)


class FakeSsh(hw.HubSsh):
    """The 'hub' is a local directory; put/get run the same tar paths as the real thing."""

    def __init__(self, base: Path):
        super().__init__("u@h", "/k", str(base))
        self.base = base
        self.removed: list[str] = []

    async def root(self):
        return str(self.base)

    async def put(self, remote_dir, tar_path):
        d = Path(remote_dir)
        d.mkdir(parents=True, exist_ok=True)
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
        shutil.rmtree(remote_dir, ignore_errors=True)

    async def base_dir_for(self, scope):
        return str(self.base / hw.base_id_for(scope))

    async def copy_dir(self, source, dest):
        import shutil
        shutil.copytree(source, dest, dirs_exist_ok=True)

    async def run(self, remote, **kw):
        if remote.startswith("mkdir -p --"):
            Path(shlex_split(remote)[3]).mkdir(parents=True, exist_ok=True)
            return b""
        raise AssertionError(f"unexpected remote command {remote!r}")

    async def list_workspaces(self):
        return [(p.name, p.stat().st_mtime) for p in sorted(self.base.glob("hub-*")) if p.is_dir()]

    async def scrub_traces(self, ws_id, thread_id):
        self.scrubbed = getattr(self, "scrubbed", []) + [(ws_id, thread_id)]


class FakeMc:
    _token = "bearer-token-for-the-hub-0123456789"

    def __init__(self, hub_edit):
        self.calls: list[tuple[str, dict]] = []
        self.hub_edit = hub_edit
        self.project_dir = ""
        self.project_deleted = False
        self.delete_is_a_noop = False
        self.timeline: list[list[dict]] = []   # one snapshot of the hub timeline per poll
        self.polls = 0

    def activity_page(self, args):
        snapshot = self.timeline[min(self.polls, len(self.timeline) - 1)] if self.timeline else []
        self.polls += 1
        after = args.get("afterPosition")
        items = [i for i in snapshot if after is None or i["position"] > after]
        return {"items": items, "hasMore": False, "nextPosition": None}

    async def tool_call(self, name, args):
        self.calls.append((name, args))
        if name == "t3_project_create":
            self.project_dir = args["workspaceRoot"]
            return {"id": "proj-1"}
        if name == "t3_project_delete":
            self.project_deleted = not self.delete_is_a_noop
            return {}
        if name == "t3_project_list":
            if self.project_deleted or not self.project_dir:
                return {"projects": [], "nextCursor": None}
            return {"projects": [{"id": "proj-1", "workspaceRoot": self.project_dir}], "nextCursor": None}
        if name == "t3_thread_read" and args.get("view") == "activity":
            return self.activity_page(args)
        if name == "t3_thread_read" and self.project_deleted:
            from app.multicode_client import MultiCodeError
            raise MultiCodeError('MultiCode tool t3_thread_read failed: {"code":"thread_not_found"}')
        if name in ("t3_thread_launch", "t3_thread_send"):
            self.hub_edit(Path(self.project_dir))
            return {"threadId": "thr-1", "runId": "run-1"}
        if name == "t3_thread_wait":
            # while snapshots of the hub timeline remain to be shown, the run is still going
            if self.polls < len(self.timeline):
                return {"status": "running", "timedOut": True}
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
    mc.timeline = [[_item(1, "command_execution", "running", "$ make"), ],
                   [_item(1, "command_execution", "completed", "$ make\nok"),
                    _item(2, "assistant_message", "completed", "fixed it")]]
    monkeypatch.setattr(backend_hub.MultiCodeClient, "from_env", classmethod(lambda cls: _Entering(mc)))
    logged = []
    original_log = AgentSession._log
    monkeypatch.setattr(AgentSession, "_log", lambda self, kind, content, **k: (
        logged.append((kind, content)), original_log(self, kind, content, **k))[1])

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
    kinds = [kind for kind, _ in logged if kind in ("tool", "text")]
    assert kinds == ["tool", "text"]        # the tool card is logged once, before the final report
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


# ── complete release, orphan sweep, routing hint ─────────────────────────────────────


@pytest.fixture
def no_wait(monkeypatch):
    import time as _time
    monkeypatch.setattr(hw.asyncio, "sleep", lambda *_: _sleep0())
    real = _time.monotonic
    ticks = iter(range(0, 10_000))
    monkeypatch.setattr(hw.time, "monotonic", lambda: next(ticks) * 1.0)
    return real


async def _sleep0():
    return None


async def _worker_turn(repo, tmp_path, monkeypatch):
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda d: None)
    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [])
    await _turn(backend, "noop")
    return backend._state, ssh, mc


@pytest.mark.asyncio
async def test_release_proves_project_thread_and_directory_are_gone(repo, tmp_path, monkeypatch, no_wait):
    state, ssh, mc = await _worker_turn(repo, tmp_path, monkeypatch)
    await hw.release_workspace(state, ssh, mc)
    names = [name for name, _ in mc.calls]
    assert names.index("t3_project_delete") < names.index("t3_project_list")
    assert ssh.scrubbed == [(state.ws_id, "thr-1")]
    assert not state.path().exists()


@pytest.mark.asyncio
async def test_release_keeps_the_record_when_the_hub_still_shows_the_project(repo, tmp_path, monkeypatch, no_wait):
    state, ssh, mc = await _worker_turn(repo, tmp_path, monkeypatch)
    mc.delete_is_a_noop = True
    with pytest.raises(hw.HubWorkspaceError, match="project still listed"):
        await hw.release_workspace(state, ssh, mc)
    assert state.path().exists()


def test_trace_scrub_removes_only_this_workspaces_provider_traces(tmp_path):
    home = tmp_path / "home"
    ws, other = "hub-0123456789abcdef", "hub-fedcba9876543210"
    for root in (".claude/projects", ".cache/claude-cli-nodejs"):
        for w in (ws, other):
            (home / root / f"-home-u-orchestra-ws-{w}").mkdir(parents=True)
            (home / root / f"-home-u-orchestra-ws-{w}" / "s.jsonl").write_text("x")
    (home / ".codex/sessions/2026").mkdir(parents=True)
    (home / ".codex/sessions/2026/mine.jsonl").write_text(f'{{"cwd":"/x/{ws}"}}')
    (home / ".codex/sessions/2026/theirs.jsonl").write_text('{"cwd":"/owner/project"}')
    (home / "provlogs").mkdir(parents=True)
    (home / "provlogs/events.mcp-abc.log").write_text("x")
    (home / "provlogs/events.mcp-other.log").write_text("x")
    done = subprocess.run(["bash", "-s", "--", ws, "mcp:abc", str(home / "provlogs")], input=hw._SCRUB_SCRIPT, text=True,
                          env={"HOME": str(home), "PATH": os.environ["PATH"]}, capture_output=True)
    assert done.returncode == 0, done.stderr
    left = sorted(str(p.relative_to(home)) for p in home.rglob("*") if p.is_file())
    assert not any(ws in p for p in left)
    assert ".codex/sessions/2026/theirs.jsonl" in left and "provlogs/events.mcp-other.log" in left
    assert any(other in p for p in left)
    assert ".codex/sessions/2026/mine.jsonl" not in left
    assert "provlogs/events.mcp-abc.log" not in left


@pytest.mark.asyncio
async def test_sweep_releases_dead_workers_keeps_live_and_clears_unrecorded_debris(
        repo, tmp_path, monkeypatch, no_wait):
    import os, time
    live, ssh, mc = await _worker_turn(repo, tmp_path, monkeypatch)
    dead = hw.WorkspaceState(ws_id="hub-aaaaaaaaaaaaaaaa", worktree=str(tmp_path / "gone-worktree"),
                             remote_dir=str(ssh.base / "hub-aaaaaaaaaaaaaaaa"))
    dead.save()
    (ssh.base / dead.ws_id).mkdir()
    old = ssh.base / "hub-bbbbbbbbbbbbbbbb"
    old.mkdir()
    os.utime(old, (time.time() - 7200,) * 2)
    fresh = ssh.base / "hub-cccccccccccccccc"
    fresh.mkdir()
    monkeypatch.setattr(backend_hub.MultiCodeClient, "from_env", classmethod(lambda cls: _Entering(mc)))
    monkeypatch.setattr(hw.HubSsh, "from_env", classmethod(lambda cls: ssh))
    report = await backend_hub.sweep_orphans({str(repo)})
    assert report["released"] == [dead.ws_id] and report["kept"] == 1 and not report["errors"]
    assert report["remote_dirs"] == [old.name]
    assert Path(live.remote_dir).exists() and fresh.exists()
    assert not (ssh.base / dead.ws_id).exists() and not old.exists()
    assert live.path().exists() and not dead.path().exists()


@pytest.mark.asyncio
async def test_sweep_deletes_an_orphan_project_under_our_root_only(repo, tmp_path, monkeypatch, no_wait):
    ssh = FakeSsh(tmp_path / "hub")
    ssh.base.mkdir()
    monkeypatch.setattr(hw.HubSsh, "from_env", classmethod(lambda cls: ssh))
    monkeypatch.setenv("MULTICODE_MCP_BASE", "http://x")
    monkeypatch.setenv("MULTICODE_MCP_TOKEN", "t")
    projects = [{"id": "p-orphan", "workspaceRoot": f"{ssh.base}/hub-dddddddddddddddd"},
                {"id": "p-owner", "workspaceRoot": "/home/u/owner-project"},
                {"id": "p-foreign", "workspaceRoot": "/elsewhere/hub-eeeeeeeeeeeeeeee"}]
    deleted = []

    class Mc:
        async def tool_call(self, name, args):
            if name == "t3_project_list":
                return {"projects": projects, "nextCursor": None}
            if name == "t3_thread_list":
                return {"threads": [{"threadId": "mcp:t1"}]}
            if name == "t3_project_delete":
                deleted.append(args["projectId"])
            return {}
    monkeypatch.setattr(backend_hub.MultiCodeClient, "from_env", classmethod(lambda cls: _Entering(Mc())))
    report = await backend_hub.sweep_orphans(set())
    assert deleted == ["p-orphan"] and report["projects"] == ["hub-dddddddddddddddd"]
    assert ssh.scrubbed == [("hub-dddddddddddddddd", "mcp:t1")]


def test_quota_hold_names_the_hub_alternative(monkeypatch):
    from app.models import hub_alternative_hint

    for key, value in {"MULTICODE_MCP_BASE": "http://x", "MULTICODE_MCP_TOKEN": "t",
                       "MULTICODE_HUB_SSH": "u@h", "MULTICODE_HUB_SSH_KEY": "/k"}.items():
        monkeypatch.setenv(key, value)
    assert "model='hubsol'" in hub_alternative_hint("luna")
    assert "model='hubsonnet'" in hub_alternative_hint("opus")
    assert hub_alternative_hint("grok") == ""
    monkeypatch.delenv("MULTICODE_HUB_SSH")
    assert hub_alternative_hint("opus") == ""


def test_quota_refusal_message_carries_the_hint(monkeypatch):
    from app.quota_gate import QuotaDecision, QuotaGateError

    for key, value in {"MULTICODE_MCP_BASE": "http://x", "MULTICODE_MCP_TOKEN": "t",
                       "MULTICODE_HUB_SSH": "u@h", "MULTICODE_HUB_SSH_KEY": "/k"}.items():
        monkeypatch.setenv(key, value)
    decision = QuotaDecision(
        state="blocked", model="gpt-6-luna", provider="codex", provider_label="Codex", lane="luna",
        gated=True, utilization=99, progress=0.5, tolerance_pp=5, limit_pct=90, observed_at=0,
        valid_until=1, reset_at=None, window_starts_at=None, reason="over")
    assert "model='hubsol'" in str(QuotaGateError(decision))


def test_hub_sol_is_allowed_for_agents_while_our_own_sol_stays_refused(monkeypatch):
    from app import models

    for key, value in {"MULTICODE_MCP_BASE": "http://x", "MULTICODE_MCP_TOKEN": "t",
                       "MULTICODE_HUB_SSH": "u@h", "MULTICODE_HUB_SSH_KEY": "/k"}.items():
        monkeypatch.setenv(key, value)
    assert models.resolve_model("hubsol") == "hub-gpt-6.1-sol"
    models.ensure_spawn_allowed("hub-gpt-6.1-sol")
    assert models.resolve_model("sol") == "gpt-6.1-sol"
    with pytest.raises(ValueError):
        models.ensure_spawn_allowed(models.resolve_model("sol"))
    assert backend_hub.HUB_MODELS["hub-gpt-6.1-sol"] == ("codex", "gpt-6.1-sol")


# ── live activity feed ───────────────────────────────────────────────────────────────


def _item(position, kind, status, text, run="run-1", title=None):
    return {"position": position, "itemId": f"it{position}", "runId": run, "type": kind,
            "status": status, "text": text, "title": title}


def _kinds(events):
    return [(e.type, e.content[:40]) for e in events]


def test_activity_stream_emits_each_item_once_in_order_across_polls():
    from app.hub_activity import HubActivityStream

    stream = HubActivityStream("run-1")
    out = []
    # poll 1: prompt, workspace noise, a running command, a running edit
    out += stream.feed([_item(0, "user_message", "completed", "task"),
                        _item(1, "command_execution", "completed", "$ Preparing", title="Workspace ready"),
                        _item(2, "command_execution", "running", "$ pytest -q"),
                        _item(3, "file_change", "running", "calc.py")])
    assert stream.cursor == 1                      # stops before the oldest running item
    # poll 2: the same items re-read, now finished, plus the next ones
    out += stream.feed([_item(2, "command_execution", "completed", "$ pytest -q\n2 passed"),
                        _item(3, "file_change", "completed", "calc.py\n+x"),
                        _item(4, "assistant_message", "completed", "midway note"),
                        _item(5, "command_execution", "completed", "$ echo done\ndone"),
                        _item(6, "assistant_message", "completed", "final answer"),
                        _item(7, "checkpoint", "completed", "[]")])
    out += stream.feed([_item(2, "command_execution", "completed", "$ pytest -q\n2 passed")])   # re-read: no repeats
    out += stream.finish("final answer")
    assert _kinds(out) == [
        ("tool_use", "Bash: pytest -q"), ("tool_use", "Edit: calc.py"),
        ("tool_result", "2 passed\n".strip()), ("file_change", "update calc.py"), ("tool_result", "applied"),
        ("text", "midway note"), ("tool_use", "Bash: echo done"), ("tool_result", "done"),
    ]
    assert stream.cursor == 7
    ids = [e.metadata["tool_use_id"] for e in out if e.type in ("tool_use", "tool_result")]
    assert ids == ["it2", "it3", "it2", "it3", "it5", "it5"]


def test_activity_stream_ignores_other_runs_and_closes_unfinished_tools():
    from app.hub_activity import HubActivityStream

    stream = HubActivityStream("run-2")
    out = stream.feed([_item(1, "command_execution", "completed", "$ old", run="run-1"),
                       _item(2, "command_execution", "running", "$ sleep 99", run="run-2")])
    out += stream.finish("")
    assert _kinds(out) == [("tool_use", "Bash: sleep 99"), ("tool_result", "(not finished)")]
    assert out[-1].metadata["is_error"] is True


def test_activity_stream_translates_provider_tools_and_reasoning():
    from app.hub_activity import HubActivityStream

    tool = '{"toolName": "Read", "input": {"file_path": "/w/a.py"}, "output": "line1"}'
    out = HubActivityStream("run-1").feed([
        _item(1, "reasoning", "completed", "thinking it over"),
        _item(2, "dynamic_tool", "completed", tool, title="Read /w/a.py")])
    assert _kinds(out) == [("thinking", "thinking it over"), ("tool_use", 'Read: {"file_path": "/w/a.py"}'),
                           ("tool_result", "line1")]


@pytest.mark.asyncio
async def test_turn_streams_hub_activity_before_the_final_report(repo, tmp_path, monkeypatch):
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda d: None)
    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [])
    running = [_item(1, "command_execution", "running", "$ make"), ]
    done = [_item(1, "command_execution", "completed", "$ make\nok"),
            _item(2, "assistant_message", "completed", "fixed it")]
    mc.timeline = [running, done]
    events = await _turn(backend, "go")
    kinds = [e.type for e in events]
    assert kinds.index("tool_use") < kinds.index("tool_result") < len(kinds) - 2
    assert kinds[-2:] == ["text", "turn_end"]
    texts = [e.content for e in events if e.type == "text"]
    assert len(texts) == 1 and texts[0].startswith("fixed it")      # the final answer is not shown twice
    assert backend._state.activity_pos == 2


def test_commit_survives_paths_outside_the_sparse_cone(repo):
    _git(repo, "sparse-checkout", "init", "--cone")
    _git(repo, "sparse-checkout", "set", "src")
    outside = repo / ".orchestra" / "tasks" / "dashboard-ui-locale" / "result.md"
    outside.parent.mkdir(parents=True)
    outside.write_text("report\n")
    (repo / "src" / "keep.txt").write_text("edited\n")
    sha, failed = hw.commit_sync(repo, [".orchestra/tasks/dashboard-ui-locale/result.md", "src/keep.txt"],
                                 [], "#V-1: hub worker turn 1")
    assert sha and not failed
    committed = _git(repo, "show", "--name-only", "--format=", "HEAD").split()
    assert sorted(committed) == [".orchestra/tasks/dashboard-ui-locale/result.md", "src/keep.txt"]


def test_one_unstageable_path_does_not_cost_the_rest_of_the_turn(repo):
    (repo / ".gitignore").write_text("secret.log\n")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-qm", "ignore")
    (repo / "secret.log").write_text("x")           # git add refuses an ignored path
    (repo / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    sha, failed = hw.commit_sync(repo, ["secret.log", "calc.py"], [], "#V-1: hub worker turn 1")
    assert sha and [p for p, _ in failed] == ["secret.log"]
    assert _git(repo, "show", "--name-only", "--format=", "HEAD").split() == ["calc.py"]


@pytest.mark.asyncio
async def test_first_prompt_names_the_task_artifact_directory(repo, tmp_path, monkeypatch):
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda d: None)
    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [])
    await _turn(backend, "do it")
    launch = next(args for name, args in mc.calls if name == "t3_thread_launch")
    assert ".orchestra/tasks/V-1/" in launch["message"] and launch["message"].rstrip().endswith("do it")


def test_hub_paths_are_shown_relative_to_the_workspace():
    from app.events import AgentEvent

    event = AgentEvent("tool_use", "Edit: /h/orchestra-ws/x/hub-1/src/a.py")
    assert backend_hub._relative(event, "/h/orchestra-ws/x/hub-1").content == "Edit: src/a.py"


# ── large repos, owned_dirs, first-turn failure, empty errors ────────────────────────


def _big_tree(repo):
    (repo / "big").mkdir()
    for i in range(5):
        (repo / "big" / f"blob{i}.bin").write_bytes(b"x" * 400)
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "big")


def test_a_big_tree_outside_owned_dirs_is_neither_uploaded_nor_deleted_on_sync(repo, tmp_path):
    _big_tree(repo)
    small = hw.ProjectOptions(max_total_bytes=1000)
    plan = hw.plan_upload(repo, ["src"], known=[], options=small)
    assert not any(p.startswith("big/") for p in plan.manifest) and "src/keep.txt" in plan.manifest
    snapshot = _tar_of({"src/keep.txt": b"edited\n", "calc.py": b"def add(a, b):\n    return a + b\n"}, tmp_path)
    result = hw.apply_changes(snapshot, repo, plan.manifest, known=[])
    assert result.deleted == [] and len(list((repo / "big").glob("*.bin"))) == 5     # never "deleted"


def test_too_large_error_tells_the_orchestrator_how_to_narrow(repo):
    _big_tree(repo)
    small = hw.ProjectOptions(max_total_bytes=1000)
    with pytest.raises(hw.HubWorkspaceError) as caught:
        hw.plan_upload(repo, None, known=[], options=small)
    text = str(caught.value)
    assert "owned_dirs" in text and "big" in text
    with pytest.raises(hw.HubWorkspaceError, match="already set"):
        hw.plan_upload(repo, ["big"], known=[], options=small)


def test_dot_directories_survive_owned_dirs_normalisation():
    assert hw._clean_rel("./.orchestra/tasks") == ".orchestra/tasks"
    assert hw._clean_rel(".orchestra/tasks") == ".orchestra/tasks"


def test_project_options_come_from_the_projects_file(tmp_path, monkeypatch):
    table = tmp_path / "projects.json"
    table.write_text(json.dumps({str(tmp_path / "big-project"): {
        "max_total_mb": 1024, "max_files": 90000, "persistent": True}}))
    monkeypatch.setenv("MULTICODE_HUB_PROJECTS_FILE", str(table))
    big = hw.project_options(str(tmp_path / "big-project"))
    assert (big.max_total_bytes, big.max_files, big.persistent) == (1024 * 1024 * 1024, 90000, True)
    other = hw.project_options(str(tmp_path / "other"))
    assert other == hw.ProjectOptions() and other.persistent is False


@pytest.mark.asyncio
async def test_upload_command_creates_the_workspace_if_it_is_missing(monkeypatch):
    """A first attempt that died before the upload left a record but no directory (seedon)."""
    ssh = hw.HubSsh("u@h", "/k", "/home/u/orchestra-ws/x")
    seen = []

    async def fake_run(self, remote, **kw):
        seen.append(remote)
        return b""
    monkeypatch.setattr(hw.HubSsh, "run", fake_run)
    await ssh.put("/home/u/orchestra-ws/x/hub-0123456789abcdef", Path("/dev/null"))
    assert seen and "mkdir -p" in seen[0] and "test -d" not in seen[0]


@pytest.mark.asyncio
async def test_a_failed_first_turn_is_retried_as_a_first_upload(repo, tmp_path, monkeypatch):
    _big_tree(repo)
    table = tmp_path / "projects.json"
    table.write_text(json.dumps({str(repo): {"max_total_mb": 0.0005}}))      # ~500 bytes: too small
    monkeypatch.setenv("MULTICODE_HUB_PROJECTS_FILE", str(table))
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda d: None)
    backend._scope = str(repo)
    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [])
    events = await _turn(backend, "go")
    assert events[-1].metadata["ok"] is False and "owned_dirs" in "".join(e.content for e in events)
    assert backend._state.uploaded is False and not Path(backend._state.remote_dir).exists()
    table.write_text(json.dumps({str(repo): {"max_total_mb": 50}}))          # the project limit is raised
    events = await _turn(backend, "again")
    assert events[-1].metadata["ok"] is True
    assert (Path(backend._state.remote_dir) / "big" / "blob0.bin").exists() and backend._state.uploaded


@pytest.mark.asyncio
async def test_ssh_failures_always_say_what_failed(monkeypatch):
    ssh = hw.HubSsh("u@h", "/k", "/home/u/orchestra-ws/x")
    monkeypatch.setattr(hw.HubSsh, "_argv", lambda self, remote: ["bash", "-c", remote])
    with pytest.raises(hw.HubWorkspaceError) as caught:
        await ssh.run("test -d /definitely/not/here")
    assert "rc=1" in str(caught.value) and "no output" in str(caught.value) and "test -d" in str(caught.value)
    with pytest.raises(hw.HubWorkspaceError, match="boom"):
        await ssh.run("echo boom >&2; exit 3")


# ── persistent project copy ──────────────────────────────────────────────────────────


def _persistent(tmp_path, monkeypatch, repo):
    table = tmp_path / "projects.json"
    table.write_text(json.dumps({str(repo): {"persistent": True}}))
    monkeypatch.setenv("MULTICODE_HUB_PROJECTS_FILE", str(table))


@pytest.mark.asyncio
async def test_persistent_project_copy_is_reused_and_only_the_delta_is_sent(repo, tmp_path, monkeypatch):
    _persistent(tmp_path, monkeypatch, repo)
    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [])
    sent: list[list[str]] = []
    first, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda d: None)
    first._scope = str(repo)
    real_put = FakeSsh.put

    async def spy(self, remote_dir, tar_path):
        with tarfile.open(tar_path) as archive:
            sent.append(sorted(archive.getnames()))
        await real_put(self, remote_dir, tar_path)
    monkeypatch.setattr(FakeSsh, "put", spy)
    await _turn(first, "one")
    state1 = first._state
    assert sorted(sent[0]) == ["calc.py", "src/keep.txt"]            # the first worker uploads everything
    (repo / "extra.txt").write_text("new\n")                         # the repo moved on before worker 2
    (repo / "calc.py").write_text("def add(a, b):\n    return a * b\n")
    second = backend_hub.HubBackend("hub-claude-haiku-5-5", str(repo), scope=str(repo))
    second._client = first._client
    await _turn(second, "two")
    assert sent[1] == ["calc.py", "extra.txt"]                        # only what changed vs the warm copy
    assert (Path(second._state.remote_dir) / "src" / "keep.txt").exists()   # the rest came from the copy
    # releasing a worker never touches the warm copy, and neither does the sweep
    await hw.release_workspace(state1, ssh, mc)
    await hw.release_workspace(second._state, ssh, mc)
    base_dir = Path(await ssh.base_dir_for(str(repo)))
    assert (base_dir / "calc.py").exists() and hw.BaseState.load(str(repo)).manifest
    monkeypatch.setattr(backend_hub.MultiCodeClient, "from_env", classmethod(lambda cls: _Entering(mc)))
    monkeypatch.setattr(hw.HubSsh, "from_env", classmethod(lambda cls: ssh))
    old = base_dir
    import os as _os, time as _time
    _os.utime(old, (_time.time() - 99999,) * 2)
    await backend_hub.sweep_orphans(set())
    assert base_dir.exists()


@pytest.mark.asyncio
async def test_non_persistent_projects_do_not_leave_a_warm_copy(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [])
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda d: None)
    backend._scope = str(repo)
    await _turn(backend, "one")
    assert not list(ssh.base.glob("proj-*"))


# ── model change ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_hub_model_change_reconfigures_the_thread_or_says_it_started_a_new_one(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [])
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda d: None)
    await _turn(backend, "one")
    await backend.retarget_model("hub-claude-opus-5-5")
    assert backend.model == "hub-claude-opus-5-5" and backend._state.thread_id == "thr-1"
    assert ("t3_thread_configure", {"threadId": "thr-1", "modelSelection": {
        "instanceId": "claudeAgent", "model": "claude-opus-5-5"}}) in mc.calls

    async def refuse(name, args):
        if name == "t3_thread_configure":
            from app.multicode_client import MultiCodeError
            raise MultiCodeError("cannot switch provider")
        return await FakeMc.tool_call(mc, name, args)
    mc.tool_call = refuse
    await backend.retarget_model("hub-gpt-6.1-sol")
    assert backend._state.thread_id == "" and "earlier hub conversation is not available" in backend._early_steer[0]
    with pytest.raises(ValueError):
        await backend.retarget_model("claude-sonnet-5-5[1m]")


@pytest.mark.asyncio
async def test_conversation_carried_from_another_runtime_is_masked_not_refused(repo, tmp_path, monkeypatch):
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda d: None)
    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [FakeMc._token])
    handoff = (f"[Orchestra conversation handoff]\n<prior-conversation>\nuser said {FakeMc._token} once\n"
               f"</prior-conversation>\n\n<current-user-message>\ncontinue\n</current-user-message>")
    events = await _turn(backend, handoff)
    assert events[-1].metadata["ok"] is True
    launch = next(args for name, args in mc.calls if name == "t3_thread_launch")["message"]
    assert FakeMc._token not in launch and "[redacted]" in launch and "user said" in launch
    # a credential outside the quoted history is still refused
    backend2, ssh2, mc2 = _backend(repo, tmp_path / "b", monkeypatch, lambda d: None)
    events = await _turn(backend2, f"use {FakeMc._token}")
    assert events[-1].metadata["ok"] is False


def test_session_hands_owned_dirs_and_scope_to_the_hub_backend(monkeypatch):
    from datetime import datetime, timezone

    from app.session import AgentSession

    for key, value in {"MULTICODE_MCP_BASE": "http://x", "MULTICODE_MCP_TOKEN": "t",
                       "MULTICODE_HUB_SSH": "u@h", "MULTICODE_HUB_SSH_KEY": "/k"}.items():
        monkeypatch.setenv(key, value)
    session = AgentSession(id="i", name="w", scope="/p/big", cwd="/p/big/wt", model="hub-claude-haiku-5-5",
                           system_prompt="x", role="worker", owned_dirs=["src", "docs"],
                           created_at=datetime.now(timezone.utc))
    backend = session._make_backend()
    assert backend._paths == ["src", "docs"] and backend._scope == "/p/big"
