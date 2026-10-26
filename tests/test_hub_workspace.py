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


@pytest.fixture(autouse=True)
def _offline_hub_pool(monkeypatch):
    from app import hub_pool

    async def pool(**kwargs):
        return {"available": True, "providers": {
            provider: {"accounts": 2, "usable": 1, "threshold_pct": 100}
            for provider in ("claude", "codex")}}
    monkeypatch.setattr(hub_pool, "get_hub_pool", pool)


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
        if remote.startswith("if test -L "):
            # Run the production name-only guard against synthetic local copies.
            return subprocess.run(["bash", "-c", remote], check=True, capture_output=True).stdout
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
        self.strict_projects = False           # launch/send fail like the real hub for a project it does not know
        self.known_projects: set[str] = set()

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
            self.known_projects.add("proj-1")
            self.project_deleted = False            # a newly created project is live again
            return {"id": "proj-1"}
        if name == "t3_project_delete":
            self.project_deleted = not self.delete_is_a_noop
            if not self.delete_is_a_noop:
                self.known_projects.discard(args.get("projectId") or args.get("id") or "proj-1")
            return {}
        if self.strict_projects and name in ("t3_thread_launch", "t3_thread_send"):
            if (args.get("projectId") or "proj-1") not in self.known_projects and name == "t3_thread_launch":
                from app.multicode_client import MultiCodeError
                raise MultiCodeError('MultiCode tool t3_thread_launch failed: {"code":"orchestration_error",'
                                     '"message":"The operation could not be completed."}')
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
    # the broker uploads only what the worker owns; the helper owns the fixture's top-level entries
    owned = sorted(p.name for p in Path(repo).iterdir() if p.name != ".git")
    backend = backend_hub.HubBackend("hub-claude-haiku-5-5", str(repo), paths=owned)
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


def _failed_hub_runs(mc, monkeypatch, *, failures=1, status="failed", reason=None,
                     reason_source="recentRuns", activity=None):
    """Deterministic terminal runs, retaining the normal upload and sync/commit paths."""
    from unittest.mock import AsyncMock

    original = mc.tool_call
    attempts = []
    sleep = AsyncMock()
    monkeypatch.setattr(backend_hub.asyncio, "sleep", sleep)

    async def call(name, args):
        if name in {"t3_thread_launch", "t3_thread_send"}:
            result = await original(name, args)
            attempts.append((name, dict(args)))
            return {**result, "runId": f"run-{len(attempts)}"}
        run_id = f"run-{len(attempts)}"
        failed = len(attempts) <= failures
        if name == "t3_thread_wait":
            result = {"status": status if failed else "completed", "timedOut": False}
            if failed and reason_source == "wait" and reason:
                result["error"] = {"message": reason}
            return result
        if name == "t3_thread_read":
            if args.get("view") == "activity":
                result = {"items": [], "hasMore": False}
                if activity and failed:
                    result["items"] = [{**activity, "runId": run_id, "position": len(attempts) * 10}]
                if reason and failed and reason_source == "activity":
                    result["items"].append({"type": "error", "status": "failed", "runId": run_id,
                                            "position": len(attempts) * 10 + 1, "text": reason})
            else:
                result = {"items": [] if failed else [
                    {"type": "assistant_message", "runId": run_id, "text": "recovered"}]}
            if failed and reason_source in {"recentRuns", "runs"}:
                result[reason_source] = [{"runId": "old-run", "error": "old unrelated error"},
                                        {"runId": run_id, "error": reason}]
            return result
        return await original(name, args)

    mc.tool_call = call
    return attempts, sleep


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["failed", "cancelled"])
@pytest.mark.parametrize("reason_source", ["recentRuns", "runs", "wait", "activity"])
async def test_failed_without_reply_and_without_work_retries_same_thread_then_succeeds(
    repo, tmp_path, monkeypatch, status, reason_source,
):
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda d: None)
    backend.model = "hub-gpt-6.1-sol"
    attempts, sleep = _failed_hub_runs(mc, monkeypatch, status=status, reason="transient provider failure",
                                     reason_source=reason_source)
    events = await _turn(backend, "fix the task")
    assert events[-1].metadata["ok"] is True
    assert any(e.type == "text" and "recovered" in e.content for e in events)
    assert [name for name, _ in attempts] == ["t3_thread_launch", "t3_thread_send"]
    assert attempts[1][1] == {"threadId": "thr-1", "message": attempts[0][1]["message"], "mode": "auto"}
    assert attempts[0][1]["modelSelection"] == {"instanceId": "codex", "model": "gpt-6.1-sol"}
    assert backend.model == "hub-gpt-6.1-sol"
    assert not any(name == "t3_thread_configure" for name, _ in mc.calls)
    sleep.assert_awaited_once_with(1)
    assert any(e.type == "status" and "retry 1/2" in e.content
               and "transient provider failure" in e.content for e in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", [None, "provider disconnected before replying"])
async def test_no_work_retries_exhausted_preserve_error_and_hub_reason(repo, tmp_path, monkeypatch, reason):
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda d: None)
    attempts, sleep = _failed_hub_runs(mc, monkeypatch, failures=10, reason=reason)
    events = await _turn(backend, "go")
    assert len(attempts) == 3
    assert [c.args for c in sleep.await_args_list] == [(1,), (2,)]
    error = next(e for e in events if e.type == "error")
    expected = reason or "no reason exposed by hub"
    assert "hub thread ended with status failed" in error.content and expected in error.content
    assert "old unrelated error" not in error.content
    assert any(e.type == "text" and expected in e.content for e in events)
    assert events[-1].metadata["stop_reason"] == "hub_error"


@pytest.mark.asyncio
async def test_platform_workspace_preparation_allows_retry(repo, tmp_path, monkeypatch):
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda d: None)
    attempts, sleep = _failed_hub_runs(mc, monkeypatch, activity={
        "type": "command_execution", "status": "completed", "title": "Workspace ready",
        "text": "$ Preparing workspace\nWorkspace preparation completed.",
        "itemId": "turn-item:provider:codex:native-item:workspace-preparation%3Arun"})
    events = await _turn(backend, "go")
    assert len(attempts) == 2
    assert events[-1].metadata["ok"] is True


@pytest.mark.asyncio
async def test_interrupt_during_retry_backoff_does_not_resend(repo, tmp_path, monkeypatch):
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda d: None)
    attempts, sleep = _failed_hub_runs(mc, monkeypatch)

    async def interrupt(delay):
        backend._abort = True
    sleep.side_effect = interrupt
    events = await _turn(backend, "go")
    assert len(attempts) == 1
    assert events[-1].metadata["stop_reason"] == "interrupted"


@pytest.mark.asyncio
@pytest.mark.parametrize("uncertain", [False, True])
async def test_retry_send_failure_never_launches_a_replacement(repo, tmp_path, monkeypatch, uncertain):
    from app.multicode_client import MultiCodeError

    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda d: None)
    attempts, sleep = _failed_hub_runs(mc, monkeypatch)
    original = mc.tool_call
    send_calls = []

    async def call(name, args):
        if name == "t3_thread_send":
            send_calls.append(args)
            raise MultiCodeError("thread send refused or delivery uncertain", retryable=uncertain)
        return await original(name, args)
    mc.tool_call = call
    events = await _turn(backend, "go")
    assert len(attempts) == 1 and len(send_calls) == 1
    assert events[-1].metadata["stop_reason"] == "hub_error"
    assert backend._state.thread_id == "thr-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("work", ["edit", "delete", "tool", "rejected", "outbox", "sync_failure", "activity_failure"])
async def test_failed_run_with_work_or_uncertain_sync_is_not_retried(repo, tmp_path, monkeypatch, work):
    from app.multicode_client import MultiCodeError

    def edit(directory):
        if work == "edit":
            (directory / "calc.py").write_text("fixed\n")
        elif work == "delete":
            (directory / "calc.py").unlink()
        elif work == "rejected":
            (directory / ".env").write_text("LOCAL_FLAG=1\n")
        elif work == "outbox":
            (directory / ".orchestra-outbox.jsonl").write_text('{}\n')

    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, edit)
    attempts, sleep = _failed_hub_runs(
        mc, monkeypatch, activity={"type": "command_execution", "status": "completed", "text": "$ true"}
        if work == "tool" else None)
    if work == "sync_failure":
        async def get(*args):
            raise hw.HubWorkspaceError("snapshot unavailable")
        monkeypatch.setattr(ssh, "get", get)
    if work == "activity_failure":
        original = mc.tool_call

        async def call(name, args):
            if name == "t3_thread_read" and args.get("view") == "activity":
                raise MultiCodeError("activity unavailable")
            return await original(name, args)
        mc.tool_call = call
    events = await _turn(backend, "go")
    assert len(attempts) == 1
    sleep.assert_not_awaited()
    assert events[-1].metadata["stop_reason"] == "hub_error"
    if work == "edit":
        assert (repo / "calc.py").read_text() == "fixed\n"
        assert _git(repo, "log", "-1", "--format=%s").startswith("#V-1: hub worker turn 1")
    if work == "delete":
        assert not (repo / "calc.py").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("reason_source", ["recentRuns", "wait", "activity"])
async def test_failed_without_reply_provider_limit_is_not_retried(repo, tmp_path, monkeypatch, reason_source):
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda d: None)
    attempts, sleep = _failed_hub_runs(mc, monkeypatch, reason="usage_limit_reached",
                                     reason_source=reason_source)
    events = await _turn(backend, "go")
    assert len(attempts) == 1
    sleep.assert_not_awaited()
    assert events[-1].metadata["stop_reason"] == "hub_provider_limit"


@pytest.mark.asyncio
async def test_hub_created_virtualenv_is_rejected_and_sibling_is_synced(repo, tmp_path, monkeypatch):
    def edit(directory):
        env = directory / ".venv-v281"
        (env / "lib").mkdir(parents=True)
        (env / "lib/package.py").write_text("generated = True\n")
        (env / "pyvenv.cfg").write_text("home = /usr/bin\n")
        (directory / "sibling.py").write_text("keep = True\n")

    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, edit)
    events = await _turn(backend, "go")
    assert events[-1].metadata["ok"] is True
    assert not (repo / ".venv-v281").exists()
    assert (repo / "sibling.py").read_text() == "keep = True\n"
    assert "sibling.py" in _git(repo, "show", "--format=", "--name-only", "HEAD")
    assert ".venv-v281" not in _git(repo, "ls-files")
    assert any("rejected: .venv-v281 (Python virtualenv" in e.content for e in events)


@pytest.mark.parametrize("marker_first", [True, False])
@pytest.mark.parametrize("prefix", ["", "././"])
def test_virtualenv_detection_is_order_independent_and_matches_directory_boundaries(
    repo, tmp_path, marker_first, prefix,
):
    files = {"tools/custom-env/pyvenv.cfg": b"home = /usr/bin\n",
             "tools/custom-env/lib/pkg.py": b"ignored\n"}
    if not marker_first:
        files = dict(reversed(list(files.items())))
    files["tools/custom-env-sibling/keep.py"] = b"keep\n"
    files = {prefix + name: data for name, data in files.items()}
    result = hw.apply_changes(_tar_of(files, tmp_path), repo, {}, known=[])
    assert len(result.changed) == 1 and result.changed[0].endswith("tools/custom-env-sibling/keep.py")
    assert result.rejected == [("tools/custom-env", "Python virtualenv (contains pyvenv.cfg)")]
    assert not (repo / "tools/custom-env").exists()


def test_virtualenv_exclusion_preserves_old_manifest_files(repo, tmp_path):
    env = repo / "custom-env"
    env.mkdir()
    (env / "old.py").write_text("already local\n")
    manifest = {"custom-env/old.py": hw.sha256_file(env / "old.py")}
    snapshot = _tar_of({"custom-env/pyvenv.cfg": b"home = /usr/bin\n",
                        "custom-env/new.py": b"do not import\n"}, tmp_path)
    result = hw.apply_changes(snapshot, repo, manifest, known=[])
    assert result.changed == result.deleted == []
    assert result.manifest == manifest
    assert (env / "old.py").read_text() == "already local\n"
    assert not (env / "new.py").exists()


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
        backend_type="hub", owned_dirs=["calc.py"], created_at=datetime.now(timezone.utc),
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


@pytest.mark.parametrize("mixed", [False, True])
@pytest.mark.parametrize("refused", [None, "private/new.txt", "missing.txt"])
@pytest.mark.parametrize("deletion_staged", [False, True])
def test_commit_returned_deletions_preserves_unrelated_index(repo, mixed, refused, deletion_staged):
    for name in ("native-modified.txt", "native-deleted.txt"):
        (repo / name).write_text("original\n")
    (repo / ".gitignore").write_text("/private/\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "baseline")
    before = _git(repo, "rev-parse", "HEAD").strip()

    # Preserve additions, deletions and different staged/unstaged native content.
    (repo / "native-modified.txt").write_text("native staged\n")
    (repo / "native-added.txt").write_text("native staged addition\n")
    (repo / "native-deleted.txt").unlink()
    _git(repo, "add", "-A")
    (repo / "native-modified.txt").write_text("native unstaged\n")
    (repo / "native-added.txt").write_text("native unstaged addition\n")
    staged = _git(repo, "diff", "--cached", "--binary")
    unstaged = _git(repo, "diff", "--binary")

    (repo / "src/keep.txt").unlink()
    if deletion_staged:
        _git(repo, "add", "-A", "--", "src/keep.txt")
    changed = []
    expected = {"src/keep.txt"}
    if mixed:
        (repo / "calc.py").write_text("# hub modification\n")
        # Identical content makes Git's default diff classify the delete/add as
        # a rename; the deletion must still be included in the commit.
        (repo / "hub-new.txt").write_text("keep\n")
        changed += ["calc.py", "hub-new.txt"]
        expected.update(changed)
    if refused:
        changed.append(refused)
        if refused.startswith("private/"):
            (repo / "private").mkdir()
            (repo / refused).write_text("local only\n")

    sha, failed = hw.commit_sync(repo, changed, ["src/keep.txt"], "hub return")

    assert sha
    assert [path for path, _ in failed] == ([refused] if refused else [])
    assert all(reason for _, reason in failed)
    assert set(_git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()) == expected
    assert _git(repo, "rev-list", "--count", f"{before}..HEAD").strip() == "1"
    assert not _git(repo, "ls-tree", "HEAD", "src/keep.txt")
    assert _git(repo, "status", "--porcelain", "--", *sorted(expected)) == ""
    assert _git(repo, "diff", "--cached", "--binary") == staged
    assert _git(repo, "diff", "--binary") == unstaged
    if mixed:
        assert _git(repo, "show", "HEAD:calc.py") == "# hub modification\n"
        assert _git(repo, "show", "HEAD:hub-new.txt") == "keep\n"
    if refused == "private/new.txt":
        assert (repo / refused).read_text() == "local only\n"
        assert _git(repo, "ls-files", "--", refused) == ""
        assert _git(repo, "check-ignore", "--", refused).strip() == refused
    if refused:
        retry_sha, retry_failed = hw.commit_sync(repo, [refused], [], "refused only")
        assert retry_sha == "" and [path for path, _ in retry_failed] == [refused]
        assert _git(repo, "rev-parse", "--short", "HEAD").strip() == sha
        assert _git(repo, "diff", "--cached", "--binary") == staged
        assert _git(repo, "diff", "--binary") == unstaged


def test_sync_commits_deletion_with_new_ignore_and_does_not_replay(repo, tmp_path):
    plan = hw.plan_upload(repo, known=[])
    before = _git(repo, "rev-parse", "HEAD").strip()
    snap = _tar_of({
        "calc.py": b"# hub modification\n",
        ".gitignore": b"/private/\n",
        "private/new.txt": b"local only\n",
    }, tmp_path)
    result = hw.apply_changes(snap, repo, plan.manifest, known=[])
    assert set(result.changed) == {"calc.py", ".gitignore", "private/new.txt"}
    assert result.deleted == ["src/keep.txt"]
    assert not result.conflicts and not result.rejected

    sha, failed = hw.commit_sync(repo, result.changed, result.deleted, "hub return")

    assert sha and [path for path, _ in failed] == ["private/new.txt"]
    assert set(_git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()) == {
        "calc.py", ".gitignore", "src/keep.txt"}
    assert _git(repo, "status", "--porcelain") == ""
    assert _git(repo, "ls-files", "--", "private/new.txt") == ""
    assert (repo / "private/new.txt").read_bytes() == b"local only\n"
    again = hw.apply_changes(snap, repo, result.manifest, known=[])
    assert again.changed == [] and again.deleted == []
    assert not again.conflicts and not again.rejected
    assert hw.commit_sync(repo, again.changed, again.deleted, "same snapshot") == ("", [])
    assert _git(repo, "rev-parse", "--short", "HEAD").strip() == sha
    assert _git(repo, "rev-list", "--count", f"{before}..HEAD").strip() == "1"


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


def _two_dirs(repo):
    for d in ("a", "b", "c"):
        (repo / d).mkdir()
        (repo / d / "mod.py").write_text(f"NAME = '{d}'\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "dirs")


@pytest.mark.asyncio
async def test_owned_dirs_changed_between_turns_reach_the_hub_on_the_next_turn(repo, tmp_path, monkeypatch):
    """V-1021: turn 1 owned=[a]; ownership grows to [a, b]; turn 2 must have b on the hub."""
    _two_dirs(repo)
    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [])
    owned: list[str] = ["a"]
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda d: None)
    backend._paths_source = lambda: tuple(owned)
    await _turn(backend, "one")
    remote = Path(backend._state.remote_dir)
    assert (remote / "a" / "mod.py").exists() and not (remote / "b").exists()
    owned[:] = ["a", "b"]
    events = await _turn(backend, "two")
    assert (remote / "b" / "mod.py").exists() and not (remote / "c").exists()
    assert events[-1].metadata["ok"] is True
    owned[:] = ["b"]                              # shrinking removes a from the hub copy, never from the worktree
    await _turn(backend, "three")
    assert not (remote / "a" / "mod.py").exists() and (repo / "a" / "mod.py").exists()
    owned[:] = []                                 # cleared ownership: refused for a non-persistent project
    events = await _turn(backend, "four")
    assert events[-1].metadata["ok"] is False and "set_worker_owned_dirs" in "".join(e.content for e in events)
    assert (repo / "a" / "mod.py").exists() and (repo / "b" / "mod.py").exists()


def test_the_session_hands_its_live_owned_dirs_to_the_hub_backend(monkeypatch):
    from datetime import datetime, timezone

    from app.session import AgentSession

    for key, value in {"MULTICODE_MCP_BASE": "http://x", "MULTICODE_MCP_TOKEN": "t",
                       "MULTICODE_HUB_SSH": "u@h", "MULTICODE_HUB_SSH_KEY": "/k"}.items():
        monkeypatch.setenv(key, value)
    session = AgentSession(id="i", name="w", scope="/p/big", cwd="/p/big/wt", model="hub-claude-haiku-5-5",
                           system_prompt="x", role="worker", owned_dirs=["a"],
                           created_at=datetime.now(timezone.utc))
    backend = session._make_backend()
    assert backend._paths_source() == ("a",)
    session.owned_dirs = ["a", "b"]               # what apply_owned_dirs does to the live session
    assert backend._paths_source() == ("a", "b")


# ── copy only what the worker needs (owner decision, V-1008) ─────────────────────────


def test_scope_is_required_unless_the_project_is_persistent():
    plain, persistent = hw.ProjectOptions(), hw.ProjectOptions(persistent=True)
    for paths in (None, [], ()):
        with pytest.raises(hw.HubWorkspaceError, match="set_worker_owned_dirs"):
            hw.require_scope(paths, plain)
        hw.require_scope(paths, persistent)
    hw.require_scope(["src"], plain)
    hw.require_scope(["src"], persistent)


@pytest.mark.asyncio
async def test_empty_owned_dirs_in_a_plain_project_is_refused_before_anything_is_uploaded(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [])
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda d: None)
    backend._paths = []
    events = await _turn(backend, "go")
    text = "".join(e.content for e in events)
    assert events[-1].metadata["ok"] is False and "set_worker_owned_dirs" in text and "persistent" in text
    assert not any(name in ("t3_project_create", "t3_thread_launch") for name, _ in mc.calls)
    assert not list((tmp_path / "hub").glob("hub-*/*")) and backend._state.uploaded is False
    backend._paths = ["calc.py"]                     # the orchestrator sets owned_dirs: the next turn goes through
    events = await _turn(backend, "go again")
    assert events[-1].metadata["ok"] is True and (Path(backend._state.remote_dir) / "calc.py").exists()
    assert not (Path(backend._state.remote_dir) / "src").exists()      # nothing beyond what it owns


@pytest.mark.asyncio
async def test_empty_owned_dirs_in_a_persistent_project_uploads_the_whole_tree(repo, tmp_path, monkeypatch):
    _persistent(tmp_path, monkeypatch, repo)
    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [])
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda d: None)
    backend._scope = str(repo)
    backend._paths = []
    events = await _turn(backend, "go")
    assert events[-1].metadata["ok"] is True
    remote = Path(backend._state.remote_dir)
    assert (remote / "calc.py").exists() and (remote / "src" / "keep.txt").exists()


# ── outbox: the only way back to Orchestra ───────────────────────────────────────────

from app import hub_outbox as ob      # noqa: E402


def _who(parent="boss"):
    return ob.Identity(session_id="sid-1", name="wrk", scope="/p/proj", parent_name=parent,
                       branch="task-V-9/x", pipeline="default")


class _Calls:
    def __init__(self, fail=None):
        self.calls: list[tuple[str, str, dict]] = []
        self.fail = fail

    async def __call__(self, method, path, body):
        self.calls.append((method, path, body))
        return {"error": self.fail} if self.fail else {"ok": True}


def test_outbox_parsing_keeps_only_the_three_tools_and_reports_the_rest():
    lines = "\n".join([
        json.dumps({"tool": "send_message", "args": {"message": "hi"}}),
        json.dumps({"tool": "spawn_worker", "args": {"name": "x"}}),
        json.dumps({"tool": "task_get", "args": {}}),
        "not json at all",
        json.dumps({"tool": "update_progress", "args": [1]}),
        json.dumps(["tool"]),
        json.dumps({"tool": "update_progress", "args": {"percent": 5, "status": "s"}}),
        "",
    ]).encode()
    entries, dropped = ob.parse_outbox(lines)
    assert [e["tool"] for e in entries] == ["send_message", "update_progress"]
    assert len(dropped) == 5 and any("spawn_worker" in d for d in dropped) and any("not JSON" in d for d in dropped)
    entries, dropped = ob.parse_outbox(b"\n".join(json.dumps({"tool": "update_progress", "args": {"percent": 1}}).encode()
                                                  for _ in range(ob.MAX_ENTRIES + 5)))
    assert len(entries) == ob.MAX_ENTRIES and dropped
    entries, dropped = ob.parse_outbox(b"x" * (ob.MAX_OUTBOX_BYTES + 10))
    assert not entries and dropped


@pytest.mark.asyncio
async def test_send_message_always_goes_to_the_parent_and_ignores_to_and_file_path():
    call = _Calls()
    entries = [{"tool": "send_message", "args": {"to": "someone-else", "message": "need a decision",
                                                  "file_path": "/etc/passwd", "delivery_id": "x"}}]
    report = await ob.execute(entries, _who("boss"), call)
    (method, path, body), = call.calls
    assert (method, path) == ("POST", "/api/sessions/boss/send") and report.done == ["send_message"]
    assert body["message"] == "need a decision" and body["sender"] == "wrk" and body["scope"] == "/p/proj"
    assert set(body) == {"message", "sender", "scope", "delivery_id"} and body["delivery_id"] != "x"
    call = _Calls()
    report = await ob.execute(entries, _who(""), call)            # no parent: nothing is sent anywhere
    assert not call.calls and "no parent" in report.dropped[0]


@pytest.mark.asyncio
async def test_progress_and_checklist_are_the_workers_own_and_bad_arguments_never_reach_the_api():
    call = _Calls()
    report = await ob.execute([
        {"tool": "update_progress", "args": {"percent": 40, "status": "halfway", "name": "other"}},
        {"tool": "update_checklist", "args": {"items": ["a", "b"], "completed": [0], "current": 1,
                                              "estimates_minutes": [3, 4], "name": "other"}},
        {"tool": "update_progress", "args": {"percent": "lots"}},
        {"tool": "update_checklist", "args": {"items": "a", "completed": []}},
    ], _who(), call)
    assert [c[1] for c in call.calls] == ["/api/sessions/wrk/progress", "/api/sessions/wrk/checklist"]
    assert call.calls[0][2] == {"percent": 40, "status": "halfway", "scope": "/p/proj"}
    assert call.calls[1][2]["estimates_minutes"] == [3, 4] and "name" not in call.calls[1][2]
    assert report.done == ["update_progress", "update_checklist"] and len(report.dropped) == 2


@pytest.mark.asyncio
async def test_api_refusals_and_failures_are_reported_not_raised():
    report = await ob.execute([{"tool": "update_progress", "args": {"percent": 1}}], _who(), _Calls(fail="not found"))
    assert report.dropped == ["update_progress: not found"] and "dropped" in report.summary()

    async def boom(*a):
        raise RuntimeError("connection refused")
    report = await ob.execute([{"tool": "update_progress", "args": {"percent": 1}},
                               {"tool": "update_progress", "args": {"percent": 2}}], _who(), boom)
    assert len(report.dropped) == 2 and not report.done


@pytest.mark.asyncio
async def test_local_api_call_uses_the_workers_own_proof(monkeypatch):
    import httpx

    seen = {}

    class Client:
        def __init__(self, **kw):
            seen["init"] = kw

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, path, json=None):
            seen["req"] = (method, path, json)
            return httpx.Response(200, json={"ok": True})
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    monkeypatch.setenv("INTERNAL_TOKEN", "tok-0123456789ab")
    monkeypatch.setenv("ORCHESTRA_URL", "http://127.0.0.1:1")
    from app.mcp_proof import issue_mcp_proof
    assert await ob.local_api_call(_who(), "POST", "/api/sessions/wrk/progress", {"percent": 1}) == {"ok": True}
    headers = seen["init"]["headers"]
    assert headers["X-Orchestra-Session-Id"] == "sid-1" and headers["X-Orchestra-Mcp-Proof"] == issue_mcp_proof("sid-1")
    assert seen["init"]["base_url"] == "http://127.0.0.1:1"


def _outbox_backend(repo, tmp_path, monkeypatch, lines, call):
    written = []

    def edit(workdir: Path):
        if written:                    # the hub agent queues its lines in the first turn only
            return
        written.append(True)
        (workdir / ob.OUTBOX_NAME).write_text("\n".join(
            line if isinstance(line, str) else json.dumps(line) for line in lines) + "\n")
        (workdir / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [])
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, edit)
    backend._bridge = ob.HubBridge(lambda: _who("boss"), call)
    return backend, ssh, mc


@pytest.mark.asyncio
async def test_hub_outbox_runs_allowed_tools_once_and_never_reaches_the_worktree(repo, tmp_path, monkeypatch):
    call = _Calls()
    backend, ssh, mc = _outbox_backend(repo, tmp_path, monkeypatch, [
        {"tool": "send_message", "args": {"to": "intruder", "message": "blocked on X"}},
        {"tool": "update_progress", "args": {"percent": 60, "status": "tests"}},
        {"tool": "merge_worker", "args": {"name": "wrk"}},
        "garbage",
    ], call)
    events = await _turn(backend, "go")
    text = events[-2].content
    assert [c[1] for c in call.calls] == ["/api/sessions/boss/send", "/api/sessions/wrk/progress"]
    assert "[hub outbox] 2 delivered" in text and "2 dropped" in text and "merge_worker" in text
    assert not (repo / ob.OUTBOX_NAME).exists() and ob.OUTBOX_NAME not in _git(repo, "ls-files")
    assert "calc.py" in _git(repo, "show", "--stat", "--format=", "HEAD")        # the real change was committed
    assert ob.OUTBOX_NAME not in _git(repo, "show", "--stat", "--format=", "HEAD")
    assert not (Path(backend._state.remote_dir) / ob.OUTBOX_NAME).exists()       # emptied on the hub
    assert ob.OUTBOX_NAME not in backend._state.manifest
    await _turn(backend, "again")                                                # the old lines are not re-run
    assert len(call.calls) == 2


@pytest.mark.asyncio
async def test_hub_outbox_without_a_link_to_orchestra_is_dropped_and_logged(repo, tmp_path, monkeypatch, caplog):
    backend, ssh, mc = _outbox_backend(repo, tmp_path, monkeypatch,
                                       [{"tool": "send_message", "args": {"message": "hi"}}], _Calls())
    backend._bridge = None
    with caplog.at_level("WARNING"):
        events = await _turn(backend, "go")
    assert "dropped" in events[-2].content and "no Orchestra link" in events[-2].content
    assert any("no Orchestra link" in r.message for r in caplog.records)
    assert not (repo / ob.OUTBOX_NAME).exists()


def test_a_local_file_named_like_the_outbox_is_never_uploaded(repo):
    (repo / ob.OUTBOX_NAME).write_text('{"tool":"send_message","args":{"message":"x"}}\n')
    plan = hw.plan_upload(repo, ["calc.py"], [])
    assert ob.OUTBOX_NAME not in plan.manifest


# ── the trimmed hub prompt ────────────────────────────────────────────────────────────


def _first_prompt(mc):
    return next(args["message"] for name, args in mc.calls if name == "t3_thread_launch")


@pytest.mark.asyncio
async def test_hub_model_gets_a_trimmed_prompt_with_the_outbox_tools(repo, tmp_path, monkeypatch):
    backend, ssh, mc = _outbox_backend(repo, tmp_path, monkeypatch, [], _Calls())
    await _turn(backend, "implement the thing")
    prompt = _first_prompt(mc)
    assert "worker wrk" in prompt and "orchestrator boss" in prompt and "task-V-9/x" in prompt
    assert ob.OUTBOX_NAME in prompt and "send_message" in prompt and "update_progress" in prompt
    assert "update_checklist" in prompt and "goes to your orchestrator boss only" in prompt
    assert "Do not run git push/clone/commit" in prompt
    assert prompt.rstrip().endswith("implement the thing") and "Task:\nimplement the thing" in prompt
    from app.manager import ROLE_SYSTEM_PROMPT
    full = ROLE_SYSTEM_PROMPT("default", "worker")
    assert len(prompt.split("Task:\n")[0]) < len(full) / 2              # materially lighter than the native prompt
    for native_only in ("spawn_worker", "task_get", "bg_create", "mcp__", "get_worker_logs", "search_logs"):
        assert native_only not in prompt.split("Task:\n")[0], native_only


@pytest.mark.asyncio
async def test_hub_prompt_has_no_outbox_section_when_nothing_can_run_it(repo, tmp_path, monkeypatch):
    backend, ssh, mc = _outbox_backend(repo, tmp_path, monkeypatch, [], _Calls())
    backend._bridge = None
    await _turn(backend, "plain task")
    prompt = _first_prompt(mc)
    assert ob.OUTBOX_NAME not in prompt and "plain task" in prompt


def test_hub_prompt_without_a_parent_offers_no_send_message():
    text = backend_hub.hub_preamble(_who(""), "V-9", has_link=True)
    assert "update_progress" in text and "send_message" not in text and ".orchestra/tasks/V-9/" in text


def test_the_session_gives_the_hub_backend_its_identity_and_bridge(monkeypatch):
    from datetime import datetime, timezone

    from app.session import AgentSession

    for key, value in {"MULTICODE_MCP_BASE": "http://x", "MULTICODE_MCP_TOKEN": "t",
                       "MULTICODE_HUB_SSH": "u@h", "MULTICODE_HUB_SSH_KEY": "/k"}.items():
        monkeypatch.setenv(key, value)
    session = AgentSession(id="i-1", name="w1", scope="/p/big", cwd="/p/big/wt", model="hub-claude-haiku-5-5",
                           system_prompt="x", role="worker", parent_name="orch-9",
                           created_at=datetime.now(timezone.utc))
    backend = session._make_backend()
    who = backend._bridge.identity()
    assert (who.session_id, who.name, who.parent_name, who.scope) == ("i-1", "w1", "orch-9", "/p/big")
    native = AgentSession(id="i-2", name="w2", scope="/p/big", cwd="/p/big/wt", model="claude-haiku-5-5",
                          system_prompt="x", role="worker", created_at=datetime.now(timezone.utc))
    assert native._make_backend() is not None      # other runtimes are unaffected by the hub bridge


# ── stale workspace after a task switch, and a false conflict on turn 2 (V-1008) ──────


def _report_editor(texts):
    """A hub agent that rewrites its own task report (outside the worker's owned_dirs) every turn."""
    turn = []

    def edit(workdir: Path):
        turn.append(1)
        target = workdir / ".orchestra" / "tasks" / "V-1" / "report.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(texts[min(len(turn), len(texts)) - 1])
    return edit


@pytest.mark.asyncio
async def test_a_report_the_hub_wrote_outside_owned_dirs_is_not_a_conflict_on_turn_two(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [])
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, _report_editor(["one\n", "two\n"]))
    backend._paths = ["calc.py"]
    report = repo / ".orchestra" / "tasks" / "V-1" / "report.md"
    events = await _turn(backend, "first")
    assert report.read_text() == "one\n" and "conflicts" not in events[-2].content
    assert "report.md" in _git(repo, "show", "--stat", "--format=", "HEAD")      # the platform committed it
    events = await _turn(backend, "second")
    assert "conflicts" not in events[-2].content, events[-2].content
    assert report.read_text() == "two\n"
    assert backend._state.hub_made == [".orchestra/tasks/V-1/report.md"]


@pytest.mark.asyncio
async def test_a_real_local_edit_of_such_a_report_is_still_a_conflict(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [])
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, _report_editor(["one\n", "hub two\n"]))
    backend._paths = ["calc.py"]
    report = repo / ".orchestra" / "tasks" / "V-1" / "report.md"
    await _turn(backend, "first")
    report.write_text("the orchestrator's own edit\n")
    events = await _turn(backend, "second")
    assert "conflicts (both sides changed" in events[-2].content
    assert report.read_text() == "the orchestrator's own edit\n"


def test_files_the_hub_made_stay_but_stale_uploads_are_still_dropped(repo):
    plan = hw.plan_upload(repo, ["calc.py"], [])
    manifest = dict(plan.manifest)
    manifest["src/keep.txt"] = "old"              # uploaded earlier, owned_dirs shrank since
    manifest["notes/report.md"] = "x"             # made by the hub
    _, drop = hw.local_delta(repo, plan, manifest, keep={"notes/report.md"})
    assert drop == ["src/keep.txt"]
    assert hw.local_delta(repo, plan, manifest)[1] == ["notes/report.md", "src/keep.txt"]


@pytest.mark.asyncio
async def test_a_workspace_released_behind_the_backend_is_not_reused(repo, tmp_path, monkeypatch, no_wait):
    """Merge released the hub copy; the live backend kept its old state and every launch failed."""
    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [])
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda d: None)
    backend._paths = ["calc.py"]
    mc.strict_projects = True
    await _turn(backend, "first")
    old = backend._state
    await hw.release_workspace(old, ssh, mc)
    assert not old.path().exists() and not Path(old.remote_dir).exists()
    events = await _turn(backend, "after the merge and a task switch")
    assert events[-1].metadata["ok"] is True, [(e.type, e.content) for e in events]
    assert backend._state.ws_id != old.ws_id and (Path(backend._state.remote_dir) / "calc.py").exists()
    assert [n for n, _ in mc.calls].count("t3_project_create") == 2
    assert backend._state.path().exists() and not old.path().exists()


@pytest.mark.asyncio
async def test_a_lost_hub_project_is_recreated_and_uploaded_again_once(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [])
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda d: None)
    backend._paths = ["calc.py"]
    mc.strict_projects = True
    await _turn(backend, "first")
    state = backend._state
    mc.known_projects.clear()                                  # the hub forgot the project
    state.project_id, state.thread_id = "mcp:gone", ""
    import shutil
    shutil.rmtree(state.remote_dir)                            # and its copy
    events = await _turn(backend, "second")
    assert events[-1].metadata["ok"] is True
    assert any("recreating" in e.content for e in events if e.type == "status")
    assert (Path(state.remote_dir) / "calc.py").exists() and state.project_id == "proj-1" and state.thread_id
    launches = [a for n, a in mc.calls if n == "t3_thread_launch"]
    assert len(launches) == 3 and "Task:\nsecond" in launches[-1]["message"]   # the preamble came along
    # a project that stays gone is reported, not retried forever
    mc.known_projects.clear()
    mc.project_dir = ""

    async def always_fail(name, args, real=mc.tool_call):
        if name == "t3_thread_launch":
            from app.multicode_client import MultiCodeError
            raise MultiCodeError('{"code":"orchestration_error"}')
        return await real(name, args)
    mc.tool_call = always_fail
    state.project_id, state.thread_id = "mcp:gone", ""
    events = await _turn(backend, "third")
    assert events[-1].metadata["ok"] is False


@pytest.mark.asyncio
async def test_a_branch_or_task_switch_releases_the_hub_copy_but_a_plain_save_does_not(monkeypatch):
    from types import SimpleNamespace

    from app import manager as manager_module
    from app.session import AgentStatus

    released = []

    async def fake_release(worktree, name):
        released.append((worktree, name))
    monkeypatch.setattr(manager_module, "_release_hub_workspaces", fake_release)
    monkeypatch.setattr(manager_module, "update_session_lifecycle", lambda *a, **k: True)
    mgr = object.__new__(manager_module.SessionManager)

    def session(status=AgentStatus.IDLE):
        return SimpleNamespace(id="s", name="w", loaded=False, branch="task-V-1/x", base_branch="main",
                               task_id="V-1", needs_switch=False, worktree_path="/wt", db_row=None, status=status)

    async def move(sess, branch, task):
        await mgr.persist_lifecycle(sess, branch=branch, base_branch="main", task_id=task, needs_switch=False)
    await move(session(), "task-V-1/x", "V-1")                   # nothing moved
    assert released == []
    await move(session(), "task-V-2/y", "V-2")                   # switch_worker_branch
    assert released == [("/wt", "w")]
    await move(session(AgentStatus.RUNNING), "task-V-3/z", "V-3")   # never under a running turn
    assert released == [("/wt", "w")]


# ── owned paths outside the sparse checkout (V-1008) ──────────────────────────────────


@pytest.fixture
def sparse_repo(repo):
    """A worktree whose cone holds only src/: artifacts/ and docs/ are committed but not on disk."""
    for rel, text in (("artifacts/report.md", "r\n"), ("artifacts/data/rows.csv", "1,2\n"), ("docs/guide.md", "g\n")):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "more")
    _git(repo, "sparse-checkout", "init", "--cone")
    _git(repo, "sparse-checkout", "set", "src")
    assert not (repo / "artifacts").exists() and not (repo / "docs").exists()
    return repo


def test_an_owned_dir_outside_the_cone_is_materialized_and_uploaded(sparse_repo):
    plan = hw.plan_upload(sparse_repo, ["artifacts"], [])
    assert {"artifacts/report.md", "artifacts/data/rows.csv"} <= set(plan.manifest)
    assert plan.materialized == ["artifacts"] and plan.new_paths == []
    assert (sparse_repo / "artifacts" / "report.md").exists()
    assert "artifacts" in _git(sparse_repo, "sparse-checkout", "list").split()
    assert not (sparse_repo / "docs").exists()                  # only what the worker owns


def test_an_owned_file_outside_a_cone_comes_with_its_directory(sparse_repo):
    plan = hw.plan_upload(sparse_repo, ["docs/guide.md"], [])
    assert "docs/guide.md" in plan.manifest and plan.materialized == ["docs/guide.md"]


def test_an_owned_path_outside_a_non_cone_sparse_checkout_is_materialized(repo):
    (repo / "artifacts").mkdir()
    (repo / "artifacts" / "report.md").write_text("r\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "more")
    _git(repo, "sparse-checkout", "init", "--no-cone")
    _git(repo, "sparse-checkout", "set", "/src/")
    assert not (repo / "artifacts").exists()
    plan = hw.plan_upload(repo, ["artifacts/report.md"], [])
    assert "artifacts/report.md" in plan.manifest and plan.materialized == ["artifacts/report.md"]


def test_a_path_inside_the_cone_is_left_alone(sparse_repo):
    plan = hw.plan_upload(sparse_repo, ["src"], [])
    assert plan.materialized == [] and "src/keep.txt" in plan.manifest
    assert _git(sparse_repo, "sparse-checkout", "list").split() == ["src"]


def test_a_path_that_is_not_in_head_is_allowed_and_reported_as_new(sparse_repo):
    plan = hw.plan_upload(sparse_repo, ["src", "tools/brand_new/"], [])
    assert plan.new_paths == ["tools/brand_new/"] and plan.materialized == []
    assert "src/keep.txt" in plan.manifest                                           # the rest still goes
    assert not (sparse_repo / "tools").exists()                              # nothing is invented locally


@pytest.mark.asyncio
async def test_the_upload_status_line_names_new_and_materialized_paths(sparse_repo, tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [])
    backend, ssh, mc = _backend(sparse_repo, tmp_path, monkeypatch, lambda d: None)
    backend._paths = ["artifacts", "out/fresh.txt"]
    events = await _turn(backend, "go")
    note = next(e.content for e in events if e.type == "status" and e.content.startswith("hub: uploading"))
    assert "new: out/fresh.txt" in note and "added to the sparse checkout: artifacts" in note
    assert (Path(backend._state.remote_dir) / "artifacts" / "report.md").read_text() == "r\n"


def test_an_empty_plan_for_owned_paths_that_exist_in_head_is_refused_by_name(repo):
    (repo / "src" / "keep.txt").unlink()                        # committed, gone from the worktree
    with pytest.raises(hw.HubWorkspaceError) as caught:
        hw.plan_upload(repo, ["src"], [])
    assert "src" in str(caught.value) and "Nothing was uploaded" in str(caught.value)


def test_an_empty_plan_is_refused_when_every_owned_file_is_excluded(repo):
    (repo / "keys").mkdir()
    (repo / "keys" / ".env").write_text("A=1\n")
    _git(repo, "add", "-f", ".")
    _git(repo, "commit", "-qm", "env")
    with pytest.raises(hw.HubWorkspaceError, match="keys"):
        hw.plan_upload(repo, ["keys"], [])


def test_one_good_owned_path_keeps_the_turn_alive_and_only_all_new_paths_pass(repo):
    (repo / "src" / "keep.txt").unlink()
    plan = hw.plan_upload(repo, ["src", "calc.py"], [])            # calc.py produced a file
    assert "calc.py" in plan.manifest
    plan = hw.plan_upload(repo, ["brand/new.py"], [])              # nothing in HEAD: not a refusal
    assert plan.new_paths == ["brand/new.py"]


def test_a_refused_scope_uploads_nothing_through_the_backend(repo, tmp_path, monkeypatch):
    import asyncio

    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [])
    (repo / "src" / "keep.txt").unlink()
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda d: None)
    backend._paths = ["src"]
    events = asyncio.run(_turn(backend, "go"))
    assert events[-1].metadata["ok"] is False and any("src" in e.content for e in events if e.type == "error")
    assert not any(n == "t3_project_create" for n, _ in mc.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("model,alternative", [
    ("hub-claude-sonnet-5-5", "hubsol"), ("hub-gpt-6.1-sol", "hubsonnet"),
])
@pytest.mark.parametrize("source", ["reply", "status", "exception"])
async def test_provider_limit_fails_turn_and_notifies_exact_parent(
    repo, tmp_path, monkeypatch, model, alternative, source,
):
    from app.hub_outbox import HubBridge, Identity
    from app.multicode_client import MultiCodeError

    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda d: None)
    backend.model = model
    original = mc.tool_call
    calls = []

    async def call(name, args):
        if source == "exception" and name == "t3_thread_launch":
            raise MultiCodeError("rate_limit_exceeded for private@example.invalid")
        if name == "t3_thread_wait":
            if source == "status":
                return {"status": "failed", "error": {"code": "usage_limit_reached",
                                                        "message": "private@example.invalid"}}
            return {"status": "completed"}
        if source == "reply" and name == "t3_thread_read" and args.get("view") == "messages":
            return {"items": [{"createdBy": "agent", "type": "assistant_message", "runId": "run-1",
                               "text": "You've hit your usage limit. Try again after reset."}]}
        return await original(name, args)

    async def api(method, path, body):
        calls.append((method, path, body))
        return {"ok": True}

    mc.tool_call = call
    backend._bridge = HubBridge(lambda: Identity("worker-id", "worker", "/scope", parent_name="parent"), api)
    events = await _turn(backend, "go")
    error = next(e for e in events if e.type == "error")
    assert "limit" in error.content and f"model='{alternative}'" in error.content
    assert error.metadata["hub_provider_limit"] is True
    assert events[-1].metadata["ok"] is False
    assert events[-1].metadata["stop_reason"] == "hub_provider_limit"
    assert len(calls) == 1
    assert calls[0][1] == "/api/sessions/parent/send"
    assert calls[0][2]["sender"] == "worker" and calls[0][2]["scope"] == "/scope"
    assert f"model='{alternative}'" in calls[0][2]["message"]
    assert "private@example.invalid" not in error.content + calls[0][2]["message"]


@pytest.mark.asyncio
async def test_pool_refusal_prevents_upload_and_new_hub_turn(repo, tmp_path, monkeypatch):
    from app import hub_pool

    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda d: None)

    async def pool(**kwargs):
        return {"available": True, "providers": {"claude": {
            "usable": 0, "accounts": 10, "threshold_pct": 100}}}
    monkeypatch.setattr(hub_pool, "get_hub_pool", pool)
    events = await _turn(backend, "go")
    assert any(e.type == "error" and "model='hubsol'" in e.content for e in events)
    assert not mc.calls and backend._state is None
    assert events[-1].metadata["ok"] is False


@pytest.mark.asyncio
async def test_relay_unavailable_is_visible_and_turn_still_runs(repo, tmp_path, monkeypatch):
    from app import hub_pool

    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda d: None)

    async def pool(**kwargs):
        return {"available": False, "providers": {}}
    monkeypatch.setattr(hub_pool, "get_hub_pool", pool)
    events = await _turn(backend, "go")
    assert any(e.type == "status" and "pool unavailable" in e.content for e in events)
    assert events[-1].metadata["ok"] is True


@pytest.mark.asyncio
async def test_successful_limit_implementation_report_is_not_provider_failure(repo, tmp_path, monkeypatch):
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda d: None)
    original = mc.tool_call

    async def call(name, args):
        if name == "t3_thread_read" and args.get("view") == "messages":
            return {"items": [{"createdBy": "agent", "type": "assistant_message", "runId": "run-1",
                               "text": "Implemented usage limit detection and rate limit tests."}]}
        return await original(name, args)
    mc.tool_call = call
    events = await _turn(backend, "go")
    assert events[-1].metadata["ok"] is True
    assert not any(e.type == "error" for e in events)


@pytest.mark.parametrize("detail,kind", [
    ("Weekly usage limit reached", "Weekly usage limit"),
    ("5-hour limit reached", "5h usage limit"),
    ("rate_limit_exceeded", "rate limit"),
    ("usage_limit_reached", "usage limit"),
    ("context_limit_reached", None),
    ("max_turns_limit_exceeded", None),
    ("connection reset", None),
])
def test_limit_errors_name_the_window_and_exclude_other_failures(detail, kind):
    assert backend_hub._provider_limit(detail) == kind
