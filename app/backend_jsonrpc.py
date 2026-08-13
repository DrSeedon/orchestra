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
import json
import logging
import os
import signal
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
            return False

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
            return False
        self._quiesced_prefix = b"".join(frames)
        logging.getLogger("app.session").info(
            "handover: carried %d already-parsed event(s) forward as raw frames", len(frames),
        )
        return True

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
        self._adopted_started_at = cli_started_at or (
            process_start_time(cli_pid) if cli_pid else 0)

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
        self._adopted_writer = None
        self._adopted_reader = None
        self._adopted_fds = None
        self._adopted_pid = None
        # reset ALL adopted-generation state, so reuse and diagnostics are deterministic
        self._adopted_started_at = 0
        self._handover_quiescing = False
        self._quiesced_prefix = b""
        if pid:
            terminate_cli_process(pid, self.RUNTIME_LABEL, self._adopted_started_at)

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


def terminate_cli_process(pid: int, label: str, started_at: int = 0) -> None:
    """SIGTERM an agent CLI we are replacing, after proving it IS that CLI (#230 T9).

    Identity is pid AND process start time AND a runtime-specific marker. The pid alone is not
    an identity: pids are reused, and this project has already been burned by exactly that with
    process groups. `started_at` is field 22 of `/proc/<pid>/stat` as recorded at handover; a
    mismatch means the number now belongs to somebody else.
    """
    logger = logging.getLogger("app.session")
    marker = {"Codex app-server": "codex", "Grok": "grok"}.get(label, label.split()[0].lower())
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            cmdline = fh.read().decode("utf-8", "replace")
        actual_start = process_start_time(pid)
    except FileNotFoundError:
        return  # already gone
    except OSError as error:
        logger.warning("cannot verify pid %s before signalling: %s", pid, error)
        return
    if marker not in cmdline:
        logger.error(
            "refusing to signal pid %s: cmdline is not a %s process (%r)",
            pid, label, cmdline[:120],
        )
        return
    if started_at and actual_start and started_at != actual_start:
        logger.error(
            "refusing to signal pid %s: start time %s != recorded %s — the pid was reused",
            pid, actual_start, started_at,
        )
        return
    try:
        os.kill(pid, signal.SIGTERM)
        logger.info("%s: replaced adopted CLI, sent SIGTERM to pid %s", label, pid)
    except ProcessLookupError:
        pass
    except OSError as error:
        logger.warning("could not terminate adopted CLI pid %s: %s", pid, error)


def process_start_time(pid: int) -> int:
    """Field 22 of /proc/<pid>/stat — the only cheap way to tell a reused pid apart."""
    try:
        with open(f"/proc/{pid}/stat", "rb") as fh:
            raw = fh.read().decode("utf-8", "replace")
    except OSError:
        return 0
    tail = raw.rpartition(")")[2].split()
    return int(tail[19]) if len(tail) > 19 else 0
