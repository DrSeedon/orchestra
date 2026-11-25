"""One application-owned ACP v1 stdio connection per canonical OAuth HOME.

No background starts, quota requests, auth retries or prompt replay. A failed owner
may be recreated only on a new explicit caller turn (never replay). Definite bans
remain latched. Profile flock also refuses
another app process, rather than creating competing daemons for the same account.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
import fcntl
import hashlib
import json
import math
import os
import re
import signal
import sqlite3
import uuid
from pathlib import Path


class AcpError(RuntimeError):
    """Locally authored, safe-to-display protocol failure (never a raw RPC body)."""


class AcpSessionError(AcpError):
    """Refused operation, with no corruption of the shared profile transport."""


class AcpRPCRejected(AcpSessionError):
    """A definitive negative response, distinct from an ambiguous transport loss."""

    def __init__(self, code=None):
        super().__init__("ACP RPC rejected; operator recovery required")
        self.code = code


class AcpQuotaCooldownError(AcpRPCRejected):
    """Temporary Antigravity quota exhaustion; trips local cooldown without retries."""

    def __init__(self, code=None, *, message: str, until_ts: float | None = None, reset_seconds: int | None = None):
        AcpSessionError.__init__(self, message)
        self.code = code
        self.until_ts = until_ts
        self.reset_seconds = reset_seconds


def _timeout_seconds(name: str, default: float) -> float:
    try:
        seconds = float(os.environ.get(name, default))
    except ValueError:
        return default
    return seconds if math.isfinite(seconds) and seconds > 0 else default


_owners: dict[Path, "AcpProfile"] = {}


def cached_profile(home: Path):
    return _owners.get(Path(home).resolve())


def orchestra_mcp_turn_active(session_id: str) -> bool:
    return bool(session_id) and any(
        owner.active_orchestra_mcp_session == session_id and not owner.failure
        for owner in _owners.values()
    )


def get_profile(home: Path):
    home = Path(home).resolve()
    owner = _owners.get(home)
    if owner is None:
        owner = _owners[home] = AcpProfile(home)
    if owner.loop is not asyncio.get_running_loop():
        raise AcpError("ACP profile belongs to another event loop")
    return owner


async def shutdown_profiles():
    owners = list(_owners.values())
    # App shutdown is the only automatic registry reset. Sessions never evict owners.
    for owner in owners:
        await owner.close("ACP application shutdown")
    _owners.clear()


def auto_approve_enabled() -> bool:
    return os.environ.get("ANTIGRAVITY_AUTO_APPROVE", "1").strip() != "0"


class AcpProfile:
    request_timeout = 20.0
    prompt_cancel_timeout = 2.5

    def __init__(self, home: Path):
        self.home = home
        from app.native_requests import profile_epoch
        self.epoch = profile_epoch(home)
        self.transport_generation = uuid.uuid4().hex
        self.permission_handlers = {}
        self.client_request_handlers = {}
        self.mux_leases = set()
        self.mux_config_hashes = {}
        self.mux_idle_tasks = {}
        self._client_tasks = set()
        self._client_request_ids = OrderedDict()
        self._client_responses = {}
        self._permanent_failure = False
        self.uncertain_sessions = set()
        self._quarantined_slots = set()
        self.recovery_cleanup_needed = False
        self.loop = asyncio.get_running_loop()
        self.prompt_idle_timeout = _timeout_seconds("ANTIGRAVITY_PROMPT_IDLE_TIMEOUT", 600)
        self.prompt_max_timeout = _timeout_seconds("ANTIGRAVITY_PROMPT_MAX_TIMEOUT", 3600)
        self._prompt_deadlines: dict[str, tuple[asyncio.Timeout, float]] = {}
        try:
            max_turns = min(3, max(1, int(os.environ.get("ANTIGRAVITY_MAX_CONCURRENT_TURNS", "3"))))
        except ValueError:
            max_turns = 3
        self.max_concurrent_turns = max_turns
        self.turn_semaphore = asyncio.Semaphore(max_turns)
        self.turn_lock = self.turn_semaphore
        self._mcp_turn_lock = asyncio.Lock()
        self.active_orchestra_mcp_session = ""
        self._setup_lock = asyncio.Lock()
        self.session_locks: dict[str, asyncio.Lock] = {}
        self._start_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self.process = None
        self._reader = None
        self._stderr = None
        self._lock_fd = None
        self._cleanup_task = None
        self._next_id = 0
        self._pending = {}
        self._late_prompts = {}
        self.listeners = {}
        self.sessions = set()
        self.models = set()
        self.model_states = {}
        self.cost_totals = {}
        self.usage_totals = {}
        self.capabilities = {}
        self.failure = ""

    @asynccontextmanager
    async def turn_slot(self, backend):
        # A timed-out native prompt may still run. Retain its slot until actual
        # close/transport death, rather than over-admitting three more prompts.
        app_session_id = getattr(backend, "app_session_id", "")
        # The provider's MCP registry can expose a sibling's server. One
        # authenticated caller per profile makes the tool-side check decisive.
        # Mux turns share the profile but must never hold an Orchestra MCP grant.
        scoped = bool(app_session_id or getattr(backend, "owner_id", ""))
        held = False
        try:
            async with asyncio.timeout(self.prompt_max_timeout if scoped else self.request_timeout):
                if scoped:
                    await self._mcp_turn_lock.acquire()
                    held = True
                await self.turn_semaphore.acquire()
        except TimeoutError:
            if held:
                self._mcp_turn_lock.release()
            raise AcpSessionError("ACP prompt capacity busy/uncertain; no submission") from None
        except BaseException:
            if held:
                self._mcp_turn_lock.release()
            raise
        try:
            if scoped:
                self.active_orchestra_mcp_session = app_session_id
            yield
        finally:
            try:
                if scoped:
                    self.active_orchestra_mcp_session = ""
                    if self.uncertain_sessions and not self.failure:
                        await self.close("ACP prompt outcome uncertain; retire MCP transport before next caller")
            finally:
                sid = backend.session_id
                if not scoped and sid in self.uncertain_sessions and sid not in self._quarantined_slots and not self.failure:
                    self._quarantined_slots.add(sid)
                else:
                    self.turn_semaphore.release()
                if held:
                    self._mcp_turn_lock.release()

    def session_lock(self, session_id: str) -> asyncio.Lock:
        lock = self.session_locks.get(session_id)
        if lock is None:
            lock = self.session_locks[session_id] = asyncio.Lock()
        return lock

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
                if not isinstance(entry, dict):continue
                for row in ([entry] if "value" in entry else entry.get("options", []) or []):
                    if isinstance(row, dict) and isinstance(row.get("value"), str):result.add(row["value"])
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
        # Thought choices describe ONLY the active family. Never extrapolate its
        # levels onto inactive families; their explicit legacy variants remain valid.
        if current in direct and state.get("thought_config_id") and not re.search(r"-(xhigh|high|medium|low)$", current):
            variants = {current + "-" + level for level in state["thought_available"]}
            catalog_variants = {v for v in legacy if any(v.startswith(family + "-")
                for family in direct if not re.search(r"-(xhigh|high|medium|low)$", family))}
            direct.update(variants & legacy if catalog_variants else variants)
            # A legacy variant for the active family cannot override its current
            # thought selector's narrower offered levels in readiness projections.
            legacy = {v for v in legacy if not v.startswith(current + "-")}
        return direct | legacy

    def remember_model_state(self, sid, result):
        state = self.model_state(result)
        if "models" not in result and sid in self.model_states:
            state["legacy_available"] = self.model_states[sid].get("legacy_available", set())
        if not state["model_present"] and state["thought_present"] and sid in self.model_states:
            previous = self.model_states[sid]
            state = {**previous, **{k:state[k] for k in
                ("thought_config_id", "current_thought", "thought_available", "thought_present")}}
        if state["current"] is not None:
            self.model_states[sid] = state
            self.models = set().union(*(self.published_models(s) for s in self.model_states.values()))
        return state

    def _check_settings(self):
        # Never rewrite existing settings or infer that absence means no spending.
        try:
            cli = json.loads((self.home / ".gemini/antigravity-acp/settings.json").read_text())
            config = json.loads((self.home / ".gemini/config/config.json").read_text())
        except (OSError, ValueError):
            raise AcpError("ACP profile requires explicit no-credit settings") from None
        if cli.get("useG1Credits") is not False or config.get("userSettings", {}).get("useAiCredits") is not False:
            raise AcpError("ACP profile credit settings must both be false")

    async def start(self, *, before_spawn=None, executable=None):
        from app import backend_antigravity as backend
        async with self._start_lock:
            if self._permanent_failure:
                raise AcpError(self.failure)
            if self.process is not None and self.process.returncode is not None and not self.failure:
                await self.close("ACP daemon exited; next explicit turn may recreate transport")
            if self.failure:
                # Only a NEW caller turn may reopen a dead transport, never replay
                # the failed prompt. Drain the old reader before replacing its pipes.
                await self.close(self.failure)
                self.process = self._reader = self._stderr = self._cleanup_task = None
                self.failure = ""
                self.transport_generation = uuid.uuid4().hex
                self.sessions.clear()
                self.models.clear()
                self.model_states.clear()
                self.mux_config_hashes.clear()
                self.cost_totals.clear()
                self.usage_totals.clear()
                self.uncertain_sessions.clear()
                self._late_prompts.clear()
                self.recovery_cleanup_needed = False
                self._client_request_ids.clear()
                self._client_responses.clear()
            if self.process is not None:
                return
            try:
                self._check_settings()
                if not backend._has_cached_credentials(self.home):
                    raise AcpError("ACP requires an existing cached login; interactive login is not supported")
                # Lifetime lock; no polling, busy wait, token locks or token copies.
                self._lock_fd = os.open(self.home / ".orchestra-acp.lock",
                                        os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
                fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                if before_spawn is not None:
                    await before_spawn()
                from app.antigravity_auth import prepare_acp_token_store
                prepare_acp_token_store(self.home)
                # One Go tokenSource/mutex, not independently refreshing subprocesses.
                from app.provider_safety import verify_provider_egress
                env = backend.cli_environment(self.home)
                if not os.environ.get("PYTEST_CURRENT_TEST"):
                    launcher = Path.home() / ".local/bin/agy.real"
                    if launcher.resolve() != Path("/usr/local/libexec/orchestra-agy-ipc.py"):
                        raise AcpError("ACP IPC launcher unavailable")
                    env.update(ALLOW_DATACENTER_OAUTH_EGRESS="0", AGY_ALLOW_WHEN_DISABLED="0",
                               ORCHESTRA_AGY_SPAWNER_SOCK="/run/orchestra-agy/spawner.sock")
                    await verify_provider_egress("antigravity", env=env, enforce_in_tests=True)
                    executable = str(launcher)
                cmd = [executable or backend.ANTIGRAVITY_BIN, "acp", "--disable-telemetry"]
                if auto_approve_enabled():
                    cmd.append("--dangerously-skip-permissions")
                cmd.extend([
                    "--gemini-dir", str(self.home / ".gemini"),
                    "--app-data-dir", "antigravity-acp",
                ])
                self.process = await asyncio.create_subprocess_exec(
                    *cmd,
                    cwd=str(self.home), env=env,
                    stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE, start_new_session=True,
                    limit=1024 * 1024,
                )
                self._reader = asyncio.create_task(self._read())
                self._stderr = asyncio.create_task(self._drain_stderr())
                initialized = await self.request("initialize", {
                    "protocolVersion": 1,
                    "clientInfo": {"name": "orchestra", "version": "1"},
                    "clientCapabilities": {},
                })
                if initialized.get("protocolVersion") != 1:
                    raise AcpError("Unsupported ACP protocol version")
                self.capabilities = initialized.get("agentCapabilities") or {}
                methods = initialized.get("authMethods") or []
                if methods:
                    oauth = next((m for m in methods if m.get("id") == "oauth-personal"), None)
                    if oauth is None:
                        raise AcpError("ACP cached personal OAuth method unavailable; no auth fallback")
                    await self.request("authenticate", {"methodId": oauth["id"]})
            except BaseException as exc:
                reason = str(exc) if isinstance(exc, AcpError) else "ACP startup failed; operator recovery required"
                await self.close(reason)
                raise AcpError(reason) from None

    async def _write(self, message, *, before_write=None, on_written=None, on_started=None):
        if self.failure or self.process is None or self.process.returncode is not None:
            raise AcpError(self.failure or "ACP daemon unavailable")
        ceiling = 1024 * 1024
        if (self.capabilities.get("promptCapabilities", {}).get("audio") is True
                and message.get("method") == "session/prompt" and any(
            block.get("type") == "audio" for block in message.get("params", {}).get("prompt", ())
            if isinstance(block, dict)
        )):
            ceiling = 32 * 1024 * 1024
        payload = (json.dumps(message, ensure_ascii=False) + "\n").encode()
        if len(payload) > ceiling:
            raise AcpSessionError("ACP message exceeds frame limit")
        async with self._write_lock:
            if before_write is not None:
                await before_write()
            if on_started is not None:
                on_started()
            self.process.stdin.write(payload)
            await self.process.stdin.drain()
            if on_written is not None:
                on_written()

    async def notify(self, method, params):
        await self._write({"jsonrpc": "2.0", "method": method, "params": params})

    async def request(self, method, params, *, timeout=None, before_write=None, on_written=None,
                      prompt_deadline=None):
        self._next_id += 1
        request_id = self._next_id
        future = self.loop.create_future()
        self._pending[request_id] = future
        sid = params.get("sessionId")
        prompt = method == "session/prompt" and isinstance(sid, str)
        hard_deadline = (prompt_deadline if prompt_deadline is not None
                         else self.loop.time() + self.prompt_max_timeout)
        started = False

        def mark_started():
            nonlocal started
            started = True

        try:
            duration = self.request_timeout if timeout is None else timeout
            async with asyncio.timeout(duration):
                await self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
                                  before_write=before_write, on_written=on_written, on_started=mark_started)
                if not prompt:
                    return await asyncio.shield(future)
            async with asyncio.timeout_at(min(hard_deadline, self.loop.time() + self.prompt_idle_timeout)) as watchdog:
                self._prompt_deadlines[sid] = (watchdog, hard_deadline)
                return await asyncio.shield(future)
        except AcpSessionError:
            raise
        except AcpError:
            if prompt and started and not self._permanent_failure:
                self.uncertain_sessions.add(sid)
            raise
        except asyncio.CancelledError:
            # A cancelled request future does not terminate an already written prompt.
            if prompt and started and not future.done():
                self.uncertain_sessions.add(sid)
            raise
        except TimeoutError:
            if not prompt or not started:
                raise AcpSessionError("ACP request timed out before prompt submission" if prompt
                                      else "ACP setup request timed out") from None
            self._prompt_deadlines.pop(sid, None)
            # Keep the original response future registered while cancelling.
            # A late success/negative RPC is terminal and releases the slot.
            try:
                async with asyncio.timeout(self.prompt_cancel_timeout):
                    if not future.done():
                        await self.notify("session/cancel", {"sessionId": sid})
                    await asyncio.shield(future)
            except AcpRPCRejected:
                pass
            except (TimeoutError, AcpError, OSError):
                self.uncertain_sessions.add(sid)
                if not future.done() and not self.failure:
                    self._late_prompts[request_id] = sid
                raise AcpSessionError("ACP prompt timed out; cancellation unconfirmed") from None
            raise AcpSessionError("ACP prompt timed out; terminal response received after deadline") from None
        except (BrokenPipeError, ConnectionResetError, OSError):
            if prompt and started:
                self.uncertain_sessions.add(sid)
            await self.close("ACP transport write failed; outcome unknown, no replay")
            raise AcpError(self.failure) from None
        finally:
            if prompt:
                self._prompt_deadlines.pop(sid, None)
            self._pending.pop(request_id, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()  # retrieve exceptions when timeout raced EOF

    def _note_prompt_activity(self, sid):
        if not isinstance(sid, str):
            return
        active = self._prompt_deadlines.get(sid)
        if active is not None:
            watchdog, hard_deadline = active
            if not watchdog.expired():
                watchdog.reschedule(min(hard_deadline, self.loop.time() + self.prompt_idle_timeout))

    async def _read(self):
        try:
            while line := await self.process.stdout.readline():
                message = json.loads(line)
                if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
                    raise AcpError("Invalid ACP envelope")
                if "id" in message:
                    rpc_id=message["id"]
                    if isinstance(rpc_id,bool) or not isinstance(rpc_id,(str,int)) or len(str(rpc_id))>256:
                        raise AcpError("Invalid ACP RPC identity")
                if "method" in message:
                    method, params = message["method"], message.get("params") or {}
                    if isinstance(params, dict) and method.startswith("session/"):
                        self._note_prompt_activity(params.get("sessionId"))
                    if "id" in message:
                        # No filesystem/terminal capability advertised. Permission
                        # requests fail closed; unknown client methods are bounded errors.
                        reply = {"jsonrpc": "2.0", "id": message["id"]}
                        if not isinstance(params, dict):
                            reply["error"] = {"code": -32602, "message": "Invalid params"}
                            await self._write(reply)
                            continue
                        if method == "session/request_permission":
                            identity = json.dumps(message["id"],sort_keys=True)
                            digest=hashlib.sha256(json.dumps(params,sort_keys=True).encode()).hexdigest()
                            if identity in self._client_request_ids:
                                if self._client_request_ids[identity]!=digest:
                                    raise AcpError("ACP native RPC identity reused with changed payload")
                                response = self._client_responses.get(identity)
                                if response is not None:
                                    await self._write(response)
                                continue  # In-flight duplicate shares the original decision.
                            self._prune_client_requests()
                            if len(self._client_tasks)>=16:
                                await self._write({"jsonrpc":"2.0","id":message["id"],"result":{"outcome":{"outcome":"cancelled"}}})
                                continue
                            self._client_request_ids[identity]=digest
                            task=asyncio.create_task(self._permission(message["id"],params))
                            self._client_tasks.add(task)
                            task.add_done_callback(self._client_tasks.discard)
                            continue
                        relay = self.client_request_handlers.get(params.get("sessionId"))
                        if method in ("fs/read_text_file", "fs/write_text_file") and relay and len(self._client_tasks) < 16:
                            task = asyncio.create_task(self._relay_fs(relay, message))
                            self._client_tasks.add(task)
                            task.add_done_callback(self._client_tasks.discard)
                            continue
                        reply["error"] = {"code": -32601, "message": "Client method unsupported"}
                        await self._write(reply)
                    elif method == "session/update":
                        sid = params.get("sessionId")
                        update = params.get("update") or {}
                        if sid in self.sessions and update.get("sessionUpdate") == "config_option_update":
                            self.remember_model_state(sid, update)
                        callback = self.listeners.get(sid)
                        if callback:
                            callback(update)
                else:
                    late = self._late_prompts.get(message.get("id"))
                    if late is not None and ("error" in message or isinstance(message.get("result"), dict)):
                        self._late_prompts.pop(message.get("id"))
                        if "error" in message:
                            from app import backend_antigravity as backend
                            from app.provider_safety import parse_antigravity_quota_cooldown, trip_antigravity_cooldown
                            if backend._is_account_disabled_payload(message["error"]):
                                self._permanent_failure = True
                                reason = "ACP confirmed account-disabled/Terms-of-Service refusal"
                                backend._trip_antigravity_circuit_breaker(reason)
                                await self.close(reason)
                                return
                            raw_err = (
                                message["error"] if isinstance(message["error"], str)
                                else json.dumps(message["error"], ensure_ascii=False)
                            )
                            is_quota, until_ts, _ = parse_antigravity_quota_cooldown(raw_err)
                            if is_quota:
                                trip_antigravity_cooldown(raw_err, until_ts=until_ts)
                        self.uncertain_sessions.discard(late)
                        if late in self._quarantined_slots:
                            self._quarantined_slots.remove(late)
                            self.turn_semaphore.release()
                        continue
                    future = self._pending.get(message.get("id"))
                    if future is None or future.done():
                        continue
                    if "error" in message:
                        # Classify definite account/ToS bans and quota cooldown BEFORE discarding details.
                        from app import backend_antigravity as backend
                        from app.provider_safety import parse_antigravity_quota_cooldown, trip_antigravity_cooldown
                        error = message["error"]
                        banned = backend._is_account_disabled_payload(error)
                        if banned:
                            self._permanent_failure = True
                            backend._trip_antigravity_circuit_breaker("ACP confirmed account-disabled/Terms-of-Service refusal")
                        if banned:
                            refusal = AcpError("ACP RPC rejected; operator recovery required")
                        else:
                            raw_err = error if isinstance(error, str) else json.dumps(error, ensure_ascii=False)
                            code = error.get("code") if isinstance(error, dict) else None
                            is_quota, until_ts, reset_s = parse_antigravity_quota_cooldown(raw_err)
                            if is_quota:
                                info = trip_antigravity_cooldown(raw_err, until_ts=until_ts)
                                refusal = AcpQuotaCooldownError(
                                    code,
                                    message=info["message"],
                                    until_ts=info["until"],
                                    reset_seconds=reset_s,
                                )
                            else:
                                refusal = AcpRPCRejected(code)
                        future.set_exception(refusal)
                        if banned:
                            await self.close("ACP confirmed account-disabled/Terms-of-Service refusal")
                            return
                    elif isinstance(message.get("result"), dict):
                        future.set_result(message["result"])
                    else:
                        raise AcpError("Invalid ACP response")
            raise AcpError("ACP daemon EOF; operator recovery required")
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.close("ACP stream ended/invalid; operator recovery required")

    async def _relay_fs(self, relay, message):
        try:
            response = await relay(message["method"], message["params"])
            await self._write({"jsonrpc": "2.0", "id": message["id"], **response})
        except (AcpError, OSError):
            pass

    async def _permission(self,rpc_id,params):
        from app import native_requests
        rid=None
        try:
            backend=self.permission_handlers.get(params.get("sessionId"))
            relay = self.client_request_handlers.get(params.get("sessionId"))
            if relay is not None:
                parsed = native_requests.validate_payload(params)
                answer = await relay("session/request_permission", params)
                outcome = (answer.get("result") or {}).get("outcome") or {}
                allowed = {o["optionId"] for o in parsed["options"] if o["kind"] == "allow_once"}
                response = {"outcome": {"outcome": "cancelled"}}
                if (parsed["kind"] == "permission" and auto_approve_enabled()
                        and native_requests.profile_epoch(self.home) == self.epoch
                        and outcome.get("optionId") in allowed):
                    response = {"outcome": {"outcome": "selected", "optionId": outcome["optionId"]}}
            elif backend is None:
                response={"outcome":{"outcome":"cancelled"}}
            else:
                parsed=native_requests.validate_payload(params)
                if auto_approve_enabled() and parsed["kind"]=="permission":
                    if native_requests.profile_epoch(self.home)!=self.epoch:
                        response={"outcome":{"outcome":"cancelled"}}
                    else:
                        option=(next((o for o in parsed["options"] if o.get("kind")=="allow_once"),None)
                                or next((o for o in parsed["options"] if o.get("kind")=="allow_always"),None))
                        response=({"outcome":{"outcome":"selected","optionId":option["optionId"]}}
                                  if option is not None else {"outcome":{"outcome":"cancelled"}})
                else:
                    result=await native_requests.request(self,rpc_id,params,backend)
                    if isinstance(result,tuple):rid,response=result
                    else:response=result
            reply = {"jsonrpc":"2.0","id":rpc_id,"result":response}
            await self._write(reply)
            self._client_responses[json.dumps(rpc_id,sort_keys=True)] = reply
            self._prune_client_requests()
            if rid:
                native_requests.finish(rid,"responded")
                if backend is not None:
                    from app.events import AgentEvent
                    backend._queue.put_nowait(AgentEvent("native_request_closed",json.dumps({"id":rid,"state":"responded"}),metadata={"item_id":"acp-native:"+rid+":closed"}))
        except asyncio.CancelledError:
            if rid:native_requests.finish(rid,"stale")
            raise
        except ValueError:
            if not self.failure:
                reply = {"jsonrpc":"2.0","id":rpc_id,"result":{"outcome":{"outcome":"cancelled"}}}
                await self._write(reply)
                self._client_responses[json.dumps(rpc_id,sort_keys=True)] = reply
                self._prune_client_requests()
        except Exception:
            if rid:native_requests.finish(rid,"unknown")
            await self.close("ACP native response failed; operator recovery required")

    def _prune_client_requests(self):
        # Completed FIFO entries are evictable. At most 16 in-flight requests
        # remain pinned; this is a bounded retry window, not a lifetime quota.
        while len(self._client_request_ids) > 512:
            key = next((k for k in self._client_request_ids if k in self._client_responses), None)
            if key is None:
                break
            self._client_request_ids.pop(key)
            self._client_responses.pop(key, None)

    async def release_session(self, sid, *, close_idle_profile=True):
        if sid not in self.sessions:
            return
        try:
            # ACP session/close is an optional extension: never invent support.
            caps = self.capabilities.get("sessionCapabilities") or {}
            if not self.failure and caps.get("close") is not None:
                await self.request("session/close", {"sessionId": sid}, timeout=2)
                if sid in self._quarantined_slots:
                    self._quarantined_slots.remove(sid)
                    self.turn_semaphore.release()
        except AcpError:
            # Optional close refusal cannot resurrect an already archived app
            # session. Remaining native memory is bounded by profile exit.
            pass
        finally:
            self.sessions.discard(sid)
            self.listeners.pop(sid, None)
            self.permission_handlers.pop(sid, None)
            self.model_states.pop(sid, None)
            self.mux_config_hashes.pop(sid, None)
            self.session_locks.pop(sid, None)
            self.cost_totals.pop(sid, None)
            self.usage_totals.pop(sid, None)
            if sid not in self._quarantined_slots:
                self.uncertain_sessions.discard(sid)
            self.models = set().union(*(self.published_models(v) for v in self.model_states.values()))
            if close_idle_profile and not self.sessions and self.process is not None:
                await self.close("ACP last owned session released")

    async def _drain_stderr(self):
        # Drain without retaining or publishing secrets; chunks bound memory even
        # for a vendor that writes a huge unterminated stderr line.
        while await self.process.stderr.read(4096):
            pass

    async def close(self, reason):
        self.failure = self.failure or reason
        for task in tuple(self.mux_idle_tasks.values()):
            if task is not asyncio.current_task():
                task.cancel()
        self.mux_idle_tasks.clear()
        for future in list(self._pending.values()):
            if not future.done():
                future.set_exception(AcpError(self.failure))
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup())
        await asyncio.shield(self._cleanup_task)

    async def _cleanup(self):
        tasks = [t for t in (self._reader, self._stderr, *self._client_tasks) if t]
        for task in tasks:
            task.cancel()
        try:
            if self.process is not None:
                try:
                    os.killpg(self.process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(self.process.wait(), 1)
                except TimeoutError:
                    pass
                # Also terminate descendants ignoring TERM after their leader exits.
                try:
                    os.killpg(self.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await self.process.wait()
            await asyncio.gather(*tasks, return_exceptions=True)
        finally:
            if self._lock_fd is not None:
                os.close(self._lock_fd)
                self._lock_fd = None
            for _ in self._quarantined_slots:
                self.turn_semaphore.release()
            self._quarantined_slots.clear()


async def select_model(owner, sid, model, effort=None):
    state = owner.model_states[sid]
    suffix = re.search(r"-(xhigh|high|medium|low)$", model)
    wanted = effort or (suffix.group(1) if suffix else None)
    base = re.sub(r"-(?:xhigh|high|medium|low)$", "", model)
    requested = base + "-" + wanted if wanted else model
    split = bool(state["config_id"] and base in state["available"] and base != requested and requested not in state["available"])
    if split:
        if state["current"] != base:
            selected = await owner.request("session/set_config_option", {
                "sessionId":sid,"configId":state["config_id"],"value":base})
            state = owner.remember_model_state(sid, selected)
            if state["current"] != base:
                raise AcpSessionError("ACP model family selection was not confirmed; prompt refused")
        def validate_thought(value):
            if value["current"] != base or base not in value["available"] or not value.get("thought_config_id") or wanted not in value["thought_available"]:
                raise AcpSessionError("Requested thought level is not advertised for selected family; no nearest fallback")
            legacy = value.get("legacy_available", set())
            variants = {v for v in legacy if any(v.startswith(family+"-") for family in value["available"]
                if not re.search(r"-(xhigh|high|medium|low)$", family))}
            if variants and requested not in legacy:
                raise AcpSessionError("ACP model/thought combination contradicts variant catalog; prompt refused")
        validate_thought(state)
        if state["current_thought"] != wanted:
            selected = await owner.request("session/set_config_option", {
                "sessionId":sid,"configId":state["thought_config_id"],"value":wanted})
            state = owner.remember_model_state(sid, selected)
            validate_thought(state)
            if state["current_thought"] != wanted:
                raise AcpSessionError("ACP thought level selection was not confirmed; prompt refused")
    else:
        if requested not in state["available"]:
            offered = ",".join(sorted(str(m)[:64] for m in state["available"])[:12])
            raise AcpSessionError(f"Requested model/effort variant is not advertised; no nearest fallback (offered={offered})")
        if state["current"] != requested:
            if state["config_id"]:
                selected = await owner.request("session/set_config_option", {
                    "sessionId":sid,"configId":state["config_id"],"value":requested})
                state = owner.remember_model_state(sid, selected)
                if state["current"] != requested or requested not in state["available"]:
                    raise AcpSessionError("ACP model selection was not confirmed; prompt refused")
            else:
                selected = await owner.request("session/set_model", {"sessionId":sid,"modelId":requested})
                confirmed = owner.model_state(selected)
                if confirmed["current"] is not None and confirmed["current"] != requested:
                    owner.remember_model_state(sid, selected)
                    raise AcpSessionError("ACP model selection mismatch; prompt refused")
                state["current"] = requested  # Legacy empty success is its advertised contract.

    owner.models = set().union(*(owner.published_models(s) for s in owner.model_states.values()))
    return requested


def ensure_interactive_input(model, provenance, *, target_session=None, allow_child_agent=True):
    """Admit durable event ownership; provenance labels alone are never authority."""
    if not is_consumer_model(model):
        return
    origin = getattr(provenance, "origin", None)
    subtype = getattr(provenance, "subtype", "")
    blocked = {"system", "platform", "unknown", "cron", "cron_command", "cron_command_timeout",
               "timer", "dreaming", "scheduler", "limit_wake", "rate_limit_retry", "server_error_retry"}
    if origin == "user" and subtype not in blocked:
        return
    def field(value, name):
        return value.get(name) if isinstance(value, dict) else getattr(value, name, None)
    if allow_child_agent and origin in {"agent", "background_task"} and subtype not in blocked:
        from app import db
        try:
            parent = db.get_session(field(target_session, "id"))
            senders = getattr(provenance, "senders", ())
            if (parent and parent["scope"] == field(target_session, "scope")
                    and parent["name"] == field(target_session, "name") and senders):
                if origin == "background_task":
                    ref = getattr(provenance, "ref", "")
                    job = db.bg_get_job(ref) if ref and senders == (ref,) else None
                    config = json.loads(job["config"]) if job else {}
                    if (job and job["type"] in {"run", "file", "merge"}
                            and job["target_session_id"] == parent["id"]
                            and job["target_scope"] == parent["scope"]
                            and config.get("_creator_session_id") == parent["id"]
                            and job["status"] in {"triggering", "triggered", "failed", "expired"}
                            and subtype in {"completed", "success", "failed", "timeout", "expired", "triggered"}):
                        return
                elif not parent.get("is_orchestrator") and subtype in {"initial_delivery", "direct_message", "http_send"}:
                    # Foreground delegated worker input is not a scheduled wake.
                    # Bind it to the durable direct parent, never a sender label.
                    source = db.get_session(parent.get("parent_id")) if parent.get("parent_id") else None
                    if source is None and not parent.get("parent_id") and parent.get("parent_name"):
                        source = db.get_session_by_name(parent["parent_name"], parent["scope"])
                    if (source and source.get("is_orchestrator") and source["id"] != parent["id"]
                            and source["scope"] == parent["scope"] and senders == (source["name"],)
                            and source.get("status") not in {"archived", "closed"}):
                        ref = getattr(provenance, "ref", "")
                        if subtype == "http_send":
                            return  # HTTP ingress already requires the parent's MCP proof.
                        if subtype == "direct_message" and ref:
                            from app.message_deliveries import _row
                            receipt = _row(ref)
                            if (receipt and receipt["source_session_id"] == source["id"]
                                    and receipt["target_session_id"] == parent["id"]):
                                return
                        if subtype == "initial_delivery" and ref:
                            with db._conn() as connection:
                                receipt = connection.execute(
                                    "SELECT session_id,scope,sender FROM initial_deliveries WHERE delivery_id=?",
                                    (ref,)).fetchone()
                            if (receipt and receipt["session_id"] == parent["id"]
                                    and receipt["scope"] == parent["scope"] and receipt["sender"] == source["name"]):
                                return
                elif parent.get("is_orchestrator") and field(target_session, "is_orchestrator"):
                    with db._conn() as connection:
                        for sender in senders:
                            source_id = None
                            if (subtype in {"direct_message", "direct_message_recovery", "codex_turn_end_hold"}
                                    and len(senders) == 1 and getattr(provenance, "ref", "")):
                                from app.message_deliveries import _row
                                receipt = _row(provenance.ref)
                                if (receipt and receipt["target_session_id"] == parent["id"]
                                        and receipt["source_name"] == sender and receipt["origin"] == "agent"):
                                    source_id = receipt["source_session_id"]
                            if source_id:
                                row = connection.execute("SELECT * FROM sessions WHERE id=?", (source_id,)).fetchone()
                            else:
                                row = connection.execute(
                                    "SELECT * FROM sessions WHERE name=? AND scope=? "
                                    "ORDER BY created_at DESC, rowid DESC LIMIT 1", (sender, parent["scope"])).fetchone()
                            child = dict(row) if row else {}
                            direct_child = child and (child["parent_id"] == parent["id"] or child["parent_name"] == parent["name"])
                            peer = (child and (child.get("is_orchestrator") or child.get("role") == "orchestrator")
                                    and child.get("status") not in {"archived", "closed"}
                                    and subtype in {"direct_message", "http_send", "direct_message_recovery", "codex_turn_end_hold"})
                            if not child or child["id"] == parent["id"] or not (direct_child or peer):
                                break
                        else:
                            return
        except (sqlite3.Error, ValueError, TypeError, KeyError):
            pass
    raise ValueError("antigravity_interactive_only: user input or verified owned event required")


def is_consumer_model(model):
    from app.models import backend_for_model
    try:
        return backend_for_model(model) == "antigravity"
    except (ValueError, TypeError, AttributeError):
        return False
