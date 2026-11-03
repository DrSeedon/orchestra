"""Visible hub names use session identity; workspace identity stays private and unique."""

import shutil

import pytest

from app import hub_workspace as hw
from app.multicode_client import MultiCodeError
from app.session import AgentSession
from tests.test_hub_workspace import repo, _backend, _offline_hub_pool, _turn


def _session_backend(root, tmp_path, monkeypatch, *, name="fix-steer-fifo", scope=None):
    backend, ssh, mc = _backend(root, tmp_path, monkeypatch, lambda _: None)
    session = AgentSession(id="session-id", name=name, cwd=str(root),
                           scope=str(scope or root), model=backend.model)
    backend._scope = session.scope
    backend._bridge = session._hub_bridge()
    return backend, ssh, mc, session


def _created_titles(mc):
    return {name: args["title"] for name, args in mc.calls
            if name in {"t3_project_create", "t3_thread_launch"}}


@pytest.mark.asyncio
async def test_project_and_thread_titles_use_canonical_session_name(repo, tmp_path, monkeypatch):
    backend, _, mc, _ = _session_backend(repo, tmp_path, monkeypatch)
    events = await _turn(backend, "synthetic task")
    assert events[-1].metadata["ok"], events
    assert _created_titles(mc) == {"t3_project_create": "hub-fix-steer-fifo",
                                   "t3_thread_launch": "hub-fix-steer-fifo"}
    assert backend._state.ws_id != "hub-fix-steer-fifo"
    assert backend.session_id == backend._state.ws_id
    assert backend._state.path().stem == backend._state.ws_id
    assert backend._state.remote_dir.endswith("/" + backend._state.ws_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("identity", ["no-bridge", "missing-name", "empty-name", "blank-name"])
async def test_no_name_keeps_legacy_fallback_without_guessing_from_cwd(
    repo, tmp_path, monkeypatch, identity,
):
    backend, _, mc = _backend(repo, tmp_path, monkeypatch, lambda _: None)
    if identity != "no-bridge":
        from types import SimpleNamespace
        from app.hub_outbox import HubBridge, Identity

        who = Identity("id", "", str(repo))
        if identity == "missing-name":
            who = SimpleNamespace(base_branch="")
        elif identity == "blank-name":
            who.name = " \t "
        backend._bridge = HubBridge(lambda: who)
    events = await _turn(backend, "synthetic task")
    assert events[-1].metadata["ok"], events
    assert _created_titles(mc) == {"t3_project_create": f"orchestra {backend.session_id}",
                                   "t3_thread_launch": backend.session_id}


@pytest.mark.asyncio
async def test_same_name_in_different_scopes_keeps_separate_workspace_records(
    repo, tmp_path, monkeypatch,
):
    def allocate_ids(mc, suffix):
        original_call = mc.tool_call

        async def call(name, args):
            result = await original_call(name, args)
            if name == "t3_project_create":
                return {"id": f"project-{suffix}"}
            if name == "t3_thread_launch":
                return {**result, "threadId": f"thread-{suffix}"}
            return result

        mc.tool_call = call

    other = tmp_path / "other-scope" / "unrelated-checkout-name"
    shutil.copytree(repo, other)
    first, _, mc1, _ = _session_backend(repo, tmp_path, monkeypatch)
    allocate_ids(mc1, "one")
    assert (await _turn(first, "first scope"))[-1].metadata["ok"]
    before = first._state.path().read_bytes()
    second, _, mc2, _ = _session_backend(other, tmp_path, monkeypatch)
    allocate_ids(mc2, "two")
    assert (await _turn(second, "second scope"))[-1].metadata["ok"]
    one, two = first._state, second._state
    assert _created_titles(mc1) == _created_titles(mc2)
    assert _created_titles(mc2)["t3_thread_launch"] == "hub-fix-steer-fifo"
    assert one.ws_id != two.ws_id and one.remote_dir != two.remote_dir
    assert (one.project_id, one.thread_id) == ("project-one", "thread-one")
    assert (two.project_id, two.thread_id) == ("project-two", "thread-two")
    for mc, state in ((mc1, one), (mc2, two)):
        launched = next(args for name, args in mc.calls if name == "t3_thread_launch")
        assert launched["projectId"] == state.project_id
    assert one.path() != two.path() and one.worktree != two.worktree
    assert one.path().read_bytes() == before
    assert hw.WorkspaceState.load(one.ws_id) == one
    assert hw.WorkspaceState.load(two.ws_id) == two
    assert (await _turn(first, "continue first scope"))[-1].metadata["ok"]
    assert first.session_id == one.ws_id
    assert [args["threadId"] for name, args in mc1.calls if name == "t3_thread_send"] == [one.thread_id]
    assert two.path().exists()


@pytest.mark.asyncio
async def test_resume_legacy_workspace_reuses_saved_ids_without_renaming(repo, tmp_path, monkeypatch):
    old_backend, _, mc = _backend(repo, tmp_path, monkeypatch, lambda _: None)
    assert (await _turn(old_backend, "legacy creation"))[-1].metadata["ok"]
    old = old_backend._state
    ids = old.ws_id, old.remote_dir, old.project_id, old.thread_id
    assert _created_titles(mc)["t3_thread_launch"] == old.ws_id
    backend, _, _, _ = _session_backend(repo, tmp_path, monkeypatch)
    backend._resume = old.ws_id

    async def client():
        return mc

    backend._client = client
    mc.calls.clear()
    events = await _turn(backend, "resume saved workspace")
    assert events[-1].metadata["ok"], events
    state = backend._state
    assert (state.ws_id, state.remote_dir, state.project_id, state.thread_id) == ids
    assert state.turns == old.turns + 1
    assert [args["threadId"] for name, args in mc.calls if name == "t3_thread_send"] == [old.thread_id]
    assert not _created_titles(mc)
    assert not any("update" in name or "delete" in name for name, _ in mc.calls)


@pytest.mark.asyncio
async def test_replacement_thread_uses_current_session_name_and_same_project(repo, tmp_path, monkeypatch):
    backend, _, mc, session = _session_backend(repo, tmp_path, monkeypatch)
    assert (await _turn(backend, "initial task"))[-1].metadata["ok"]
    state = backend._state
    original_call = mc.tool_call

    async def call(name, args):
        if name == "t3_thread_send":
            raise MultiCodeError("thread_not_found")
        return await original_call(name, args)

    mc.tool_call = call
    mc.calls.clear()
    session.name = "recovered-worker"
    events = await _turn(backend, "replace refused thread")
    assert events[-1].metadata["ok"], events
    assert _created_titles(mc) == {"t3_thread_launch": "hub-recovered-worker"}
    launched = next(args for name, args in mc.calls if name == "t3_thread_launch")
    assert launched["projectId"] == state.project_id
    assert backend.session_id == state.ws_id
