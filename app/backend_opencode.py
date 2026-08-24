"""OpenCodeBackend — wraps an `opencode serve` daemon (HTTP + SSE) as a BackendLike.

Shape: Codex-like managed subprocess (one turn per send) with Claude-like streaming
richness over a SEPARATE global SSE bus (`GET /event`).

Turn boundary = polling `GET /session/status` (authoritative daemon state), NOT the SSE
`session.idle` event. Rationale (task #97): the SSE bus is global with 30s heartbeats and
frequently MISSES `session.idle`; combined with a chat POST that could hang forever, the
turn never ended → orchestrator stuck `running` for 11h in prod. A direct status query
cannot be "missed" the way a fire-once event can. We submit via `prompt_async` (returns
204 immediately) so a lost HTTP response can no longer strand a turn. SSE is kept ONLY for
live streaming of text/tool/reasoning parts.

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
from app.usage_contract import AggregateUsage, TurnUsage, current_context

logger = logging.getLogger(__name__)

OPENCODE_BIN = shutil.which("opencode") or os.environ.get("OPENCODE_BIN", "opencode")

# Boundary-hint sentinels yielded by _handle_sse — the caller verifies completion via
# GET /session/status rather than trusting these SSE events (which can be missed/lie).
_SESSION_IDLE = object()
_SESSION_ERR = object()


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

# Native cost comes from the daemon. This map is a direct-construction fallback;
# Orchestra passes the registered ModelSpec context limit into the backend.
OPENCODE_CONTEXT_LIMITS = {
    "claude-sonnet-4-6": 200000,
    "claude-opus-4-6": 200000,
    "mimo-v2.5-free": 258000,
}
DEFAULT_CONTEXT = 200000

DAEMON_READY_TIMEOUT = 30   # wait for GET /app to return 200 (gosu startup slower)
PORT_RETRIES = 3
STATUS_POLL_INTERVAL = 3    # seconds between GET /session/status polls (boundary detection)
SUBMIT_GRACE = 20           # max wait for first busy/activity before trusting "idle" as done
STATUS_FAIL_THRESHOLD = 3   # consecutive status-poll failures before declaring the turn dead


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
                 provider_id: str = "unknown",
                 context_limit: int | None = None):
        # model may be "provider/modelID" or a bare modelID; split if prefixed.
        self._upstream_model_id = model
        if "/" in model:
            provider_id, model = model.split("/", 1)
        self.model = model
        self.provider_id = provider_id
        self._transport_provider_id = (
            "opencode" if provider_id == "opencode" else "openrouter"
        )
        self._transport_model_id = (
            model if provider_id == "opencode" else self._upstream_model_id
        )
        self._context_limit = context_limit
        self.cwd = cwd
        self.system_prompt = system_prompt
        self._mcp_servers = mcp_servers or {}
        self._is_orchestrator = is_orchestrator
        self._session_id: str | None = resume_session_id
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._port: int | None = None
        self._http: Optional[httpx.AsyncClient] = None
        self._turn_active: bool = False
        self._sse_response: Optional[httpx.Response] = None

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    def retarget_model(self, model: str) -> None:
        """Change the per-prompt route while preserving the OpenCode session."""
        if self._turn_active:
            raise RuntimeError("cannot retarget OpenCode model while a turn is active")
        try:
            from app.models import get_model_spec

            spec = get_model_spec(model)
            provider_id = spec.provider
            self._context_limit = spec.context_length
        except ValueError:
            provider_id = model.split("/", 1)[0] if "/" in model else self.provider_id
        self._upstream_model_id = model
        model_id = model
        if "/" in model:
            _, model_id = model.split("/", 1)
        self.model = model_id
        self.provider_id = provider_id
        self._transport_provider_id = (
            "opencode" if provider_id == "opencode" else "openrouter"
        )
        self._transport_model_id = (
            model_id if provider_id == "opencode" else self._upstream_model_id
        )

    @property
    def is_alive(self) -> bool:
        """Whether the OpenCode daemon is still available for the active turn."""
        return self._proc is not None and self._proc.returncode is None

    @property
    def _base(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    # ── lifecycle ──

    async def connect(self) -> None:
        try:
            await self._start_daemon()
            self._http = httpx.AsyncClient(
                base_url=self._base,
                timeout=httpx.Timeout(connect=30, read=None, write=60, pool=30),
            )
            if not self._session_id:
                resp = await self._http.post("/session", json={})
                resp.raise_for_status()
                self._session_id = resp.json()["id"]
        except Exception:
            await self.disconnect()
            raise

    def _build_inline_config(self) -> str:
        """Build highest-precedence OpenCode config without persisting API secrets."""
        config: dict = {}
        if self._mcp_servers:
            config["mcp"] = _to_opencode_mcp(self._mcp_servers)
        config["permission"] = {"edit": "allow", "bash": "allow", "webfetch": "allow",
                                "external_directory": "allow", "doom_loop": "allow"}
        base_url = os.environ.get("ANTHROPIC_BASE_URL", "")
        if base_url and not base_url.endswith("/v1"):
            base_url = base_url.rstrip("/") + "/v1"
        config["provider"] = {
            "openrouter": {
                "options": {
                    "apiKey": "{env:ANTHROPIC_API_KEY}",
                    **({"baseURL": base_url} if base_url else {}),
                },
            },
        }
        config["model"] = (
            f"{self._transport_provider_id}/{self._transport_model_id}"
        )
        return json.dumps(config)

    def _build_daemon_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["OPENCODE_CONFIG_CONTENT"] = self._build_inline_config()
        raw_uid = os.environ.get("ORCHESTRA_AGENT_UID")
        uid = _resolve_uid(raw_uid) if raw_uid else None
        if uid is not None:
            env["HOME"] = "/workspace"
            env["XDG_DATA_HOME"] = "/workspace/.local/share"
            env["XDG_CONFIG_HOME"] = "/workspace/.config"
        return env

    async def _start_daemon(self) -> None:
        env = self._build_daemon_env()
        raw_uid = os.environ.get("ORCHESTRA_AGENT_UID")
        uid = _resolve_uid(raw_uid) if raw_uid else None
        # Use gosu for proper uid switch — preexec_fn setuid doesn't fully work
        # with Bun's posix_spawn (child inherits parent's saved-set-uid permissions)
        cmd_prefix: list[str] = []
        if uid is not None:
            cmd_prefix = ["gosu", str(uid)]
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
                except (
                    httpx.ConnectError,
                    httpx.ReadError,
                    httpx.ConnectTimeout,
                    httpx.ReadTimeout,
                ):
                    pass
                await asyncio.sleep(0.2)
        return False

    # ── messaging ──

    async def send(self, message: str) -> None:
        if not self._http or not self._session_id:
            raise RuntimeError("OpenCodeBackend not connected")
        if self._turn_active:
            raise RuntimeError("OpenCodeBackend turn already in progress")
        # SSE only for live streaming of parts; turn boundary comes from status polling.
        self._sse_response = await self._http.send(
            self._http.build_request("GET", "/event"),
            stream=True,
        )
        # prompt_async returns 204 immediately — the daemon processes the turn in the
        # background, so a lost HTTP response can no longer strand us. Note: `model` is
        # NESTED here (unlike the old /message which had providerID/modelID top-level).
        body = {
            "model": {
                "providerID": self._transport_provider_id,
                "modelID": self._transport_model_id,
            },
            "parts": [{"type": "text", "text": message}],
        }
        if self.system_prompt:
            body["system"] = self.system_prompt
        try:
            resp = await self._http.post(f"/session/{self._session_id}/prompt_async", json=body)
            resp.raise_for_status()
        except Exception:
            # never leave turn_active / a half-open SSE stream set on a failed submit
            if self._sse_response is not None:
                with contextlib.suppress(Exception):
                    await self._sse_response.aclose()
                self._sse_response = None
            raise
        self._turn_active = True

    async def events(self) -> AsyncIterator[AgentEvent]:
        if not self._http:
            return
        # Wait for send() to open SSE + mark the turn active.
        for _ in range(300):
            if self._turn_active and self._sse_response:
                break
            await asyncio.sleep(0.1)
        if not self._turn_active or not self._sse_response:
            return

        seen_use: set[str] = set()
        seen_result: set[str] = set()
        emitted_len: dict[str, int] = {}   # per-part-id text already emitted (suffix-only)
        sse = self._sse_lines()
        next_line: Optional[asyncio.Task[str]] = None
        poll: Optional[asyncio.Task[None]] = None
        sse_live = True                     # False once the SSE stream ends/errors
        error_out: str | None = None        # non-None → yield error_turn_end(error_out)
        normal_end = False                  # True → build turn_end from message API

        saw_activity = False                # first busy/retry OR any SSE event for our sid
        status_fails = 0
        loop = asyncio.get_event_loop()
        start = loop.time()                  # submit grace only; not a total turn deadline
        poll_now = False                    # SSE idle hint → poll status immediately
        try:
            while True:
                if sse_live and (next_line is None or next_line.done()):
                    next_line = asyncio.ensure_future(sse.__anext__())
                if poll is None or poll.done():
                    poll = asyncio.ensure_future(asyncio.sleep(STATUS_POLL_INTERVAL))

                if poll_now:
                    pass                    # skip the wait — poll status immediately
                else:
                    waitset: set[asyncio.Task] = {poll}
                    if sse_live and next_line is not None:
                        waitset.add(next_line)
                    await asyncio.wait(waitset, return_when=asyncio.FIRST_COMPLETED)

                # ── SSE line (live streaming) ──
                if sse_live and next_line is not None and next_line.done():
                    try:
                        raw = next_line.result()
                    except StopAsyncIteration:
                        sse_live = False    # stream closed — status polling confirms completion
                        poll_now = True
                    except Exception as e:
                        yield AgentEvent("error", f"sse read failed: {e}")
                        error_out = f"sse_failed: {e}"
                        break
                    else:
                        for ev in self._handle_sse(raw, seen_use, seen_result, emitted_len):
                            if ev is _SESSION_IDLE:
                                poll_now = True   # verify via status, don't trust SSE alone
                            elif ev is _SESSION_ERR:
                                error_out = "session_error"
                            else:
                                saw_activity = True
                                yield ev
                        if error_out:
                            break

                # ── status poll (authoritative boundary) ──
                if poll_now or poll.done():
                    poll_now = False
                    st = await self._session_status()
                    if st is None:
                        status_fails += 1
                        if status_fails >= STATUS_FAIL_THRESHOLD or self._proc_dead():
                            error_out = "status_poll_failed"
                            break
                    else:
                        status_fails = 0
                        if st in ("busy", "retry"):
                            saw_activity = True
                        elif st == "idle" and (saw_activity or loop.time() - start > SUBMIT_GRACE):
                            if not saw_activity:
                                logger.info("opencode: idle from submit with no activity — ending after grace")
                            normal_end = True
                            break
        finally:
            # Cancel pending futures, close SSE, and ALWAYS clear per-turn state — a
            # cancel/close mid-events() must not leave _turn_active stuck (else the next
            # send() raises "turn already in progress"). A pending __anext__ must be
            # awaited-after-cancel before aclose(), or it raises "already running".
            for fut in (next_line, poll):
                if fut is not None and not fut.done():
                    fut.cancel()
                    with contextlib.suppress(BaseException):
                        await fut
            aclose = getattr(sse, "aclose", None)
            if aclose is not None:
                with contextlib.suppress(BaseException):
                    await aclose()
            self._turn_active = False
            self._sse_response = None

        # ── terminal turn_end (exactly one, on every path) ──
        if error_out is not None:
            yield self._error_turn_end(error_out)
            return
        if normal_end:
            try:
                msg = await self._fetch_last_message()
            except Exception as e:
                yield self._error_turn_end(f"message_fetch_failed: {e}")
                return
            if not msg:
                yield self._error_turn_end("no_assistant_message")
                return
            yield self._turn_end(msg)

    def _handle_sse(self, raw: str, seen_use: set, seen_result: set,
                    emitted_len: dict) -> "list":
        """Parse one SSE line → list of AgentEvent for our session, plus the sentinels
        _SESSION_IDLE / _SESSION_ERR (boundary hints — the caller verifies via status)."""
        evt = self._parse_sse(raw)
        if evt is None:
            return []
        props = evt.get("properties") or {}
        evt_sid = props.get("sessionID")
        if not evt_sid:
            return []                       # global heartbeat — irrelevant to the boundary
        if evt_sid != self._session_id:
            return []                       # another session's event
        t = evt.get("type", "")
        if t == "message.part.updated":
            return self._map_part(props.get("part") or {}, seen_use, seen_result, emitted_len)
        if t == "file.edited":
            return [AgentEvent("file_change", f"update {props.get('file', '')}")]
        if t == "session.error":
            err = props.get("error")
            return [AgentEvent("error", json.dumps(err) if err else "session error"),
                    _SESSION_ERR]
        if t == "session.idle":
            return [_SESSION_IDLE]
        return []                           # status/diff/plugin/step → ignore

    async def _session_status(self) -> str | None:
        """GET /session/status → 'idle' | 'busy' | 'retry'; None on httpx failure.

        The endpoint lists ONLY busy/retry sessions, so our session being ABSENT means
        idle. None (connection error) is NOT idle — the caller tolerates transient fails.
        """
        if not self._http or not self._session_id:
            return None
        try:
            r = await self._http.get("/session/status", timeout=5)
            if r.status_code != 200:
                return None
            data = r.json()
        except Exception:
            return None
        entry = data.get(self._session_id) if isinstance(data, dict) else None
        if not entry:
            return "idle"
        return entry.get("type", "idle")

    async def _fetch_last_message(self) -> dict | None:
        """GET /session/{id}/message → the last assistant message (for turn_end cost/tokens).

        Normalizes both shapes the endpoint may return: a flat AssistantMessage, or
        {info, parts}. Returns None if no assistant message exists.
        """
        if not self._http or not self._session_id:
            return None
        r = await self._http.get(f"/session/{self._session_id}/message", timeout=10)
        r.raise_for_status()
        msgs = r.json()
        if not isinstance(msgs, list):
            return None
        for m in reversed(msgs):
            info = m.get("info") if isinstance(m.get("info"), dict) else m
            if info.get("role") == "assistant":
                return m
        return None

    def _proc_dead(self) -> bool:
        return self._proc is not None and self._proc.returncode is not None

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
        # message endpoint returns {info, parts} OR a flat AssistantMessage — normalize.
        nested = msg.get("info")
        info: dict = nested if isinstance(nested, dict) else msg
        tok = info.get("tokens", {}) or {}
        cache = tok.get("cache", {}) or {}
        input_t = int(tok.get("input", 0) or 0)
        output_t = int(tok.get("output", 0) or 0)
        cache_read = int(cache.get("read", 0) or 0)
        cache_create = int(cache.get("write", 0) or 0)
        max_tokens = (
            self._context_limit
            or OPENCODE_CONTEXT_LIMITS.get(self.model, DEFAULT_CONTEXT)
        )
        cache_total = cache_read + cache_create
        cost = float(info.get("cost", 0) or 0)
        err = info.get("error")
        stop_reason = info.get("finish", "end_turn") if err is None else "error"
        turn_usage = TurnUsage(
            AggregateUsage.normalized(
                input_tokens=input_t,
                output_tokens=output_t,
                cache_read_tokens=cache_read,
                cache_create_tokens=cache_create,
                model_calls=1,
            ),
            current_context(input_t, max_tokens),
        )
        return AgentEvent("turn_end", f"stop_reason={stop_reason}", metadata={
            "session_id": self._session_id,
            "ok": err is None,
            "stop_reason": stop_reason,
            "num_turns": 1,
            "cost_usd": cost,
            "cost_usd_cached": cost,
            "cache_hit": int(cache_read * 100 / cache_total) if cache_total else 0,
            **turn_usage.metadata(),
        }, usage=turn_usage)

    def _error_turn_end(self, reason: str) -> AgentEvent:
        max_tokens = (
            self._context_limit
            or OPENCODE_CONTEXT_LIMITS.get(self.model, DEFAULT_CONTEXT)
        )
        turn_usage = TurnUsage(
            AggregateUsage.normalized(),
            current_context(
                None,
                max_tokens,
                unknown_reason="OpenCode turn failed before reporting current context",
            ),
        )
        return AgentEvent("turn_end", f"stop_reason={reason}", metadata={
            "session_id": self._session_id,
            "ok": False,
            "stop_reason": reason,
            "cost_usd": 0,
            "cost_usd_cached": 0,
            "cache_hit": 0,
            **turn_usage.metadata(),
        }, usage=turn_usage)

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
        # No chat task to reap — prompt_async is fire-and-forget (awaited in send()), and
        # the events() loop owns SSE cleanup + _turn_active reset via its finally block.
        self._turn_active = False
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
