"""#324 — only the systemd socket-activated instance may start the TG bridge.

An app started by an agent in its worktree inherits the production TG_BRIDGE_TOKEN from
the copied `.env` and fights the real process for getUpdates, so the user's incoming
Telegram messages disappear.

`start_bridge` is imported by name at module scope on purpose: conftest's autouse
`_no_tg_bridge` fixture replaces the module ATTRIBUTE `tg_bridge.start_bridge` with an
AsyncMock, and this binding keeps pointing at the real coroutine. Calling the mock would
make every assertion below vacuous.
"""

import os

import pytest

import app.tg_bridge as tb
from app.tg_bridge import UnmanagedInstanceError, start_bridge


class _ReachedBridgeBody(Exception):
    """Raised in place of the first real step of start_bridge."""


@pytest.fixture
def bridge_body_tripwire(monkeypatch):
    """Make the first real step of start_bridge explode.

    Without it a guard that silently stopped firing would let the refusal tests pass
    against a bridge that actually started: the coroutine would run on to the
    "no token" branch and return None, and `pytest.raises` is the only thing standing
    between that and a green run.
    """
    async def _boom():
        raise _ReachedBridgeBody()

    monkeypatch.setattr(tb, "_reset_tg_delivery_state", _boom)


@pytest.fixture
def manager_stub():
    class _Manager:
        tg_topics_remover = None

    return _Manager()


def _as_worktree_instance(monkeypatch, tmp_path):
    """Environment of an app an agent starts in its worktree: systemd variables are
    inherited from the live service, cwd is a worktree copy of the repository."""
    worktree = tmp_path / "worktrees" / "home-kesha-orchestra" / "some-worker"
    worktree.mkdir(parents=True)
    monkeypatch.chdir(worktree)
    monkeypatch.setenv("LISTEN_PID", str(os.getpid() + 1))
    monkeypatch.setenv("LISTEN_FDS", "59")
    monkeypatch.setenv("NOTIFY_SOCKET", "/run/systemd/notify")
    monkeypatch.setenv("INVOCATION_ID", "04fd72909f134e93ab9726ccebc88331")
    monkeypatch.setenv("SYSTEMD_EXEC_PID", str(os.getpid() + 1))


@pytest.mark.asyncio
async def test_worktree_instance_refuses_to_start(
    monkeypatch, tmp_path, manager_stub, bridge_body_tripwire
):
    _as_worktree_instance(monkeypatch, tmp_path)

    with pytest.raises(UnmanagedInstanceError) as excinfo:
        await start_bridge(manager_stub)

    assert tb.bot is None
    # Fail loud: the refusal has to say which check failed and where it happened, or the
    # agent who started the instance cannot tell a guard from a crash.
    message = str(excinfo.value)
    assert "LISTEN_PID" in message
    assert str(os.getpid()) in message
    assert os.getcwd() in message


@pytest.mark.asyncio
async def test_bare_process_refuses_to_start(
    monkeypatch, manager_stub, bridge_body_tripwire
):
    """No systemd variables at all — the guard must fail closed, not open."""
    for key in ("LISTEN_PID", "LISTEN_FDS", "NOTIFY_SOCKET", "SYSTEMD_EXEC_PID"):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(UnmanagedInstanceError) as excinfo:
        await start_bridge(manager_stub)

    assert tb.bot is None
    assert "LISTEN_PID is unset" in str(excinfo.value)


@pytest.mark.asyncio
async def test_socket_activated_instance_is_let_through(
    monkeypatch, manager_stub, bridge_body_tripwire
):
    """Permitting arm. A guard that only ever refuses is indistinguishable from a guard
    wired to reject everything, which would take the production bridge down with it."""
    monkeypatch.setenv("LISTEN_PID", str(os.getpid()))

    with pytest.raises(_ReachedBridgeBody):
        await start_bridge(manager_stub)


def test_live_service_environment_passes_the_guard(monkeypatch):
    """The recorded environment of the running orchestra.service, replayed verbatim:
    MainPID 2577299 with LISTEN_PID=2577299 (measured 18.08.2026). The bridge must not
    need any operator action to keep working."""
    monkeypatch.setattr(os, "getpid", lambda: 2577299)
    monkeypatch.setenv("LISTEN_PID", "2577299")
    monkeypatch.setenv("LISTEN_FDS", "59")
    monkeypatch.setenv("NOTIFY_SOCKET", "/run/systemd/notify")

    assert tb._unmanaged_instance_reason() is None
