"""Offline return packaging and transport-only retry of a retained workspace."""

import asyncio
import io
import shlex
import tarfile
from unittest.mock import AsyncMock

import pytest

from app import backend_hub, hub_workspace as hw
from tests.test_hub_uv import ShellSsh
from tests.test_hub_workspace import _backend, _git, _offline_hub_pool, _turn, repo


def put(root, rel, data):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


@pytest.mark.asyncio
async def test_old_packaging_overflows_on_blocked_caches_new_packaging_recovers(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "MAX_TOTAL_BYTES", 64 * 1024)
    remote = tmp_path / "hub-0123456789abcdef"
    remote.mkdir()
    baseline = hw.plan_upload(repo, known=[]).manifest
    for rel in baseline:
        put(remote, rel, (repo / rel).read_bytes())
    for name in hw.BLOCKED_DIRS:
        put(remote, f"tools/{name}/cache.bin", b"cache")
    for rel in ("nested/.venv/lib/huge.bin", "web/node_modules/pkg/huge.bin", "venv/huge.bin"):
        put(remote, rel, b"x" * (256 * 1024))
    put(remote, "tools/custom-env/pyvenv.cfg", b"home = /synthetic\n")
    put(remote, "tools/custom-env/lib/huge.bin", b"x" * (256 * 1024))
    wanted = {
        "calc.py": b"fixed source\n",
        "results/result.json": b'{"ok": true}\n',
        ".orchestra/tasks/V-1/report.md": b"report\n",
        "media/demo.mp4": b"\0synthetic video bytes",
        "web/node_modules-notes/keep.txt": b"legitimate\n",
        "tools/custom-env-sibling/keep.py": b"legitimate\n",
        "tmp/ghidra-early.rep/idata/annotations": b"unique analysis\n",
        "tmp/sdk/tool": b"SDK material is not name-blocked\n",
        "tmp/ghidra.zip": b"\0synthetic SDK archive",
        ".env.example": b"EXAMPLE=placeholder\n",
    }
    for rel, data in wanted.items():
        put(remote, rel, data)
    ssh = ShellSsh()
    old = tmp_path / "old.tar"
    with pytest.raises(hw.HubWorkspaceError, match="limit 131072 bytes"):
        await ssh.run(f"tar -cf - -C {shlex.quote(str(remote))} --exclude=./.git --exclude=./.venv .",
                      stdout=old, max_out=hw.MAX_TOTAL_BYTES * 2)
    out = tmp_path / "new.tar"
    await ssh.get(str(remote), out)
    with tarfile.open(out) as archive:
        names = {m.name.removeprefix("./") for m in archive if m.isfile()}
    assert names == set(baseline) | set(wanted) | {"tools/custom-env/pyvenv.cfg"}
    assert out.stat().st_size < 131072
    result = hw.apply_changes(out, repo, baseline, known=[])
    assert result.deleted == result.conflicts == []
    assert set(result.changed) == set(wanted)
    for rel, data in wanted.items():
        assert (repo / rel).read_bytes() == data
    assert (remote / "nested/.venv/lib/huge.bin").stat().st_size == 256 * 1024


@pytest.mark.asyncio
async def test_exclusions_do_not_delete_legacy_manifest_entries(repo, tmp_path):
    remote = tmp_path / "hub-0123456789abcdef"
    remote.mkdir()
    put(remote, "custom/pyvenv.cfg", b"home = /synthetic\n")
    put(remote, "custom/cache.py", b"new cache\n")
    manifest = {}
    for rel in ("custom/old.py", "nested/node_modules/old.js", "nested/.venv/old.py"):
        manifest[rel] = hw.sha256_file(put(repo, rel, b"local legacy\n"))
    out = tmp_path / "out.tar"
    await ShellSsh().get(str(remote), out)
    result = hw.apply_changes(out, repo, manifest, known=[])
    assert result.changed == result.deleted == []
    assert result.manifest == manifest
    assert all((repo / rel).read_bytes() == b"local legacy\n" for rel in manifest)


@pytest.mark.asyncio
async def test_genuine_oversize_refuses_without_mutating_worktree_state_or_remote(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "MAX_TOTAL_BYTES", 64 * 1024)
    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [])
    remote = tmp_path / "hub-0123456789abcdef"
    output = put(remote, "results/large.mp4", b"\0" * (256 * 1024))
    manifest = hw.plan_upload(repo, known=[]).manifest
    state = hw.WorkspaceState(remote.name, str(repo), str(remote), manifest=manifest,
                              uploaded=True, thread_id="retained-thread", input_manifest={})
    state.save()
    before = state.path().read_bytes()
    head = _git(repo, "rev-parse", "HEAD")
    backend = backend_hub.HubBackend("hub-gpt-6.1-sol", str(repo))
    for attempt in range(2):
        scratch = tmp_path / f"attempt{attempt}"
        scratch.mkdir()
        with pytest.raises(hw.HubWorkspaceError) as error:
            await backend._sync_back(ShellSsh(), state, repo, scratch)
        message = str(error.value)
        assert "received at least 131073 bytes" in message
        assert "limit 131072 bytes" in message and remote.name in message
        assert (scratch / "out.tar").stat().st_size <= 131072
        assert state.path().read_bytes() == before
        assert not (repo / "results").exists()
        assert _git(repo, "rev-parse", "HEAD") == head
        assert output.stat().st_size == 256 * 1024


@pytest.mark.asyncio
async def test_transport_only_retry_commits_current_outputs_once_and_keeps_input_originals(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [])
    original = put(repo, "inputs/original.bin", b"\0immutable original")
    manifest = hw.plan_upload(repo, known=[]).manifest
    remote = tmp_path / "hub-0123456789abcdef"
    for rel in manifest:
        put(remote, rel, (repo / rel).read_bytes())
    state = hw.WorkspaceState(remote.name, str(repo), str(remote), manifest=dict(manifest),
                              uploaded=True, thread_id="retained-thread", project_id="retained-project")
    hw.capture_inputs(repo, state, manifest)
    state.save()
    # Recovery starts from a persisted pre-failure record; the hub already holds turn outputs.
    state = hw.WorkspaceState.load(state.ws_id)
    assert state.input_manifest == {"inputs/original.bin": hw.sha256_file(original)}
    wanted = {"calc.py": b"current fixed code\n", "results/output.json": b'{}\n',
              ".orchestra/tasks/V-1/report.md": b"current report\n", "media/demo.mp4": b"\0current video"}
    for rel, data in wanted.items():
        put(remote, rel, data)
    put(remote, "nested/node_modules/pkg/cache", b"cache")
    backend = backend_hub.HubBackend("hub-gpt-6.1-sol", str(repo))
    for name in ("_client", "_provision", "_start", "send", "connect"):
        monkeypatch.setattr(backend, name, AsyncMock(side_effect=AssertionError(name)))
    ssh = ShellSsh()
    monkeypatch.setattr(ssh, "put", AsyncMock(side_effect=AssertionError("upload refresh")))
    monkeypatch.setattr(ssh, "ensure_uv", AsyncMock(side_effect=AssertionError("provision uv")))
    monkeypatch.setattr(ssh, "delete_files", AsyncMock(side_effect=AssertionError("remote deletion")))
    monkeypatch.setattr(ssh, "remove", AsyncMock(side_effect=AssertionError("workspace deletion")))
    initial_count = int(_git(repo, "rev-list", "--count", "HEAD"))
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    note = await backend._sync_back(ssh, state, repo, scratch)
    assert "changed 4, deleted 0, commit" in note and "return archive" in note
    assert "NOT COMMITTED" not in note
    assert int(_git(repo, "rev-list", "--count", "HEAD")) == initial_count + 1
    assert set(_git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()) == set(wanted)
    for rel, data in wanted.items():
        assert (repo / rel).read_bytes() == data
    assert original.read_bytes() == b"\0immutable original"
    assert _git(repo, "ls-files", "inputs/original.bin") == ""
    assert state.input_manifest == hw.WorkspaceState.load(state.ws_id).input_manifest
    head = _git(repo, "rev-parse", "HEAD")
    note = await backend._sync_back(ssh, state, repo, scratch)
    assert "changed 0, deleted 0" in note
    assert _git(repo, "rev-parse", "HEAD") == head
    assert state.ws_id == remote.name and state.thread_id == "retained-thread"
    assert state.project_id == "retained-project" and remote.is_dir()
    # Recovery may inspect names before downloading; it still performs no
    # provisioning, model call, upload or deletion (all forbidden above).
    downloads = [command for command, _ in ssh.calls if command.startswith("tar -cf")]
    inspections = [command for command, _ in ssh.calls if command.startswith("if test -L ")]
    assert len(downloads) == len(inspections) == 2 and len(ssh.calls) == 4
    assert all(stdin is None for _, stdin in ssh.calls)


@pytest.mark.asyncio
async def test_sync_failure_is_visible_as_failed_turn_without_model_resend(repo, tmp_path, monkeypatch):
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda _: None)
    async def refused(*args):
        raise hw.HubWorkspaceError("synthetic transport refusal")
    monkeypatch.setattr(ssh, "get", refused)
    events = await _turn(backend, "go")
    assert events[-1].type == "turn_end" and events[-1].metadata["ok"] is False
    assert any("hub sync FAILED" in event.content for event in events)
    assert backend._state.path().exists() and not ssh.removed
    assert [name for name, _ in mc.calls if name in {"t3_thread_launch", "t3_thread_send"}] == ["t3_thread_launch"]


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [0, 1024, 1025])
async def test_download_limit_exact_boundary(tmp_path, size):
    out = tmp_path / "download"
    ssh = ShellSsh()
    command = f"head -c {size} /dev/zero"
    if size <= 1024:
        await ssh.run(command, stdout=out, max_out=1024)
        assert out.stat().st_size == size
    else:
        with pytest.raises(hw.HubWorkspaceError, match="received at least 1025 bytes, limit 1024 bytes"):
            await ssh.run(command, stdout=out, max_out=1024)
        assert out.stat().st_size <= 1024


@pytest.mark.asyncio
async def test_download_timeout_and_failed_tar_do_not_apply_partial_output(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [])
    state = hw.WorkspaceState("hub-0123456789abcdef", str(repo), str(tmp_path / "hub-0123456789abcdef"),
                              manifest=hw.plan_upload(repo, known=[]).manifest, input_manifest={})
    state.save()
    before = state.path().read_bytes()
    ssh = ShellSsh()
    backend = backend_hub.HubBackend("hub-gpt-6.1-sol", str(repo))
    # Missing directory / tar failure is fatal, even if stdout created a partial file.
    with pytest.raises(hw.HubWorkspaceError, match="retained workspace"):
        await backend._sync_back(ssh, state, repo, tmp_path)
    assert state.path().read_bytes() == before
    assert (repo / "calc.py").exists()
    with pytest.raises(hw.HubWorkspaceError, match="timed out"):
        await ssh.run("exec tail -f /dev/null", stdout=tmp_path / "timeout", timeout=0.05)


def test_truncated_tar_never_applies_earlier_members_or_deletes_originals(repo, tmp_path):
    archive = tmp_path / "truncated.tar"
    with tarfile.open(archive, "w") as handle:
        info = tarfile.TarInfo("calc.py")
        info.size = 3
        handle.addfile(info, io.BytesIO(b"new"))
        info = tarfile.TarInfo("new.bin")
        info.size = 20000
        handle.addfile(info, io.BytesIO(b"x" * info.size))
    archive.write_bytes(archive.read_bytes()[:2048])
    before = (repo / "calc.py").read_bytes()
    with pytest.raises(tarfile.TarError):
        hw.apply_changes(archive, repo, hw.plan_upload(repo, known=[]).manifest, known=[])
    assert (repo / "calc.py").read_bytes() == before
    assert (repo / "src/keep.txt").exists()


@pytest.mark.asyncio
async def test_cancelled_download_reaps_its_process(tmp_path, monkeypatch):
    real_spawn = asyncio.create_subprocess_exec
    spawned = asyncio.Event()
    processes = []

    async def capture(*args, **kwargs):
        process = await real_spawn(*args, **kwargs)
        processes.append(process)
        spawned.set()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", capture)
    task = asyncio.create_task(ShellSsh().run("exec tail -f /dev/null", stdout=tmp_path / "cancelled"))
    await spawned.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(processes) == 1 and processes[0].returncode is not None


@pytest.mark.asyncio
async def test_return_tar_does_not_follow_remote_symlinks(repo, tmp_path):
    remote = tmp_path / "hub-0123456789abcdef"
    remote.mkdir()
    outside = put(tmp_path, "outside/should-not-travel.txt", b"outside\n")
    (remote / "dirlink").symlink_to(outside.parent, target_is_directory=True)
    (remote / "filelink").symlink_to(outside)
    out = tmp_path / "out.tar"
    await ShellSsh().get(str(remote), out)
    with tarfile.open(out) as handle:
        assert not any(member.isfile() for member in handle)
    result = hw.apply_changes(out, repo, {}, known=[])
    assert result.changed == result.deleted == []
    assert {rel for rel, reason in result.rejected if "not a regular file" in reason} == {"dirlink", "filelink"}


@pytest.mark.asyncio
async def test_failed_local_download_write_reaps_process(tmp_path, monkeypatch):
    out = tmp_path / "full-disk"
    real_open = type(out).open
    real_spawn = asyncio.create_subprocess_exec
    processes = []

    class FullDisk(io.BytesIO):
        def write(self, data):
            raise OSError("synthetic disk full")

    def open_file(path, *args, **kwargs):
        return FullDisk() if path == out else real_open(path, *args, **kwargs)

    async def capture(*args, **kwargs):
        process = await real_spawn(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(type(out), "open", open_file)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", capture)
    try:
        with pytest.raises(OSError, match="synthetic disk full"):
            await ShellSsh().run("exec cat /dev/zero", stdout=out)
        assert len(processes) == 1 and processes[0].returncode is not None
    finally:
        for process in processes:
            if process.returncode is None:
                process.kill()
                await process.communicate()
