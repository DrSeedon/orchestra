"""One application-owned ACP v1 stdio connection per canonical OAuth HOME.

No background starts, quota requests, auth retries or prompt replay. A failed owner
is latched until application shutdown/operator recovery. Profile flock also refuses
another app process, rather than creating competing daemons for the same account.
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
import uuid
from pathlib import Path


class AcpError(RuntimeError):
    """Locally authored, safe-to-display protocol failure (never a raw RPC body)."""


class AcpSessionError(AcpError):
    """Refused operation, with no corruption of the shared profile transport."""


_owners: dict[Path, "AcpProfile"] = {}


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


async def shutdown_profiles():
    owners = list(_owners.values())
    # App shutdown is the only automatic registry reset. Sessions never evict owners.
    for owner in owners:
        await owner.close("ACP application shutdown")
    _owners.clear()


class AcpProfile:
    request_timeout = 20.0
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
        self.turn_lock = asyncio.Lock()
        self._start_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self.process = None
        self._reader = None
        self._stderr = None
        self._lock_fd = None
        self._cleanup_task = None
        self._next_id = 0
        self._pending = {}
        self.listeners = {}
        self.sessions = set()
        self.models = set()
        self.model_states = {}
        self.cost_totals = {}
        self.capabilities = {}
        self.failure = ""

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

    async def start(self):
        from app import backend_antigravity as backend
        async with self._start_lock:
            if self.failure:
                raise AcpError(self.failure)
            if self.process is not None:
                if self.process.returncode is not None:
                    await self.close("ACP daemon exited; operator recovery required")
                    raise AcpError(self.failure)
                return
            try:
                self._check_settings()
                if not backend._has_cached_credentials(self.home):
                    raise AcpError("ACP requires an existing cached login; interactive login is not supported")
                # Lifetime lock; no polling, busy wait, token locks or token copies.
                self._lock_fd = os.open(self.home / ".orchestra-acp.lock",
                                        os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
                fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.process = await asyncio.create_subprocess_exec(
                    backend.ANTIGRAVITY_BIN, "acp", "--disable-telemetry",
                    "--gemini-dir", str(self.home / ".gemini"),
                    "--app-data-dir", "antigravity-acp",
                    cwd=str(self.home), env=backend.cli_environment(self.home),
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

    async def _write(self, message, *, before_write=None, on_written=None):
        if self.failure or self.process is None or self.process.returncode is not None:
            raise AcpError(self.failure or "ACP daemon unavailable")
        payload = (json.dumps(message, ensure_ascii=False) + "\n").encode()
        if len(payload) > 1024 * 1024:
            raise AcpError("ACP message exceeds 1 MiB limit")
        async with self._write_lock:
            if before_write is not None:
                await before_write()
            self.process.stdin.write(payload)
            await self.process.stdin.drain()
            if on_written is not None:
                on_written()

    async def notify(self, method, params):
        await self._write({"jsonrpc": "2.0", "method": method, "params": params})

    async def request(self, method, params, *, timeout=None, before_write=None, on_written=None):
        self._next_id += 1
        request_id = self._next_id
        future = self.loop.create_future()
        self._pending[request_id] = future
        try:
            async with asyncio.timeout(self.request_timeout if timeout is None else timeout):
                await self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
                                  before_write=before_write, on_written=on_written)
                return await asyncio.shield(future)
        except AcpSessionError:
            raise
        except asyncio.CancelledError:
            # The backend shields submitted prompts and sends protocol cancellation.
            raise
        except BaseException as exc:
            reason = str(exc) if isinstance(exc, AcpError) else "ACP request failed/timed out; operator recovery required"
            await self.close(reason)
            raise AcpError(reason) from None
        finally:
            self._pending.pop(request_id, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()  # retrieve exceptions when timeout raced EOF

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
                    if "id" in message:
                        # No filesystem/terminal capability advertised. Permission
                        # requests fail closed; unknown client methods are bounded errors.
                        reply = {"jsonrpc": "2.0", "id": message["id"]}
                        if method == "session/request_permission":
                            identity = json.dumps(message["id"],sort_keys=True)
                            digest=hashlib.sha256(json.dumps(params,sort_keys=True).encode()).hexdigest()
                            if identity in self._client_request_ids:
                                if self._client_request_ids[identity]!=digest:
                                    raise AcpError("ACP native RPC identity reused with changed payload")
                                continue  # Exact native retry cannot create another card/response.
                            if len(self._client_tasks)>=16 or len(self._client_request_ids)>=4096:
                                await self._write({"jsonrpc":"2.0","id":message["id"],"result":{"outcome":{"outcome":"cancelled"}}})
                                continue
                            self._client_request_ids[identity]=digest
                            task=asyncio.create_task(self._permission(message["id"],params))
                            self._client_tasks.add(task)
                            task.add_done_callback(self._client_tasks.discard)
                            continue
                        else:
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
                    future = self._pending.get(message.get("id"))
                    if future is None or future.done():
                        continue
                    if "error" in message:
                        # Classify definite account/ToS bans BEFORE discarding details.
                        # Only the fixed safe reason reaches durable state, never raw RPC.
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
            raise AcpError("ACP daemon EOF; operator recovery required")
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.close("ACP stream ended/invalid; operator recovery required")

    async def _permission(self,rpc_id,params):
        from app import native_requests
        rid=None
        try:
            backend=self.permission_handlers.get(params.get("sessionId"))
            if backend is None:
                response={"outcome":{"outcome":"cancelled"}}
            else:
                result=await native_requests.request(self,rpc_id,params,backend)
                if isinstance(result,tuple):rid,response=result
                else:response=result
            await self._write({"jsonrpc":"2.0","id":rpc_id,"result":response})
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
                await self._write({"jsonrpc":"2.0","id":rpc_id,"result":{"outcome":{"outcome":"cancelled"}}})
        except Exception:
            if rid:native_requests.finish(rid,"unknown")
            await self.close("ACP native response failed; operator recovery required")

    async def _drain_stderr(self):
        # Drain without retaining or publishing secrets; chunks bound memory even
        # for a vendor that writes a huge unterminated stderr line.
        while await self.process.stderr.read(4096):
            pass

    async def close(self, reason):
        self.failure = self.failure or reason
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
            parent = None  # Missing durable evidence must deny, never authorize a wake.
        senders = getattr(provenance, "senders", ())
        blocked = {"system", "platform", "unknown", "cron", "timer", "dreaming", "scheduler", "limit_wake", "rate_limit_retry", "server_error_retry"}
        if (parent and parent.get("is_orchestrator") and field(target_session, "is_orchestrator")
                and parent["scope"] == field(target_session, "scope")
                and parent["name"] == field(target_session, "name") and senders
                and getattr(provenance, "subtype", "") not in blocked):
            with db._conn() as connection:
                for sender in senders:
                    # The latest durable identity owns a reused name, including after
                    # completion/archive. An in-memory sender label is not authority.
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
