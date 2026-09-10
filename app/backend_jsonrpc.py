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
import contextlib
import json
import os
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

    # Current-generation pipe transports shared by Codex and Grok.
    _owned_reader: Optional[asyncio.StreamReader] = None
    _owned_writer: Optional[asyncio.StreamWriter] = None
    _owned_read_transport = None

    @property
    def _out(self) -> Optional[asyncio.StreamReader]:
        if self._owned_reader is not None:
            return self._owned_reader
        return self._proc.stdout if self._proc else None

    @property
    def _in(self):
        if self._owned_writer is not None:
            return self._owned_writer
        return self._proc.stdin if self._proc else None

    @property
    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.returncode is None


    @property
    def pid(self) -> Optional[int]:
        """PID of this generation's child process."""
        return self._proc.pid if self._proc is not None else None


    @staticmethod
    def new_child_pipes() -> tuple[int, int, int, int]:
        """Two pipe pairs: the CLI's stdin/stdout ends, and the two ends we keep (#237 T1).

        Returned as ``(child_stdin, child_stdout, our_stdin_side, our_stdout_side)``. The
        caller passes the first two to the spawn as numeric descriptors and MUST close them
        afterwards — the child has its own copies by then, and holding ours open would keep
        the CLI from ever seeing EOF.
        """
        child_stdin, our_stdin_side = os.pipe()   # us -> CLI
        our_stdout_side, child_stdout = os.pipe()  # CLI -> us
        return child_stdin, child_stdout, our_stdin_side, our_stdout_side

    async def attach_owned_pipes(self, fd_in: int, fd_out: int, *, limit: int) -> None:
        """Drive our ends of a spawned CLI's pipes through this event loop (#237 T1).

        Both descriptors become OURS the moment this is called, success or failure — the
        caller must not close them afterwards. Halfway through, `fd_out` already belongs to a
        live read transport while `fd_in` does not, and an outside cleanup cannot tell the
        two apart. Closing the wrong one is worse than leaking it: uvloop hands the freed
        number straight to its next internal descriptor, and the transport reads a
        different file (measured in #237 — `fd 13` came back as `/dev/null`).
        """
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader(limit=limit)
        read_file = os.fdopen(fd_out, "rb", 0)
        read_transport = None
        try:
            read_transport, _read_protocol = await loop.connect_read_pipe(
                lambda: asyncio.StreamReaderProtocol(reader), read_file
            )
            write_transport, protocol = await loop.connect_write_pipe(
                asyncio.streams.FlowControlMixin, os.fdopen(fd_in, "wb", 0)
            )
        except BaseException:
            # Close through whoever owns it now, not by descriptor number.
            with contextlib.suppress(Exception):
                read_transport.close() if read_transport is not None else read_file.close()
            raise
        self._owned_reader = reader
        self._owned_writer = asyncio.StreamWriter(write_transport, protocol, reader, loop)
        self._owned_read_transport = read_transport

    async def teardown_owned_pipes(self) -> None:
        """Close both ends of this generation's transport.

        Closing goes through the transports, never `os.close`: `os.fdopen` gave them the
        descriptor, and closing it twice surfaces as EBADF inside an unrelated later test.
        `close()` only SCHEDULES the real close, so this yields until it has run — otherwise
        the moment a descriptor is released is decided by the scheduler, and a replacement
        CLI can be spawned while the previous generation's ends are still open.
        """
        writer, read_transport = self._owned_writer, self._owned_read_transport
        self._owned_writer = None
        self._owned_reader = None
        self._owned_read_transport = None
        if writer is not None:
            with contextlib.suppress(Exception):
                writer.close()
        if read_transport is not None:
            with contextlib.suppress(Exception):
                read_transport.close()
        if writer is not None or read_transport is not None:
            await asyncio.sleep(0)


    async def _request(self, method: str, params: dict | None) -> dict:
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
