"""Application-owned ACP v1 stdio transport pool per canonical OAuth HOME.

Each distinct (cwd, mcpServers) workspace signature gets an isolated `agy acp`
process under the single profile flock (matching T3 Code and avoiding `agy 1.5.9`'s
`--process-per-session` unauthenticated-worker pre-Mendel catalog race), while
sessions sharing the same signature reuse one warm daemon. Cold startup/auth is
serialized per profile; active turns are bounded by `Semaphore(3)` and per-session locks.
"""
from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import re
import signal
import sqlite3
import time
import uuid
from pathlib import Path


class AcpError(RuntimeError):
    """Locally authored, safe-to-display protocol failure (never a raw RPC body)."""


class AcpSessionError(AcpError):
    """Refused operation, with no corruption of the shared profile transport."""


_owners: dict[Path, "AcpProfile"] = {}


def auto_approve_enabled() -> bool:
    return os.environ.get("ANTIGRAVITY_AUTO_APPROVE", "1").strip() != "0"


def transport_signature(cwd: str | Path, mcp_servers: list | dict | None = None) -> str:
    return hashlib.sha256(str(Path(cwd).resolve()).encode()).hexdigest()


def cached_profile(home: Path):
    return _owners.get(Path(home).resolve())


def get_profile(home: Path):
    home = Path(home).resolve()
    owner = _owners.get(home)
    if owner is None:
        owner = _owners[home] = AcpProfile(home)
    if owner.loop is not asyncio.get_running_loop():
        raise AcpError("ACP profile belongs to another event loop")
    return owner


async def release_archived_session(home: Path, native_session_id: str | None):
    if not native_session_id:
        return
    owner = cached_profile(home)
    if owner is not None:
        await owner.release_session(native_session_id)


async def shutdown_profiles():
    owners = list(_owners.values())
    # App shutdown is the only automatic registry reset. Sessions never evict owners.
    for owner in owners:
        await owner.close("ACP application shutdown")
    _owners.clear()


class _AcpTransport:
    def __init__(self, owner: "AcpProfile", key: str):
        self.owner = owner
        self.key = key
        self.process: asyncio.subprocess.Process | None = None
        self._write_lock = asyncio.Lock()
        self._reader: asyncio.Task | None = None
        self._stderr: asyncio.Task | None = None
        self._cleanup_task: asyncio.Task | None = None
        self._next_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self.sessions: set[str] = set()
        self.active_prompts = 0
        self.last_used = time.monotonic()
        self.closing = False

    @property
    def is_alive(self) -> bool:
        return bool(not self.closing and self.process is not None and self.process.returncode is None)

    async def write(self, message, *, before_write=None, on_written=None):
        if self.owner.failure or self.closing or self.process is None or self.process.returncode is not None:
            raise AcpError(self.owner.failure or "ACP daemon unavailable")
        payload = (json.dumps(message, ensure_ascii=False) + "\n").encode()
        if len(payload) > 1024 * 1024:
            raise AcpError("ACP message exceeds 1 MiB limit")
        async with self._write_lock:
            if before_write is not None:
                await before_write()
            self.process.stdin.write(payload)
            await self.process.stdin.drain()
            self.last_used = time.monotonic()
            if on_written is not None:
                on_written()

    async def read_loop(self):
        try:
            while line := await self.process.stdout.readline():
                message = json.loads(line)
                if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                    raise AcpError("Invalid ACP envelope")
                if "id" in message:
                    rpc_id = message["id"]
                    if isinstance(rpc_id, bool) or not isinstance(rpc_id, (str, int)) or len(str(rpc_id)) > 256:
                        raise AcpError("Invalid ACP RPC identity")
                if "method" in message:
                    method, params = message["method"], message.get("params") or {}
                    if "id" in message:
                        reply = {"jsonrpc": "2.0", "id": message["id"]}
                        if method == "session/request_permission":
                            identity = f"{self.key}:{json.dumps(message['id'], sort_keys=True)}"
                            digest = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
                            if identity in self.owner._client_request_ids:
                                if self.owner._client_request_ids[identity] != digest:
                                    raise AcpError("ACP native RPC identity reused with changed payload")
                                continue
                            if len(self.owner._client_tasks) >= 16 or len(self.owner._client_request_ids) >= 4096:
                                await self.write({"jsonrpc": "2.0", "id": message["id"], "result": {"outcome": {"outcome": "cancelled"}}})
                                continue
                            self.owner._client_request_ids[identity] = digest
                            task = asyncio.create_task(self.owner._permission(self, message["id"], params))
                            self.owner._client_tasks.add(task)
                            task.add_done_callback(self.owner._client_tasks.discard)
                            continue
                        else:
                            reply["error"] = {"code": -32601, "message": "Client method unsupported"}
                        await self.write(reply)
                    elif method == "session/update":
                        sid = params.get("sessionId")
                        update = params.get("update") or {}
                        if sid in self.owner.sessions and update.get("sessionUpdate") == "config_option_update":
                            self.owner.remember_model_state(sid, update)
                        callback = self.owner.listeners.get(sid)
                        if callback:
                            callback(update)
                else:
                    future = self._pending.get(message.get("id"))
                    if future is None or future.done():
                        continue
                    if "error" in message:
                        from app import backend_antigravity as backend
                        error = message["error"]
                        banned = backend._is_account_disabled_payload(error)
                        if banned:
                            backend._trip_antigravity_circuit_breaker("ACP confirmed account-disabled/Terms-of-Service refusal")
                        local = isinstance(error, dict) and error.get("code") in {-32601, -32602} and not banned
                        refusal = AcpSessionError if local else AcpError
                        future.set_exception(refusal("ACP RPC rejected; operator recovery required"))
                    elif isinstance(message.get("result"), dict):
                        future.set_result(message["result"])
                    else:
                        raise AcpError("Invalid ACP response")
            if self.closing:
                return
            raise AcpError("ACP daemon EOF; operator recovery required")
        except asyncio.CancelledError:
            raise
        except Exception:
            if not self.closing:
                await self.owner.close("ACP stream ended/invalid; operator recovery required")

    async def drain_stderr(self):
        while await self.process.stderr.read(4096):
            pass

    async def close(self):
        self.closing = True
        reason = self.owner.failure or "ACP transport closed"
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(AcpError(reason))
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup())
        await asyncio.shield(self._cleanup_task)

    async def _cleanup(self):
        tasks = [t for t in (self._reader, self._stderr) if t]
        for task in tasks:
            task.cancel()
        if self.process is not None:
            try:
                os.killpg(self.process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(self.process.wait(), 1)
            except TimeoutError:
                pass
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await self.process.wait()
        await asyncio.gather(*tasks, return_exceptions=True)


class AcpProfile:
    request_timeout = 25.0
    prompt_timeout = 600.0

    def __init__(self, home: Path):
        self.home = home
        from app.native_requests import profile_epoch
        self.epoch = profile_epoch(home)
        self.transport_generation = uuid.uuid4().hex
        self.permission_handlers = {}
        self._client_tasks = set()
        self._client_request_ids = {}
        self.loop = asyncio.get_running_loop()
        try:
            max_turns = max(1, int(os.environ.get("ANTIGRAVITY_MAX_CONCURRENT_TURNS", "3")))
        except ValueError:
            max_turns = 3
        try:
            max_daemons = max(1, int(os.environ.get("ANTIGRAVITY_MAX_DAEMONS", "4")))
        except ValueError:
            max_daemons = 4
        self.max_concurrent_turns = max_turns
        self.max_daemons = max_daemons
        self.turn_semaphore = asyncio.Semaphore(max_turns)
        self.turn_lock = self.turn_semaphore
        self._setup_lock = asyncio.Lock()
        self.session_locks: dict[str, asyncio.Lock] = {}
        self._start_lock = asyncio.Lock()
        self._transports: dict[str, _AcpTransport] = {}
        self._session_transport: dict[str, str] = {}
        self._last_process: asyncio.subprocess.Process | None = None
        self._lock_fd = None
        self._cleanup_task = None
        self.listeners = {}
        self.sessions = set()
        self.models = set()
        self.model_states = {}
        self.cost_totals = {}
        self.capabilities = {}
        self.failure = ""

    @property
    def process(self):
        for tr in reversed(list(self._transports.values())):
            if tr.process is not None:
                return tr.process
        return self._last_process

    def is_transport_alive(self, transport_key: str | None = None) -> bool:
        if self.failure:
            return False
        if transport_key and transport_key in self._transports:
            return self._transports[transport_key].is_alive
        return any(tr.is_alive for tr in self._transports.values())

    def session_lock(self, session_id: str) -> asyncio.Lock:
        lock = self.session_locks.get(session_id)
        if lock is None:
            lock = self.session_locks[session_id] = asyncio.Lock()
        return lock

    def register_session_transport(self, session_id: str, transport_key: str) -> None:
        self._session_transport[session_id] = transport_key
        tr = self._transports.get(transport_key)
        if tr is not None:
            tr.sessions.add(session_id)

    async def release_session(self, session_id: str) -> None:
        tkey = self._session_transport.pop(session_id, None)
        self.sessions.discard(session_id)
        self.listeners.pop(session_id, None)
        self.permission_handlers.pop(session_id, None)
        if not tkey:
            return
        tr = self._transports.get(tkey)
        if tr is None:
            return
        tr.sessions.discard(session_id)
        if not tr.sessions and tr.active_prompts == 0 and not tr._pending:
            self._transports.pop(tkey, None)
            await tr.close()

    @staticmethod
    def model_state(result):
        """Keep both selector values and the peer's optional variant catalog."""
        options = result.get("configOptions") or []
        def select(category):
            return next((o for o in options if isinstance(o, dict) and
                         (o.get("category") == category or o.get("id") == category)), None)
        def values(option):
            result = set()
            for entry in (option or {}).get("options", []) or []:
                if not isinstance(entry, dict):
                    continue
                for row in ([entry] if "value" in entry else entry.get("options", []) or []):
                    if isinstance(row, dict) and isinstance(row.get("value"), str):
                        result.add(row["value"])
            return result
        option, thought = select("model"), select("thought_level")
        models = result.get("models") or {}
        legacy = {r["modelId"] for r in models.get("availableModels", []) or []
                  if isinstance(r, dict) and isinstance(r.get("modelId"), str)}
        return {"config_id": option.get("id") if option else None,
                "current": option.get("currentValue") if option else models.get("currentModelId"),
                "available": values(option) if option else legacy,
                "thought_config_id": thought.get("id") if thought else None,
                "current_thought": thought.get("currentValue") if thought else None,
                "thought_available": values(thought), "legacy_available": legacy,
                "model_present": option is not None or bool(models), "thought_present": thought is not None}

    @staticmethod
    def published_models(state):
        direct = set(state["available"])
        legacy = set(state.get("legacy_available", ()))
        current = state.get("current")
        if current in direct and state.get("thought_config_id") and not re.search(r"-(xhigh|high|medium|low)$", current):
            variants = {current + "-" + level for level in state["thought_available"]}
            catalog_variants = {v for v in legacy if any(v.startswith(family + "-")
                for family in direct if not re.search(r"-(xhigh|high|medium|low)$", family))}
            direct.update(variants & legacy if catalog_variants else variants)
            legacy = {v for v in legacy if not v.startswith(current + "-")}
        return direct | legacy

    def remember_model_state(self, sid, result):
        state = self.model_state(result)
        if "models" not in result and sid in self.model_states:
            state["legacy_available"] = self.model_states[sid].get("legacy_available", set())
        if not state["model_present"] and state["thought_present"] and sid in self.model_states:
            previous = self.model_states[sid]
            state = {**previous, **{k: state[k] for k in
                ("thought_config_id", "current_thought", "thought_available", "thought_present")}}
        if state["current"] is not None:
            self.model_states[sid] = state
            self.models = set().union(*(self.published_models(s) for s in self.model_states.values()))
        return state

    def _check_settings(self):
        try:
            cli = json.loads((self.home / ".gemini/antigravity-acp/settings.json").read_text())
            config = json.loads((self.home / ".gemini/config/config.json").read_text())
        except (OSError, ValueError):
            raise AcpError("ACP profile requires explicit no-credit settings") from None
        if cli.get("useG1Credits") is not False or config.get("userSettings", {}).get("useAiCredits") is not False:
            raise AcpError("ACP profile credit settings must both be false")

    def _resolve_transport(self, params: dict | None, transport_key: str) -> _AcpTransport:
        sid = (params or {}).get("sessionId") if isinstance(params, dict) else None
        key = self._session_transport.get(sid, transport_key) if isinstance(sid, str) and sid else transport_key
        tr = self._transports.get(key)
        if tr is None:
            raise AcpError(self.failure or "ACP daemon unavailable")
        return tr

    async def _evict_idle_transport_if_needed(self):
        live = [tr for tr in self._transports.values() if tr.is_alive]
        if len(live) < self.max_daemons:
            return
        idle = sorted(
            (tr for tr in live if tr.active_prompts == 0 and not tr._pending),
            key=lambda tr: tr.last_used,
        )
        if not idle:
            return
        victim = idle[0]
        self._transports.pop(victim.key, None)
        for sid in list(victim.sessions):
            self._session_transport.pop(sid, None)
            self.sessions.discard(sid)
        await victim.close()

    async def start(self, transport_key: str = "default"):
        from app import backend_antigravity as backend
        async with self._start_lock:
            if self.failure:
                raise AcpError(self.failure)
            existing = self._transports.get(transport_key)
            if existing is not None:
                if existing.process is not None and existing.process.returncode is not None:
                    await self.close("ACP daemon exited; operator recovery required")
                    raise AcpError(self.failure)
                return
            tr = _AcpTransport(self, transport_key)
            try:
                self._check_settings()
                if not backend._has_cached_credentials(self.home):
                    raise AcpError("ACP requires an existing cached login; interactive login is not supported")
                if self._lock_fd is None:
                    self._lock_fd = os.open(self.home / ".orchestra-acp.lock",
                                            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
                    fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                await self._evict_idle_transport_if_needed()
                cmd = [backend.ANTIGRAVITY_BIN, "acp", "--disable-telemetry"]
                if auto_approve_enabled():
                    cmd.append("--dangerously-skip-permissions")
                cmd.extend([
                    "--gemini-dir", str(self.home / ".gemini"),
                    "--app-data-dir", "antigravity-acp",
                ])
                tr.process = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=str(self.home), env=backend.cli_environment(self.home),
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE, start_new_session=True,
                    limit=1024 * 1024,
                )
                self._last_process = tr.process
                self._transports[transport_key] = tr
                tr._reader = asyncio.create_task(tr.read_loop())
                tr._stderr = asyncio.create_task(tr.drain_stderr())
                initialized = await self.request("initialize", {
                    "protocolVersion": 1,
                    "clientInfo": {"name": "orchestra", "version": "1"},
                    "clientCapabilities": {},
                }, transport_key=transport_key)
                if initialized.get("protocolVersion") != 1:
                    raise AcpError("Unsupported ACP protocol version")
                self.capabilities = initialized.get("agentCapabilities") or {}
                methods = initialized.get("authMethods") or []
                if methods:
                    oauth = next((m for m in methods if m.get("id") == "oauth-personal"), None)
                    if oauth is None:
                        raise AcpError("ACP cached personal OAuth method unavailable; no auth fallback")
                    await self.request("authenticate", {"methodId": oauth["id"]}, transport_key=transport_key)
            except BaseException as exc:
                self._transports.pop(transport_key, None)
                await tr.close()
                reason = str(exc) if isinstance(exc, AcpError) else "ACP startup failed; operator recovery required"
                await self.close(reason)
                raise AcpError(reason) from None

    async def _write(self, message, *, before_write=None, on_written=None, transport_key: str = "default"):
        params = message.get("params") if isinstance(message, dict) else None
        tr = self._resolve_transport(params if isinstance(params, dict) else None, transport_key)
        await tr.write(message, before_write=before_write, on_written=on_written)

    async def notify(self, method, params, *, transport_key: str = "default"):
        await self._write({"jsonrpc": "2.0", "method": method, "params": params}, transport_key=transport_key)

    async def request(self, method, params, *, timeout=None, before_write=None, on_written=None,
                      transport_key: str = "default"):
        tr = self._resolve_transport(params, transport_key)
        tr._next_id += 1
        request_id = tr._next_id
        future = self.loop.create_future()
        tr._pending[request_id] = future
        if method == "session/prompt":
            tr.active_prompts += 1
        try:
            async with asyncio.timeout(self.request_timeout if timeout is None else timeout):
                await self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
                                  before_write=before_write, on_written=on_written, transport_key=tr.key)
                return await asyncio.shield(future)
        except AcpSessionError:
            raise
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            reason = str(exc) if isinstance(exc, AcpError) else "ACP request failed/timed out; operator recovery required"
            await self.close(reason)
            raise AcpError(reason) from None
        finally:
            if method == "session/prompt":
                tr.active_prompts = max(0, tr.active_prompts - 1)
            tr._pending.pop(request_id, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()

    async def _permission(self, tr: _AcpTransport, rpc_id, params):
        from app import native_requests
        rid = None
        try:
            backend = self.permission_handlers.get(params.get("sessionId"))
            if backend is None:
                response = {"outcome": {"outcome": "cancelled"}}
            else:
                parsed = native_requests.validate_payload(params)
                if auto_approve_enabled() and parsed["kind"] == "permission":
                    if native_requests.profile_epoch(self.home) != self.epoch:
                        response = {"outcome": {"outcome": "cancelled"}}
                    else:
                        option = (next((o for o in parsed["options"] if o.get("kind") == "allow_once"), None)
                                  or next((o for o in parsed["options"] if o.get("kind") == "allow_always"), None))
                        response = ({"outcome": {"outcome": "selected", "optionId": option["optionId"]}}
                                    if option is not None else {"outcome": {"outcome": "cancelled"}})
                else:
                    result = await native_requests.request(self, rpc_id, params, backend)
                    if isinstance(result, tuple):
                        rid, response = result
                    else:
                        response = result
            await tr.write({"jsonrpc": "2.0", "id": rpc_id, "result": response})
            if rid:
                native_requests.finish(rid, "responded")
                if backend is not None:
                    from app.events import AgentEvent
                    backend._queue.put_nowait(AgentEvent("native_request_closed",
                        json.dumps({"id": rid, "state": "responded"}),
                        metadata={"item_id": "acp-native:" + rid + ":closed"}))
        except asyncio.CancelledError:
            if rid:
                native_requests.finish(rid, "stale")
            raise
        except ValueError:
            if not self.failure and not tr.closing:
                await tr.write({"jsonrpc": "2.0", "id": rpc_id, "result": {"outcome": {"outcome": "cancelled"}}})
        except Exception:
            if rid:
                native_requests.finish(rid, "unknown")
            await self.close("ACP native response failed; operator recovery required")

    async def close(self, reason):
        self.failure = self.failure or reason
        for tr in list(self._transports.values()):
            for future in list(tr._pending.values()):
                if not future.done():
                    future.set_exception(AcpError(self.failure))
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup())
        await asyncio.shield(self._cleanup_task)

    async def _cleanup(self):
        client_tasks = list(self._client_tasks)
        for task in client_tasks:
            task.cancel()
        transports = list(self._transports.values())
        self._transports.clear()
        self._session_transport.clear()
        try:
            await asyncio.gather(*(tr.close() for tr in transports), *client_tasks, return_exceptions=True)
        finally:
            if self._lock_fd is not None:
                os.close(self._lock_fd)
                self._lock_fd = None


def ensure_interactive_input(model, provenance, *, target_session=None, allow_child_agent=True):
    """User input or a verified durable direct-child report, never scheduled activation."""
    if not is_consumer_model(model):
        return
    origin = getattr(provenance, "origin", None)
    if origin == "user":
        return
    def field(value, name):
        return value.get(name) if isinstance(value, dict) else getattr(value, name, None)
    if origin == "agent" and allow_child_agent and field(target_session, "is_orchestrator"):
        from app import db
        try:
            parent = db.get_session(field(target_session, "id"))
        except sqlite3.Error:
            parent = None
        senders = getattr(provenance, "senders", ())
        blocked = {"system", "platform", "unknown", "cron", "timer", "dreaming", "scheduler", "limit_wake", "rate_limit_retry", "server_error_retry"}
        if (parent and parent.get("is_orchestrator") and field(target_session, "is_orchestrator")
                and parent["scope"] == field(target_session, "scope")
                and parent["name"] == field(target_session, "name") and senders
                and getattr(provenance, "subtype", "") not in blocked):
            with db._conn() as connection:
                for sender in senders:
                    child = connection.execute(
                        "SELECT id,parent_id,parent_name FROM sessions WHERE name=? AND scope=? "
                        "ORDER BY created_at DESC, rowid DESC LIMIT 1", (sender, parent["scope"])).fetchone()
                    if not child or child["id"] == parent["id"] or not (
                        child["parent_id"] == parent["id"] or child["parent_name"] == parent["name"]):
                        break
                else:
                    return
    raise ValueError("antigravity_interactive_only: explicit user input or verified direct-child report required")


def is_consumer_model(model):
    from app.models import backend_for_model
    try:
        return backend_for_model(model) == "antigravity"
    except (ValueError, TypeError, AttributeError):
        return False
