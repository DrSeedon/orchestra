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
import json
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

    @property
    def is_alive(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def _request(self, method: str, params: dict) -> dict:
        if not self._proc or not self._proc.stdin or self._proc.returncode is not None:
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
        if not self._proc or not self._proc.stdin:
            raise RuntimeError(f"{self.RUNTIME_LABEL} stdin is unavailable")
        encoded = (json.dumps(payload, ensure_ascii=False) + "\n").encode()
        async with self._write_lock:
            self._proc.stdin.write(encoded)
            await self._proc.stdin.drain()

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
