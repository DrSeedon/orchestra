"""Private filename containment using invented text and local fake transports only."""

import copy
import asyncio
import os
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app import hub_workspace as hw
from tests.test_hub_workspace import (
    FakeSsh, _backend, _offline_hub_pool, _tar_of, _turn, repo,
)

PRIVATE_PATHS = (
    "COMPANY-DATA.md", "company-data.md", "docs/COMPANY-DATA.md",
    "src/deep/CoMpAnY-DaTa.Md",
)
FIXTURE = "invented company fixture; no personal records\n"


def _write(root, rel, text=FIXTURE):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.mark.parametrize("rel", PRIVATE_PATHS)
@pytest.mark.parametrize("ownership", ["narrow", "exact", "whole"])
def test_private_filename_never_in_initial_manifest_or_archive(repo, tmp_path, rel, ownership):
    original = _write(repo, rel)
    public = {"README.md", "company-data.md.example", "public-company-data.md"}
    for name in public:
        _write(repo, name, "public documentation\n")
    paths = {"narrow": ["src"], "exact": [rel], "whole": None}[ownership]
    plan = hw.plan_upload(repo, paths, known=[])
    assert rel not in plan.manifest
    assert public <= plan.manifest.keys()
    archive = tmp_path / "upload.tar"
    hw.write_tar(repo, sorted(plan.manifest), archive)
    import tarfile
    with tarfile.open(archive) as packed:
        assert set(packed.getnames()) == set(plan.manifest)
        assert all(Path(name).name.casefold() != "company-data.md" for name in packed.getnames())
    assert original.read_text() == FIXTURE


def test_explicit_tracked_private_owned_file_refuses_empty_work_area(repo):
    import subprocess
    rel = "COMPANY-DATA.md"
    original = _write(repo, rel)
    subprocess.run(["git", "-C", str(repo), "add", rel], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "synthetic fixture"],
                   check=True, capture_output=True)
    with pytest.raises(hw.HubWorkspaceError, match="none of the worker's owned paths"):
        hw.plan_upload(repo, [rel], known=[])
    assert original.read_text() == FIXTURE


@pytest.mark.parametrize("rel", PRIVATE_PATHS)
def test_direct_archive_refuses_before_creating_output(repo, tmp_path, rel):
    _write(repo, rel)
    output = tmp_path / "upload.tar"
    with pytest.raises(hw.HubFilePolicyError):
        hw.write_tar(repo, ["calc.py", rel], output)
    assert not output.exists()


@pytest.mark.parametrize("rel", PRIVATE_PATHS)
def test_import_rejects_private_filename_and_preserves_public_behavior(repo, tmp_path, rel):
    original = _write(repo, rel)
    manifest = hw.plan_upload(repo, known=[]).manifest
    snapshot = _tar_of({rel: b"invented replacement\n", "calc.py": b"public change\n",
                        "src/keep.txt": b"keep\n"}, tmp_path)
    result = hw.apply_changes(snapshot, repo, manifest, known=[])
    assert result.changed == ["calc.py"] and result.deleted == []
    assert rel not in result.manifest
    assert rel in dict(result.rejected)
    assert original.read_text() == FIXTURE
    assert (repo / "calc.py").read_text() == "public change\n"


@pytest.mark.parametrize("history", ["manifest", "inputs"])
def test_import_with_private_history_refuses_without_touching_sources(repo, tmp_path, history):
    rel = "nested/CoMpAnY-DaTa.Md"
    original = _write(repo, rel)
    manifest = hw.plan_upload(repo, known=[]).manifest
    inputs = {}
    (manifest if history == "manifest" else inputs)[rel] = hw.sha256_file(original)
    before = copy.deepcopy((manifest, inputs))
    content = (repo / "calc.py").read_bytes()
    snapshot = _tar_of({"calc.py": b"must not apply\n"}, tmp_path)
    with pytest.raises(hw.HubFilePolicyError):
        hw.apply_changes(snapshot, repo, manifest, known=[], inputs=inputs)
    assert (manifest, inputs) == before
    assert original.read_text() == FIXTURE and (repo / "calc.py").read_bytes() == content


@pytest.mark.parametrize("location", ["plan", "manifest", "keep"])
def test_delta_refuses_private_evidence_instead_of_dropping_it(repo, location):
    plan = hw.plan_upload(repo, known=[])
    manifest, keep = dict(plan.manifest), set()
    target = {"plan": plan.manifest, "manifest": manifest, "keep": keep}[location]
    if isinstance(target, set):
        target.add("nested/COMPANY-DATA.md")
    else:
        target["nested/COMPANY-DATA.md"] = "historical-synthetic-digest"
    before = copy.deepcopy((plan.manifest, manifest, keep))
    with pytest.raises(hw.HubFilePolicyError):
        hw.local_delta(repo, plan, manifest, keep)
    assert (plan.manifest, manifest, keep) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("persistent", [False, True])
async def test_initial_provider_copy_is_clean_including_persistent_base(repo, tmp_path, monkeypatch, persistent):
    for rel in PRIVATE_PATHS:
        _write(repo, rel)
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda _: None)
    backend._scope = str(repo)
    monkeypatch.setattr(hw, "project_options", lambda _: hw.ProjectOptions(persistent=persistent))
    events = await _turn(backend, "inspect public source")
    assert events[-1].metadata["ok"]
    assert any(name == "t3_thread_launch" for name, _ in mc.calls)
    state = backend._state
    for rel in PRIVATE_PATHS:
        assert rel not in state.manifest and rel not in state.input_manifest
        assert not (Path(state.remote_dir) / rel).exists()
        assert (repo / rel).read_text() == FIXTURE
        if persistent:
            assert not (Path(await ssh.base_dir_for(str(repo))) / rel).exists()
    assert (Path(state.remote_dir) / "calc.py").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("history", ["manifest", "input_manifest", "hub_made"])
async def test_stale_history_blocks_turn_even_when_remote_file_is_gone(repo, tmp_path, monkeypatch, history):
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda _: None)
    assert (await _turn(backend, "public first turn"))[-1].metadata["ok"]
    state = backend._state
    rel = "old/CoMpAnY-DaTa.Md"
    target = getattr(state, history)
    if isinstance(target, list):
        target.append(rel)
    else:
        target[rel] = "historical-synthetic-digest"
    state.save()
    before = state.path().read_bytes()
    mc.calls.clear()
    events = await _turn(backend, "continue")
    assert not events[-1].metadata["ok"]
    assert "owner review" in events[-1].content
    assert mc.calls == [] and ssh.removed == []
    assert state.path().read_bytes() == before
    assert hw.WorkspaceState.load(state.ws_id).__dict__ == state.__dict__


@pytest.mark.asyncio
@pytest.mark.parametrize("new_backend", [False, True])
async def test_unmanifested_copy_blocks_refresh_or_replacement_and_latches_history(
        repo, tmp_path, monkeypatch, new_backend):
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda _: None)
    assert (await _turn(backend, "public first turn"))[-1].metadata["ok"]
    state = backend._state
    before = copy.deepcopy((state.manifest, state.input_manifest, state.thread_id))
    foreign = _write(Path(state.remote_dir), "nested/CoMpAnY-DaTa.Md")
    if new_backend:
        backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda _: None)
    mc.calls.clear()
    events = await _turn(backend, "continue")
    assert not events[-1].metadata["ok"]
    assert "owner review" in events[-1].content
    assert not any(name in {"t3_thread_send", "t3_thread_launch", "t3_project_delete"}
                   for name, _ in mc.calls)
    retained = hw.WorkspaceState.load(state.ws_id)
    assert (retained.manifest, retained.input_manifest, retained.thread_id) == before
    assert retained.file_policy_blocked and foreign.read_text() == FIXTURE
    assert ssh.removed == []
    foreign.unlink()  # Synthetic owner cleanup cannot erase a thread's exposure history.
    events = await _turn(backend, "retry after fixture cleanup")
    assert not events[-1].metadata["ok"]
    assert hw.WorkspaceState.load(state.ws_id).file_policy_blocked


@pytest.mark.asyncio
@pytest.mark.parametrize("evidence", ["manifest", "copy", "latched"])
async def test_persistent_base_refuses_before_update_or_copy_and_preserves_evidence(
        repo, tmp_path, monkeypatch, evidence):
    ssh = FakeSsh(tmp_path / "hub")
    base_dir = Path(await ssh.base_dir_for(str(repo)))
    base_dir.mkdir(parents=True)
    plan = hw.plan_upload(repo, known=[])
    base = hw.BaseState(hw.base_id_for(str(repo)), str(repo), dict(plan.manifest))
    rel = "nested/COMPANY-DATA.md"
    foreign = _write(base_dir, rel)
    if evidence == "manifest":
        base.manifest[rel] = hw.sha256_file(foreign)
    elif evidence == "latched":
        base.file_policy_blocked = True
        foreign.unlink()
    base.save()
    before = copy.deepcopy(base.manifest)
    ssh.put, ssh.delete_files, ssh.copy_dir = AsyncMock(), AsyncMock(), AsyncMock()
    dest = str(tmp_path / hw.WorkspaceState.new_id())
    with pytest.raises(hw.HubFilePolicyError):
        await hw.provision_from_base(ssh, repo, str(repo), plan, dest)
    ssh.put.assert_not_awaited()
    ssh.delete_files.assert_not_awaited()
    ssh.copy_dir.assert_not_awaited()
    assert not Path(dest).exists()
    retained = hw.BaseState.load(str(repo))
    assert retained.manifest == before
    if evidence == "copy":
        assert retained.file_policy_blocked
        foreign.unlink()
        with pytest.raises(hw.HubFilePolicyError):
            await hw.provision_from_base(ssh, repo, str(repo), plan, dest)
    elif evidence == "manifest":
        assert foreign.read_text() == FIXTURE


@pytest.mark.asyncio
@pytest.mark.parametrize("rel", PRIVATE_PATHS)
async def test_name_only_remote_check_uses_actual_shell_on_synthetic_files(tmp_path, rel):
    ssh = FakeSsh(tmp_path)
    remote = tmp_path / hw.WorkspaceState.new_id()
    await ssh.assert_file_policy(str(remote))  # missing first-upload copy is allowed
    remote.mkdir()
    _write(remote, "README.md", "public\n")
    await ssh.assert_file_policy(str(remote))
    original = _write(remote, rel)
    with pytest.raises(hw.HubFilePolicyError) as error:
        await ssh.assert_file_policy(str(remote))
    assert str(remote) not in str(error.value)  # no local inventories in the public error
    assert original.read_text() == FIXTURE


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [hw.HubWorkspaceError("scan transport failed"), OSError("scan unavailable")])
async def test_scan_errors_propagate_without_cleanup_or_false_policy_evidence(repo, tmp_path, monkeypatch, failure):
    ssh = FakeSsh(tmp_path)
    state = hw.WorkspaceState(hw.WorkspaceState.new_id(), str(repo),
                              str(tmp_path / hw.WorkspaceState.new_id()), input_manifest={})
    state.save()
    before = state.path().read_bytes()
    monkeypatch.setattr(ssh, "run", AsyncMock(side_effect=failure))
    with pytest.raises(type(failure), match=str(failure)):
        await hw.check_workspace_file_policy(ssh, state)
    assert not state.file_policy_blocked and state.path().read_bytes() == before
    assert ssh.removed == []


@pytest.mark.asyncio
@pytest.mark.parametrize("uploaded", [False, True])
@pytest.mark.parametrize("history", ["manifest", "input_manifest"])
async def test_sync_after_verified_fixture_removal_never_deletes_local_original(
        repo, tmp_path, monkeypatch, uploaded, history):
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda _: None)
    original = _write(repo, "COMPANY-DATA.md")
    digest = hw.sha256_file(original)
    remote = tmp_path / "hub" / hw.WorkspaceState.new_id()
    remote.mkdir(parents=True)
    # The verified foreign fixture was removed by an operator. Its absence in
    # this snapshot must never become a deletion of the retained local original.
    _write(remote, "calc.py", "public remote version\n")
    plan = hw.plan_upload(repo, known=[])
    manifest, inputs = dict(plan.manifest), {}
    (manifest if history == "manifest" else inputs)["COMPANY-DATA.md"] = digest
    state = hw.WorkspaceState(remote.name, str(repo), str(remote), manifest=manifest,
                              input_manifest=inputs, uploaded=uploaded, thread_id="old-thread")
    state.save()
    before = state.path().read_bytes()
    scratch = tmp_path / "sync-scratch"
    scratch.mkdir()
    public_before = (repo / "calc.py").read_bytes()
    with pytest.raises(hw.HubFilePolicyError):
        await backend._sync_back(ssh, state, repo, scratch)
    assert original.read_text() == FIXTURE and hw.sha256_file(original) == digest
    assert state.path().read_bytes() == before
    assert (repo / "calc.py").read_bytes() == public_before
    assert mc.calls == [] and ssh.removed == []
    # Neither an incomplete upload nor missing remote data bypasses provisioning.
    with pytest.raises(hw.HubFilePolicyError):
        await backend._provision(mc, ssh, repo, state, plan, hw.ProjectOptions(),
                                 not uploaded, scratch)
    assert original.exists() and state.path().read_bytes() == before


@pytest.mark.asyncio
async def test_automatic_release_does_not_delete_private_evidence(repo, tmp_path, monkeypatch):
    ssh = FakeSsh(tmp_path / "hub")
    remote = tmp_path / "hub" / hw.WorkspaceState.new_id()
    foreign = _write(remote, "COMPANY-DATA.md")
    state = hw.WorkspaceState(remote.name, str(repo), str(remote), thread_id="old-thread",
                              project_id="project", input_manifest={})
    state.save()
    from types import SimpleNamespace
    mc = SimpleNamespace(tool_call=AsyncMock())
    with pytest.raises(hw.HubFilePolicyError):
        await hw.release_workspace(state, ssh, mc)
    mc.tool_call.assert_not_awaited()
    assert not ssh.removed and foreign.read_text() == FIXTURE
    assert hw.WorkspaceState.load(state.ws_id).file_policy_blocked


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["steer", "retarget"])
async def test_tainted_history_cannot_reach_steer_or_model_configuration(repo, tmp_path, monkeypatch, route):
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda _: None)
    assert (await _turn(backend, "public first turn"))[-1].metadata["ok"]
    state = backend._state
    state.input_manifest["COMPANY-DATA.md"] = "historical-synthetic-digest"
    state.save()
    before = state.path().read_bytes()
    mc.calls.clear()
    with pytest.raises(hw.HubFilePolicyError):
        if route == "steer":
            backend._turn_active, backend._run_id = True, "active-run"
            await backend.send("steer")
        else:
            await backend.retarget_model("hub-gpt-6.1-sol")
    assert mc.calls == [] and backend._early_steer == []
    assert state.path().read_bytes() == before and ssh.removed == []


@pytest.mark.asyncio
async def test_partial_upload_without_manifest_is_checked_before_any_more_writes(repo, tmp_path, monkeypatch):
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda _: None)
    ws_id = hw.WorkspaceState.new_id()
    remote = tmp_path / "hub" / ws_id
    foreign = _write(remote, "COMPANY-DATA.md")
    state = hw.WorkspaceState(ws_id, str(repo), str(remote), uploaded=False, input_manifest={})
    state.save()
    plan = hw.plan_upload(repo, known=[])
    scratch = tmp_path / "partial-scratch"
    scratch.mkdir()
    ssh.put, ssh.delete_files = AsyncMock(), AsyncMock()
    with pytest.raises(hw.HubFilePolicyError):
        await backend._provision(mc, ssh, repo, state, plan, hw.ProjectOptions(), True, scratch)
    ssh.put.assert_not_awaited()
    ssh.delete_files.assert_not_awaited()
    assert mc.calls == [] and foreign.read_text() == FIXTURE
    assert state.manifest == {} and state.input_manifest == {} and not state.uploaded
    assert hw.WorkspaceState.load(ws_id).file_policy_blocked


@pytest.mark.asyncio
async def test_actual_find_failure_is_not_treated_as_an_empty_copy(repo, tmp_path, monkeypatch):
    from tests.test_hub_message_v1066 import LocalSsh
    import os

    remote = tmp_path / hw.WorkspaceState.new_id()
    remote.mkdir()
    executable = _write(tmp_path, "fake-bin/find", "#!/bin/sh\nexit 9\n")
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(executable.parent) + os.pathsep + os.environ["PATH"])
    ssh = LocalSsh(tmp_path)
    state = hw.WorkspaceState(remote.name, str(repo), str(remote), input_manifest={})
    state.save()
    before = state.path().read_bytes()
    with pytest.raises(hw.HubWorkspaceError, match="rc=9") as error:
        await hw.check_workspace_file_policy(ssh, state)
    assert not isinstance(error.value, hw.HubFilePolicyError)
    assert state.path().read_bytes() == before and not state.file_policy_blocked


@pytest.mark.asyncio
async def test_stale_in_memory_record_cannot_clear_persisted_refusal(repo, tmp_path, monkeypatch):
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda _: None)
    assert (await _turn(backend, "public first turn"))[-1].metadata["ok"]
    stale = backend._state
    retained = hw.WorkspaceState.load(stale.ws_id)
    foreign = _write(Path(retained.remote_dir), "COMPANY-DATA.md")
    with pytest.raises(hw.HubFilePolicyError):
        await hw.check_workspace_file_policy(ssh, retained)
    assert not stale.file_policy_blocked  # Another caller holds the old object.
    foreign.unlink()
    scratch = tmp_path / "stale-scratch"
    scratch.mkdir()
    before = retained.path().read_bytes()
    with pytest.raises(hw.HubFilePolicyError):
        await backend._sync_back(ssh, stale, repo, scratch)
    assert retained.path().read_bytes() == before
    assert hw.WorkspaceState.load(stale.ws_id).file_policy_blocked


@pytest.mark.asyncio
async def test_sync_checks_foreign_name_without_reading_contents(repo, tmp_path, monkeypatch):
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda _: None)
    assert (await _turn(backend, "public first turn"))[-1].metadata["ok"]
    state = backend._state
    foreign = _write(Path(state.remote_dir), "nested/COMPANY-DATA.md")
    ssh.get = AsyncMock()
    scratch = tmp_path / "guarded-sync"
    scratch.mkdir()
    with pytest.raises(hw.HubFilePolicyError):
        await backend._sync_back(ssh, state, repo, scratch)
    ssh.get.assert_not_awaited()
    assert foreign.read_text() == FIXTURE and hw.WorkspaceState.load(state.ws_id).file_policy_blocked


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("changed", [False, True])
def test_native_merge_provenance_stays_independent_of_remote_refusal(repo, legacy, changed):
    original = _write(repo, "COMPANY-DATA.md")
    digest = hw.sha256_file(original)
    state = hw.WorkspaceState(hw.WorkspaceState.new_id(), str(repo), "",
                              manifest={"COMPANY-DATA.md": digest}, file_policy_blocked=True,
                              input_manifest=None if legacy else {"COMPANY-DATA.md": digest})
    state.save()
    if changed:
        original.write_text("invented changed local fixture\n")
        with pytest.raises(hw.HubWorkspaceError, match="restore the uploaded original") as error:
            hw.merge_inputs(repo, "HEAD")
        assert not isinstance(error.value, hw.HubFilePolicyError)
    else:
        assert hw.merge_inputs(repo, "HEAD") == {"COMPANY-DATA.md": digest}
    retained = hw.WorkspaceState.load(state.ws_id)
    assert retained.file_policy_blocked
    assert retained.manifest == state.manifest
    assert retained.input_manifest == {"COMPANY-DATA.md": digest}
    assert original.exists()


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
