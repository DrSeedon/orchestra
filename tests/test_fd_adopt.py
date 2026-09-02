"""#230 T2–T9: adopt a surviving agent process instead of respawning it.

RED on purpose until docs/tasks/230/plan.md is implemented. Every oracle here is written so a
fake implementation fails it: adoption is proved by an event that crosses the pipe AFTER the
handover, not by a flag someone set.

The behaviour was measured first, on throwaway systemd units (docs/tasks/230/research.md F1,
plan.md falsifiers): a real Codex and a real Claude CLI keep streaming their turn to the next
supervisor generation, and a Claude turn waits 120 s for a permission answer that only the new
generation can give.
"""
import asyncio
import contextlib
import json
import os
import signal
from datetime import datetime, timezone
from unittest.mock import patch

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    from app.db import init_db
    init_db()
    return db_path


@pytest.fixture
def mgr(db, tmp_path, monkeypatch):
    wt_root = tmp_path / "worktrees"
    wt_root.mkdir()
    monkeypatch.setattr("app.workspace.WORKTREE_ROOT", wt_root)
    from app.manager import SessionManager
    return SessionManager()


def _pipe_pair():
    """(our_write_end, our_read_end) plus the CLI's ends, like an adopted process."""
    cli_to_us_r, cli_to_us_w = os.pipe()
    us_to_cli_r, us_to_cli_w = os.pipe()
    return cli_to_us_r, cli_to_us_w, us_to_cli_r, us_to_cli_w


async def _read_bounded(fd: int, timeout: float = 5.0, until: bytes | None = None) -> bytes:
    """Read with a deadline, then FAIL — a test that HANGS on regression gets skipped one day.

    With `until`, keeps accumulating across reads until the marker appears: returning on the
    first chunk would give a false red on a frame that arrives in pieces. The descriptor is
    put back into blocking mode on the way out, so a later reader is unaffected.
    """
    was_blocking = os.get_blocking(fd)
    os.set_blocking(fd, False)
    buf = b""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    try:
        while loop.time() < deadline:
            try:
                chunk = os.read(fd, 65536)
            except BlockingIOError:
                await asyncio.sleep(0.02)
                continue
            buf += chunk
            if until is None or until in buf:
                return buf
            if not chunk:
                break
        raise AssertionError(
            f"expected {until!r} on fd {fd} within {timeout}s, got {buf[:120]!r}"
            if until else f"nothing arrived on fd {fd} within {timeout}s")
    finally:
        os.set_blocking(fd, was_blocking)


def _store_active_turn(session_id: str, turn_id: str):
    """Put the in-flight turn id where T4 must persist it. Returns what is actually stored:
    before T4 adds the column there is nowhere to put it, and the oracle says so out loud
    instead of quietly dropping the fourth argument of adopt()."""
    import sqlite3
    from app.db import _conn
    try:
        with _conn() as c:
            c.execute("UPDATE sessions SET active_turn_id=? WHERE id=?", (turn_id, session_id))
        return turn_id
    except sqlite3.OperationalError as exc:
        # ONLY "no such column" is a legitimate reason to weaken this oracle. "database is
        # locked" must not silently do it, or a locked DB turns the test quietly green.
        if "no such column" not in str(exc):
            raise
        return None


def _save_running_session(session_id="adopted-1", model="gpt-5.6-luna", thread="thread-abc"):
    from app.db import save_session
    save_session({
        "id": session_id, "name": session_id, "scope": "/tmp", "cwd": "/tmp",
        "model": model, "system_prompt": "", "status": "running",
        "session_id": thread, "cost_usd": 0.0, "worktree_path": None, "branch": None,
        "is_orchestrator": False, "role": "worker", "pipeline": "default", "color": "#818cf8",
        "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
    })


# ------------------------------------------------- T2: Codex adopts and reads the live stream

@pytest.mark.asyncio
async def test_t2_codex_adopt_does_not_spawn_and_reads_the_live_stream(monkeypatch):
    from app.backend_codex import CodexBackend

    backend = CodexBackend(model="gpt-5.6-luna", cwd="/tmp", system_prompt="")

    async def explode(*a, **kw):
        raise AssertionError("adopt() must NOT spawn a process — the CLI is already running")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", explode)

    cli_out_r, cli_out_w, cli_in_r, cli_in_w = _pipe_pair()
    try:
        # bounded: an adopt() that waits for a handshake from the live app-server would hang
        # here forever, because nothing has been written to the pipe yet (reproduced: 35s)
        await asyncio.wait_for(
            backend.adopt(cli_in_w, cli_out_r, thread_id="thread-abc",
                          active_turn_id="turn-xyz"),
            timeout=5,
        )
        assert backend.session_id == "thread-abc"
        assert backend.is_alive is True

        # the surviving app-server emits an event of the turn it never stopped working on;
        # a stub that merely sets flags cannot deliver this
        os.write(cli_out_w, (json.dumps({
            "method": "turn/completed",
            "params": {"threadId": "thread-abc",
                       "turn": {"id": "turn-xyz", "items": [
                           {"type": "agentMessage", "text": "FINISHED"}]}},
        }) + "\n").encode())

        seen = []
        async def collect():
            async for event in backend.events():
                seen.append(event)
                break

        await asyncio.wait_for(collect(), timeout=5)
        assert seen, "adopted backend must deliver events that arrived after the handover"
    finally:
        # ONLY the CLI-side ends. cli_in_w/cli_out_r belong to the adopted transports
        # (os.fdopen took them): closing them here too is a double close that resurfaces as
        # EBADF from asyncio's __del__ inside some LATER test — a flake that reads as a defect.
        for fd in (cli_out_w, cli_in_r):
            try:
                os.close(fd)
            except OSError:
                pass


# ------------------------------------------------- T3: Claude transport over inherited pipes

@pytest.mark.asyncio
async def test_t3_inherited_fd_transport_round_trip_and_fragmentation():
    from app.backend_claude import InheritedFdTransport

    cli_out_r, cli_out_w, cli_in_r, cli_in_w = _pipe_pair()
    try:
        transport = InheritedFdTransport(cli_in_w, cli_out_r)
        await transport.connect()
        assert transport.is_ready() is True

        # a frame LARGER than PIPE_BUF (4096) arrives in several reads — this is the
        # partial-line risk named in research F3, and the reason a one-line test is not enough
        big = {"type": "assistant", "message": {"content": "x" * 9000}}
        os.write(cli_out_w, (json.dumps(big) + "\n").encode())
        os.write(cli_out_w, (json.dumps({"type": "result", "subtype": "success"}) + "\n").encode())

        got = []
        async def collect():
            async for message in transport.read_messages():
                got.append(message)
                if len(got) == 2:
                    break

        await asyncio.wait_for(collect(), timeout=5)
        assert got[0] == big, "a frame split across reads must be reassembled, not truncated"
        assert got[1] == {"type": "result", "subtype": "success"}

        # our answer must reach the CLI — this is the permission control_response path from
        # falsifier 1. Bounded on purpose: an implementation that buffers the frame until
        # close() would otherwise hang the suite instead of failing (reproduced: 45s, exit 143)
        await transport.write(json.dumps({"type": "control_response"}) + "\n")
        await _read_bounded(cli_in_r, until=b"control_response")

        await transport.close()
        assert transport.is_ready() is False
    finally:
        # ONLY the CLI-side ends. cli_in_w/cli_out_r belong to the adopted transports
        # (os.fdopen took them): closing them here too is a double close that resurfaces as
        # EBADF from asyncio's __del__ inside some LATER test — a flake that reads as a defect.
        for fd in (cli_out_w, cli_in_r):
            try:
                os.close(fd)
            except OSError:
                pass


@pytest.mark.asyncio
async def test_t3_write_before_connect_fails_loudly_not_with_nameerror():
    """Guard added after the freeze: the not-ready path raised NameError until the import
    was fixed, and the ticket oracle never walks it."""
    from claude_agent_sdk import CLIConnectionError

    from app.backend_claude import InheritedFdTransport

    r, w = os.pipe()
    try:
        transport = InheritedFdTransport(w, r)
        with pytest.raises(CLIConnectionError):
            await transport.write("{}\n")
    finally:
        os.close(r)
        os.close(w)


# --- post-freeze guards for the blocking findings of the implementation review ---

@pytest.mark.asyncio
async def test_impl_leftover_head_is_fed_back_so_the_frame_survives():
    """The bytes the previous generation had already read must be prepended, or the first frame
    arrives headless and is dropped as invalid JSON — possibly the terminal event."""
    import base64

    from app.backend_codex import CodexBackend

    frame = json.dumps({"method": "turn/completed",
                        "params": {"threadId": "t", "turn": {"id": "x", "items": []}}})
    head, tail = frame[:20].encode(), frame[20:].encode() + b"\n"

    backend = CodexBackend(model="gpt-5.6-luna", cwd="/tmp", system_prompt="")
    cli_out_r, cli_out_w, cli_in_r, cli_in_w = _pipe_pair()
    try:
        await backend.adopt(cli_in_w, cli_out_r, thread_id="t", active_turn_id="x",
                            leftover=base64.b64encode(head).decode(), cli_pid=0)
        os.write(cli_out_w, tail)  # only the TAIL crosses the pipe

        seen = []

        async def collect():
            async for event in backend.events():
                seen.append(event)
                break

        await asyncio.wait_for(collect(), timeout=5)
        assert seen, "the reassembled frame must be delivered, not dropped as invalid JSON"
    finally:
        await backend.teardown_adopted()
        # only the CLI-side ends: the adopted transports own cli_in_w/cli_out_r
        for fd in (cli_out_w, cli_in_r):
            try:
                os.close(fd)
            except OSError:
                pass


@pytest.mark.asyncio
async def test_impl_adopted_disconnect_tears_down_and_terminates_the_cli(monkeypatch):
    """`disconnect()` used to return immediately for an adopted backend (no Process, no scope),
    so a replacement CLI ran next to the adopted one — an unowned duplicate."""
    from app import backend_jsonrpc
    from app.backend_codex import CodexBackend

    killed = []
    monkeypatch.setattr(backend_jsonrpc, "terminate_cli_process",
                        lambda pid, label, started_at=0: killed.append(pid))

    backend = CodexBackend(model="gpt-5.6-luna", cwd="/tmp", system_prompt="")
    cli_out_r, cli_out_w, cli_in_r, cli_in_w = _pipe_pair()
    try:
        await backend.adopt(cli_in_w, cli_out_r, thread_id="t", active_turn_id="x",
                            cli_pid=4242)
        assert backend.pid == 4242, "the pid must survive into this generation"
        reader_task = backend._reader_task
        await backend.disconnect()
        assert killed == [4242], "replacing an adopted CLI must terminate it"
        assert reader_task.done(), "the adopted reader task must be cancelled"
        assert backend.is_alive is False
    finally:
        for fd in (cli_out_w, cli_in_r):
            try:
                os.close(fd)
            except OSError:
                pass


@pytest.mark.asyncio
async def test_impl_partial_handover_rolls_back_the_stored_descriptor(mgr, monkeypatch):
    """Half a pair is worse than none: not adoptable, and the sweep keeps it because the
    session still exists. The failed handover must remove what it already stored."""
    from tests.conftest import make_backend_mock

    _save_running_session("rollback-1")
    backend = make_backend_mock()
    backend.fd_in, backend.fd_out = 21, 22
    backend.active_turn_id = "turn-r"
    backend.leftover = ""
    backend.pid = 0

    stored, removed = [], []

    def flaky_store(name, fds):
        if name.endswith(".stdout"):
            raise RuntimeError("systemd store is full")
        stored.append(name)

    monkeypatch.setattr("app.fdstore.store_fds", flaky_store)
    monkeypatch.setattr("app.fdstore.remove_fds", lambda name: removed.append(name))

    with patch("app.session.AgentSession._make_backend", return_value=backend):
        await mgr.auto_resume_all()
        session = mgr.get("rollback-1")
        assert session is not None
        session._backend = backend
        handed = await mgr._hand_over_backend(session)

    assert handed is False, "a partial handover must fall back to stopping the agent"
    assert stored == ["agent.rollback-1.stdin"]
    assert removed == ["agent.rollback-1.stdin"], (
        f"the already-stored descriptor must be rolled back, removed={removed}")


@pytest.mark.asyncio
async def test_impl_quiesce_does_not_fabricate_process_death_and_carries_events():
    """Round-2 findings: cancelling the reader fired `_process/exited` (a live agent looked
    dead mid-handover), and parsed-but-unconsumed events were declared lost."""
    from app.backend_codex import CodexBackend

    backend = CodexBackend(model="gpt-5.6-luna", cwd="/tmp", system_prompt="")
    cli_out_r, cli_out_w, cli_in_r, cli_in_w = _pipe_pair()
    try:
        await backend.adopt(cli_in_w, cli_out_r, thread_id="t", active_turn_id="x")
        # one complete frame arrives and is parsed into the queue, nobody consumes it
        os.write(cli_out_w, (json.dumps({
            "method": "turn/completed",
            "params": {"threadId": "t", "turn": {"id": "x", "items": []}},
        }) + "\n").encode())
        await asyncio.sleep(0.3)
        assert not backend._notifications.empty(), "precondition: an event is queued"

        assert await backend.quiesce_for_handover() is True

        # The queue is EMPTY after quiescing BY DESIGN, so asserting on it proves nothing —
        # the first version of this guard stayed green with the flag removed. What actually
        # happens without the flag is that `_process/exited` is CARRIED FORWARD in `leftover`,
        # so that is where the assertion belongs.
        import base64
        carried = base64.b64decode(backend.leftover)
        assert b"_process/exited" not in carried, (
            f"quiescing must not fabricate the agent's death, got {carried[:120]!r}")
        assert b"turn/completed" in carried, (
            f"the queued terminal event must travel to the next generation, got {carried[:80]!r}")
        # and the pending-request lie must not be fabricated either
        assert not any(f.done() for f in backend._pending_requests.values()), (
            "quiescing must not complete in-flight requests with a fabricated error")
    finally:
        await backend.teardown_adopted()
        for fd in (cli_out_w, cli_in_r):
            try:
                os.close(fd)
            except OSError:
                pass


@pytest.mark.asyncio
async def test_impl_handover_refused_while_a_request_is_in_flight():
    """Round-3 finding: cancelling the reader completed pending JSON-RPC futures with a
    fabricated "app-server exited" error — a lie about a process that is still alive. A mid-turn
    `turn/steer` would end with an unknown outcome across the restart, so refuse instead."""
    from app.backend_codex import CodexBackend

    backend = CodexBackend(model="gpt-5.6-luna", cwd="/tmp", system_prompt="")
    cli_out_r, cli_out_w, cli_in_r, cli_in_w = _pipe_pair()
    try:
        await backend.adopt(cli_in_w, cli_out_r, thread_id="t", active_turn_id="x")
        pending = asyncio.get_running_loop().create_future()
        backend._pending_requests[99] = pending

        assert await backend.quiesce_for_handover() is False, (
            "a handover that would orphan an in-flight request must be refused")
        assert not pending.done(), "the pending request must not be failed by the refusal"

        pending.cancel()
        assert await backend.quiesce_for_handover() is True, (
            "with nothing in flight the handover proceeds")
    finally:
        await backend.teardown_adopted()
        for fd in (cli_out_w, cli_in_r):
            try:
                os.close(fd)
            except OSError:
                pass


@pytest.mark.asyncio
async def test_impl_quiescing_does_not_fail_a_late_pending_request():
    """The reader's `finally` completes pending futures with "app-server exited". During a
    handover that is a LIE about a live process. The caller refuses a handover while requests
    are in flight, so this window is narrow — a request landing between the cancel and the
    finally — which is exactly why it needs its own oracle instead of a race."""
    from app.backend_codex import CodexBackend

    backend = CodexBackend(model="gpt-5.6-luna", cwd="/tmp", system_prompt="")
    cli_out_r, cli_out_w, cli_in_r, cli_in_w = _pipe_pair()
    late = None  # referenced in finally: a failing precondition must not become a NameError
    try:
        await backend.adopt(cli_in_w, cli_out_r, thread_id="t", active_turn_id="x")

        # PROVE the reader entered its body before cancelling it. A task cancelled before its
        # first step never runs `finally`, so the probe would observe "no effect" and read as
        # "no defect" — measured: with the gate deliberately removed this guard still passed
        # until this wait was added.
        os.write(cli_out_w, (json.dumps({"method": "thread/status/changed",
                                         "params": {"threadId": "t"}}) + "\n").encode())
        for _ in range(200):
            await asyncio.sleep(0.01)
            if not backend._notifications.empty():
                break
        assert not backend._notifications.empty(), "precondition: the reader is inside its loop"
        assert backend._reader_task.get_coro().cr_frame is not None, "reader coroutine started"

        backend._handover_quiescing = True  # the state a handover establishes
        late = asyncio.get_running_loop().create_future()
        backend._pending_requests[7] = late

        backend._reader_task.cancel()
        # `_read_stdout` catches CancelledError and returns, so awaiting it completes normally —
        # the cancellation is swallowed by design, and the `finally` still runs.
        with contextlib.suppress(asyncio.CancelledError):
            await backend._reader_task
        assert backend._reader_task.done()

        assert not late.done(), (
            "a request in flight during quiescing must NOT be failed with a fabricated "
            "'app-server exited' — the CLI is alive and may still answer it")
    finally:
        if late is not None:
            late.cancel()
        await backend.teardown_adopted()
        for fd in (cli_out_w, cli_in_r):
            try:
                os.close(fd)
            except OSError:
                pass


@pytest.mark.asyncio
async def test_impl_failed_handover_does_not_leave_quiescing_stuck_on():
    """Заход 4: the flag suppresses BOTH halves of the "process died" story and used to be
    cleared only by `teardown_adopted` — which a non-adopted backend never calls. Stuck ON, a
    REAL death is completely silent: no `_process/exited`, and pending futures are never
    completed, so their callers wait forever."""
    from app.backend_codex import CodexBackend

    backend = CodexBackend(model="gpt-5.6-luna", cwd="/tmp", system_prompt="")
    cli_out_r, cli_out_w, cli_in_r, cli_in_w = _pipe_pair()
    try:
        await backend.adopt(cli_in_w, cli_out_r, thread_id="t", active_turn_id="x")
        # make the re-encoding path fail: an unserialisable object in the queue
        await backend._notifications.put({"method": "x", "params": {"bad": object()}})

        assert await backend.quiesce_for_handover() is False
        assert backend._handover_quiescing is False, (
            "a refused handover must not leave the backend in the quiescing state — "
            "its real death would then be silent")

        # and the proof that silence is what was at stake: with the flag clear, the reader's
        # finally still tells the truth
        late = asyncio.get_running_loop().create_future()
        backend._pending_requests[11] = late
        backend._reader_task = asyncio.create_task(backend._read_stdout())
        await asyncio.sleep(0.05)
        os.close(cli_out_w)  # the CLI dies for real -> EOF
        await asyncio.wait_for(backend._reader_task, timeout=5)
        assert late.done(), "a REAL death must complete pending requests, not stay silent"
    finally:
        for fd in (cli_out_w, cli_in_r):
            try:
                os.close(fd)
            except OSError:
                pass


def test_t1_unknown_start_time_refuses_to_signal(monkeypatch, tmp_path):
    """Заход 4, note 2: an unrecorded start time must NOT be re-measured at adopt time — that
    describes whoever holds the pid NOW. Unknown identity means refuse, and an orphan surviving
    beats killing a stranger."""
    from app import backend_jsonrpc

    numeric_kills = []
    pidfd_signals = []
    monkeypatch.setattr(
        backend_jsonrpc.os, "kill", lambda pid, sig: numeric_kills.append(pid)
    )
    monkeypatch.setattr(
        backend_jsonrpc.os, "pidfd_open", lambda pid, flags=0: 91_110,
        raising=False,
    )
    monkeypatch.setattr(
        backend_jsonrpc.signal,
        "pidfd_send_signal",
        lambda pidfd, sig, *args, **kwargs: pidfd_signals.append((pidfd, sig)),
        raising=False,
    )
    real_close = backend_jsonrpc.os.close
    monkeypatch.setattr(
        backend_jsonrpc.os,
        "close",
        lambda fd: None if fd == 91_110 else real_close(fd),
    )
    monkeypatch.setattr(backend_jsonrpc, "process_start_time", lambda pid: 777)
    real_open = open

    def fake_open(path, *a, **kw):
        if str(path).endswith("/cmdline"):
            return real_open(tmp_path / "cmdline", *a, **kw)
        return real_open(path, *a, **kw)

    from app.backend_codex import CODEX_BIN
    codex_path = backend_jsonrpc._normalise_executable(CODEX_BIN)
    (tmp_path / "cmdline").write_bytes(
        b"node\0" + os.fsencode(codex_path) + b"\0app-server\0--stdio\0"
    )
    monkeypatch.setattr("builtins.open", fake_open)

    backend_jsonrpc.terminate_cli_process(4242, "Codex app-server", 0)
    assert numeric_kills == []
    assert pidfd_signals == [], (
        "with no recorded start time the identity is unproven — do not signal"
    )


def test_t1_helper_uses_pidfd_and_refuses_a_reused_pid(monkeypatch, tmp_path):
    """Round-2 finding: pid alone is not an identity. A reused number must not be signalled."""
    from app import backend_jsonrpc

    numeric_kills = []
    pidfd_signals = []
    closed_pidfds = []
    monkeypatch.setattr(
        backend_jsonrpc.os, "kill", lambda pid, sig: numeric_kills.append(pid)
    )
    monkeypatch.setattr(
        backend_jsonrpc.os, "pidfd_open", lambda pid, flags=0: 91_111,
        raising=False,
    )
    monkeypatch.setattr(
        backend_jsonrpc.signal,
        "pidfd_send_signal",
        lambda pidfd, sig, *args, **kwargs: pidfd_signals.append((pidfd, sig)),
        raising=False,
    )
    real_close = backend_jsonrpc.os.close
    monkeypatch.setattr(
        backend_jsonrpc.os,
        "close",
        lambda fd: closed_pidfds.append(fd) if fd == 91_111 else real_close(fd),
    )
    monkeypatch.setattr(backend_jsonrpc, "process_start_time", lambda pid: 999)

    real_open = open

    def fake_open(path, *a, **kw):
        if str(path).endswith("/cmdline"):
            return real_open(tmp_path / "cmdline", *a, **kw)
        return real_open(path, *a, **kw)

    from app.backend_codex import CODEX_BIN
    codex_path = backend_jsonrpc._normalise_executable(CODEX_BIN)
    (tmp_path / "cmdline").write_bytes(
        b"node\0" + os.fsencode(codex_path) + b"\0app-server\0--stdio\0"
    )
    monkeypatch.setattr("builtins.open", fake_open)

    backend_jsonrpc.terminate_cli_process(4242, "Codex app-server", 999)
    assert numeric_kills == [], "numeric os.kill reopens the PID-reuse race"
    assert pidfd_signals == [(91_111, signal.SIGTERM)]
    assert closed_pidfds == [91_111]

    pidfd_signals.clear()
    closed_pidfds.clear()
    backend_jsonrpc.terminate_cli_process(4242, "Codex app-server", 111)
    assert pidfd_signals == [], "a pid whose start time does not match must NOT be signalled"
    assert closed_pidfds == [91_111]

    pidfd_signals.clear()
    closed_pidfds.clear()
    (tmp_path / "cmdline").write_bytes(b"/usr/bin/notcodex-helper\0app-server\0--stdio\0")
    backend_jsonrpc.terminate_cli_process(4242, "Codex app-server", 999)
    assert pidfd_signals == [], "a foreign command must NOT be signalled"
    assert closed_pidfds == [91_111]


@pytest.mark.asyncio
async def test_impl_teardown_passes_the_recorded_start_time_not_zero(monkeypatch):
    """The identity check is only as good as what reaches it.

    The previous oracle called the primitive directly with `started_at` typed by hand, so it
    never walked `teardown_adopted` — which zeroed `_adopted_started_at` BEFORE reading it and
    handed 0 to the check, disabling pid-reuse protection permanently.
    """
    from app import backend_jsonrpc
    from app.backend_codex import CodexBackend

    calls = []
    monkeypatch.setattr(backend_jsonrpc, "terminate_cli_process",
                        lambda pid, label, started_at=0: calls.append((pid, label, started_at)))

    backend = CodexBackend(model="gpt-5.6-luna", cwd="/tmp", system_prompt="")
    cli_out_r, cli_out_w, cli_in_r, cli_in_w = _pipe_pair()
    try:
        await backend.adopt(cli_in_w, cli_out_r, thread_id="t", active_turn_id="x",
                            cli_pid=4242, cli_started_at=999)
        await backend.teardown_adopted()
    finally:
        for fd in (cli_out_w, cli_in_r):
            try:
                os.close(fd)
            except OSError:
                pass

    assert calls == [(4242, "Codex app-server", 999)], (
        f"teardown must pass the RECORDED start time through, got {calls}")


@pytest.mark.asyncio
async def test_impl_adopt_does_not_invent_a_missing_start_time(monkeypatch):
    """Заход 4, note 2, through the REAL adopt path: a lost record must stay lost.

    Re-measuring at adopt time describes whoever holds that pid NOW, so a stranger would be
    blessed as the agent. The previous oracle called the primitive directly and never walked
    this path — the mutation survived it.
    """
    from app import backend_jsonrpc
    from app.backend_codex import CodexBackend

    monkeypatch.setattr(backend_jsonrpc, "process_start_time", lambda pid: 555)
    calls = []
    monkeypatch.setattr(backend_jsonrpc, "terminate_cli_process",
                        lambda pid, label, started_at=0: calls.append((pid, label, started_at)))

    backend = CodexBackend(model="gpt-5.6-luna", cwd="/tmp", system_prompt="")
    cli_out_r, cli_out_w, cli_in_r, cli_in_w = _pipe_pair()
    try:
        # the recorded value was lost (0) — the live pid belongs to somebody, but not provably us
        await backend.adopt(cli_in_w, cli_out_r, thread_id="t", active_turn_id="x",
                            cli_pid=4242, cli_started_at=0)
        assert backend.cli_started_at == 0, (
            "a missing start time must stay missing, not be measured from whoever holds the pid")
        await backend.teardown_adopted()
    finally:
        for fd in (cli_out_w, cli_in_r):
            try:
                os.close(fd)
            except OSError:
                pass

    assert calls == [(4242, "Codex app-server", 0)], (
        f"the unknown identity must reach the check as unknown, got {calls}")


# ------------------------------------- T4: shutdown hands over instead of killing the backend

@pytest.mark.asyncio
async def test_t4_shutdown_hands_over_instead_of_disconnecting(mgr, monkeypatch):
    """Today `session.stop()` calls `_disconnect_backend()` (app/session.py:2854) and the
    lifespan calls `manager.shutdown_all()` — so the current shutdown kills the very CLI we
    are trying to preserve."""
    from tests.conftest import make_backend_mock

    _save_running_session("handover-1")
    backend = make_backend_mock()
    backend.fd_in, backend.fd_out = 11, 12
    backend.active_turn_id = "turn-xyz"
    backend.leftover = '{"partial":'  # bytes already consumed out of the pipe (research F3)

    torn_down = []
    backend.disconnect = lambda *a, **kw: torn_down.append("disconnect")

    stored = []
    monkeypatch.setattr("app.fdstore.store_fds",
                        lambda name, fds: stored.append((name, tuple(fds))))

    with patch("app.session.AgentSession._make_backend", return_value=backend):
        await mgr.auto_resume_all()
        session = mgr.get("handover-1")
        assert session is not None
        # FIXTURE FIX (after the freeze, assertions untouched): a mid-turn session has a LIVE
        # backend. `_backend` is built lazily in `_ensure_backend` (app/session.py:1343), so
        # without this the oracle pinned a state that cannot occur — there would be no pipes
        # to hand over at all, and no implementation could pass it.
        session._backend = backend

        async def _record_disconnect(*a, **kw):
            torn_down.append("_disconnect_backend")

        monkeypatch.setattr(session, "_disconnect_backend", _record_disconnect)
        await mgr.shutdown_all()

    # the full mapping, not just the names: a handover that swaps stdin and stdout would
    # attach the agent's input to its output, and LISTEN_FDNAMES order is NOT preserved
    assert dict(stored) == {
        "agent.handover-1.stdin": (11,),
        "agent.handover-1.stdout": (12,),
    }, f"descriptors must be handed over under their OWN names, got {dict(stored)}"
    assert torn_down == [], f"handover must not tear the backend down, did: {torn_down}"

    # the next generation has to know WHICH turn these bytes belong to, and what was
    # already consumed into the dying process's buffer (research F3: leftover bytes)
    from app.db import get_session
    row = get_session("handover-1")
    assert row["active_turn_id"] == "turn-xyz", (
        "without the turn id the adopted stream cannot be attributed to a turn")
    assert row["leftover"] == '{"partial":', (
        "the partial line must survive the handover BY VALUE — an always-NULL column would "
        f"satisfy a schema check and lose the bytes; got {row['leftover']!r}")


# ----------------------------------------------- T5: startup adopts the turn, does not reset it

@pytest.mark.asyncio
async def test_t5_adopted_session_is_adopted_not_reset(mgr, monkeypatch):
    """The adopt CONTRACT: exact descriptors, exact ids, no reconnect, status preserved.

    Uses the standard backend double on purpose — this test is about the arguments and the
    status, not about streaming (see the next test, which needs a real backend for that).
    """
    from app.db import get_session
    from app.session_state import AgentStatus
    from tests.conftest import make_backend_mock

    _save_running_session("adopted-1", thread="thread-abc")
    expected_turn = _store_active_turn("adopted-1", "turn-xyz")
    assert expected_turn == "turn-xyz", (
        "T4 must have added the active_turn_id column; without it the fourth argument of "
        "adopt() cannot be checked at all")

    cli_out_r, cli_out_w, cli_in_r, cli_in_w = _pipe_pair()
    monkeypatch.setattr("app.fdstore.acquire_fds", lambda: {
        "agent.adopted-1.stdin": cli_in_w,
        "agent.adopted-1.stdout": cli_out_r,
    })

    adopted, connected = [], []
    backend = make_backend_mock()

    async def track_adopt(fd_in, fd_out, thread_id, active_turn_id=None, **kwargs):
        # **kwargs: adopt() gained leftover/cli_pid/cli_started_at when the implementation
        # review required carrying them across generations. The assertion is unchanged.
        adopted.append((fd_in, fd_out, thread_id, active_turn_id))

    async def track_connect(*a, **kw):
        connected.append(True)

    backend.adopt = track_adopt
    backend.connect = track_connect
    try:
        with patch("app.session.AgentSession._make_backend", return_value=backend):
            await mgr.auto_resume_all()

        assert adopted == [(cli_in_w, cli_out_r, "thread-abc", "turn-xyz")], (
            f"adopt must receive exactly the inherited descriptors and the stored turn id, "
            f"got {adopted}")
        assert connected == [], "the CLI is alive — adopting must not reconnect it"
        session = mgr.get("adopted-1")
        assert session is not None
        assert session.status == AgentStatus.RUNNING
        assert get_session("adopted-1")["status"] == "running"
    finally:
        # ONLY the CLI-side ends. cli_in_w/cli_out_r belong to the adopted transports
        # (os.fdopen took them): closing them here too is a double close that resurfaces as
        # EBADF from asyncio's __del__ inside some LATER test — a flake that reads as a defect.
        for fd in (cli_out_w, cli_in_r):
            try:
                os.close(fd)
            except OSError:
                pass


@pytest.mark.asyncio
async def test_t5_adopted_turn_completes_from_the_pipe(mgr, monkeypatch):
    """The CONTINUATION, with a real CodexBackend: a completion frame written into the pipe
    AFTER adoption must end the adopted turn.

    Deliberately not using the standard double: its `events()` is an EMPTY iterator, so the
    turn would end on its own and this check would pass without the pipe being read at all.
    """
    from app.backend_codex import CodexBackend
    from app.session_state import AgentStatus

    _save_running_session("adopted-2", thread="thread-live")
    _store_active_turn("adopted-2", "turn-live")
    cli_out_r, cli_out_w, cli_in_r, cli_in_w = _pipe_pair()
    monkeypatch.setattr("app.fdstore.acquire_fds", lambda: {
        "agent.adopted-2.stdin": cli_in_w,
        "agent.adopted-2.stdout": cli_out_r,
    })
    real = CodexBackend(model="gpt-5.6-luna", cwd="/tmp", system_prompt="")

    async def explode(*a, **kw):
        raise AssertionError("resuming an adopted session must not spawn a CLI")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", explode)
    try:
        with patch("app.session.AgentSession._make_backend", return_value=real):
            await mgr.auto_resume_all()
            session = mgr.get("adopted-2")
            assert session is not None
            assert session.status == AgentStatus.RUNNING

            os.write(cli_out_w, (json.dumps({
                "method": "turn/completed",
                "params": {"threadId": "thread-live",
                           "turn": {"id": "turn-live", "items": [
                               {"type": "agentMessage", "text": "FINISHED"}]}},
            }) + "\n").encode())

            await asyncio.wait_for(session.wait_for_turn_completion(), timeout=10)
            assert session.status == AgentStatus.IDLE, (
                "the adopted turn must be able to COMPLETE through the inherited pipe")
    finally:
        # ONLY the CLI-side ends. cli_in_w/cli_out_r belong to the adopted transports
        # (os.fdopen took them): closing them here too is a double close that resurfaces as
        # EBADF from asyncio's __del__ inside some LATER test — a flake that reads as a defect.
        for fd in (cli_out_w, cli_in_r):
            try:
                os.close(fd)
            except OSError:
                pass


@pytest.mark.asyncio
async def test_t5_session_without_inheritance_still_resets_to_idle(mgr, monkeypatch):
    """The negative case: no inheritance -> today's behaviour, reset to idle."""
    from app.session_state import AgentStatus
    from tests.conftest import make_backend_mock

    _save_running_session("orphaned-1")
    monkeypatch.setattr("app.fdstore.acquire_fds", lambda: {})

    with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
        await mgr.auto_resume_all()

    session = mgr.get("orphaned-1")
    assert session is not None
    assert session.status == AgentStatus.IDLE


# ---------------------------------- T6: the gate runs BEFORE systemd, classification fail-closed

@pytest.mark.asyncio
async def test_t6_drain_never_waits_for_a_mutating_call(monkeypatch):
    """Кнопка рестарта не ждёт мутаций (решение юзера 28.08.2026).

    Ловит возврат ожидания: если бюджет снова станет положительным, дефолтный вызов
    провисит те самые секунды, ради отсутствия которых правка и делалась.
    """
    from app import main as app_main

    assert app_main.MUTATING_DRAIN_BUDGET_S == 0.0

    monkeypatch.setattr(app_main, "inflight_mutating_count", lambda: 1, raising=False)

    loop = asyncio.get_running_loop()
    t0 = loop.time()
    await app_main.drain_mutating_requests()
    waited = loop.time() - t0
    assert waited < 0.05, f"restart must not wait for in-flight mutating calls, waited {waited}"


@pytest.mark.asyncio
async def test_t6_budget_exhausted_refuses_the_restart(monkeypatch):
    """An accepted mutating call cannot be retroactively called 'never started'."""
    from app import main as app_main

    monkeypatch.setattr(app_main, "inflight_mutating_count", lambda: 2, raising=False)
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    # the outer boundary is what makes this FAIL instead of reporting 120s later, if the
    # implementation reads the module constant instead of the budget it was handed
    result = await asyncio.wait_for(app_main.drain_mutating_requests(budget_s=0.3), timeout=5)
    assert result is False
    assert loop.time() - t0 < 1.5, "drain must not outlive its budget"


def test_t6_classification_comes_from_the_route_table_and_fails_closed():
    """Not from the HTTP verb: a GET route may mutate, and guessing would drop such a call.

    Table-driven over the app's REAL routes, plus a path the table does not know.
    """
    from app import main as app_main

    routes = [r for r in app_main.app.routes if getattr(r, "path", "").startswith("/api/")]
    assert routes, "no /api routes found — the census would classify nothing"

    for route in routes:
        for method in sorted(getattr(route, "methods", set()) or set()):
            if method in ("HEAD", "OPTIONS"):
                continue
            verdict = app_main.is_mutating_path(method, route.path)
            assert isinstance(verdict, bool), f"{method} {route.path} -> {verdict!r}"

    # expected classifications for REAL routes: `lambda *_: True` would be fail-safe for
    # integrity and still defeat the point, blocking restarts on read-only traffic
    assert app_main.is_mutating_path("POST", "/api/sessions/{name}/send") is True
    assert app_main.is_mutating_path("POST", "/api/sessions") is True
    assert app_main.is_mutating_path("GET", "/api/sessions") is False
    assert app_main.is_mutating_path("GET", "/api/sessions/{name}/stream") is False

    # the restart endpoint must not be counted as mutating traffic: its own preflight would
    # otherwise wait for the request that asked for the restart — a self-deadlock
    assert app_main.is_mutating_path("POST", "/api/restart") is False

    # an unknown path must count as mutating: unknown means "I do not know", not "safe"
    assert app_main.is_mutating_path("POST", "/api/this-route-does-not-exist") is True
    assert app_main.is_mutating_path("GET", "/api/this-route-does-not-exist") is True


@pytest.mark.asyncio
async def test_t6_real_middleware_counts_mutating_but_not_streams():
    """The census must be moved by an ACTUAL request through the middleware, not by a stub."""
    from starlette.applications import Starlette
    from starlette.responses import StreamingResponse, JSONResponse
    from starlette.routing import Route
    import httpx

    from app import main as app_main

    seen = {}

    async def mutate(request):
        seen["mutating_during"] = app_main.inflight_mutating_count()
        return JSONResponse({"ok": True})

    async def stream(request):
        async def body():
            seen["streams_during"] = app_main.inflight_stream_count()
            seen["mutating_during_stream"] = app_main.inflight_mutating_count()
            yield b"data: x\n\n"

        return StreamingResponse(body(), media_type="text/event-stream")

    probe = Starlette(routes=[
        Route("/api/sessions/x/send", mutate, methods=["POST"]),
        Route("/api/events", stream, methods=["GET"]),
    ])
    probe.add_middleware(app_main.RequestCensusMiddleware)

    transport = httpx.ASGITransport(app=probe)
    async with httpx.AsyncClient(transport=transport, base_url="http://probe") as client:
        await client.post("/api/sessions/x/send", json={})
        async with client.stream("GET", "/api/events") as response:
            async for _chunk in response.aiter_bytes():
                break

    assert seen["mutating_during"] == 1, "a mutating request must be counted while it runs"
    assert seen["mutating_during_stream"] == 0, "an SSE stream is not a mutating request"
    assert seen["streams_during"] == 1, "streams are counted separately, and never drained"
    assert app_main.inflight_mutating_count() == 0, "the census must fall back to zero"


def test_t6_admission_gate_rejects_new_mutating_calls_as_retryable():
    """A call refused BEFORE its side effect is honestly retryable — that is the whole point."""
    from app import main as app_main

    # control arm FIRST: with the gate open, a mutating call must be ALLOWED. Without this
    # assert, a constant `{allowed: False, retryable: True}` passes — which in production is
    # "the gate closed before a restart and never reopened", i.e. every mutating tool call
    # answered "retry later" forever, with a green oracle.
    app_main.open_mutating_admission()
    assert app_main.mutating_admission_verdict("POST", "/api/sessions/x/send")["allowed"] is True

    app_main.close_mutating_admission()
    try:
        verdict = app_main.mutating_admission_verdict("POST", "/api/sessions/x/send")
        assert verdict["allowed"] is False
        assert verdict["retryable"] is True
        assert verdict["outcome_unknown"] is False
        # a read-only call is never gated: the gate protects side effects, not traffic
        assert app_main.mutating_admission_verdict("GET", "/api/sessions")["allowed"] is True
    finally:
        app_main.open_mutating_admission()
    assert app_main.mutating_admission_verdict("POST", "/api/sessions/x/send")["allowed"] is True, (
        "the gate must REOPEN; a stuck-closed gate starves every mutating tool call")


@pytest.mark.asyncio
async def test_t6_restart_endpoint_refuses_before_touching_systemd(monkeypatch):
    """A gate inside the lifespan is too late: systemctl restart is already committed by then."""
    from app.routes import system as system_routes

    invoked = []
    monkeypatch.setattr(system_routes, "_restart_service_after_response",
                        lambda *a, **kw: invoked.append(True), raising=False)

    async def refuse():
        return {"ok": False, "reason": "2 mutating tool calls still in flight"}

    monkeypatch.setattr(system_routes, "restart_preflight", refuse, raising=False)

    with pytest.raises(Exception) as excinfo:
        await system_routes.restart_server()

    assert getattr(excinfo.value, "status_code", None) == 409
    assert invoked == [], "systemd must NOT be invoked when the preflight refuses"


@pytest.mark.asyncio
async def test_t6_successful_preflight_reaches_systemd_without_waiting_on_itself(monkeypatch):
    """The restart request is itself an HTTP request: if the census counts it, the drain waits
    for the very call that asked for the restart and never finishes."""
    import httpx
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    from app import main as app_main
    from app.routes import system as system_routes

    scheduled = []
    monkeypatch.setattr(system_routes, "_restart_service_after_response",
                        lambda *a, **kw: scheduled.append(True), raising=False)

    async def restart(request):
        result = await system_routes.restart_preflight()
        if not result["ok"]:
            return JSONResponse({"error": result["reason"]}, status_code=409)
        system_routes._restart_service_after_response()
        return JSONResponse({"ok": True})

    probe = Starlette(routes=[Route("/api/restart", restart, methods=["POST"])])
    probe.add_middleware(app_main.RequestCensusMiddleware)

    transport = httpx.ASGITransport(app=probe)
    async with httpx.AsyncClient(transport=transport, base_url="http://probe") as client:
        response = await asyncio.wait_for(client.post("/api/restart", json={}), timeout=10)

    assert response.status_code == 200, response.text
    assert scheduled == [True], "a successful preflight must reach the systemd seam"
    # the real preflight deliberately leaves admission CLOSED (a restart follows); in a test
    # nothing follows, so restore it — otherwise every later mutating request gets 503
    app_main.open_mutating_admission()
    assert app_main.mutating_admission_verdict("POST", "/api/sessions/x/send")["allowed"] is True


@pytest.mark.asyncio
async def test_t6_admission_reopens_if_the_restart_never_happens(monkeypatch):
    """Post-freeze regression guard, not a ticket oracle.

    The full suite found this: a SUCCESSFUL preflight leaves admission closed (a restart is
    supposed to follow and kill the process). When the restart does not happen, the gate stayed
    shut and every mutating tool call got 503 — the exact "closed and never reopened" state the
    independent review warned about, here in production rather than in the oracle.
    """
    from app import main as app_main
    from app.routes import system as system_routes

    monkeypatch.setattr(system_routes, "_watchdog_budget_s", lambda: 0.1, raising=False)
    monkeypatch.setattr(app_main, "inflight_mutating_count", lambda: 0, raising=False)
    scheduled = []

    async def fake_restart(*a, **kw):
        # async, because the caller hands this to asyncio.create_task — a sync double raises
        # "a coroutine was expected, got None" (my third sync-double-for-async-contract slip)
        scheduled.append(True)
        return {"ok": True}

    monkeypatch.setattr(system_routes, "_restart_service_after_response", fake_restart,
                        raising=False)
    try:
        result = await system_routes.restart_server()
        assert result["ok"] is True
        assert app_main.mutating_admission_verdict("POST", "/api/sessions/x/send")["allowed"] \
            is False, "right after a successful preflight the gate must be CLOSED"

        await asyncio.sleep(0.4)
        assert app_main.mutating_admission_verdict("POST", "/api/sessions/x/send")["allowed"] \
            is True, "a restart that never happened must not starve every mutating call"
    finally:
        app_main.open_mutating_admission()


def test_t6_concrete_paths_resolve_to_their_route_template():
    """Post-freeze regression guard, not a ticket oracle. Found by the pre-mortem.

    The middleware sees CONCRETE paths; the route table holds templates. Comparing them
    directly made every parameterised route "unknown" -> mutating, so ordinary dashboard GETs
    would have held the restart drain and been refused by the admission gate.
    """
    from app import main as app_main

    # concrete GET on a parameterised route: read-only, must NOT be counted as mutating
    assert app_main.is_mutating_path("GET", "/api/sessions/some-worker/context") is False
    # concrete POST on a parameterised route: mutating
    assert app_main.is_mutating_path("POST", "/api/sessions/some-worker/send") is True
    # still fail-closed for a path that matches nothing
    assert app_main.is_mutating_path("GET", "/api/nope/nope/nope") is True


@pytest.mark.asyncio
async def test_269_restart_header_states_both_values_on_ordinary_responses():
    """#269: the pause must be readable in BOTH directions, on a response nobody was refused.

    Only the closed arm ("1") is not enough: a restart that never happens reopens admission
    silently (`restart_preflight` with an undrained tail), and a page loaded mid-restart sent
    nothing, so it never saw a 503. This is the send_wrapper point — a read-only request is
    never refused, so it cannot reach the refusal branch.
    """
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    import httpx

    from app import main as app_main

    async def read(request):
        return JSONResponse({"ok": True})

    probe = Starlette(routes=[Route("/api/sessions", read, methods=["GET"])])
    probe.add_middleware(app_main.RequestCensusMiddleware)

    transport = httpx.ASGITransport(app=probe)
    async with httpx.AsyncClient(transport=transport, base_url="http://probe") as client:
        app_main.open_mutating_admission()
        opened = await client.get("/api/sessions")
        app_main.close_mutating_admission()
        try:
            closed = await client.get("/api/sessions")
        finally:
            app_main.open_mutating_admission()
        reopened = await client.get("/api/sessions")

    assert opened.headers.get("X-Orchestra-Restarting") == "0"
    assert closed.headers.get("X-Orchestra-Restarting") == "1", (
        "a read-only response must still carry the pause: the dashboard's heartbeat is a GET")
    assert reopened.headers.get("X-Orchestra-Restarting") == "0", (
        "a header stuck at 1 leaves the client paused until its own 120s ceiling")
    generations = {
        opened.headers.get("X-Orchestra-Generation"),
        closed.headers.get("X-Orchestra-Generation"),
        reopened.headers.get("X-Orchestra-Generation"),
    }
    assert len(generations) == 1 and None not in generations
    started = {
        opened.headers.get("X-Orchestra-Started-At"),
        closed.headers.get("X-Orchestra-Started-At"),
        reopened.headers.get("X-Orchestra-Started-At"),
    }
    assert len(started) == 1 and None not in started


@pytest.mark.asyncio
async def test_269_restart_header_is_on_the_refusal_itself():
    """#269: the 503 answers WITHOUT reaching send_wrapper, so it needs its own header.

    Covered separately on purpose: a test that only checks ordinary responses is green while
    the refused call — the one the client is looking at — carries no state at all.
    """
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    import httpx

    from app import main as app_main

    reached = []

    async def mutate(request):
        reached.append(True)
        return JSONResponse({"ok": True})

    probe = Starlette(routes=[Route("/api/sessions/x/send", mutate, methods=["POST"])])
    probe.add_middleware(app_main.RequestCensusMiddleware)

    transport = httpx.ASGITransport(app=probe)
    async with httpx.AsyncClient(transport=transport, base_url="http://probe") as client:
        app_main.close_mutating_admission()
        try:
            refused = await client.post("/api/sessions/x/send", json={})
        finally:
            app_main.open_mutating_admission()

    assert refused.status_code == 503
    assert refused.json()["error"]["code"] == "restart_pending"
    assert not reached, "the refusal must happen before the handler, i.e. before send_wrapper"
    assert refused.headers.get("X-Orchestra-Restarting") == "1"
    assert refused.headers.get("X-Orchestra-Generation")
    assert refused.headers.get("X-Orchestra-Started-At")


# ------------------------------------------------------------- T7: fail-closed orphan sweep

@pytest.mark.asyncio
async def test_t7_orphan_sweep_refuses_on_empty_registry(mgr, monkeypatch):
    """An empty registry means 'I know nothing', not 'they are all dead'."""
    closed = []
    monkeypatch.setattr("app.fdstore.acquire_fds", lambda: {"agent.ghost.stdout": 41})
    monkeypatch.setattr("app.manager.close_orphan_fd", lambda fd: closed.append(fd),
                        raising=False)

    swept = await mgr.sweep_orphan_fds()

    assert swept == 0
    assert closed == [], "no sweeping when the registry is empty"


@pytest.mark.asyncio
async def test_t7_orphan_sweep_closes_only_unknown_fds(mgr, monkeypatch):
    from tests.conftest import make_backend_mock

    _save_running_session("known-1")
    closed, killed = [], []
    monkeypatch.setattr("app.fdstore.acquire_fds", lambda: {
        "agent.known-1.stdout": 40, "agent.ghost.stdout": 41,
    })
    monkeypatch.setattr("app.manager.close_orphan_fd", lambda fd: closed.append(fd),
                        raising=False)
    monkeypatch.setattr("app.manager.orphan_pids", lambda: {41: 4242}, raising=False)
    monkeypatch.setattr("app.manager.terminate_orphan_process",
                        lambda pid: killed.append(pid), raising=False)

    with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
        await mgr.auto_resume_all()
        swept = await mgr.sweep_orphan_fds()

    assert closed == [41], f"only the unknown descriptor may be closed, closed {closed}"
    assert swept == 1
    assert killed == [4242], (
        "closing an fd only gives the CLI EOF; a known-pid orphan must be terminated")


# ------------------------------------- T9: new tools and prompt land on the NEXT turn

@pytest.mark.asyncio
async def test_t9_stale_adopted_session_respawns_cli_on_next_turn(mgr, monkeypatch):
    """The adopted CLI keeps the OLD tool list and prompt: those can only change by
    re-spawning it, and that must happen at the turn boundary, not mid-turn."""
    from tests.conftest import make_backend_mock

    _save_running_session("stale-1")
    cli_out_r, cli_out_w, cli_in_r, cli_in_w = _pipe_pair()
    monkeypatch.setattr("app.fdstore.acquire_fds", lambda: {
        "agent.stale-1.stdin": cli_in_w, "agent.stale-1.stdout": cli_out_r,
    })
    connects = []
    backend = make_backend_mock()

    async def track_connect(*a, **kw):
        connects.append(True)

    async def noop_adopt(*a, **kw):
        return None

    backend.connect = track_connect
    backend.adopt = noop_adopt
    try:
        with patch("app.session.AgentSession._make_backend", return_value=backend):
            await mgr.auto_resume_all()
            session = mgr.get("stale-1")
            assert session is not None
            assert session.tools_are_stale is True, (
                "an adopted CLI carries the tool list it was born with")
            assert connects == [], "mid-turn the CLI must NOT be re-spawned"

            old_backend = session._backend
            disconnected, assembled = [], []
            # async, because the real contract is `async def disconnect` — a sync double here
            # would force defensive code in production (my own note: a double must not be
            # weaker than the object it replaces)
            async def track_disconnect(*a, **kw):
                disconnected.append(True)

            backend.disconnect = track_disconnect
            monkeypatch.setattr(
                "app.manager.SessionManager.assemble_prompt",
                # returns a TUPLE, like the real assemble_prompt (prompt, overlay)
                lambda self, *a, **kw: (assembled.append(True) or "fresh prompt", None),
                raising=False,
            )
            fresh = make_backend_mock()

            async def fresh_connect(*a, **kw):
                connects.append(True)

            fresh.connect = fresh_connect
            with patch("app.session.AgentSession._make_backend", return_value=fresh):
                # driven through the REAL next turn: a perfect refresh method that send()
                # never calls would swap nothing in production. Bounded because send() takes
                # the non-reentrant `_lifecycle_lock` (app/session.py:411): a refresh that
                # re-enters it would deadlock the suite instead of failing.
                from app.events import MessageProvenance
                await asyncio.wait_for(
                    session.send(
                        "next turn starts here",
                        provenance=MessageProvenance(origin="user", senders=("user",)),
                    ),
                    timeout=10,
                )

            assert session._backend is not old_backend, (
                "toggling a flag and calling connect() on the SAME backend keeps the old "
                "tool list — the CLI process itself must be replaced")
            assert disconnected == [True], "the stale CLI must be released"
            assert connects == [True], "the next turn must run on a freshly spawned CLI"
            assert assembled, "the prompt must be reassembled from disk (#220)"
            assert session.tools_are_stale is False
    finally:
        # ONLY the CLI-side ends. cli_in_w/cli_out_r belong to the adopted transports
        # (os.fdopen took them): closing them here too is a double close that resurfaces as
        # EBADF from asyncio's __del__ inside some LATER test — a flake that reads as a defect.
        for fd in (cli_out_w, cli_in_r):
            try:
                os.close(fd)
            except OSError:
                pass
