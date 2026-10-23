"""Pinned uv provisioning with fake SSH; no network, provider CLI or real hub."""

import asyncio
import hashlib
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import hub_workspace as hw


class ShellSsh(hw.HubSsh):
    """Execute the actual remote commands in a temporary HOME, without using SSH."""

    def __init__(self):
        super().__init__("unused", "unused", "")
        self.calls = []
        self.corrupt_upload = False

    def _argv(self, remote):
        return ["/bin/bash", "-c", remote]

    async def run(self, remote, **kwargs):
        self.calls.append((remote, kwargs.get("stdin")))
        if self.corrupt_upload and kwargs.get("stdin"):
            kwargs["stdin"].write_bytes(b"corrupted transport")
        return await super().run(remote, **kwargs)


@pytest.fixture
def toolchain(tmp_path, monkeypatch):
    home = tmp_path / "hub home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    version = f"uv {hw.HUB_UV_VERSION} (x86_64-unknown-linux-gnu)"
    payload = f"#!/bin/sh\nprintf '%s\\n' '{version}'\n".encode()

    # This fixture isolates transfer/installation from local ELF/version validation,
    # tested separately below. A shell script stands in for the executable on fake SSH.
    def snapshot(scratch):
        path = scratch / "uv-upload"
        path.write_bytes(payload)
        return path, hashlib.sha256(payload).hexdigest(), version

    monkeypatch.setattr(hw, "_uv_snapshot", snapshot)
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    return SimpleNamespace(ssh=ShellSsh(), scratch=scratch, home=home,
                           binary=home / hw.HUB_UV_BIN / "uv", payload=payload)


@pytest.mark.asyncio
async def test_uv_cold_install_and_warm_reuse(toolchain):
    t = toolchain
    await t.ssh.ensure_uv(t.scratch)
    assert t.binary.read_bytes() == t.payload
    assert t.binary.stat().st_mode & 0o777 == 0o700
    assert not (t.scratch / "uv-upload").exists()
    inode = t.binary.stat().st_ino
    await t.ssh.ensure_uv(t.scratch)
    assert t.binary.stat().st_ino == inode
    assert sum(payload is not None for _, payload in t.ssh.calls) == 1
    assert not list(t.binary.parent.glob(".uv.*"))


@pytest.mark.asyncio
@pytest.mark.parametrize("broken", ["contents", "mode", "deleted"])
async def test_uv_repairs_old_or_damaged_installation(toolchain, broken):
    t = toolchain
    await t.ssh.ensure_uv(t.scratch)
    if broken == "contents":
        t.binary.write_text("old or damaged binary")
    elif broken == "mode":
        t.binary.chmod(0o600)
    else:
        t.binary.unlink()
    await t.ssh.ensure_uv(t.scratch)
    assert t.binary.read_bytes() == t.payload
    assert os.access(t.binary, os.X_OK)
    assert sum(payload is not None for _, payload in t.ssh.calls) == 2


@pytest.mark.asyncio
async def test_corrupt_upload_preserves_previous_installation_and_recovers(toolchain):
    t = toolchain
    t.binary.parent.mkdir(parents=True)
    t.binary.write_bytes(b"previous installation")
    t.ssh.corrupt_upload = True
    with pytest.raises(hw.HubWorkspaceError, match="rc=1"):
        await t.ssh.ensure_uv(t.scratch)
    assert t.binary.read_bytes() == b"previous installation"
    assert not list(t.binary.parent.glob(".uv.*"))
    assert not (t.scratch / "uv-upload").exists()
    t.ssh.corrupt_upload = False
    await t.ssh.ensure_uv(t.scratch)
    assert t.binary.read_bytes() == t.payload


@pytest.mark.asyncio
async def test_remote_version_is_verified_before_publish(toolchain, monkeypatch):
    t = toolchain
    original = hw._uv_snapshot

    def wrong_version(scratch):
        path, digest, _ = original(scratch)
        return path, digest, "uv unexpected-version"

    monkeypatch.setattr(hw, "_uv_snapshot", wrong_version)
    with pytest.raises(hw.HubWorkspaceError, match="rc=1"):
        await t.ssh.ensure_uv(t.scratch)
    assert not t.binary.exists()
    assert not list(t.binary.parent.glob(".uv.*"))


@pytest.mark.asyncio
async def test_remote_platform_is_checked_before_upload(toolchain, monkeypatch):
    t = toolchain
    commands = t.home / "commands"
    commands.mkdir()
    uname = commands / "uname"
    uname.write_text("#!/bin/sh\nprintf 'Darwin arm64\\n'\n")
    uname.chmod(0o700)
    monkeypatch.setenv("PATH", f"{commands}:{os.environ['PATH']}")
    with pytest.raises(hw.HubWorkspaceError, match="requires Linux x86_64"):
        await t.ssh.ensure_uv(t.scratch)
    assert len(t.ssh.calls) == 1 and t.ssh.calls[0][1] is None
    assert not t.binary.exists()


@pytest.mark.asyncio
async def test_parallel_installations_publish_complete_binary(toolchain):
    t = toolchain
    other = t.scratch.parent / "other"
    other.mkdir()
    await asyncio.gather(t.ssh.ensure_uv(t.scratch), t.ssh.ensure_uv(other))
    assert t.binary.read_bytes() == t.payload
    assert not list(t.binary.parent.glob(".uv.*"))
    assert not (t.scratch / "uv-upload").exists()
    assert not (other / "uv-upload").exists()


@pytest.mark.asyncio
async def test_ssh_failure_is_not_treated_as_missing_uv(toolchain, monkeypatch):
    t = toolchain

    async def disconnected(*args, **kwargs):
        raise hw.HubWorkspaceError("connection unavailable")

    monkeypatch.setattr(t.ssh, "run", disconnected)
    with pytest.raises(hw.HubWorkspaceError, match="connection unavailable"):
        await t.ssh.ensure_uv(t.scratch)
    assert not t.binary.exists()
    assert not (t.scratch / "uv-upload").exists()


@pytest.mark.asyncio
async def test_unexpected_probe_does_not_upload(toolchain, monkeypatch):
    from unittest.mock import AsyncMock

    probe = AsyncMock(return_value=b"unrecognized output")
    monkeypatch.setattr(toolchain.ssh, "run", probe)
    with pytest.raises(hw.HubWorkspaceError, match="unexpected hub uv"):
        await toolchain.ssh.ensure_uv(toolchain.scratch)
    assert probe.await_count == 1


def _source(tmp_path, monkeypatch):
    home = tmp_path / "vps"
    source = home / ".local/bin/uv"
    source.parent.mkdir(parents=True)
    monkeypatch.setattr(hw.Path, "home", classmethod(lambda cls: home))
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    return source, scratch


def test_snapshot_never_falls_back_to_path(tmp_path, monkeypatch):
    _, scratch = _source(tmp_path, monkeypatch)
    with pytest.raises(hw.HubWorkspaceError, match="FileNotFoundError"):
        hw._uv_snapshot(scratch)


@pytest.mark.parametrize("content", [b"#!/bin/sh\nexit 127", b"not executable", b"\x7fELF\x02\x01" + b"\0" * 14])
def test_snapshot_refuses_shim_or_wrong_architecture(tmp_path, monkeypatch, content):
    source, scratch = _source(tmp_path, monkeypatch)
    source.write_bytes(content)
    with pytest.raises(hw.HubWorkspaceError, match="Linux x86_64 ELF"):
        hw._uv_snapshot(scratch)


@pytest.mark.parametrize("version", ["uv 0.11.27", "uv 0.11.280", "unexpected", "uv 0.11.28\nextra"])
def test_snapshot_refuses_wrong_version(tmp_path, monkeypatch, version):
    source, scratch = _source(tmp_path, monkeypatch)
    shutil.copyfile(sys.executable, source)
    monkeypatch.setattr(hw.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=version))
    with pytest.raises(hw.HubWorkspaceError, match="must be version"):
        hw._uv_snapshot(scratch)


def test_snapshot_hashes_validated_bytes_despite_source_replacement(tmp_path, monkeypatch):
    source, scratch = _source(tmp_path, monkeypatch)
    shutil.copyfile(sys.executable, source)
    expected = source.read_bytes()

    def version(argv, **kwargs):
        assert Path(argv[0]).read_bytes() == expected
        assert kwargs["timeout"] == 20
        source.write_bytes(b"replacement")
        return SimpleNamespace(stdout=f"uv {hw.HUB_UV_VERSION} (x86_64-unknown-linux-gnu)\n")

    monkeypatch.setattr(hw.subprocess, "run", version)
    snapshot, digest, actual_version = hw._uv_snapshot(scratch)
    assert snapshot.read_bytes() == expected
    assert digest == hashlib.sha256(expected).hexdigest()
    assert actual_version.startswith(f"uv {hw.HUB_UV_VERSION} ")


@pytest.mark.asyncio
async def test_download_excludes_uv_environment_but_keeps_results(tmp_path, monkeypatch):
    import tarfile

    home = tmp_path / "hub"
    workspace = home / "hub-0123456789abcdef"
    (workspace / ".venv/lib").mkdir(parents=True)
    (workspace / ".venv/lib/dependency.py").write_text("dependency")
    (workspace / "result.py").write_text("result")
    archive = tmp_path / "out.tar"
    ssh = ShellSsh()
    await ssh.get(str(workspace), archive)
    with tarfile.open(archive) as handle:
        names = handle.getnames()
    assert "./result.py" in names
    assert not any(name.startswith("./.venv") for name in names)


def _provision_case(tmp_path, monkeypatch, files=("pyproject.toml", "uv.lock")):
    from unittest.mock import AsyncMock
    from app import backend_hub

    root = tmp_path / "worktree"
    root.mkdir()
    for name in files:
        (root / name).write_text("test context")
    monkeypatch.setattr(hw, "STATE_DIR", tmp_path / "state")
    state = hw.WorkspaceState("hub-0123456789abcdef", str(root), "/hub/copy")
    plan = hw.UploadPlan(manifest={name: hw.sha256_file(root / name) for name in files})
    backend = backend_hub.HubBackend("hub-gpt-6.1-sol", str(root))
    mc = SimpleNamespace(tool_call=AsyncMock(return_value={"id": "project-1"}))
    order = []

    async def ensure(*args):
        order.append("uv")

    async def put(*args):
        order.append("upload")

    ssh = SimpleNamespace(ensure_uv=AsyncMock(side_effect=ensure),
                          put=AsyncMock(side_effect=put), delete_files=AsyncMock())
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    return SimpleNamespace(backend=backend, mc=mc, ssh=ssh, root=root, state=state,
                           plan=plan, scratch=scratch, order=order)


@pytest.mark.asyncio
@pytest.mark.parametrize("persistent", [False, True])
async def test_backend_provisions_before_upload_and_rechecks_resumed_turn(tmp_path, monkeypatch, persistent):
    from unittest.mock import AsyncMock

    t = _provision_case(tmp_path, monkeypatch)

    async def base(*args):
        t.order.append("upload")
        return 2, 0

    monkeypatch.setattr(hw, "provision_from_base", AsyncMock(side_effect=base))
    options = hw.ProjectOptions(persistent=persistent)
    await t.backend._provision(t.mc, t.ssh, t.root, t.state, t.plan, options, True, t.scratch)
    assert t.order == ["uv", "upload"]
    assert t.state.project_id == "project-1" and t.state.uploaded
    await t.backend._provision(t.mc, t.ssh, t.root, t.state, t.plan, options, False, t.scratch)
    assert t.order == ["uv", "upload", "uv"]
    assert t.ssh.ensure_uv.await_count == 2
    assert t.mc.tool_call.await_count == 1
    # A pre-existing thread must also receive the explicit PATH, not just new threads.
    prompt = t.backend._prompt("continue", first=False)
    assert f'export PATH="$HOME/{hw.HUB_UV_BIN}:$PATH"' in prompt
    assert "uv run --frozen python -m pytest <paths> -q" in prompt
    assert prompt.endswith("continue")


@pytest.mark.asyncio
async def test_backend_uv_failure_prevents_upload_and_project_creation(tmp_path, monkeypatch):
    t = _provision_case(tmp_path, monkeypatch)
    t.ssh.ensure_uv.side_effect = hw.HubWorkspaceError("uv missing")
    with pytest.raises(hw.HubWorkspaceError, match="uv missing"):
        await t.backend._provision(t.mc, t.ssh, t.root, t.state, t.plan,
                                   hw.ProjectOptions(), True, t.scratch)
    t.ssh.put.assert_not_awaited()
    t.mc.tool_call.assert_not_awaited()
    assert not t.state.uploaded and not t.backend._uv_ready


@pytest.mark.asyncio
@pytest.mark.parametrize("files", [(), ("pyproject.toml",), ("uv.lock",)])
async def test_backend_incomplete_python_pair_needs_no_uv(tmp_path, monkeypatch, files):
    t = _provision_case(tmp_path, monkeypatch, files)
    await t.backend._provision(t.mc, t.ssh, t.root, t.state, t.plan,
                               hw.ProjectOptions(), True, t.scratch)
    t.ssh.ensure_uv.assert_not_awaited()
    assert t.state.uploaded
    assert t.backend._prompt("continue", first=False) == "continue"
