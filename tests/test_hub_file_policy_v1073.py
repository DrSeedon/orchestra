"""Owner-authorized company inputs; credential and structural protections stay active.

The owner superseded the COMPANY-DATA.md exclusion on 2026-11-04. These tests
exercise the new transfer contract rather than the retired filename classification.
"""

import asyncio
import os
import subprocess
import tarfile
from pathlib import Path

import pytest

from app import hub_workspace as hw
from tests.test_hub_workspace import (
    FakeSsh, _backend, _offline_hub_pool, _tar_of, _turn, repo,
)

COMPANY_PATHS = (
    "COMPANY-DATA.md", "company-data.md", "docs/COMPANY-DATA.md",
    "src/deep/CoMpAnY-DaTa.Md", ".orchestra/kb/company.md",
)
FIXTURE = "invented company offer and tender; no credentials\n"


def _write(root, rel, text=FIXTURE):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.mark.parametrize("rel", COMPANY_PATHS)
@pytest.mark.parametrize("ownership", ["exact", "whole"])
def test_company_input_is_uploaded_and_archived(repo, tmp_path, rel, ownership):
    original = _write(repo, rel)
    plan = hw.plan_upload(repo, [rel] if ownership == "exact" else None, known=[])
    assert plan.manifest[rel] == hw.sha256_file(original)
    archive = tmp_path / "upload.tar"
    hw.write_tar(repo, sorted(plan.manifest), archive)
    with tarfile.open(archive) as packed:
        assert packed.extractfile(rel).read() == FIXTURE.encode()
    assert original.read_text() == FIXTURE


def test_company_input_keeps_owned_directory_scope(repo):
    _write(repo, "other/COMPANY-DATA.md")
    _write(repo, "src/COMPANY-DATA.md")
    plan = hw.plan_upload(repo, ["src"], known=[])
    assert "src/COMPANY-DATA.md" in plan.manifest
    assert "other/COMPANY-DATA.md" not in plan.manifest


@pytest.mark.parametrize("rel", COMPANY_PATHS)
def test_company_input_round_trips_without_bypassing_credential_checks(repo, tmp_path, rel):
    original = _write(repo, rel)
    manifest = hw.plan_upload(repo, known=[]).manifest
    replacement = b"invented revised company offer\n"
    snapshot = _tar_of({rel: replacement, "calc.py": b"public change\n",
                        "src/keep.txt": b"keep\n", ".env": b"excluded fixture\n"}, tmp_path)
    result = hw.apply_changes(snapshot, repo, manifest, known=[])
    assert rel in result.changed and result.manifest[rel] == hw.sha256_file(original)
    assert original.read_bytes() == replacement
    assert ".env" in dict(result.rejected) and not (repo / ".env").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("persistent", [False, True])
async def test_company_input_reaches_initial_worker_and_persistent_base(repo, tmp_path, monkeypatch, persistent):
    for rel in COMPANY_PATHS:
        _write(repo, rel)
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda _: None)
    backend._scope = str(repo)
    monkeypatch.setattr(hw, "project_options", lambda _: hw.ProjectOptions(persistent=persistent))
    events = await _turn(backend, "inspect authorized company records")
    assert events[-1].metadata["ok"], events[-1].content
    assert any(name == "t3_thread_launch" for name, _ in mc.calls)
    for rel in COMPANY_PATHS:
        assert rel in backend._state.manifest
        assert (Path(backend._state.remote_dir) / rel).read_text() == FIXTURE
        if persistent:
            assert (Path(await ssh.base_dir_for(str(repo))) / rel).read_text() == FIXTURE


@pytest.mark.asyncio
@pytest.mark.parametrize("history", ["manifest", "input_manifest", "hub_made", "blocked"])
async def test_legacy_company_history_does_not_block_provider_turn(repo, tmp_path, monkeypatch, history):
    backend, _, mc = _backend(repo, tmp_path, monkeypatch, lambda _: None)
    assert (await _turn(backend, "initial turn"))[-1].metadata["ok"]
    state = backend._state
    rel = "old/CoMpAnY-DaTa.Md"
    if history == "blocked":
        state.file_policy_blocked = True
    else:
        target = getattr(state, history)
        if isinstance(target, list):
            target.append(rel)
        else:
            target[rel] = "historical-synthetic-digest"
    state.save()
    mc.calls.clear()
    events = await _turn(backend, "continue")
    assert events[-1].metadata["ok"], events[-1].content
    assert any(name == "t3_thread_send" for name, _ in mc.calls)


@pytest.mark.asyncio
async def test_legacy_blocked_base_is_usable_without_deleting_history(repo, tmp_path, monkeypatch):
    _write(repo, "COMPANY-DATA.md")
    ssh = FakeSsh(tmp_path / "hub")
    base = hw.BaseState(hw.base_id_for(str(repo)), str(repo), file_policy_blocked=True)
    base.save()
    plan = hw.plan_upload(repo, known=[])
    dest = await ssh.dir_for(hw.WorkspaceState.new_id())
    await hw.provision_from_base(ssh, repo, str(repo), plan, dest)
    assert (Path(dest) / "COMPANY-DATA.md").read_text() == FIXTURE
    assert hw.BaseState.load(str(repo)).file_policy_blocked


@pytest.mark.parametrize("rel", [".env", "credentials.json", "keys/id_rsa"])
def test_company_authorization_does_not_include_credential_files(repo, rel):
    _write(repo, rel)
    assert rel not in hw.plan_upload(repo, known=[]).manifest


def test_company_file_containing_literal_credential_stays_excluded(repo):
    credential = "invented-test-credential-value-0123456789"
    _write(repo, "COMPANY-DATA.md", credential)
    plan = hw.plan_upload(repo, known=[credential])
    assert "COMPANY-DATA.md" not in plan.manifest
    with pytest.raises(hw.HubWorkspaceError, match="credential"):
        hw.assert_no_secret(credential, [credential], "task prompt")


@pytest.mark.parametrize("rel", ["../escape.md", "/absolute.md"])
def test_company_permission_does_not_allow_paths_outside_workspace(rel):
    with pytest.raises(hw.HubWorkspaceError):
        hw.assert_file_policy([rel])


@pytest.fixture
def permission_shell(tmp_path):
    """Run the production shell check unprivileged, even in root-owned CI.

    An inherited fixture-only directory FD avoids changing permissions on any
    ancestors outside the fixture when the child drops its numeric UID/GID.
    """
    tmp_path.chmod(0o755)
    directory_fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)

    class PermissionSsh(hw.HubSsh):
        async def run(self, remote, **kwargs):
            identity = {"user": 65534, "group": 65534, "extra_groups": []} if os.geteuid() == 0 else {}
            result = await asyncio.to_thread(
                subprocess.run, ["/bin/bash", "-c", remote],
                pass_fds=(directory_fd,), capture_output=True, timeout=15, **identity)
            if result.returncode:
                raise hw.HubWorkspaceError(hw._ssh_failure(
                    remote, result.returncode, result.stdout, result.stderr, False))
            return result.stdout

    try:
        yield PermissionSsh("unused", "unused", ""), Path(f"/proc/self/fd/{directory_fd}")
    finally:
        os.close(directory_fd)


@pytest.mark.asyncio
@pytest.mark.parametrize("leaf_exists", [False, True])
async def test_actual_shell_unreadable_parent_is_not_missing(
        permission_shell, tmp_path, monkeypatch, leaf_exists):
    ssh, visible_root = permission_shell
    await ssh.run('test "$(id -u)" -ne 0')
    parent = tmp_path / "sealed"
    parent.mkdir()
    ws_id = hw.WorkspaceState.new_id()
    if leaf_exists:
        original = _write(parent / ws_id, "COMPANY-DATA.md")
    monkeypatch.setattr(hw, "STATE_DIR", tmp_path / "records")
    state = hw.WorkspaceState(ws_id, str(tmp_path), str(visible_root / "sealed" / ws_id),
                              input_manifest={})
    state.save()
    before = state.path().read_bytes()
    parent.chmod(0)
    try:
        with pytest.raises(hw.HubWorkspaceError, match="errno 13") as error:
            await hw.check_workspace_file_policy(ssh, state)
        assert not isinstance(error.value, hw.HubFilePolicyError)
        assert state.path().read_bytes() == before and not state.file_policy_blocked
    finally:
        parent.chmod(0o755)
    if leaf_exists:
        assert original.read_text() == FIXTURE


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["missing-ancestors", "clean", "lost"])
async def test_actual_shell_missing_and_clean_copies_stay_allowed(permission_shell, tmp_path, kind):
    ssh, visible_root = permission_shell
    await ssh.run('test "$(id -u)" -ne 0')
    ws_id = hw.WorkspaceState.new_id()
    if kind == "missing-ancestors":
        remote = visible_root / "not-created" / "nested" / ws_id
    else:
        directory = tmp_path / ws_id
        directory.mkdir()
        remote = visible_root / ws_id
        _write(directory, "README.md", "public fixture\n")
        await ssh.assert_file_policy(str(remote))
        if kind == "lost":
            (directory / "README.md").unlink()
            directory.rmdir()
    await ssh.assert_file_policy(str(remote))


@pytest.mark.asyncio
@pytest.mark.parametrize("fault,expected_errno", [("not-directory", 20), ("symlink-loop", 40)])
async def test_actual_shell_non_enoent_errors_stay_errors(permission_shell, tmp_path, fault, expected_errno):
    ssh, visible_root = permission_shell
    await ssh.run('test "$(id -u)" -ne 0')
    parent = tmp_path / "fault"
    if fault == "not-directory":
        parent.write_text("invented public fixture\n")
    else:
        parent.symlink_to("fault", target_is_directory=True)
    remote = visible_root / "fault" / hw.WorkspaceState.new_id()
    with pytest.raises(hw.HubWorkspaceError, match=f"errno {expected_errno}") as error:
        await ssh.assert_file_policy(str(remote))
    assert not isinstance(error.value, hw.HubFilePolicyError)


@pytest.mark.asyncio
async def test_actual_shell_missing_errno_probe_interpreter_fails_closed(permission_shell, tmp_path, monkeypatch):
    ssh, visible_root = permission_shell
    await ssh.run('test "$(id -u)" -ne 0')
    ws_id = hw.WorkspaceState.new_id()
    (tmp_path / ws_id).mkdir()
    executable = _write(tmp_path, "only-find/find", '#!/bin/sh\nexec /usr/bin/find "$@"\n')
    executable.chmod(0o755)
    # Existing directory and find are available; only the new metadata probe's
    # interpreter is unavailable. It must not silently classify the copy clean.
    monkeypatch.setenv("PATH", str(visible_root / "only-find"))
    with pytest.raises(hw.HubWorkspaceError, match="rc=127"):
        await ssh.assert_file_policy(str(visible_root / ws_id))
