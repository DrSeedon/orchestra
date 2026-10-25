"""Owner-requested clean start (V-1083): invented text and local fake transports only."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from app import hub_workspace as hw
from tests.test_hub_workspace import FakeSsh, _backend, _offline_hub_pool, _turn, repo  # noqa: F401

FIXTURE = "invented company fixture; no personal records\n"
PRIVATE = "nested/CoMpAnY-DaTa.Md"


def _options(monkeypatch, **kw):
    monkeypatch.setattr(hw, "project_options", lambda _: hw.ProjectOptions(**kw))


def _snapshot(state_dir: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(state_dir.glob("*.json"))}


async def _dirty_old(repo, tmp_path, monkeypatch, how="history"):
    """A first turn, then private-file evidence in its record (history) or its remote copy."""
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda _: None)
    assert (await _turn(backend, "public first turn"))[-1].metadata["ok"]
    old = backend._state
    if how == "history":
        old.manifest[PRIVATE] = "historical-synthetic-digest"
        old.file_policy_blocked = True
        old.save()
    else:
        target = Path(old.remote_dir) / PRIVATE
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(FIXTURE)
    return backend, ssh, mc, old


@pytest.mark.asyncio
@pytest.mark.parametrize("duplicate_removed", [False, True])
async def test_without_option_old_history_stays_refused_before_and_after_duplicate_removal(
        repo, tmp_path, monkeypatch, duplicate_removed):
    backend, ssh, mc, old = await _dirty_old(repo, tmp_path, monkeypatch, "copy")
    mc.calls.clear()
    events = await _turn(backend, "continue")
    assert not events[-1].metadata["ok"]
    if duplicate_removed:
        (Path(old.remote_dir) / PRIVATE).unlink()
    before = _snapshot(hw.STATE_DIR)
    for fresh_backend in (backend, _backend(repo, tmp_path, monkeypatch, lambda _: None)[0]):
        events = await _turn(fresh_backend, "again")
        assert not events[-1].metadata["ok"] and "owner review" in events[-1].content
    assert _snapshot(hw.STATE_DIR) == before
    assert not any(n in {"t3_thread_launch", "t3_thread_send"} for n, _ in mc.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("persistent", [False, True])
@pytest.mark.parametrize("how", ["history", "copy"])
async def test_clean_start_creates_new_generation_and_leaves_old_bytes(
        repo, tmp_path, monkeypatch, persistent, how):
    backend, ssh, mc, old = await _dirty_old(repo, tmp_path, monkeypatch, how)
    # a stale warm base descended from the dirty copy must neither be read nor written
    base_dir = Path(await ssh.base_dir_for(str(repo)))
    base_dir.mkdir(parents=True)
    (base_dir / "poisoned.txt").write_text("ancestry marker\n")
    hw.BaseState(hw.base_id_for(str(repo)), str(repo), {"poisoned.txt": "x"},
                 file_policy_blocked=True).save()
    (repo / PRIVATE).parent.mkdir(exist_ok=True)
    (repo / PRIVATE).write_text(FIXTURE)
    _options(monkeypatch, persistent=persistent, clean_start=True)
    before = _snapshot(hw.STATE_DIR)
    old_remote = {p: p.read_bytes() for p in Path(old.remote_dir).rglob("*") if p.is_file()}
    mc.calls.clear()
    if how == "copy":   # the V-1073 guard has already latched this finding (and stays the only writer)
        _options(monkeypatch, persistent=persistent)
        assert not (await _turn(backend, "refused"))[-1].metadata["ok"]
        _options(monkeypatch, persistent=persistent, clean_start=True)
        before = _snapshot(hw.STATE_DIR)
    events = await _turn(backend, "start clean")
    assert events[-1].metadata["ok"]
    new = backend._state
    assert new.ws_id != old.ws_id and new.remote_dir != old.remote_dir
    assert any(name == "t3_thread_launch" for name, _ in mc.calls)         # a brand-new thread
    assert new.clean_start and new.clean_start_of == [old.ws_id]
    after = _snapshot(hw.STATE_DIR)
    for name, data in before.items():
        assert after[name] == data                      # old records and the base: same bytes
    assert not any(name == "t3_thread_send" for name, _ in mc.calls)       # old thread never resumed
    assert not any(name == "t3_project_delete" for name, _ in mc.calls)
    assert {p: p.read_bytes() for p in old_remote} == old_remote           # old copy untouched
    assert not (base_dir / "calc.py").exists()                              # base never refreshed/copied
    remote = Path(new.remote_dir)
    assert (remote / "calc.py").exists() and (remote / "poisoned.txt").exists() is False
    assert not any(part.casefold() == "company-data.md" for p in remote.rglob("*") for part in p.parts)
    for table in (new.manifest, new.input_manifest or {}):
        assert not any("company-data" in rel.casefold() for rel in table)
    assert (repo / PRIVATE).read_text() == FIXTURE


@pytest.mark.asyncio
async def test_clean_generation_survives_restart_retry_and_option_removal(repo, tmp_path, monkeypatch):
    backend, ssh, mc, old = await _dirty_old(repo, tmp_path, monkeypatch)
    _options(monkeypatch, clean_start=True)
    assert (await _turn(backend, "start clean"))[-1].metadata["ok"]
    new_id = backend._state.ws_id
    before = _snapshot(hw.STATE_DIR)
    _options(monkeypatch)                                  # the owner removes the option
    restarted, _, _ = _backend(repo, tmp_path, monkeypatch, lambda _: None)
    restarted._resume = new_id
    events = await _turn(restarted, "continue the clean worker")
    assert events[-1].metadata["ok"] and restarted._state.ws_id == new_id
    after = _snapshot(hw.STATE_DIR)
    assert after[f"{old.ws_id}.json"] == before[f"{old.ws_id}.json"]
    # a different, unauthorized backend (no resume, option off) is refused again
    stranger, _, _ = _backend(repo, tmp_path, monkeypatch, lambda _: None)
    events = await _turn(stranger, "no authorization")
    assert not events[-1].metadata["ok"] and "owner review" in events[-1].content


@pytest.mark.asyncio
async def test_clean_generation_itself_is_never_exempt(repo, tmp_path, monkeypatch):
    backend, ssh, mc, old = await _dirty_old(repo, tmp_path, monkeypatch)
    _options(monkeypatch, clean_start=True)
    assert (await _turn(backend, "start clean"))[-1].metadata["ok"]
    new = backend._state
    leftover = Path(new.remote_dir) / PRIVATE
    leftover.parent.mkdir(parents=True, exist_ok=True)
    leftover.write_text(FIXTURE)
    mc.calls.clear()
    events = await _turn(backend, "continue")
    assert not events[-1].metadata["ok"] and "owner review" in events[-1].content
    assert hw.WorkspaceState.load(new.ws_id).file_policy_blocked
    assert not any(n in {"t3_thread_send", "t3_thread_launch"} for n, _ in mc.calls)


@pytest.mark.asyncio
async def test_clean_start_requires_explicit_scope_before_any_upload(repo, tmp_path, monkeypatch):
    backend, ssh, mc, old = await _dirty_old(repo, tmp_path, monkeypatch)
    _options(monkeypatch, persistent=True, clean_start=True)   # persistent would allow a whole upload
    backend._paths = []
    mc.calls.clear()
    events = await _turn(backend, "start clean")
    assert not events[-1].metadata["ok"] and "owned_dirs" in events[-1].content
    assert mc.calls == []
    assert list((tmp_path / "hub").glob("hub-*")) == [Path(old.remote_dir)]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["dir", "file", "symlink"])
async def test_new_generation_target_must_not_exist(repo, tmp_path, monkeypatch, kind):
    backend, ssh, mc, old = await _dirty_old(repo, tmp_path, monkeypatch)
    _options(monkeypatch, clean_start=True)
    target = tmp_path / "hub" / "hub-0123456789abcdef"
    monkeypatch.setattr(hw.WorkspaceState, "new_id", staticmethod(lambda: target.name))
    if kind == "dir":
        target.mkdir()
    elif kind == "file":
        target.write_text("invented\n")
    else:
        target.symlink_to(tmp_path / "elsewhere")
    mc.calls.clear()
    events = await _turn(backend, "start clean")
    assert not events[-1].metadata["ok"]
    assert mc.calls == [] and hw.WorkspaceState.load(target.name) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["enotdir", "eacces"])
async def test_new_generation_target_inspection_errors_fail_closed(tmp_path, fault):
    ssh = FakeSsh(tmp_path)
    parent = tmp_path / "parent"
    if fault == "enotdir":
        parent.write_text("invented\n")
    else:
        if os.geteuid() == 0:
            pytest.skip("permission checks need an unprivileged user")
        parent.mkdir()
        parent.chmod(0)
    try:
        with pytest.raises((hw.HubWorkspaceError, subprocess.CalledProcessError)):  # fake run: check=True
            await ssh.assert_fresh_target(str(parent / hw.WorkspaceState.new_id()))
    finally:
        if parent.is_dir():
            parent.chmod(0o755)


@pytest.mark.asyncio
async def test_ordinary_clean_path_unchanged_with_option_off(repo, tmp_path, monkeypatch):
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda _: None)
    assert (await _turn(backend, "ordinary"))[-1].metadata["ok"]
    assert not backend._state.clean_start and backend._state.clean_start_of == []
    assert (await _turn(backend, "second"))[-1].metadata["ok"]
    assert not backend._state.clean_start


@pytest.mark.asyncio
@pytest.mark.parametrize("poison", ["blocked", "uninspected", "manifest"])
async def test_new_worktree_with_poisoned_base_starts_clean_without_touching_base(
        repo, tmp_path, monkeypatch, poison):
    """No prior WorkspaceState at all: only the project's persistent base is poisoned."""
    assert hw.states_for_worktree(str(repo)) == []
    base_dir = Path(await FakeSsh(tmp_path / "hub").base_dir_for(str(repo)))
    base_dir.mkdir(parents=True)
    (base_dir / "COMPANY-DATA.md").write_text(FIXTURE)       # uninspected leftover in the base copy
    (base_dir / "stale.txt").write_text("ancestry marker\n")
    base = hw.BaseState(hw.base_id_for(str(repo)), str(repo), {"stale.txt": "x"})
    if poison == "blocked":
        base.file_policy_blocked = True
    elif poison == "manifest":
        base.manifest[PRIVATE] = "historical-synthetic-digest"
    base.save()
    (repo / PRIVATE).parent.mkdir(exist_ok=True)
    (repo / PRIVATE).write_text(FIXTURE)
    # control: the poisoned base itself still refuses a normal base provision
    if poison != "uninspected":   # (the control would latch the base; "uninspected" must stay unlatched)
        plan = hw.plan_upload(repo, ["src"], known=[])
        with pytest.raises(hw.HubFilePolicyError):
            await hw.provision_from_base(FakeSsh(tmp_path / "hub"), repo, str(repo), plan,
                                         str(tmp_path / "hub" / hw.WorkspaceState.new_id()))
    before = _snapshot(hw.STATE_DIR)
    base_files = {p: p.read_bytes() for p in base_dir.rglob("*") if p.is_file()}
    _options(monkeypatch, persistent=True, clean_start=True)
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda _: None)
    backend._scope = str(repo)
    events = await _turn(backend, "start clean")
    assert events[-1].metadata["ok"]
    new = backend._state
    assert new.clean_start and new.clean_start_of == []
    after = _snapshot(hw.STATE_DIR)
    assert {k: v for k, v in after.items() if k != f"{new.ws_id}.json"} == {
        k: v for k, v in before.items() if k != f"{new.ws_id}.json"}   # base record: same bytes
    assert {p: p.read_bytes() for p in base_dir.rglob("*") if p.is_file()} == base_files
    remote = Path(new.remote_dir)
    assert (remote / "calc.py").exists() and not (remote / "stale.txt").exists()
    assert not any(p.name.casefold() == "company-data.md" for p in remote.rglob("*"))
    assert not any("company-data" in rel.casefold() for rel in (*new.manifest, *(new.input_manifest or {})))
    assert (repo / PRIVATE).read_text() == FIXTURE
    # retry / restart after the option is removed continues without the base
    _options(monkeypatch, persistent=True)
    restarted, _, _ = _backend(repo, tmp_path, monkeypatch, lambda _: None)
    restarted._resume, restarted._scope = new.ws_id, str(repo)
    assert (await _turn(restarted, "continue"))[-1].metadata["ok"]
    assert restarted._state.ws_id == new.ws_id
    assert {p: p.read_bytes() for p in base_dir.rglob("*") if p.is_file()} == base_files


@pytest.mark.asyncio
async def test_new_worktree_clean_generation_contamination_still_refuses(repo, tmp_path, monkeypatch):
    _options(monkeypatch, persistent=True, clean_start=True)
    backend, ssh, mc = _backend(repo, tmp_path, monkeypatch, lambda _: None)
    backend._scope = str(repo)
    assert (await _turn(backend, "start clean"))[-1].metadata["ok"]
    leftover = Path(backend._state.remote_dir) / PRIVATE
    leftover.parent.mkdir(parents=True, exist_ok=True)
    leftover.write_text(FIXTURE)
    _options(monkeypatch, persistent=True)
    mc.calls.clear()
    events = await _turn(backend, "continue")
    assert not events[-1].metadata["ok"] and "owner review" in events[-1].content
    assert not any(n in {"t3_thread_send", "t3_thread_launch"} for n, _ in mc.calls)


def test_project_option_is_read_only_from_explicit_true(tmp_path, monkeypatch):
    path = tmp_path / "projects.json"
    monkeypatch.setenv("MULTICODE_HUB_PROJECTS_FILE", str(path))
    scope = str(tmp_path / "scope")
    for value, expected in ((True, True), ("yes", False), (1, False)):
        path.write_text(json.dumps({scope: {"clean_start": value, "persistent": False}}))
        assert hw.project_options(scope).clean_start is expected
    path.write_text("{}")
    assert hw.project_options(scope).clean_start is False
