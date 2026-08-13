"""Общий JSON-RPC-over-stdio транспорт для бэкендов на внешнем процессе.

Только транспорт: запись в stdin, корреляция id→future, накопление stderr,
liveness. Семантику (что за события, как их конвертить, как считать usage)
каждый бэкенд реализует сам — она у Codex и Grok расходится законно
(замер difflib: _read_stdout 0.23, send 0.22, _turn_completed 0.06), и
объединять её было бы ошибкой.

Требует от класса-носителя атрибуты, которые оба бэкенда и так заводят:
``_proc``, ``_pending_requests``, ``_request_seq``, ``_write_lock``, ``_last_stderr``.
"""

import asyncio
import base64
import contextlib
import errno
import json
import logging
import os
import shutil
import signal
from pathlib import Path
from typing import Optional


class JsonRpcStdioTransport:
    #: имя рантайма в тексте ошибок — единственное, чем отличались тела методов
    RUNTIME_LABEL: str = "JSON-RPC agent"
    #: Grok шлёт конверт {"jsonrpc": "2.0", ...}, Codex — нет
    JSONRPC_ENVELOPE: bool = False

    # Заводятся в __init__ класса-носителя; объявлены здесь для типизации.
    _proc: Optional[asyncio.subprocess.Process]
    _pending_requests: dict[int, asyncio.Future]
    _request_seq: int
    _write_lock: asyncio.Lock
    _last_stderr: str

    #: Adopted transport (#230): the CLI outlived a supervisor restart, so there is no
    #: Process object at all — only its pipes, handed back by systemd's fd store.
    _adopted_reader: Optional[asyncio.StreamReader] = None
    _adopted_writer: Optional[asyncio.StreamWriter] = None
    _adopted_fds: Optional[tuple[int, int]] = None
    _adopted_pid: Optional[int] = None
    _adopted_read_transport = None
    _handover_quiescing: bool = False
    _adopted_started_at: int = 0
    _quiesced_prefix: bytes = b""

    @property
    def _out(self) -> Optional[asyncio.StreamReader]:
        if self._adopted_reader is not None:
            return self._adopted_reader
        return self._proc.stdout if self._proc else None

    @property
    def _in(self):
        if self._adopted_writer is not None:
            return self._adopted_writer
        return self._proc.stdin if self._proc else None

    @property
    def is_alive(self) -> bool:
        if self._adopted_writer is not None:
            return not self._adopted_writer.is_closing()
        return self._proc is not None and self._proc.returncode is None

    @property
    def fd_in(self) -> Optional[int]:
        """OUR end of the CLI's stdin, the descriptor systemd must keep (#230 T4)."""
        if self._adopted_fds is not None:
            return self._adopted_fds[0]
        if self._proc is None or self._proc.stdin is None:
            return None
        transport = getattr(self._proc.stdin, "transport", None)
        pipe = transport.get_extra_info("pipe") if transport else None
        return pipe.fileno() if pipe is not None else None

    @property
    def fd_out(self) -> Optional[int]:
        if self._adopted_fds is not None:
            return self._adopted_fds[1]
        if self._proc is None:
            return None
        # the reader side is reachable only through the process transport (measured: both
        # extraction paths verified on a spawned child before this was written)
        transport = getattr(self._proc, "_transport", None)
        pipe_transport = transport.get_pipe_transport(1) if transport else None
        pipe = pipe_transport.get_extra_info("pipe") if pipe_transport else None
        return pipe.fileno() if pipe is not None else None

    @property
    def cli_started_at(self) -> int:
        """Start time of the CLI, so a reused pid cannot be mistaken for it (#230)."""
        if self._adopted_started_at:
            return self._adopted_started_at
        return process_start_time(self._proc.pid) if self._proc is not None else 0

    @property
    def pid(self) -> Optional[int]:
        """OS pid of the CLI, so an orphaned process can be reaped later (#230 T7).

        An ADOPTED transport did not spawn anything, so the pid travels through the DB across
        restarts: the process itself never changed.
        """
        if self._proc is not None:
            return self._proc.pid
        return self._adopted_pid

    async def quiesce_for_handover(self, drain_budget_s: float = 1.0) -> bool:
        """Stop reading, THEN let the buffer settle, before anyone snapshots it (#230 T4).

        Snapshotting while the reader is alive is a race: it can pull more bytes out of the
        kernel into a process that is about to die, and it can move whole notifications into an
        in-memory queue that nothing transfers. So: cancel the reader first, then give the
        consumer a bounded moment to drain what it already parsed.
        """
        # FAIL-CLOSED FIRST: a pending JSON-RPC request (a mid-turn `turn/steer`, a compact)
        # has an unknown outcome — the CLI may have acted on it and we would never see the
        # answer. Cancelling the reader completes those futures with a fabricated "exited"
        # error, which is a LIE about a process that is still alive. Refusing the handover
        # costs this agent its turn the old, visible way instead.
        pending = [rid for rid, fut in (self._pending_requests or {}).items() if not fut.done()]
        compact_pending = getattr(self, "_compact_future", None)
        if pending or (compact_pending is not None and not compact_pending.done()):
            logging.getLogger("app.session").error(
                "handover refused: %d in-flight request(s) %s and compact=%s — their outcome "
                "would be unknown to the next generation",
                len(pending), pending[:5], compact_pending is not None,
            )
            return False  # flag not set yet on this path

        # Mark the pause BEFORE cancelling: `_read_stdout`'s finally enqueues `_process/exited`
        # otherwise, and the session would see a live agent as dead in the middle of a handover.
        self._handover_quiescing = True
        task = getattr(self, "_reader_task", None)
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._reader_task = None
        queue = getattr(self, "_notifications", None)
        if queue is None:
            return True
        loop = asyncio.get_running_loop()
        deadline = loop.time() + drain_budget_s
        while not queue.empty() and loop.time() < deadline:
            await asyncio.sleep(0.02)
        if queue.empty():
            return True
        # Anything still queued is a PARSED event of a live turn — possibly `turn/completed`.
        # Declaring it lost would break the zero-loss contract, so re-encode the frames and
        # hand them to the next generation ahead of the buffered bytes: that is where they came
        # from, and the reader will parse them again.
        frames: list[bytes] = []
        try:
            while not queue.empty():
                frames.append(json.dumps(queue.get_nowait(), ensure_ascii=False).encode() + b"\n")
        except Exception as error:
            logging.getLogger("app.session").error(
                "handover: %d parsed event(s) could not be re-encoded (%s) — refusing handover",
                queue.qsize(), error,
            )
            self.abort_handover()
            return False
        self._quiesced_prefix = b"".join(frames)
        logging.getLogger("app.session").info(
            "handover: carried %d already-parsed event(s) forward as raw frames", len(frames),
        )
        return True

    def abort_handover(self) -> None:
        """Undo the quiescing state when the handover will NOT happen (#230).

        The flag suppresses both halves of the "process died" story, and only
        `teardown_adopted` used to clear it — which a non-adopted backend never calls. Left
        stuck ON, a REAL death becomes completely silent: no `_process/exited`, and pending
        futures are never completed, so their callers wait forever.
        """
        self._handover_quiescing = False
        self._quiesced_prefix = b""

    @property
    def leftover_bytes(self) -> bytes:
        """Bytes already pulled out of the kernel pipe into our buffer (#230 T4).

        Everything still IN the pipe survives a restart by itself (measured, research F3);
        these do not. `_buffer` is stdlib-private, hence the guarded read: if a future Python
        renames it we hand over an empty leftover and lose at most one partial frame, instead
        of failing the whole handover.
        """
        reader = self._out
        buffered = bytes(getattr(reader, "_buffer", b"") if reader is not None else b"")
        # parsed-but-unconsumed frames came off the stream BEFORE these bytes
        return self._quiesced_prefix + buffered

    @property
    def leftover(self) -> str:
        """Bytes already pulled out of the kernel pipe into our buffer (#230 T4).

        Everything still IN the pipe survives a restart by itself (measured, research F3);
        these do not. `_buffer` is stdlib-private, hence the guarded read: if a future Python
        renames it we hand over an empty leftover and lose at most one partial frame, instead
        of failing the whole handover.
        """
        # base64 so the DB TEXT column cannot mangle a partial multi-byte frame
        return base64.b64encode(self.leftover_bytes).decode("ascii")

    async def adopt_pipes(self, fd_in: int, fd_out: int, *, limit: int,
                          leftover: str = "", cli_pid: int = 0,
                          cli_started_at: int = 0) -> None:
        """Attach reader/writer to descriptors we did not open (#230 T2).

        `leftover` is base64 of the bytes the PREVIOUS generation had already pulled out of the
        pipe. They are fed back into the reader before anything else, otherwise the first frame
        arrives headless and is dropped as invalid JSON — possibly the terminal event.
        """
        import os

        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader(limit=limit)
        if leftover:
            reader.feed_data(base64.b64decode(leftover))
        read_transport, _read_protocol = await loop.connect_read_pipe(
            lambda: asyncio.StreamReaderProtocol(reader), os.fdopen(fd_out, "rb", 0)
        )
        self._adopted_read_transport = read_transport
        transport, protocol = await loop.connect_write_pipe(
            asyncio.streams.FlowControlMixin, os.fdopen(fd_in, "wb", 0)
        )
        self._adopted_reader = reader
        self._adopted_writer = asyncio.StreamWriter(transport, protocol, reader, loop)
        self._adopted_fds = (fd_in, fd_out)
        self._adopted_pid = cli_pid or None
        # NOT `or process_start_time(cli_pid)`: a lost record must stay lost. Re-measuring
        # here would describe whoever holds that pid NOW and would bless a stranger.
        self._adopted_started_at = cli_started_at

    async def teardown_adopted(self) -> None:
        """Release an adopted CLI for real: reader, transports, and the process (#230 T9).

        `disconnect()` used to return immediately here (no Process, no scope unit), so a
        replacement CLI was spawned while the adopted one kept running — an unowned duplicate.
        """
        task = getattr(self, "_reader_task", None)
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._reader_task = None
        writer = self._adopted_writer
        if writer is not None:
            with contextlib.suppress(Exception):
                writer.close()
        # both ends: closing only the writer leaked the read descriptor every replacement
        read_transport = self._adopted_read_transport
        if read_transport is not None:
            with contextlib.suppress(Exception):
                read_transport.close()
        self._adopted_read_transport = None
        pid = self._adopted_pid
        started_at = self._adopted_started_at  # read BEFORE the reset below wipes it
        self._adopted_writer = None
        self._adopted_reader = None
        self._adopted_fds = None
        self._adopted_pid = None
        # reset ALL adopted-generation state, so reuse and diagnostics are deterministic
        self._adopted_started_at = 0
        self._handover_quiescing = False
        self._quiesced_prefix = b""
        if pid:
            terminate_cli_process(pid, self.RUNTIME_LABEL, started_at)

    async def _request(self, method: str, params: dict) -> dict:
        if self._in is None or not self.is_alive:
            raise RuntimeError(f"{self.RUNTIME_LABEL} is not running")
        self._request_seq += 1
        request_id = self._request_seq
        future = asyncio.get_running_loop().create_future()
        self._pending_requests[request_id] = future
        try:
            await self._write(self._envelope({"method": method, "id": request_id,
                                              "params": params}))
            result = await future
            return result if isinstance(result, dict) else {}
        finally:
            self._pending_requests.pop(request_id, None)

    async def _notify(self, method: str, params: dict) -> None:
        await self._write(self._envelope({"method": method, "params": params}))

    async def _write(self, payload: dict) -> None:
        stream = self._in
        if stream is None:
            raise RuntimeError(f"{self.RUNTIME_LABEL} stdin is unavailable")
        encoded = (json.dumps(payload, ensure_ascii=False) + "\n").encode()
        async with self._write_lock:
            stream.write(encoded)
            await stream.drain()

    def _envelope(self, payload: dict) -> dict:
        return {"jsonrpc": "2.0", **payload} if self.JSONRPC_ENVELOPE else payload

    async def _drain_stderr(self) -> None:
        proc = self._proc
        if not proc or not proc.stderr:
            return
        try:
            while True:
                chunk = await proc.stderr.read(4096)
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace")
                self._last_stderr = (self._last_stderr + text)[-4000:]
        except asyncio.CancelledError:
            return


_TOOL_ARGUMENT_LONG_FIELDS = {
    "content", "context", "description", "message", "prompt", "system_prompt", "task",
}


def bounded_tool_arguments(value, *, field: str = ""):
    """Keep tool telemetry structured without letting prompts flood the log."""
    if isinstance(value, dict):
        return {
            str(key): bounded_tool_arguments(item, field=str(key))
            for key, item in list(value.items())[:50]
        }
    if isinstance(value, list):
        return [bounded_tool_arguments(item, field=field) for item in value[:50]]
    if isinstance(value, str):
        limit = 4000 if field in _TOOL_ARGUMENT_LONG_FIELDS else 1500
        if len(value) > limit:
            omitted = len(value) - limit
            return f"{value[:limit]}… [truncated {omitted} chars]"
    return value


def _normalise_executable(path: str) -> str:
    """Resolve a configured executable and reject missing or malformed paths."""
    if not isinstance(path, str) or not path or "\0" in path:
        raise ValueError("invalid executable path")
    path = os.path.expanduser(path)
    if not os.path.isabs(path):
        path = shutil.which(path) or ""
    if not path:
        raise FileNotFoundError("configured executable was not found")
    return str(Path(path).resolve(strict=True))


def _runtime_argv(argv: list[str], label: str | None) -> str | None:
    """Return the matching managed runtime, accepting only its known argv shape."""
    if not argv:
        return None
    if label is None:
        allowed = ("codex", "grok")
    elif label == "Codex app-server":
        allowed = ("codex",)
    elif label in ("Grok", "Grok ACP agent"):
        allowed = ("grok",)
    else:
        return None

    try:
        for runtime in allowed:
            if runtime == "codex":
                from app.backend_codex import CODEX_BIN
                configured_path = CODEX_BIN
            else:
                from app.backend_grok import GROK_BIN
                configured_path = GROK_BIN
            try:
                expected = _normalise_executable(configured_path)
            except (OSError, ValueError, TypeError):
                continue
            if runtime == "codex":
                if len(argv) < 3 or tuple(argv[-2:]) != ("app-server", "--stdio"):
                    continue
            else:
                if (
                    len(argv) < 4
                    or argv[-2:] != ["--always-approve", "stdio"]
                ):
                    continue

            if os.path.basename(argv[0]) in ("node", "nodejs"):
                executable_index = 1
            else:
                executable_index = 0
            if len(argv) <= executable_index:
                continue
            if _normalise_executable(argv[executable_index]) != expected:
                continue
            if runtime == "grok" and (
                len(argv) <= executable_index + 1
                or argv[executable_index + 1] != "agent"
            ):
                continue
            return runtime
    except (OSError, ValueError, TypeError):
        return None
    return None


def terminate_cli_process(pid: int, label: str | None, started_at: int = 0) -> None:
    """SIGTERM a managed CLI only after pinning and proving its process identity (#258)."""
    logger = logging.getLogger("app.session")
    if not started_at:
        logger.error(
            "refusing to signal pid %s: no recorded start time, identity cannot be proven",
            pid,
        )
        return

    pidfd: int | None = None
    try:
        try:
            pidfd = os.pidfd_open(pid)
        except ProcessLookupError:
            return
        except OSError as error:
            if error.errno == errno.ESRCH:
                return
            logger.error("refusing to signal pid %s: pidfd_open failed: %s", pid, error)
            return

        try:
            with open(f"/proc/{pid}/cmdline", "rb") as fh:
                raw_cmdline = fh.read()
            argv = [os.fsdecode(part) for part in raw_cmdline.split(b"\0") if part]
            if not argv:
                raise ValueError("empty /proc cmdline")
            actual_start = process_start_time(pid)
        except ProcessLookupError:
            return
        except (OSError, UnicodeError, ValueError, IndexError) as error:
            logger.error("refusing to signal pid %s: /proc identity read failed: %s", pid, error)
            return

        if not actual_start:
            logger.error("refusing to signal pid %s: process start time is unavailable", pid)
            return
        if actual_start != started_at:
            logger.error(
                "refusing to signal pid %s: start time %s != recorded %s — the pid was reused",
                pid, actual_start, started_at,
            )
            return
        runtime = _runtime_argv(argv, label)
        if runtime is None:
            logger.error(
                "refusing to signal pid %s: argv does not match a managed runtime (%r)",
                pid, argv[:12],
            )
            return
        try:
            signal.pidfd_send_signal(pidfd, signal.SIGTERM)
        except ProcessLookupError:
            return
        except OSError as error:
            if error.errno == errno.ESRCH:
                return
            logger.error("could not terminate adopted CLI pid %s through pidfd: %s", pid, error)
            return
        logger.info("%s: replaced adopted CLI, sent SIGTERM to pid %s", runtime, pid)
    except Exception as error:
        logger.error("refusing to signal pid %s: identity verification failed: %s", pid, error)
    finally:
        if pidfd is not None:
            try:
                os.close(pidfd)
            except OSError as error:
                logger.error("could not close pidfd for pid %s: %s", pid, error)


def process_start_time(pid: int) -> int:
    """Field 22 of /proc/<pid>/stat — the only cheap way to tell a reused pid apart."""
    try:
        with open(f"/proc/{pid}/stat", "rb") as fh:
            raw = fh.read().decode("utf-8", "replace")
    except OSError:
        return 0
    tail = raw.rpartition(")")[2].split()
    try:
        return int(tail[19]) if len(tail) > 19 else 0
    except (ValueError, IndexError):
        return 0
