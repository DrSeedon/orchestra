"""OpenCodeBackend — wraps an `opencode serve` daemon (HTTP + SSE) as a BackendLike.

Shape: Codex-like managed subprocess (one turn per send, native cost in the chat
response) but with Claude-like streaming richness delivered over a SEPARATE global
SSE bus (`GET /event`) rather than inline. The hard part is coordinating two sources:
the SSE stream (incremental parts) and the awaited chat POST (authoritative final
cost/tokens). `session.idle` is the turn boundary.

We talk to the daemon with plain httpx (not the opencode-ai SDK): the SDK's pydantic
event types silently drop `reasoning`/`message.part.delta`/unknown events, and we need
raw-dict fidelity. httpx is already a dependency.
"""

import asyncio
import contextlib
import json
import logging
import os
import shutil
import socket
from typing import AsyncIterator, Optional

import httpx

from app.events import AgentEvent

logger = logging.getLogger(__name__)

OPENCODE_BIN = shutil.which("opencode") or os.environ.get("OPENCODE_BIN", "opencode")


def _resolve_uid(val: str) -> int | None:
    """Resolve ORCHESTRA_AGENT_UID (name or numeric) to int uid."""
    try:
        return int(val)
    except ValueError:
        pass
    import pwd
    try:
        return pwd.getpwnam(val).pw_uid
    except KeyError:
        logger.warning(f"Cannot resolve uid for '{val}'")
        return None

# Native cost comes from the daemon, so no TOKEN_PRICES table — only a context map.
OPENCODE_CONTEXT_LIMITS = {
    "claude-sonnet-4-6": 200000,
    "claude-opus-4-6": 200000,
    "mimo-v2.5-free": 258000,
}
DEFAULT_CONTEXT = 200000

TURN_TIMEOUT = 1800        # hard ceiling on a single turn (s)
DAEMON_READY_TIMEOUT = 30  # wait for GET /app to return 200 (gosu startup slower)
PORT_RETRIES = 3


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


import re as _re

_XML_TAG_RE = _re.compile(r"</?(?:path|type|entries|content|output|error|result|stdout|stderr|status|exit_code)[^>]*>")


def _clean_tool_output(text: str) -> str:
    """Strip XML-like tags from OpenCode built-in tool output and truncate."""
    cleaned = _XML_TAG_RE.sub("", text).strip()
    cleaned = cleaned if cleaned else text
    if len(cleaned) > 2000:
        cleaned = cleaned[:2000] + "\n... (truncated)"
    return cleaned


def _to_opencode_mcp(servers: dict) -> dict:
    """Translate Orchestra MCP dict ({command, args, env}) → OpenCode McpLocalConfig."""
    out = {}
    for name, cfg in servers.items():
        command = [cfg["command"], *cfg.get("args", [])]
        out[name] = {
            "type": "local",
            "command": command,
            "environment": {k: str(v) for k, v in cfg.get("env", {}).items()},
            "enabled": True,
        }
    return out


class OpenCodeBackend:
    def __init__(self, model: str, cwd: str, system_prompt: str = "",
                 resume_session_id: str | None = None,
                 mcp_servers: dict | None = None,
                 is_orchestrator: bool = False,
                 provider_id: str = "anthropic"):
        # model may be "provider/modelID" or a bare modelID; split if prefixed.
        if "/" in model:
            provider_id, model = model.split("/", 1)
        self.model = model
        self.provider_id = provider_id
        self.cwd = cwd
        self.system_prompt = system_prompt
        self._mcp_servers = mcp_servers or {}
        self._is_orchestrator = is_orchestrator
        self._session_id: str | None = resume_session_id
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._port: int | None = None
        self._http: Optional[httpx.AsyncClient] = None
        self._chat_task: Optional[asyncio.Task] = None
        self._sse_response: Optional[httpx.Response] = None

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    @property
    def _base(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    # ── lifecycle ──

    async def connect(self) -> None:
        self._write_opencode_json()
        await self._start_daemon()
        self._http = httpx.AsyncClient(base_url=self._base, timeout=httpx.Timeout(TURN_TIMEOUT))
        if not self._session_id:
            resp = await self._http.post("/session", json={})
            resp.raise_for_status()
            self._session_id = resp.json()["id"]

    def _write_opencode_json(self) -> None:
        """Write opencode.json to /tmp (not workspace — secrets would be visible to client).

        Config contains API keys and internal tokens. /tmp is tmpfs in Docker,
        not visible via file browser, not persisted.
        """
        # opencode reads opencode.json from CWD — write via subprocess setuid (agent owns cwd)
        path = os.path.join(self.cwd, "opencode.json")
        config = {}
        if os.path.exists(path):
            try:
                with open(path) as f:
                    config = json.load(f)
            except (ValueError, OSError):
                logger.warning("existing opencode.json unreadable; overwriting")
                config = {}
        if self._mcp_servers:
            config["mcp"] = {**config.get("mcp", {}), **_to_opencode_mcp(self._mcp_servers)}
        config["permission"] = {"edit": "allow", "bash": "allow", "webfetch": "allow",
                                "external_directory": "allow", "doom_loop": "allow"}
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
        if base_url and not base_url.endswith("/v1"):
            base_url = base_url.rstrip("/") + "/v1"
        config["provider"] = config.get("provider", {})
        config["provider"]["openrouter"] = {
            "options": {"apiKey": api_key, **({"baseURL": base_url} if base_url else {})},
        }
        full_model = f"{self.provider_id}/{self.model}" if self.provider_id != "anthropic" else self.model
        config["model"] = f"openrouter/{full_model}"
        content = json.dumps(config, indent=2)
        raw_uid = os.environ.get("ORCHESTRA_AGENT_UID")
        uid = _resolve_uid(raw_uid) if raw_uid else None
        # Write as agent via gosu (root can't write to agent-owned dirs with cap_drop=ALL)
        raw_uid = os.environ.get("ORCHESTRA_AGENT_UID", "")
        if raw_uid:
            import subprocess as sp
            gosu = shutil.which("gosu")
            if gosu:
                sp.run([gosu, raw_uid, "tee", path], input=content.encode(), capture_output=True, check=True)
            else:
                with open(path, "w") as f:
                    f.write(content)
        else:
            with open(path, "w") as f:
                f.write(content)
        self._config_path = path

    async def _start_daemon(self) -> None:
        env = dict(os.environ)
        raw_uid = os.environ.get("ORCHESTRA_AGENT_UID")
        uid = _resolve_uid(raw_uid) if raw_uid else None
        # Use gosu for proper uid switch — preexec_fn setuid doesn't fully work
        # with Bun's posix_spawn (child inherits parent's saved-set-uid permissions)
        cmd_prefix: list[str] = []
        if uid is not None:
            cmd_prefix = ["gosu", str(uid)]
            env["HOME"] = "/workspace"
            env["XDG_DATA_HOME"] = "/workspace/.local/share"
            env["XDG_CONFIG_HOME"] = "/workspace/.config"
        last_err = None
        for attempt in range(PORT_RETRIES):
            self._port = _free_port()
            self._proc = await asyncio.create_subprocess_exec(
                *cmd_prefix, OPENCODE_BIN, "serve", "--port", str(self._port),
                "--hostname", "127.0.0.1", "--log-level", "ERROR",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                env=env, cwd=self.cwd,
            )
            if await self._wait_ready():
                return
            last_err = f"daemon not ready on port {self._port} (attempt {attempt + 1})"
            logger.warning(last_err)
            await self._kill_proc()
        raise RuntimeError(f"OpenCode daemon failed to start: {last_err}")

    def _cleanup_config(self) -> None:
        """Remove opencode.json after daemon loaded it — secrets should not persist on disk."""
        if hasattr(self, '_config_path') and self._config_path and os.path.exists(self._config_path):
            try:
                raw_uid = os.environ.get("ORCHESTRA_AGENT_UID")
                uid = _resolve_uid(raw_uid) if raw_uid else None
                if uid is not None:
                    import subprocess as sp
                    sp.run(["python3", "-c", f"import os; os.setuid({uid}); os.remove('{self._config_path}')"],
                           capture_output=True)
                else:
                    os.remove(self._config_path)
            except OSError as e:
                logger.warning(f"Failed to cleanup opencode.json: {e}")

    async def _wait_ready(self) -> bool:
        deadline = asyncio.get_event_loop().time() + DAEMON_READY_TIMEOUT
        async with httpx.AsyncClient(base_url=self._base, timeout=2) as probe:
            while asyncio.get_event_loop().time() < deadline:
                if self._proc and self._proc.returncode is not None:
                    return False  # daemon died (likely EADDRINUSE)
                try:
                    r = await probe.get("/app")
                    if r.status_code == 200:
                        return True
                except (httpx.ConnectError, httpx.ReadError, httpx.ConnectTimeout):
                    pass
                await asyncio.sleep(0.2)
        return False

    # ── messaging ──

    async def send(self, message: str) -> None:
        if not self._http or not self._session_id:
            raise RuntimeError("OpenCodeBackend not connected")
        if self._chat_task and not self._chat_task.done():
            raise RuntimeError("OpenCodeBackend turn already in progress")
        self._sse_response = await self._http.send(
            self._http.build_request("GET", "/event"),
            stream=True,
        )
        body = {
            "providerID": self.provider_id,
            "modelID": self.model,
            "parts": [{"type": "text", "text": message}],
        }
        if self.system_prompt:
            body["system"] = self.system_prompt
        url = f"/session/{self._session_id}/message"
        self._chat_task = asyncio.ensure_future(self._post_chat(url, body))

    async def _post_chat(self, url: str, body: dict) -> dict:
        assert self._http is not None
        resp = await self._http.post(url, json=body)
        resp.raise_for_status()
        return resp.json()

    async def events(self) -> AsyncIterator[AgentEvent]:
        if not self._http:
            return
        # Wait for send() which opens SSE + fires chat task
        for i in range(300):
            if self._chat_task and self._sse_response:
                break
            await asyncio.sleep(0.1)
        if not self._chat_task or not self._sse_response:
            return
        # Snapshot the task: a concurrent disconnect() may null self._chat_task while
        # this iterator runs — work with the local so we never hit AttributeError.
        chat_task = self._chat_task
        seen_use: set[str] = set()
        seen_result: set[str] = set()
        emitted_len: dict[str, int] = {}   # per-part-id text already emitted (suffix-only)
        sse = self._sse_lines()
        next_line: Optional[asyncio.Future] = None
        error_out: str | None = None       # non-None → yield error_turn_end(error_out) after cleanup
        normal_end = False                  # True → yield turn_end from chat result
        last_meaningful = asyncio.get_event_loop().time()
        INACTIVITY_TIMEOUT = 30  # force turn_end if only heartbeats for 30s
        try:
            while True:
                next_line = asyncio.ensure_future(sse.__anext__())
                done, _ = await asyncio.wait(
                    {next_line, chat_task},
                    timeout=TURN_TIMEOUT, return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    await self.interrupt()
                    error_out = "turn_timeout"
                    break
                if next_line in done:
                    try:
                        raw = next_line.result()
                    except StopAsyncIteration:
                        normal_end = True
                        break
                    except Exception as e:
                        yield AgentEvent("error", f"sse read failed: {e}")
                        error_out = f"sse_failed: {e}"
                        break
                    evt = self._parse_sse(raw)
                    if evt is None:
                        continue
                    props = evt.get("properties") or {}
                    evt_sid = props.get("sessionID")
                    if evt_sid and evt_sid != self._session_id:
                        continue
                    if not evt_sid:
                        # Global event (heartbeat) — check inactivity
                        if chat_task.done() and (asyncio.get_event_loop().time() - last_meaningful) > INACTIVITY_TIMEOUT:
                            logger.info(f"SSE inactivity timeout ({INACTIVITY_TIMEOUT}s) — chat done, forcing turn_end")
                            normal_end = True
                            break
                        continue
                    t = evt.get("type", "")
                    if t == "message.part.updated":
                        last_meaningful = asyncio.get_event_loop().time()
                        for e in self._map_part(props.get("part") or {},
                                                seen_use, seen_result, emitted_len):
                            yield e
                    elif t == "file.edited":
                        last_meaningful = asyncio.get_event_loop().time()
                        yield AgentEvent("file_change", f"update {props.get('file', '')}")
                    elif t == "session.error":
                        err = props.get("error")
                        yield AgentEvent("error", json.dumps(err) if err else "session error")
                        normal_end = True
                        break
                    elif t == "session.idle":
                        normal_end = True
                        break
                    # else: status/diff/plugin → ignore
                else:
                    # chat task finished before SSE idle — wait up to 10s for SSE to catch up
                    if chat_task.cancelled():
                        error_out = "chat_cancelled"
                        break
                    exc = chat_task.exception()
                    if exc:
                        yield AgentEvent("error", str(exc))
                        error_out = f"chat_failed: {exc}"
                        break
                    # Drain remaining SSE events for up to 10s before falling through to turn_end
                    deadline = asyncio.get_event_loop().time() + 10
                    while asyncio.get_event_loop().time() < deadline:
                        try:
                            line_fut = asyncio.ensure_future(sse.__anext__())
                            done2, _ = await asyncio.wait({line_fut}, timeout=max(0, deadline - asyncio.get_event_loop().time()))
                            if not done2:
                                line_fut.cancel()
                                with contextlib.suppress(BaseException):
                                    await line_fut
                                break
                            try:
                                raw2 = line_fut.result()
                            except StopAsyncIteration:
                                break
                            except Exception:
                                break
                            evt2 = self._parse_sse(raw2)
                            if evt2:
                                props2 = evt2.get("properties") or {}
                                if props2.get("sessionID") == self._session_id:
                                    t2 = evt2.get("type", "")
                                    if t2 == "message.part.updated":
                                        for ev in self._map_part(props2.get("part") or {}, seen_use, seen_result, emitted_len):
                                            yield ev
                                    elif t2 == "session.idle":
                                        break
                        except Exception:
                            break
                    normal_end = True
                    break
        finally:
            # Close the SSE generator. A pending __anext__ must be awaited-after-cancel
            # FIRST, else gen.aclose() raises "asynchronous generator is already running".
            if next_line is not None:
                next_line.cancel()
                with contextlib.suppress(BaseException):
                    await next_line
            aclose = getattr(sse, "aclose", None)
            if aclose is not None:
                with contextlib.suppress(BaseException):
                    await aclose()
            # Reap the chat task UNLESS the normal path will await it below. Covers
            # consumer-closed-generator, SSE failure, timeout, cancel, error_out — so
            # the task never leaks / logs "Task was destroyed".
            if not normal_end and not chat_task.done():
                chat_task.cancel()
                with contextlib.suppress(BaseException):
                    await chat_task

        if error_out is not None:
            self._chat_task = None
            self._sse_response = None
            yield self._error_turn_end(error_out)
            return
        if normal_end:
            # BaseException catch: a concurrent cancel makes wait_for raise
            # CancelledError (BaseException) — must still yield exactly one turn_end.
            if chat_task.cancelled():
                yield self._error_turn_end("chat_cancelled")
                return
            try:
                msg = await asyncio.wait_for(chat_task, timeout=10)
            except asyncio.CancelledError:
                yield self._error_turn_end("chat_cancelled")
                return
            except Exception as e:
                yield self._error_turn_end(f"chat_await_failed: {e}")
                return
            yield self._turn_end(msg)
        # Reset per-turn state so next events() call waits for new send()
        self._chat_task = None
        self._sse_response = None

    async def _sse_lines(self) -> AsyncIterator[str]:
        if not self._sse_response:
            return
        try:
            async for line in self._sse_response.aiter_lines():
                if line:
                    yield line
        finally:
            await self._sse_response.aclose()
            self._sse_response = None

    @staticmethod
    def _parse_sse(line: str) -> dict | None:
        if line.startswith("data:"):
            line = line[5:].strip()
        if not line:
            return None
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return None

    def _map_part(self, part: dict, seen_use: set, seen_result: set,
                  emitted_len: dict) -> list[AgentEvent]:
        events: list[AgentEvent] = []
        ptype = part.get("type")
        if ptype in ("text", "reasoning"):
            # part.updated for a text/reasoning part fires multiple times with the
            # CUMULATIVE text (empty → full). Emit only the new suffix per part id so
            # the transcript never duplicates a growing prefix.
            if part.get("synthetic"):
                return events
            text = part.get("text") or ""
            etype = "text" if ptype == "text" else "thinking"
            pid = part.get("id")
            if not pid:
                # No stable id → can't safely dedupe by offset; emit as-is.
                if text:
                    events.append(AgentEvent(etype, text))
                return events
            prev = emitted_len.get(pid, 0)
            if len(text) > prev:
                events.append(AgentEvent(etype, text[prev:]))
                emitted_len[pid] = len(text)
        elif ptype == "tool":
            cid = part.get("callID", "")
            state = part.get("state", {})
            status = state.get("status", "")
            tool = part.get("tool", "")
            if cid and cid not in seen_use and status in ("pending", "running", "completed", "error"):
                seen_use.add(cid)
                try:
                    inp = json.dumps(state.get("input", {}), ensure_ascii=False)
                except (TypeError, ValueError):
                    inp = str(state.get("input", ""))
                short = tool.split("_", 1)[-1] if tool.startswith("orchestra_") else tool
                events.append(AgentEvent("tool_use", f"{tool}: {inp}",
                                         metadata={"tool_name": tool, "short_name": short}))
            if status in ("completed", "error") and cid and cid not in seen_result:
                seen_result.add(cid)
                out = state.get("output", "") if status == "completed" else state.get("error", "")
                out = _clean_tool_output(str(out))
                events.append(AgentEvent("tool_result", out))
        # step-start / step-finish / file / snapshot / patch → no AgentEvent
        return events

    def _turn_end(self, msg: dict) -> AgentEvent:
        info = msg.get("info", {})
        tok = info.get("tokens", {}) or {}
        cache = tok.get("cache", {}) or {}
        input_t = int(tok.get("input", 0) or 0)
        output_t = int(tok.get("output", 0) or 0)
        cache_read = int(cache.get("read", 0) or 0)
        cache_create = int(cache.get("write", 0) or 0)
        max_tokens = OPENCODE_CONTEXT_LIMITS.get(self.model, DEFAULT_CONTEXT)
        cache_total = cache_read + cache_create
        cost = float(info.get("cost", 0) or 0)
        err = info.get("error")
        stop_reason = info.get("finish", "end_turn") if err is None else "error"
        return AgentEvent("turn_end", f"stop_reason={stop_reason}", metadata={
            "session_id": self._session_id,
            "ok": err is None,
            "stop_reason": stop_reason,
            "num_turns": 1,
            "cost_usd": cost,
            "cost_usd_cached": cost,
            "context_pct": min(100, int(input_t * 100 / max_tokens)) if max_tokens else 0,
            "context_tokens": input_t,
            "max_tokens": max_tokens,
            "cache_hit": int(cache_read * 100 / cache_total) if cache_total else 0,
            "cache_read": cache_read,
            "cache_create": cache_create,
            "input_tokens": input_t,
            "output_tokens": output_t,
            "cached_input_tokens": cache_read,
        })

    def _error_turn_end(self, reason: str) -> AgentEvent:
        return AgentEvent("turn_end", f"stop_reason={reason}", metadata={
            "session_id": self._session_id,
            "ok": False,
            "stop_reason": reason,
            "cost_usd": 0,
            "cost_usd_cached": 0,
            "context_pct": 0,
            "context_tokens": 0,
            "max_tokens": OPENCODE_CONTEXT_LIMITS.get(self.model, DEFAULT_CONTEXT),
            "cache_hit": 0,
            "cache_read": 0,
            "cache_create": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cached_input_tokens": 0,
        })

    # ── teardown ──

    async def interrupt(self) -> None:
        if self._http and self._session_id:
            try:
                await asyncio.wait_for(
                    self._http.post(f"/session/{self._session_id}/abort"), timeout=3)
            except Exception as e:
                logger.warning(f"OpenCode abort failed: {e}")

    async def reconnect(self) -> None:
        await self.disconnect()
        await asyncio.sleep(1)
        await self.connect()

    async def disconnect(self) -> None:
        try:
            await asyncio.wait_for(self.interrupt(), timeout=3)
        except Exception:
            pass
        # Reap an in-flight chat task so it doesn't leak / log "Task was destroyed".
        # suppress BaseException — cancel() makes the await raise CancelledError.
        if self._chat_task and not self._chat_task.done():
            self._chat_task.cancel()
            with contextlib.suppress(BaseException):
                await self._chat_task
        elif self._chat_task and self._chat_task.done():
            with contextlib.suppress(BaseException):
                self._chat_task.exception()   # retrieve to silence unhandled-exception warning
        self._chat_task = None
        if self._sse_response:
            with contextlib.suppress(Exception):
                await self._sse_response.aclose()
            self._sse_response = None
        if self._http:
            try:
                await asyncio.wait_for(self._http.aclose(), timeout=3)
            except Exception:
                pass
            self._http = None
        await self._kill_proc()

    async def _kill_proc(self) -> None:
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._proc.kill()
                await self._proc.wait()   # reap — no zombie
        self._proc = None
