"""#258: orphan sweep must never signal a stale/reused numeric PID."""

import builtins
import io
import logging
import os
import signal
import subprocess
from datetime import datetime, timezone

import pytest


@pytest.fixture
def manager():
    from app.db import init_db
    from app.manager import SessionManager

    init_db()
    instance = SessionManager()
    # The production guard refuses every sweep when the registry is empty. A known live
    # session is the control arm: the unknown FD below reaches the real orphan path.
    instance.sessions["known-live-session"] = object()
    return instance


def _save_handover_identity(
    session_id: str,
    *,
    pid: int,
    started_at: int,
    backend_type: str,
) -> None:
    from app.db import save_handover_state, save_session

    save_session({
        "id": session_id,
        "name": session_id,
        "scope": "/tmp",
        "cwd": "/tmp",
        "model": "gpt-5.6-luna",
        "system_prompt": "",
        "status": "idle",
        "session_id": "thread-old",
        "cost_usd": 0.0,
        "worktree_path": None,
        "branch": None,
        "is_orchestrator": False,
        "role": "worker",
        "pipeline": "default",
        "backend_type": backend_type,
        "color": "#818cf8",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    })
    save_handover_state(session_id, "", "", pid, started_at)


def _proc_stat(pid: int, started_at: int) -> bytes:
    # process_start_time reads field 22: tail index 19 after the closing command parenthesis.
    tail = ["S", *("0" for _ in range(18)), str(started_at)]
    return f"{pid} (orchestra-test) {' '.join(tail)}\n".encode()


def _close_if_open(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass


@pytest.mark.asyncio
async def test_t1_first_restart_reused_foreign_pid_survives_real_sweep(
    manager,
    monkeypatch,
    caplog,
):
    """First restart: a handover PID is stale before the new supervisor sweeps its FD.

    This deliberately uses a real foreign process. The old implementation sends it SIGTERM;
    the fixed path must open a pidfd, reject the mismatched lifetime/runtime, and leave it alive.
    """
    from app import backend_jsonrpc

    foreign = subprocess.Popen(["/usr/bin/sleep", "30"])
    actual_start = backend_jsonrpc.process_start_time(foreign.pid)
    assert actual_start > 1
    _save_handover_identity(
        "gone-after-handover",
        pid=foreign.pid,
        started_at=actual_start - 1,
        backend_type="codex",
    )
    # A runtime switch is persisted independently of the handover tuple. The sweep must not
    # use this mutable field as proof of what owns the old PID.
    from app.db import _conn

    with _conn() as connection:
        connection.execute(
            "UPDATE sessions SET backend_type = 'grok' WHERE id = ?",
            ("gone-after-handover",),
        )

    orphan_fd, peer_fd = os.pipe()
    monkeypatch.setattr(
        "app.fdstore.acquire_fds",
        lambda: {"agent:gone-after-handover:stdout": orphan_fd},
    )
    real_pidfd_open = os.pidfd_open
    opened: list[int] = []

    def track_pidfd_open(pid: int, flags: int = 0) -> int:
        opened.append(pid)
        return real_pidfd_open(pid, flags)

    monkeypatch.setattr(os, "pidfd_open", track_pidfd_open)
    caplog.set_level(logging.ERROR)
    try:
        swept = await manager.sweep_orphan_fds()
        try:
            foreign.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            pass

        assert foreign.poll() is None, (
            "the first-restart sweep signalled a foreign process through a stale/reused PID"
        )
        assert swept == 1
        with pytest.raises(OSError):
            os.fstat(orphan_fd)
        assert opened == [foreign.pid], (
            "the negative arm must reach pidfd identity validation, not skip the signal path"
        )
        assert any(
            record.levelno >= logging.ERROR and str(foreign.pid) in record.getMessage()
            for record in caplog.records
        ), "unproven identity must be refused loudly with the candidate PID"
    finally:
        if foreign.poll() is None:
            foreign.terminate()
        foreign.wait(timeout=3)
        _close_if_open(orphan_fd)
        _close_if_open(peer_fd)


@pytest.mark.asyncio
async def test_t1_verified_codex_and_grok_orphans_signal_only_through_pidfd(
    manager,
    monkeypatch,
):
    """Positive controls: the safety check must not turn into 'never reap an orphan'."""
    from app.backend_codex import CODEX_BIN
    from app.backend_grok import GROK_BIN

    codex_pid, grok_pid = 2_147_480_001, 2_147_480_002
    codex_start, grok_start = 881_001, 881_002
    # backend_type is intentionally contradictory: it is not part of the coherent snapshot.
    _save_handover_identity(
        "verified-codex", pid=codex_pid, started_at=codex_start, backend_type="grok"
    )
    _save_handover_identity(
        "verified-grok", pid=grok_pid, started_at=grok_start, backend_type="codex"
    )

    codex_fd, codex_peer = os.pipe()
    grok_fd, grok_peer = os.pipe()
    monkeypatch.setattr(
        "app.fdstore.acquire_fds",
        lambda: {
            "agent:verified-codex:stdout": codex_fd,
            "agent:verified-grok:stdout": grok_fd,
        },
    )

    cmdlines = {
        codex_pid: b"node\0" + os.fsencode(CODEX_BIN) + b"\0app-server\0--stdio\0",
        grok_pid: (
            b"node\0" + os.fsencode(GROK_BIN) + b"\0agent\0--always-approve\0stdio\0"
        ),
    }
    starts = {codex_pid: codex_start, grok_pid: grok_start}
    real_open = builtins.open
    events: list[tuple] = []

    def fake_open(path, *args, **kwargs):
        raw = os.fspath(path)
        for pid in (codex_pid, grok_pid):
            if raw == f"/proc/{pid}/cmdline":
                events.append(("cmdline", pid))
                return io.BytesIO(cmdlines[pid])
            if raw == f"/proc/{pid}/stat":
                events.append(("stat", pid))
                return io.BytesIO(_proc_stat(pid, starts[pid]))
        return real_open(path, *args, **kwargs)

    pidfds = {codex_pid: 90_001, grok_pid: 90_002}

    def fake_pidfd_open(pid: int, flags: int = 0) -> int:
        events.append(("pidfd_open", pid))
        return pidfds[pid]

    signalled: list[tuple[int, signal.Signals]] = []

    def fake_pidfd_send_signal(pidfd, sig, *args, **kwargs):
        events.append(("pidfd_signal", pidfd))
        signalled.append((pidfd, sig))

    real_close = os.close
    closed_pidfds: list[int] = []

    def fake_close(fd: int) -> None:
        if fd in pidfds.values():
            events.append(("pidfd_close", fd))
            closed_pidfds.append(fd)
            return
        real_close(fd)

    numeric_signals: list[tuple[int, signal.Signals]] = []
    monkeypatch.setattr(builtins, "open", fake_open)
    monkeypatch.setattr(os, "pidfd_open", fake_pidfd_open)
    monkeypatch.setattr(signal, "pidfd_send_signal", fake_pidfd_send_signal)
    monkeypatch.setattr(os, "close", fake_close)
    monkeypatch.setattr(os, "kill", lambda pid, sig: numeric_signals.append((pid, sig)))
    try:
        swept = await manager.sweep_orphan_fds()

        assert swept == 2
        assert numeric_signals == [], "numeric os.kill reopens the PID-reuse race"
        assert signalled == [
            (pidfds[codex_pid], signal.SIGTERM),
            (pidfds[grok_pid], signal.SIGTERM),
        ]
        assert closed_pidfds == [pidfds[codex_pid], pidfds[grok_pid]]
        for pid in (codex_pid, grok_pid):
            assert events.index(("pidfd_open", pid)) < events.index(("cmdline", pid)), (
                "pidfd must pin the process before /proc identity is read"
            )
    finally:
        for fd in (codex_fd, codex_peer, grok_fd, grok_peer):
            _close_if_open(fd)


@pytest.mark.asyncio
async def test_t1_unverifiable_candidate_does_not_abort_later_orphan_cleanup(
    manager,
    monkeypatch,
    caplog,
):
    """One malformed /proc record is local; the next verified orphan still gets reaped."""
    from app.backend_codex import CODEX_BIN

    denied_pid, verified_pid = 2_147_480_011, 2_147_480_012
    denied_start, verified_start = 882_011, 882_012
    _save_handover_identity(
        "unverifiable", pid=denied_pid, started_at=denied_start, backend_type="codex"
    )
    _save_handover_identity(
        "later-valid", pid=verified_pid, started_at=verified_start, backend_type="codex"
    )
    denied_fd, denied_peer = os.pipe()
    verified_fd, verified_peer = os.pipe()
    monkeypatch.setattr(
        "app.fdstore.acquire_fds",
        lambda: {
            "agent:unverifiable:stdout": denied_fd,
            "agent:later-valid:stdout": verified_fd,
        },
    )

    real_open = builtins.open

    def fake_open(path, *args, **kwargs):
        raw = os.fspath(path)
        if raw in {
            f"/proc/{denied_pid}/cmdline",
            f"/proc/{verified_pid}/cmdline",
        }:
            return io.BytesIO(
                b"node\0" + os.fsencode(CODEX_BIN) + b"\0app-server\0--stdio\0"
            )
        if raw == f"/proc/{denied_pid}/stat":
            malformed = ["S", *("0" for _ in range(18)), "not-a-number"]
            return io.BytesIO(
                f"{denied_pid} (bad-stat) {' '.join(malformed)}\n".encode()
            )
        if raw == f"/proc/{verified_pid}/stat":
            return io.BytesIO(_proc_stat(verified_pid, verified_start))
        return real_open(path, *args, **kwargs)

    opened: list[int] = []

    def fake_pidfd_open(pid: int, flags: int = 0) -> int:
        opened.append(pid)
        return {denied_pid: 90_011, verified_pid: 90_012}[pid]

    signalled: list[tuple[int, signal.Signals]] = []
    real_close = os.close
    closed_pidfds: list[int] = []

    def fake_close(fd: int) -> None:
        if fd in {90_011, 90_012}:
            closed_pidfds.append(fd)
            return
        real_close(fd)

    numeric_signals: list[tuple[int, signal.Signals]] = []
    monkeypatch.setattr(builtins, "open", fake_open)
    monkeypatch.setattr(os, "pidfd_open", fake_pidfd_open)
    monkeypatch.setattr(
        signal,
        "pidfd_send_signal",
        lambda pidfd, sig, *args, **kwargs: signalled.append((pidfd, sig)),
    )
    monkeypatch.setattr(os, "close", fake_close)
    monkeypatch.setattr(os, "kill", lambda pid, sig: numeric_signals.append((pid, sig)))
    caplog.set_level(logging.ERROR)
    try:
        swept = await manager.sweep_orphan_fds()

        assert swept == 2
        assert opened == [denied_pid, verified_pid]
        assert numeric_signals == []
        assert signalled == [(90_012, signal.SIGTERM)], (
            "failure to verify one candidate must not block a later legitimate orphan"
        )
        assert closed_pidfds == [90_011, 90_012], (
            "both the malformed candidate and the signalled candidate must release their pidfd"
        )
        assert any(
            record.levelno >= logging.ERROR and str(denied_pid) in record.getMessage()
            for record in caplog.records
        ), "malformed /proc identity must be loud and identify the refused PID"
    finally:
        for fd in (denied_fd, denied_peer, verified_fd, verified_peer):
            _close_if_open(fd)
