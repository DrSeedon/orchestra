"""MCPClient — connects to MCP stdio servers, exposes their tools to the loop.

Pure asyncio JSON-RPC 2.0 over stdio. NO `mcp` SDK, NO anyio — on purpose: the SDK's
`stdio_client` is an anyio task group, and holding it across connect()/disconnect() that
run in DIFFERENT asyncio tasks raises "Attempted to exit cancel scope in a different task",
which during cancellation escapes and kills the uvicorn event loop (clean exit 0). See
docs/tasks/106/research.md. Without anyio there are no cancel scopes: cross-task close is a
non-event, and a dead subprocess just fails in-flight requests → tool-error strings.

MCP stdio transport = newline-delimited JSON-RPC 2.0 on stdin/stdout; server logs on stderr
(we DEVNULL it). Handshake: initialize → notifications/initialized → tools/list → tools/call.

Tool schemas are translated to OpenAI function-format WITHOUT a name prefix (role prompts
reference bare names like `spawn_worker`). Duplicate tool names across servers are a hard
error (the model cannot disambiguate). connect() is atomic on hard errors: it stops every
started child and clears state before re-raising, so the backend can fall back to built-ins
with nothing leaked.
"""

import asyncio
import contextlib
import json
import logging
import os
import signal

logger = logging.getLogger(__name__)

CALL_TIMEOUT = 120            # seconds per tool call
INIT_TIMEOUT = 30            # seconds per-server handshake
TERM_GRACE = 3              # SIGTERM → wait → SIGKILL
STDIO_LIMIT = 16 * 1024 * 1024  # one JSON-RPC record; fail loud above this bound
PROTOCOL_VERSION = "2025-06-18"


class MCPError(Exception):
    """A JSON-RPC error envelope returned by a server (turned into a tool-error string)."""


class _Server:
    """One stdio child process and its JSON-RPC plumbing."""

    def __init__(self, name: str, cfg: dict) -> None:
        self.name = name
        self.cfg = cfg
        self.tools: list[dict] = []           # this server's tools/list entries
        self.proc: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._next_id = 0
        self._alive = False

    async def start(self) -> None:
        env = {**os.environ, **(self.cfg.get("env") or {})}
        self.proc = await asyncio.create_subprocess_exec(
            self.cfg["command"], *(self.cfg.get("args") or []),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,   # server logs to stderr; drop to avoid pipe-fill block
            env={k: str(v) for k, v in env.items()},
            start_new_session=True,              # own process group → killpg can reap grandchildren
            limit=STDIO_LIMIT,
        )
        self._alive = True
        self._reader = asyncio.create_task(self._read_loop())
        await self._handshake()

    async def _handshake(self) -> None:
        await self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "orchestra-harness", "version": "1"},
        }, INIT_TIMEOUT)
        self._notify("notifications/initialized", {})

    async def list_tools(self) -> list[dict]:
        result = await self._request("tools/list", {}, INIT_TIMEOUT)
        self.tools = result.get("tools", []) if isinstance(result, dict) else []
        return self.tools

    async def call_tool(self, name: str, args: dict) -> dict:
        return await self._request(
            "tools/call", {"name": name, "arguments": args}, CALL_TIMEOUT)

    def alive(self) -> bool:
        return bool(self._alive and self.proc and self.proc.returncode is None)

    def _notify(self, method: str, params: dict) -> None:
        if not self.proc or self.proc.stdin is None:
            return
        with contextlib.suppress(Exception):
            line = json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n"
            self.proc.stdin.write(line.encode())

    async def _request(self, method: str, params: dict, timeout: float) -> dict:
        if not self.proc or self.proc.stdin is None:
            raise ConnectionError(f"MCP server '{self.name}' not started")
        self._next_id += 1
        req_id = self._next_id
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[req_id] = fut
        msg = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        # finally always drops the pending entry — a write/drain failure (dead stdin),
        # a timeout, or a caller cancellation must never leak a future (it would either
        # linger until EOF or raise "exception never retrieved" in the reader's finalizer).
        try:
            self.proc.stdin.write((json.dumps(msg) + "\n").encode())
            await self.proc.stdin.drain()
            envelope = await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(req_id, None)
        # Envelope handling in ONE place: error → raise, else return the bare result.
        if isinstance(envelope, dict) and envelope.get("error") is not None:
            raise MCPError(_fmt_jsonrpc_error(envelope["error"]))
        return envelope.get("result", {}) if isinstance(envelope, dict) else {}

    async def _read_loop(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        failure: Exception | None = None
        try:
            while True:
                line = await self.proc.stdout.readline()
                if not line:               # EOF — subprocess closed stdout / died
                    break
                try:
                    msg = json.loads(line)
                except (ValueError, TypeError) as exc:
                    raise MCPError(
                        f"MCP server '{self.name}' emitted invalid JSON: "
                        f"{line[:160].decode(errors='replace')}"
                    ) from exc
                req_id = msg.get("id") if isinstance(msg, dict) else None
                fut = self._pending.pop(req_id, None) if req_id is not None else None
                if fut is not None and not fut.done():
                    fut.set_result(msg)
                # messages without a known id (server-initiated requests/notifications) → ignore
        except Exception as e:             # reader must never crash the loop
            failure = e
            logger.warning(f"MCP '{self.name}' read loop error: {e}")
        finally:
            self._alive = False
            detail = f": {failure}" if failure is not None else ""
            err = ConnectionError(f"MCP server '{self.name}' closed{detail}")
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(err)
            self._pending.clear()

    async def stop(self) -> None:
        self._alive = False
        if self._reader is not None:
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reader
            self._reader = None
        if self.proc is not None and self.proc.returncode is None:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            try:
                await asyncio.wait_for(self.proc.wait(), TERM_GRACE)
            except asyncio.TimeoutError:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGKILL)
                # bounded wait — if killpg missed (wrong pgid/PermissionError) never hang teardown
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(self.proc.wait(), TERM_GRACE)


class MCPClient:
    def __init__(self) -> None:
        self._servers: dict[str, _Server] = {}    # server name → _Server
        self._tool_server: dict[str, str] = {}    # tool name → server name
        self._schemas: list[dict] = []
        self._reconnect_locks: dict[str, asyncio.Lock] = {}   # one per server name

    async def connect(self, servers: dict) -> None:
        """Spawn + initialize every server. A single bad server is skipped (non-fatal); a
        STRUCTURAL error (duplicate tool name) tears the whole MCP layer down and re-raises
        so the backend can fall back to built-ins with nothing leaked."""
        try:
            for name, cfg in (servers or {}).items():
                srv = _Server(name, cfg)
                try:
                    await srv.start()
                    await srv.list_tools()
                except Exception as e:        # one server failing to start is non-fatal
                    logger.warning(f"MCP server '{name}' failed to start: {e}")
                    await srv.stop()
                    continue
                try:
                    self._register(srv)       # raises on duplicate tool name
                except Exception:
                    await srv.stop()          # this srv isn't in _servers yet — stop it here
                    raise                     # → outer handler tears down the rest
        except Exception:
            await self.disconnect()           # atomic: stop ALL registered, clear state
            raise

    def _register(self, srv: _Server) -> None:
        for tool in srv.tools:
            name = tool.get("name", "")
            if name in self._tool_server:
                raise ValueError(
                    f"duplicate MCP tool name '{name}' (server '{srv.name}' collides with "
                    f"'{self._tool_server[name]}')")
            self._tool_server[name] = srv.name
            self._schemas.append(_to_openai_schema(tool))
        self._servers[srv.name] = srv

    def _rebuild_registry(self) -> None:
        """Recompute tool→server and schemas from all live servers (after a reconnect swaps
        one server's tools). Re-validates duplicate names across servers. ATOMIC: builds into
        temporaries and commits only on success, so a duplicate-name error never leaves a
        half-rebuilt registry."""
        tool_server: dict[str, str] = {}
        schemas: list[dict] = []
        for srv in self._servers.values():
            for tool in srv.tools:
                name = tool.get("name", "")
                if name in tool_server:
                    raise ValueError(
                        f"duplicate MCP tool name '{name}' after reconnect "
                        f"(server '{srv.name}' collides with '{tool_server[name]}')")
                tool_server[name] = srv.name
                schemas.append(_to_openai_schema(tool))
        self._tool_server = tool_server
        self._schemas = schemas

    def tool_schemas(self) -> list[dict]:
        """OpenAI function-format schemas for all MCP tools (no name prefix)."""
        return list(self._schemas)

    def has_tool(self, name: str) -> bool:
        return name in self._tool_server

    async def call(self, name: str, args: dict) -> str:
        """Call an MCP tool → text content. Errors come back as strings, never raised."""
        server_name = self._tool_server.get(name)
        if server_name is None:
            return f"[mcp error] unknown tool: {name}"
        srv = self._servers.get(server_name)
        if srv is None:
            return f"[mcp error] server '{server_name}' not connected"
        if not srv.alive():
            await self._reconnect(server_name)
            srv = self._servers.get(server_name)
            if srv is None or not srv.alive():
                return f"[mcp error] server '{server_name}' is down"
        try:
            result = await srv.call_tool(name, args)
        except MCPError as e:
            return f"[mcp error] {name}: {e}"
        except Exception as e:                # subprocess death / timeout → tool error, not a crash
            logger.warning(f"MCP call '{name}' failed: {e}")
            return f"[mcp error] {name} failed: {e}"
        return _extract_text(result)

    async def _reconnect(self, name: str) -> None:
        """One-shot relaunch of a dead server. On failure, leave it dead (built-ins + other
        servers still work). Bounded — no busy-loop. A per-server lock serializes concurrent
        callers so two parallel call()s on a dead server can't spawn two children (one would
        be overwritten in _servers and leak)."""
        lock = self._reconnect_locks.setdefault(name, asyncio.Lock())
        async with lock:
            old = self._servers.get(name)
            if old is None or old.alive():     # another caller already revived it
                return
            await old.stop()
            srv = _Server(name, old.cfg)
            try:
                await srv.start()
                await srv.list_tools()
            except Exception as e:
                logger.warning(f"MCP server '{name}' reconnect failed: {e}")
                await srv.stop()
                return
            self._servers[name] = srv
            try:
                self._rebuild_registry()
            except ValueError as e:            # new tool set collides with another server
                logger.warning(f"MCP server '{name}' reconnect produced a name collision: {e}")
                await srv.stop()
                self._servers.pop(name, None)
                self._rebuild_registry()       # registry without the bad server (no dup → won't raise)

    async def disconnect(self) -> None:
        await asyncio.gather(*(s.stop() for s in self._servers.values()),
                             return_exceptions=True)
        self._servers.clear()
        self._tool_server.clear()
        self._schemas.clear()


def _to_openai_schema(tool: dict) -> dict:
    """MCP Tool (name/description/inputSchema JSON Schema) → OpenAI function-format."""
    params = tool.get("inputSchema") or {"type": "object", "properties": {}}
    return {
        "type": "function",
        "function": {
            "name": tool.get("name", ""),
            "description": tool.get("description") or "",
            "parameters": params,
        },
    }


def _fmt_jsonrpc_error(error) -> str:
    if isinstance(error, dict):
        msg = error.get("message", "error")
        code = error.get("code")
        return f"{msg} (code {code})" if code is not None else str(msg)
    return str(error)


def _extract_text(result: dict) -> str:
    """Pull text out of a tools/call result. Concatenate text content blocks; for non-text
    content (images/embedded resources) fall back to a short marker. An MCP-level error
    result (isError) is returned as an error string."""
    parts: list[str] = []
    for block in (result.get("content") if isinstance(result, dict) else None) or []:
        if not isinstance(block, dict):
            continue
        text = block.get("text")
        if text is not None:
            parts.append(text)
        else:
            parts.append(f"[{block.get('type', 'content')}]")
    out = "\n".join(parts).strip()
    if isinstance(result, dict) and result.get("isError"):
        return f"[mcp error] {out}" if out else "[mcp error] tool returned an error"
    return out if out else "(no output)"
