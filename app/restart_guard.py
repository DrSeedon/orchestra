"""Independent bounded exit guard for a restarting Orchestra supervisor."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
import select
import selectors
import signal
import subprocess
import sys
import time
from typing import Callable


logger = logging.getLogger(__name__)

RESTART_POST_CLEANUP_EXIT_BUDGET_S = 5.0
# 2.0 с не хватало на загруженной машине: форк helper'а не успевал ответить READY,
# рестарт молча отменялся, и снаружи это выглядело как «сервис игнорирует рестарт».
# 25.08 подряд отменились 5 рестартов при loadavg 7.5 и 1.8 ГБ свободной памяти.
RESTART_GUARD_READY_TIMEOUT_S = 15.0
# Шаг опроса живости цели, когда pidfd недоступен и epoll о смерти не сообщит.
_FALLBACK_POLL_S = 0.25


@dataclass(slots=True)
class GuardHandle:
    helper_pid: int
    process: subprocess.Popen
    progress_writer: int


class ProcessIdentityMismatch(RuntimeError):
    pass


class RestartGuardUnavailable(RuntimeError):
    pass


_active_guard: GuardHandle | None = None


def _read_starttime(pid: int) -> int:
    with open(f"/proc/{pid}/stat", "rb") as stream:
        raw = stream.read().decode("utf-8", "replace")
    fields = raw.rpartition(")")[2].split()
    if len(fields) <= 19:
        raise ValueError("process starttime is unavailable")
    return int(fields[19])


def open_verified_pidfd(
    pid: int,
    expected_start_ticks: int,
    *,
    pidfd_open: Callable[[int], int] | None = None,
    read_starttime: Callable[[int], int] = _read_starttime,
) -> int:
    """Pin ``pid`` before comparing its starttime, closing the PID-reuse race."""
    if pidfd_open is None:
        pidfd_open = getattr(os, "pidfd_open", None)
        if pidfd_open is None:
            # Без pidfd_open сторож отказывался подниматься, и КАЖДЫЙ рестарт молча
            # отменялся: 25.08 на этой машине (Python без pidfd_open, ядро 7.0) так
            # сгорели пять рестартов подряд. Держим процесс открытым каталогом
            # /proc/<pid> — он тоже перестаёт разрешаться после смерти процесса,
            # а защиту от переиспользования PID даёт сверка starttime ниже, а не сам fd.
            pidfd_open = lambda target: os.open(  # noqa: E731
                f"/proc/{target}", os.O_RDONLY | os.O_DIRECTORY
            )
    pidfd = pidfd_open(pid)
    try:
        actual_start_ticks = read_starttime(pid)
        if actual_start_ticks != expected_start_ticks:
            raise ProcessIdentityMismatch(
                f"starttime {actual_start_ticks} != expected {expected_start_ticks}"
            )
        return pidfd
    except BaseException:
        os.close(pidfd)
        raise


def _write_progress(handle: GuardHandle, phase: str, task_class: str) -> None:
    if handle.progress_writer < 0:
        return
    payload = json.dumps(
        {"phase": phase, "task_class": task_class},
        separators=(",", ":"),
    ).encode() + b"\n"
    os.write(handle.progress_writer, payload)


def _close_progress_writer(handle: GuardHandle) -> None:
    fd, handle.progress_writer = handle.progress_writer, -1
    if fd < 0:
        return
    try:
        os.close(fd)
    except OSError:
        pass


def _reap_helper(process: subprocess.Popen) -> None:
    """Bounded graceful stop → terminate → kill; return only after wait() proves exit."""
    try:
        process.wait(timeout=2.0)
        return
    except subprocess.TimeoutExpired:
        process.terminate()
    try:
        process.wait(timeout=2.0)
        return
    except subprocess.TimeoutExpired:
        process.kill()
    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired as error:
        raise RestartGuardUnavailable(
            f"restart guard helper pid={process.pid} survived SIGKILL"
        ) from error


def arm_guard(
    *,
    target_pid: int,
    start_ticks: int,
    post_cleanup_budget: float = RESTART_POST_CLEANUP_EXIT_BUDGET_S,
    event_log: str | Path | None = None,
) -> GuardHandle:
    """Start a helper whose only inherited application FD is its progress pipe."""
    global _active_guard

    if _active_guard is not None:
        if _active_guard.process.poll() is None:
            try:
                _write_progress(_active_guard, "aborted", "restart.abort")
            except OSError:
                pass
        _close_progress_writer(_active_guard)
        _reap_helper(_active_guard.process)
        _active_guard = None

    progress_read_fd, progress_write_fd = os.pipe()
    ready_read_fd, ready_write_fd = os.pipe()
    command = [
        sys.executable,
        "-m",
        "app.restart_guard",
        "--pid",
        str(target_pid),
        "--start-ticks",
        str(start_ticks),
        "--progress-fd",
        str(progress_read_fd),
        "--ready-fd",
        str(ready_write_fd),
        "--post-cleanup-budget",
        str(post_cleanup_budget),
    ]
    if event_log is not None:
        command.extend(("--event-log", os.fspath(event_log)))
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            close_fds=True,
            pass_fds=(progress_read_fd, ready_write_fd),
            start_new_session=True,
        )
    except BaseException:
        os.close(progress_read_fd)
        os.close(progress_write_fd)
        os.close(ready_read_fd)
        os.close(ready_write_fd)
        raise
    os.close(progress_read_fd)
    os.close(ready_write_fd)
    try:
        readable, _writable, _exceptional = select.select(
            [ready_read_fd],
            [],
            [],
            RESTART_GUARD_READY_TIMEOUT_S,
        )
        ready = os.read(ready_read_fd, 64) if readable else b""
        if ready != b"READY\n":
            raise RestartGuardUnavailable(
                f"restart guard helper pid={process.pid} failed readiness handshake"
            )
    except BaseException:
        try:
            os.close(progress_write_fd)
        except OSError:
            pass
        _reap_helper(process)
        raise
    finally:
        os.close(ready_read_fd)
    handle = GuardHandle(process.pid, process, progress_write_fd)
    _active_guard = handle
    return handle


def note_shutdown_phase(phase: str, task_class: str) -> None:
    """Report teardown progress without allowing diagnostics to break teardown."""
    handle = _active_guard
    if handle is None:
        return
    try:
        _write_progress(handle, phase, task_class)
    except OSError as error:
        logger.warning(
            "restart guard progress write failed: %s: %s",
            type(error).__name__,
            error,
        )


async def abort_guard(reason: str) -> None:
    """Disarm the current helper and wait until it can no longer signal the target."""
    global _active_guard

    handle = _active_guard
    if handle is None:
        return
    try:
        _write_progress(handle, "aborted", "restart.abort")
    except OSError as error:
        logger.warning(
            "restart guard abort write failed (%s): %s: %s",
            reason,
            type(error).__name__,
            error,
        )
    finally:
        _close_progress_writer(handle)

    # Deliberately synchronous and bounded: cancellation of the event loop must not interrupt
    # the safety operation and let rollback resume while the helper can still signal us.
    _reap_helper(handle.process)
    if _active_guard is handle:
        _active_guard = None


def _close_ready_fd(fd: int | None) -> None:
    if fd is None:
        return
    try:
        os.close(fd)
    except OSError:
        pass


def _terminal_event(
    event: str,
    *,
    forced: bool,
    pid: int,
    start_ticks: int,
    phase: str,
    task_class: str,
    started: float,
) -> dict:
    return {
        "event": event,
        "forced": forced,
        "pid": pid,
        "start_ticks": start_ticks,
        "phase": phase,
        "task_class": task_class,
        "elapsed_s": time.monotonic() - started,
    }


def _emit_terminal(event: dict, event_log: Path | None) -> None:
    line = json.dumps(event, separators=(",", ":"))
    print(line, file=sys.stderr, flush=True)
    if event_log is not None:
        with event_log.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")


def _send_signal(pidfd: int, pid: int, expected_start_ticks: int, sig: int) -> None:
    """Сигнал по pidfd, а без него — по pid с пересверкой starttime.

    `pidfd_send_signal` требует НАСТОЯЩИЙ pidfd; с fallback-дескриптором /proc/<pid>
    он отвечает PermissionError. Путь по pid безопасен только вместе с повторной
    сверкой времени старта: PID переиспользуются, и без неё сигнал уйдёт чужому.
    """
    send = getattr(signal, "pidfd_send_signal", None)
    if send is not None and hasattr(os, "pidfd_open"):
        send(pidfd, sig)
        return
    try:
        actual = _read_starttime(pid)
    except FileNotFoundError as error:      # процесс уже умер → ProcessLookupError, как у pidfd
        raise ProcessLookupError(pid) from error
    if actual != expected_start_ticks:
        raise ProcessLookupError(pid)
    os.kill(pid, sig)


def _helper_main(args: argparse.Namespace) -> int:
    started = time.monotonic()
    phase = "armed"
    task_class = "restart_guard.progress"
    event_log = Path(args.event_log) if args.event_log else None
    ready_fd = args.ready_fd
    try:
        pidfd = open_verified_pidfd(args.pid, args.start_ticks)
    except ProcessIdentityMismatch:
        _close_ready_fd(ready_fd)
        _emit_terminal(
            _terminal_event(
                "identity_mismatch",
                forced=False,
                pid=args.pid,
                start_ticks=args.start_ticks,
                phase="identity_check",
                task_class="pidfd_identity",
                started=started,
            ),
            event_log,
        )
        return 3
    except ProcessLookupError:
        _close_ready_fd(ready_fd)
        _emit_terminal(
            _terminal_event(
                "clean_exit",
                forced=False,
                pid=args.pid,
                start_ticks=args.start_ticks,
                phase=phase,
                task_class=task_class,
                started=started,
            ),
            event_log,
        )
        return 0

    selector = selectors.DefaultSelector()
    progress_open = True
    buffer = b""
    cleanup_deadline: float | None = None
    try:
        # Каталог /proc/<pid> из fallback-пути НЕ регистрируется в epoll (PermissionError):
        # опрашиваемым он быть не может. Тогда смерть процесса ловим коротким опросом
        # starttime ниже, а не событием готовности.
        pidfd_pollable = hasattr(os, "pidfd_open")
        if pidfd_pollable:
            selector.register(pidfd, selectors.EVENT_READ, "pidfd")
        selector.register(args.progress_fd, selectors.EVENT_READ, "progress")
        if ready_fd is not None:
            os.write(ready_fd, b"READY\n")
            os.close(ready_fd)
            ready_fd = None
        while True:
            timeout = None
            if cleanup_deadline is not None:
                timeout = max(0.0, cleanup_deadline - time.monotonic())
            if not pidfd_pollable:
                # Без опрашиваемого pidfd смерть цели не приходит событием: просыпаемся
                # сами и проверяем её. Иначе select(None) ждал бы вечно.
                timeout = _FALLBACK_POLL_S if timeout is None else min(timeout, _FALLBACK_POLL_S)
            ready = selector.select(timeout)
            if not ready and not pidfd_pollable and cleanup_deadline is None:
                try:
                    if _read_starttime(args.pid) != args.start_ticks:
                        raise ProcessLookupError(args.pid)
                except (FileNotFoundError, ProcessLookupError):
                    _emit_terminal(
                        _terminal_event(
                            "clean_exit", forced=False, pid=args.pid,
                            start_ticks=args.start_ticks, phase=phase,
                            task_class=task_class, started=started,
                        ),
                        event_log,
                    )
                    return 0
                continue
            if not ready:
                try:
                    _send_signal(pidfd, args.pid, args.start_ticks, signal.SIGKILL)
                except ProcessLookupError:
                    event = "clean_exit"
                    forced = False
                else:
                    event = "forced_fallback"
                    forced = True
                _emit_terminal(
                    _terminal_event(
                        event,
                        forced=forced,
                        pid=args.pid,
                        start_ticks=args.start_ticks,
                        phase=phase,
                        task_class=task_class,
                        started=started,
                    ),
                    event_log,
                )
                return 0

            if any(key.data == "pidfd" for key, _mask in ready):
                _emit_terminal(
                    _terminal_event(
                        "clean_exit",
                        forced=False,
                        pid=args.pid,
                        start_ticks=args.start_ticks,
                        phase=phase,
                        task_class=task_class,
                        started=started,
                    ),
                    event_log,
                )
                return 0

            for key, _mask in ready:
                if key.data != "progress":
                    continue
                chunk = os.read(args.progress_fd, 65536)
                if not chunk:
                    selector.unregister(args.progress_fd)
                    progress_open = False
                    if cleanup_deadline is None:
                        _emit_terminal(
                            _terminal_event(
                                "progress_lost",
                                forced=False,
                                pid=args.pid,
                                start_ticks=args.start_ticks,
                                phase=phase,
                                task_class=task_class,
                                started=started,
                            ),
                            event_log,
                        )
                        return 2
                    continue
                buffer += chunk
                while b"\n" in buffer:
                    raw_line, buffer = buffer.split(b"\n", 1)
                    try:
                        progress = json.loads(raw_line)
                        phase = str(progress["phase"])
                        task_class = str(progress["task_class"])
                    except (json.JSONDecodeError, KeyError, TypeError, UnicodeDecodeError):
                        continue
                    if phase == "aborted":
                        _emit_terminal(
                            _terminal_event(
                                "aborted",
                                forced=False,
                                pid=args.pid,
                                start_ticks=args.start_ticks,
                                phase=phase,
                                task_class=task_class,
                                started=started,
                            ),
                            event_log,
                        )
                        return 0
                    if phase == "application_teardown_complete" and cleanup_deadline is None:
                        cleanup_deadline = time.monotonic() + args.post_cleanup_budget
    finally:
        _close_ready_fd(ready_fd)
        selector.close()
        os.close(pidfd)
        if progress_open:
            os.close(args.progress_fd)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--start-ticks", type=int, required=True)
    parser.add_argument("--progress-fd", type=int, required=True)
    parser.add_argument("--ready-fd", type=int)
    parser.add_argument("--post-cleanup-budget", type=float, required=True)
    parser.add_argument("--event-log")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(_helper_main(_parse_args()))
