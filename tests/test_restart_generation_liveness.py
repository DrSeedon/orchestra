"""#379 T1 — bounded supervisor exit after durable restart cleanup."""

from __future__ import annotations

import asyncio
import ast
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.backend_jsonrpc import process_start_time


_GUARD_MODULE = Path(__file__).parents[1] / "app" / "restart_guard.py"


def _events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _start_guard(
    target: subprocess.Popen,
    progress_fd: int,
    event_log: Path,
    *,
    budget: float,
    start_ticks: int | None = None,
) -> subprocess.Popen:
    identity = process_start_time(target.pid) if start_ticks is None else start_ticks
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "app.restart_guard",
            "--pid",
            str(target.pid),
            "--start-ticks",
            str(identity),
            "--progress-fd",
            str(progress_fd),
            "--post-cleanup-budget",
            str(budget),
            "--event-log",
            str(event_log),
        ],
        pass_fds=(progress_fd,),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )


def _send_phase(fd: int, phase: str, task_class: str) -> None:
    os.write(fd, (json.dumps({
        "phase": phase,
        "task_class": task_class,
    }) + "\n").encode())


def _cleanup_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


@pytest.mark.skipif(
    not callable(getattr(os, "pidfd_open", None)),
    reason="host Python lacks os.pidfd_open; injected unit coverage below",
)
def test_t1_clean_supervisor_exit_is_distinct_from_forced_fallback(tmp_path):
    assert _GUARD_MODULE.is_file(), (
        "bounded supervisor-exit guard is missing from the production package"
    )
    target = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.3)"])
    target_start = process_start_time(target.pid)
    read_fd, write_fd = os.pipe()
    guard = None
    event_log = tmp_path / "clean.jsonl"
    try:
        guard = _start_guard(target, read_fd, event_log, budget=0.8)
        os.close(read_fd)
        read_fd = -1
        _send_phase(write_fd, "application_teardown_complete", "post_lifespan_runtime")
        os.close(write_fd)
        write_fd = -1

        target.wait(timeout=2)
        _stdout, stderr = guard.communicate(timeout=2)
        events = _events(event_log)

        assert guard.returncode == 0, stderr
        assert target.returncode == 0
        assert events
        terminal = events[-1]
        assert {
            key: terminal[key]
            for key in ("event", "forced", "phase", "pid", "start_ticks", "task_class")
        } == {
            "event": "clean_exit",
            "forced": False,
            "phase": "application_teardown_complete",
            "pid": target.pid,
            "start_ticks": target_start,
            "task_class": "post_lifespan_runtime",
        }
        assert terminal["elapsed_s"] >= 0
    finally:
        if read_fd >= 0:
            os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)
        _cleanup_process(target)
        _cleanup_process(guard)


@pytest.mark.skipif(
    not callable(getattr(os, "pidfd_open", None)),
    reason="host Python lacks os.pidfd_open; injected unit coverage below",
)
def test_t1_late_uvloop_executor_waiter_is_forced_after_cleanup_and_named(tmp_path):
    assert _GUARD_MODULE.is_file(), (
        "bounded supervisor-exit guard is missing from the production package"
    )
    target_code = """
import asyncio
import threading
import uvloop

async def main():
    loop = asyncio.get_running_loop()
    loop.run_in_executor(None, threading.Event().wait)
    print('READY', flush=True)

asyncio.run(main(), loop_factory=uvloop.new_event_loop)
"""
    target = subprocess.Popen(
        [sys.executable, "-c", target_code],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    read_fd, write_fd = os.pipe()
    guard = None
    event_log = tmp_path / "forced.jsonl"
    exited = False
    try:
        assert target.stdout is not None
        assert target.stdout.readline().strip() == "READY"
        guard = _start_guard(target, read_fd, event_log, budget=0.2)
        os.close(read_fd)
        read_fd = -1
        _send_phase(
            write_fd,
            "application_teardown_complete",
            "post_lifespan_runtime",
        )
        os.close(write_fd)
        write_fd = -1

        try:
            target.wait(timeout=2)
            exited = True
        except subprocess.TimeoutExpired:
            pass
        _stdout, stderr = guard.communicate(timeout=2)
        events = _events(event_log)

        assert exited, f"restart guard left supervisor pid={target.pid} alive; {stderr}"
        assert target.returncode == -signal.SIGKILL
        assert guard.returncode == 0, stderr
        assert events and events[-1]["event"] == "forced_fallback"
        assert events[-1]["forced"] is True
        assert events[-1]["pid"] == target.pid
        assert events[-1]["phase"] == "application_teardown_complete"
        assert events[-1]["task_class"] == "post_lifespan_runtime"
        assert events[-1]["elapsed_s"] >= 0.2
    finally:
        if read_fd >= 0:
            os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)
        _cleanup_process(target)
        _cleanup_process(guard)


@pytest.mark.skipif(
    not callable(getattr(os, "pidfd_open", None)),
    reason="host Python lacks os.pidfd_open; injected unit coverage below",
)
def test_t1_guard_never_forces_before_application_teardown_and_reports_progress_loss(
    tmp_path,
):
    assert _GUARD_MODULE.is_file(), (
        "bounded supervisor-exit guard is missing from the production package"
    )
    target = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    read_fd, write_fd = os.pipe()
    guard = None
    event_log = tmp_path / "progress-lost.jsonl"
    try:
        guard = _start_guard(target, read_fd, event_log, budget=0.2)
        os.close(read_fd)
        read_fd = -1
        _send_phase(write_fd, "bg_jobs", "BgJobManager.shutdown")

        # More than twice the post-cleanup budget: an implementation that starts its timer
        # at arm time instead of at the boundary kills the target here.
        import time
        time.sleep(0.5)
        assert target.poll() is None, "guard forced exit before application teardown completed"
        assert not any(event.get("forced") for event in _events(event_log))

        os.close(write_fd)  # unexpected EOF, not an explicit abort
        write_fd = -1
        _stdout, stderr = guard.communicate(timeout=2)
        events = _events(event_log)

        assert guard.returncode == 2, stderr
        assert target.poll() is None
        assert events and events[-1]["event"] == "progress_lost"
        assert events[-1]["forced"] is False
        assert events[-1]["phase"] == "bg_jobs"
        assert events[-1]["task_class"] == "BgJobManager.shutdown"
    finally:
        if read_fd >= 0:
            os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)
        _cleanup_process(target)
        _cleanup_process(guard)


@pytest.mark.skipif(
    not callable(getattr(os, "pidfd_open", None)),
    reason="host Python lacks os.pidfd_open; injected unit coverage below",
)
def test_t1_wrong_starttime_is_identity_mismatch_and_never_signals(tmp_path):
    assert _GUARD_MODULE.is_file(), (
        "bounded supervisor-exit guard is missing from the production package"
    )
    target = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    read_fd, write_fd = os.pipe()
    guard = None
    event_log = tmp_path / "identity-mismatch.jsonl"
    try:
        wrong_start = process_start_time(target.pid) + 1
        guard = _start_guard(
            target,
            read_fd,
            event_log,
            budget=0.1,
            start_ticks=wrong_start,
        )
        os.close(read_fd)
        read_fd = -1
        _send_phase(write_fd, "application_teardown_complete", "post_lifespan_runtime")
        os.close(write_fd)
        write_fd = -1
        _stdout, stderr = guard.communicate(timeout=2)
        events = _events(event_log)

        assert guard.returncode == 3, stderr
        assert target.poll() is None, "identity mismatch signalled a foreign/reused PID"
        assert events and events[-1]["event"] == "identity_mismatch"
        assert events[-1]["forced"] is False
        assert events[-1]["pid"] == target.pid
        assert events[-1]["start_ticks"] == wrong_start
        assert events[-1]["phase"] == "identity_check"
        assert events[-1]["task_class"] == "pidfd_identity"
    finally:
        if read_fd >= 0:
            os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)
        _cleanup_process(target)
        _cleanup_process(guard)


def test_t1_force_implementation_uses_pidfd_not_numeric_pid():
    assert _GUARD_MODULE.is_file(), (
        "bounded supervisor-exit guard is missing from the production package"
    )
    tree = ast.parse(_GUARD_MODULE.read_text())
    calls = {
        f"{node.func.value.id}.{node.func.attr}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
    }
    # pidfd_send_signal берётся через getattr (его нет на интерпретаторах без pidfd),
    # поэтому проверяем ИМЯ в исходнике, а не дословный ast-вызов.
    assert "pidfd_send_signal" in _GUARD_MODULE.read_text()
    # os.kill РАЗРЕШЁН только внутри _send_signal и только под сверкой starttime: полный
    # запрет закреплял отказ рестарта на интерпретаторах без pidfd_open. Опасность даёт
    # не сам os.kill, а сигнал по номеру БЕЗ проверки, что за номером тот же процесс.
    from app import restart_guard as _guard_for_source
    source = _GUARD_MODULE.read_text()
    guard_fn = ast.parse(source)
    killers = [
        node for node in ast.walk(guard_fn)
        if isinstance(node, ast.FunctionDef)
        and any(
            isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and f"{call.func.value.id}.{call.func.attr}" == "os.kill"
            for call in ast.walk(node)
        )
    ]
    assert [fn.name for fn in killers] == ["_send_signal"], (
        "os.kill must live only in _send_signal, which re-verifies starttime"
    )
    guarded = ast.dump(killers[0])
    assert "_read_starttime" in guarded, "os.kill without a starttime re-check reuses PIDs"
    assert hasattr(_guard_for_source, "_send_signal")


def test_t1_verified_pidfd_is_opened_before_starttime_is_compared():
    assert _GUARD_MODULE.is_file(), (
        "bounded supervisor-exit guard is missing from the production package"
    )
    from app import restart_guard

    verify = getattr(restart_guard, "open_verified_pidfd", None)
    assert callable(verify), "guard has no single stable identity acquisition seam"
    order: list[str] = []

    def pidfd_open(pid: int) -> int:
        assert pid == 12345
        order.append("pidfd_open")
        return 91_001

    def read_start(pid: int) -> int:
        assert pid == 12345
        order.append("read_starttime")
        return 67890

    result = verify(
        12345,
        67890,
        pidfd_open=pidfd_open,
        read_starttime=read_start,
    )

    assert result == 91_001
    assert order == ["pidfd_open", "read_starttime"], (
        "starttime read before pidfd_open leaves a PID-reuse race"
    )


def test_t1_missing_pidfd_capability_falls_back_without_losing_identity_check():
    """Без pidfd_open сторож обязан РАБОТАТЬ, а не отказывать.

    Прежний оракул требовал здесь RestartGuardUnavailable, и это закрепляло дефект:
    на интерпретаторе без pidfd_open каждый рестарт молча отменялся (25.08, пять подряд).
    Защиту от переиспользования PID даёт сверка starttime, а не сам тип дескриптора,
    поэтому проверяем ОБА плеча: живой процесс открывается, подменённый отвергается.
    """
    script = """
import os

if hasattr(os, "pidfd_open"):
    del os.pidfd_open
from app import restart_guard

pid = os.getpid()
start_ticks = restart_guard._read_starttime(pid)

fd = restart_guard.open_verified_pidfd(pid, start_ticks)
assert fd >= 0
os.close(fd)

try:
    restart_guard.open_verified_pidfd(pid, start_ticks + 999)
except restart_guard.ProcessIdentityMismatch:
    pass
else:
    raise AssertionError("PID reuse was not rejected without pidfd_open")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_t1_injected_pidfd_open_preserves_identity_validation_and_success():
    from app import restart_guard

    read_fd, write_fd = os.pipe()
    try:
        def pidfd_open(pid: int) -> int:
            assert pid == 12345
            return read_fd

        def read_start(pid: int) -> int:
            assert pid == 12345
            return 67890

        assert restart_guard.open_verified_pidfd(
            12345,
            67890,
            pidfd_open=pidfd_open,
            read_starttime=read_start,
        ) == read_fd
    finally:
        os.close(write_fd)
        os.close(read_fd)

    mismatch_fd = os.open(os.devnull, os.O_RDONLY)
    try:
        with pytest.raises(restart_guard.ProcessIdentityMismatch):
            restart_guard.open_verified_pidfd(
                12345,
                11111,
                pidfd_open=lambda _pid: mismatch_fd,
                read_starttime=lambda _pid: 67890,
            )
    finally:
        with pytest.raises(OSError):
            os.close(mismatch_fd)


@pytest.mark.asyncio
@pytest.mark.skipif(
    not callable(getattr(os, "pidfd_open", None)),
    reason="host Python lacks os.pidfd_open; injected unit coverage below",
)
async def test_t1_production_guard_arm_leaks_neither_listener_nor_agent_pipes(
    monkeypatch,
    tmp_path,
):
    from app.routes import system

    arm_guard = getattr(system, "_arm_supervisor_exit_guard", None)
    guard_api = getattr(system, "restart_guard", None)
    assert callable(arm_guard) and guard_api is not None, (
        "production restart path has no inspectable guard arm"
    )

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    agent_in, agent_in_peer = os.pipe()
    agent_out, agent_out_peer = os.pipe()
    forbidden = {
        os.readlink(f"/proc/self/fd/{fd}")
        for fd in (listener.fileno(), agent_in, agent_out)
    }
    for fd in (listener.fileno(), agent_in, agent_out):
        os.set_inheritable(fd, True)

    target = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        handle = arm_guard(
            target_pid=target.pid,
            start_ticks=process_start_time(target.pid),
            post_cleanup_budget=0.5,
            event_log=tmp_path / "arm.jsonl",
        )
        helper_targets = {
            os.readlink(fd)
            for fd in (Path("/proc") / str(handle.helper_pid) / "fd").iterdir()
        }
        assert forbidden.isdisjoint(helper_targets), (
            f"restart helper inherited listener/agent descriptors: {forbidden & helper_targets}"
        )
        await guard_api.abort_guard("test cleanup")
        assert handle.process.poll() == 0
        events = _events(tmp_path / "arm.jsonl")
        assert events and events[-1]["event"] == "aborted"
        assert events[-1]["forced"] is False
        assert events[-1]["phase"] == "aborted"
        assert events[-1]["task_class"] == "restart.abort"
    finally:
        _cleanup_process(target)
        listener.close()
        for fd in (agent_in, agent_in_peer, agent_out, agent_out_peer):
            os.close(fd)


@pytest.mark.asyncio
async def test_t1_production_path_arms_guard_after_interrupt_mark_and_durable_state(
    monkeypatch,
):
    from app import main as app_main
    from app.routes import system

    durable = getattr(system, "_drain_restart_durable_state", None)
    arm_guard = getattr(system, "_arm_supervisor_exit_guard", None)
    assert callable(durable) and callable(arm_guard), (
        "restart path has no durable-state barrier plus independent supervisor-exit guard"
    )

    order: list[str] = []
    monkeypatch.setattr(system, "_RESPONSE_FLUSH_PAUSE_S", 0)
    monkeypatch.setattr(app_main, "drain_mutating_requests", AsyncMock(return_value=True))
    monkeypatch.setattr(system, "_drain_sessions", lambda: [])
    handover = AsyncMock(side_effect=lambda _sessions: order.append("handover") or {
        "ok": True,
        "handed_over": [],
    })
    monkeypatch.setattr(
        system.manager,
        "prepare_restart_handover",
        handover,
    )
    monkeypatch.setattr(
        system.manager,
        "mark_for_restart_stop",
        lambda _sessions: order.append("interrupt"),
    )
    monkeypatch.setattr(
        system,
        "_drain_restart_durable_state",
        AsyncMock(side_effect=lambda: order.append("durable_state")),
    )
    monkeypatch.setattr(
        system,
        "_record_restart_outcome",
        lambda _outcome: order.append("record"),
    )
    monkeypatch.setattr(
        system,
        "_arm_supervisor_exit_guard",
        lambda: order.append("guard"),
    )
    monkeypatch.setattr(
        "app.live_broker.broker.close_subscribers",
        lambda: order.append("broker"),
    )
    monkeypatch.setattr(
        system.os,
        "kill",
        lambda _pid, _signal: order.append("signal"),
    )

    result = await system._restart_service_after_response()

    assert result["ok"] is True
    handover.assert_not_awaited()
    assert order == ["interrupt", "durable_state", "record", "guard", "broker", "signal"]


@pytest.mark.asyncio
async def test_t1_durable_state_timeout_still_restarts_and_reports_journal_loss(
    monkeypatch,
    caplog,
):
    from app import main as app_main
    from app.routes import system

    durable = getattr(system, "_drain_restart_durable_state", None)
    arm_guard = getattr(system, "_arm_supervisor_exit_guard", None)
    assert callable(durable) and callable(arm_guard), (
        "restart path has no observable durable-state failure boundary"
    )

    monkeypatch.setattr(system, "_RESPONSE_FLUSH_PAUSE_S", 0)
    monkeypatch.setattr(app_main, "drain_mutating_requests", AsyncMock(return_value=True))
    monkeypatch.setattr(system, "_drain_sessions", lambda: [])
    monkeypatch.setattr(
        system.manager,
        "prepare_restart_handover",
        AsyncMock(return_value={"ok": True, "handed_over": []}),
    )
    monkeypatch.setattr(
        system,
        "_drain_restart_durable_state",
        AsyncMock(return_value={
            "ok": False,
            "phase": "session_db",
            "task_class": "AgentSession._drain_handoff_log_writes",
            "reason": "deadline exceeded",
        }),
    )
    armed: list[bool] = []
    signalled: list[bool] = []
    monkeypatch.setattr(system, "_arm_supervisor_exit_guard", lambda: armed.append(True))
    monkeypatch.setattr(system.os, "kill", lambda *_args: signalled.append(True))

    result = await system._restart_service_after_response()

    assert result["ok"] is True
    assert armed == [True] and signalled == [True]
    assert result["journal_loss"] == {
        "ok": False,
        "phase": "session_db",
        "task_class": "AgentSession._drain_handoff_log_writes",
        "reason": "deadline exceeded",
    }
    assert system.manager.draining is False
    assert app_main.mutating_admission_verdict(
        "POST", "/api/sessions/worker/send",
    )["allowed"] is True
    message = "\n".join(record.getMessage() for record in caplog.records)
    assert f"pid={os.getpid()}" in message
    assert "phase=session_db" in message
    assert "task_class=AgentSession._drain_handoff_log_writes" in message


@pytest.mark.asyncio
async def test_t1_locked_log_write_is_retried_before_reporting_success(monkeypatch):
    import sqlite3

    from app.session import AgentSession

    calls: list[str] = []

    def locked_once(*_args, **_kwargs):
        calls.append("write")
        if len(calls) == 1:
            raise sqlite3.OperationalError("database is locked")
        return 1

    monkeypatch.setattr("app.session.add_log", locked_once)
    session = AgentSession(
        id="locked-log", name="locked-log", scope="/repo", cwd="/repo",
        model="gpt-5.6-sol", role="worker", pipeline="default",
    )
    session._log("status", "persist me")

    result = await session._drain_handoff_log_writes()

    assert calls == ["write", "write"], "database lock gets one bounded retry"
    assert result == {"ok": True, "retried_log_writes": 1}


@pytest.mark.asyncio
async def test_t1_restart_response_contains_current_journal_loss(monkeypatch):
    from app.routes import system

    loss = {
        "ok": False,
        "phase": "session_db",
        "task_class": "AgentSession._drain_handoff_log_writes",
        "reason": "OperationalError: database is locked",
    }
    monkeypatch.setattr(
        system, "restart_preflight", AsyncMock(return_value={"ok": True}),
    )
    monkeypatch.setattr(
        system,
        "_restart_service_after_response",
        AsyncMock(return_value={
            "ok": True,
            "prepared": True,
            "journal_loss": loss,
            "cut_turns": 0,
            "cut_names": [],
            "cut_ids": [],
        }),
    )
    monkeypatch.setattr(system, "_signal_restart_after_response", AsyncMock(), raising=False)

    response = await system.restart_server()

    assert response["scheduled"] is True
    assert response["journal_loss"] == loss
    system._restart_service_after_response.assert_awaited_once_with(signal=False)


@pytest.mark.asyncio
async def test_t1_manager_durable_drain_snapshots_and_waits_for_every_session():
    from app.manager import SessionManager

    manager = SessionManager()
    drains = [AsyncMock(), AsyncMock(), AsyncMock()]
    manager.sessions = {
        f"session-{index}": SimpleNamespace(_drain_handoff_log_writes=drain)
        for index, drain in enumerate(drains)
    }
    method = getattr(manager, "drain_restart_persistence", None)
    assert callable(method), "SessionManager has no real durable restart drain"

    result = await method()

    assert result == {"ok": True, "drained": 3}
    for drain in drains:
        drain.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_t1_real_durable_barrier_enforces_budget_and_failure_identity(monkeypatch):
    from app.routes import system

    durable = getattr(system, "_drain_restart_durable_state", None)
    assert callable(durable), "restart durable-state barrier is missing"

    blocker = asyncio.Event()

    async def never_finishes():
        await blocker.wait()

    monkeypatch.setattr(
        system.manager,
        "drain_restart_persistence",
        never_finishes,
        raising=False,
    )
    monkeypatch.setattr(system, "RESTART_DURABLE_STATE_BUDGET_S", 0.01, raising=False)

    result = await asyncio.wait_for(durable(), timeout=1)

    assert result == {
        "ok": False,
        "phase": "session_db",
        "task_class": "AgentSession._drain_handoff_log_writes",
        "reason": "TimeoutError: deadline exceeded after 0.01s",
    }


@pytest.mark.asyncio
async def test_t1_real_durable_barrier_names_persistent_log_loss(monkeypatch):
    from app.routes import system

    monkeypatch.setattr(
        system.manager,
        "drain_restart_persistence",
        AsyncMock(return_value={
            "ok": False,
            "drained": 1,
            "losses": [{
                "session_id": "locked",
                "session_name": "locked",
                "reason": "RuntimeError: OperationalError: database is locked",
            }],
        }),
    )

    result = await system._drain_restart_durable_state()

    assert result["phase"] == "session_db"
    assert result["task_class"] == "AgentSession._drain_handoff_log_writes"
    assert "database is locked" in result["reason"]


@pytest.mark.asyncio
async def test_t1_after_arm_signal_failure_aborts_guard_before_handover_rollback(
    monkeypatch,
):
    from app import main as app_main
    from app.routes import system

    guard_api = getattr(system, "restart_guard", None)
    durable = getattr(system, "_drain_restart_durable_state", None)
    arm_guard = getattr(system, "_arm_supervisor_exit_guard", None)
    assert guard_api is not None and callable(durable) and callable(arm_guard), (
        "after-arm failure cannot disarm the independent restart guard"
    )

    order: list[str] = []
    monkeypatch.setattr(system, "_RESPONSE_FLUSH_PAUSE_S", 0)
    monkeypatch.setattr(app_main, "drain_mutating_requests", AsyncMock(return_value=True))
    monkeypatch.setattr(system, "_drain_sessions", lambda: [])
    monkeypatch.setattr(
        system.manager,
        "prepare_restart_handover",
        AsyncMock(return_value={"ok": True, "handed_over": []}),
    )
    monkeypatch.setattr(
        system,
        "_drain_restart_durable_state",
        AsyncMock(return_value={"ok": True, "drained": 0}),
    )
    monkeypatch.setattr(
        system,
        "_arm_supervisor_exit_guard",
        lambda: order.append("arm"),
    )
    monkeypatch.setattr(
        guard_api,
        "abort_guard",
        AsyncMock(side_effect=lambda _reason: order.append("guard_abort")),
    )
    monkeypatch.setattr(
        system.manager,
        "rollback_restart_handover",
        AsyncMock(side_effect=lambda: order.append("rollback")),
    )
    monkeypatch.setattr("app.live_broker.broker.close_subscribers", lambda: None)

    def signal_fails(_pid, _signal):
        order.append("signal")
        raise RuntimeError("injected signal failure")

    monkeypatch.setattr(system.os, "kill", signal_fails)

    with pytest.raises(RuntimeError, match="injected signal failure"):
        await system._restart_service_after_response()

    assert order == ["arm", "signal", "guard_abort", "rollback"]
    assert system.manager.draining is False
    assert app_main.mutating_admission_verdict(
        "POST", "/api/sessions/worker/send",
    )["allowed"] is True


@pytest.mark.asyncio
async def test_t1_shutdown_sequence_marks_bg_and_handoff_before_cleanup_complete(
    monkeypatch,
):
    from app import main as app_main

    shutdown_runtime = getattr(app_main, "_shutdown_runtime", None)
    assert callable(shutdown_runtime), (
        "lifespan teardown is not an observable ordered shutdown sequence"
    )

    order: list[tuple[str, str] | str] = []
    monkeypatch.setattr(
        "app.restart_guard.note_shutdown_phase",
        lambda phase, task_class: order.append((phase, task_class)),
    )
    monkeypatch.setattr(
        "app.merge_operations.shutdown_merge_operations",
        AsyncMock(side_effect=lambda: order.append("merge_done")),
    )
    monkeypatch.setattr("app.rag_service.shutdown", lambda: order.append("rag_done"))
    monkeypatch.setattr(
        "app.tg_bridge.stop_bridge",
        AsyncMock(side_effect=lambda: order.append("tg_done")),
    )
    monkeypatch.setattr(
        "app.bg_jobs.bg_manager.shutdown",
        AsyncMock(side_effect=lambda: order.append("bg_done")),
    )
    monkeypatch.setattr(
        app_main.manager,
        "shutdown_all",
        AsyncMock(side_effect=lambda: order.append("handoff_done")),
    )

    done_task = asyncio.create_task(asyncio.sleep(0))
    await done_task
    await shutdown_runtime(
        restart_inbox_drain=None,
        snapshot_task=done_task,
        bridge_task=done_task,
    )

    assert order.index("bg_done") < order.index("handoff_done")
    cleanup = ("application_teardown_complete", "post_lifespan_runtime")
    assert cleanup in order
    assert order.index("handoff_done") < order.index(cleanup)


def test_t1_lifespan_calls_shutdown_runtime_after_yield_mechanically():
    from app import main as app_main

    source = Path(app_main.__file__).read_text()
    tree = ast.parse(source)
    lifespan = next(
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "lifespan"
    )
    yield_index = next(
        index for index, statement in enumerate(lifespan.body)
        if any(isinstance(node, (ast.Yield, ast.YieldFrom)) for node in ast.walk(statement))
    )
    shutdown_calls = []
    for index, statement in enumerate(lifespan.body):
        if not (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Await)
            and isinstance(statement.value.value, ast.Call)
        ):
            continue
        function = statement.value.value.func
        if isinstance(function, ast.Name) and function.id == "_shutdown_runtime":
            shutdown_calls.append(index)

    assert shutdown_calls == [yield_index + 1], (
        "lifespan must directly await _shutdown_runtime exactly once immediately after yield"
    )
