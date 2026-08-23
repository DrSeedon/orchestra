"""Executable regression checks for #379 implementation-review findings."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.backend_jsonrpc import process_start_time


def _stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)


@pytest.mark.asyncio
async def test_review_cancelled_startup_tasks_finish_before_teardown_marker(
    monkeypatch,
):
    from app import main as app_main
    from app import restart_guard

    order: list[str] = []
    phase_started = asyncio.Event()
    release_cleanup = asyncio.Event()
    cancelled = [asyncio.Event(), asyncio.Event()]

    async def lingering(index: int) -> None:
        try:
            await asyncio.Event().wait()
        finally:
            cancelled[index].set()
            await release_cleanup.wait()
            order.append(f"cancelled-{index}")

    def phase(name: str, _task_class: str) -> None:
        order.append(name)
        phase_started.set()

    monkeypatch.setattr(restart_guard, "note_shutdown_phase", phase)
    monkeypatch.setattr(
        "app.merge_operations.shutdown_merge_operations",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr("app.rag_service.shutdown", lambda: None)
    monkeypatch.setattr("app.tg_bridge.stop_bridge", AsyncMock(return_value=None))
    monkeypatch.setattr("app.bg_jobs.bg_manager.shutdown", AsyncMock(return_value=None))
    monkeypatch.setattr(app_main.manager, "shutdown_all", AsyncMock(return_value=None))

    inbox_task = asyncio.create_task(lingering(0))
    snapshot_task = asyncio.create_task(lingering(1))
    bridge_task = asyncio.create_task(asyncio.sleep(0))
    await asyncio.sleep(0)
    shutdown = asyncio.create_task(app_main._shutdown_runtime(
        inbox_task,
        snapshot_task,
        False,
        bridge_task,
    ))
    await asyncio.gather(*(event.wait() for event in cancelled))

    assert phase_started.is_set() is False, (
        "shutdown phases started while cancelled startup tasks were still cleaning up"
    )
    release_cleanup.set()
    await shutdown

    marker = order.index("application_teardown_complete")
    assert order.index("cancelled-0") < marker
    assert order.index("cancelled-1") < marker


@pytest.mark.asyncio
async def test_review_production_arm_requires_helper_readiness(monkeypatch, tmp_path):
    from app import restart_guard

    target = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"])
    try:
        with pytest.raises(RuntimeError, match="readiness|ready|identity"):
            restart_guard.arm_guard(
                target_pid=target.pid,
                start_ticks=process_start_time(target.pid) + 1,
                post_cleanup_budget=0.1,
                event_log=tmp_path / "identity.jsonl",
            )
        assert target.poll() is None
        assert restart_guard._active_guard is None
    finally:
        await restart_guard.abort_guard("test cleanup")
        _stop_process(target)


@pytest.mark.asyncio
async def test_review_abort_escalates_helper_termination_and_reaps(monkeypatch):
    from app import restart_guard

    process = MagicMock()
    process.pid = 91_111
    process.poll.return_value = None
    process.wait.side_effect = [
        subprocess.TimeoutExpired("guard", 2),
        subprocess.TimeoutExpired("guard", 2),
        0,
    ]
    read_fd, write_fd = os.pipe()
    restart_guard._active_guard = restart_guard.GuardHandle(
        helper_pid=process.pid,
        process=process,
        progress_writer=write_fd,
    )
    try:
        await restart_guard.abort_guard("injected stuck helper")
    finally:
        restart_guard._active_guard = None
        os.close(read_fd)

    process.terminate.assert_called_once_with()
    process.kill.assert_called_once_with()
    assert process.wait.call_count == 3


@pytest.mark.asyncio
async def test_review_abort_failure_keeps_handover_quiesced_and_gates_closed(monkeypatch):
    from app import main as app_main
    from app.routes import system

    system.manager.begin_drain()
    app_main.close_mutating_admission()
    rollback = AsyncMock()
    monkeypatch.setattr(system.manager, "rollback_restart_handover", rollback)
    monkeypatch.setattr(
        system.restart_guard,
        "abort_guard",
        AsyncMock(side_effect=RuntimeError("helper still alive")),
    )
    try:
        with pytest.raises(RuntimeError, match="helper still alive"):
            await system._abort_restart("injected abort failure")
        rollback.assert_not_awaited()
        assert system.manager.draining is True
        assert app_main.mutating_admission_verdict(
            "POST",
            "/api/sessions/worker/send",
        )["allowed"] is False
    finally:
        system.manager.end_drain()
        app_main.open_mutating_admission()


@pytest.mark.asyncio
async def test_review_failed_reap_retains_active_guard_until_verified_retry():
    from app import restart_guard

    process = MagicMock()
    process.pid = 91_112
    process.wait.side_effect = [
        subprocess.TimeoutExpired("guard", 2),
        subprocess.TimeoutExpired("guard", 2),
        subprocess.TimeoutExpired("guard", 2),
    ]
    read_fd, write_fd = os.pipe()
    handle = restart_guard.GuardHandle(
        helper_pid=process.pid,
        process=process,
        progress_writer=write_fd,
    )
    restart_guard._active_guard = handle
    replacement_fd = -1
    try:
        with pytest.raises(restart_guard.RestartGuardUnavailable, match="survived SIGKILL"):
            await restart_guard.abort_guard("first attempt")
        assert restart_guard._active_guard is handle
        assert handle.progress_writer == -1

        # Deterministically reuse the old numeric slot. A retry must not write into or close
        # this unrelated descriptor merely because the retained handle used to own that number.
        replacement_fd = os.open("/dev/null", os.O_RDONLY)
        if replacement_fd != write_fd:
            os.dup2(replacement_fd, write_fd)
            os.close(replacement_fd)
            replacement_fd = write_fd

        process.wait.side_effect = [0]
        await restart_guard.abort_guard("verified retry")
        assert restart_guard._active_guard is None
        assert os.fstat(replacement_fd)
    finally:
        restart_guard._active_guard = None
        if replacement_fd >= 0:
            os.close(replacement_fd)
        os.close(read_fd)


@pytest.mark.asyncio
async def test_review_wrapper_does_not_retry_failed_disarm_or_reopen(monkeypatch):
    from app import main as app_main
    from app.routes import system

    system.manager.begin_drain()
    app_main.close_mutating_admission()
    rollback = AsyncMock()
    abort = AsyncMock(side_effect=RuntimeError("helper still alive"))
    monkeypatch.setattr(system, "_do_restart_service", AsyncMock(side_effect=ValueError("primary")))
    monkeypatch.setattr(system.manager, "rollback_restart_handover", rollback)
    monkeypatch.setattr(system.restart_guard, "abort_guard", abort)
    try:
        with pytest.raises(RuntimeError, match="helper still alive"):
            await system._restart_service_after_response()
        abort.assert_awaited_once_with("the restart path failed")
        rollback.assert_not_awaited()
        assert system.manager.draining is True
        assert app_main.mutating_admission_verdict(
            "POST",
            "/api/sessions/worker/send",
        )["allowed"] is False
    finally:
        system.manager.end_drain()
        app_main.open_mutating_admission()
