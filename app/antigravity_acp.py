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


def auto_approve_enabled() -> bool:
    return os.environ.get("ANTIGRAVITY_AUTO_APPROVE", "1").strip() != "0"


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
        self._client_request_ids = OrderedDict()
        self._client_responses = {}
        self._permanent_failure = False
        self.uncertain_sessions = set()
        self._quarantined_slots = set()
        self.loop = asyncio.get_running_loop()
        try:
            max_turns = min(3, max(1, int(os.environ.get("ANTIGRAVITY_MAX_CONCURRENT_TURNS", "3"))))
        except ValueError:
            max_turns = 3
        self.max_concurrent_turns = max_turns
        self.turn_semaphore = asyncio.Semaphore(max_turns)
        self.turn_lock = self.turn_semaphore
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
        try:
            async with asyncio.timeout(self.request_timeout):
                await self.turn_semaphore.acquire()
        except TimeoutError:
            raise AcpSessionError("ACP prompt capacity busy/uncertain; no submission") from None
        try:
            yield
        finally:
            sid = backend.session_id
            if sid in self.uncertain_sessions and not self.failure:
                self._quarantined_slots.add(sid)
            else:
                self.turn_semaphore.release()

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

    async def start(self):
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
                self.cost_totals.clear()
                self.usage_totals.clear()
                self.uncertain_sessions.clear()
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
                from app.antigravity_auth import prepare_acp_token_store
                prepare_acp_token_store(self.home)
                # One Go tokenSource/mutex, not independently refreshing subprocesses.
                cmd = [backend.ANTIGRAVITY_BIN, "acp", "--disable-telemetry"]
                if auto_approve_enabled():
                    cmd.append("--dangerously-skip-permissions")
                cmd.extend([
                    "--gemini-dir", str(self.home / ".gemini"),
                    "--app-data-dir", "antigravity-acp",
                ])
                self.process = await asyncio.create_subprocess_exec(
                    *cmd,
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
            raise AcpSessionError("ACP message exceeds 1 MiB limit")
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
        except TimeoutError:
            sid = params.get("sessionId")
            if sid:
                self.uncertain_sessions.add(sid)
            raise AcpSessionError("ACP session timed out; outcome unknown, explicit recovery required") from None
        except (BrokenPipeError, ConnectionResetError, OSError):
            await self.close("ACP transport write failed; outcome unknown, no replay")
            raise AcpError(self.failure) from None
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
                            self._permanent_failure = True
                            backend._trip_antigravity_circuit_breaker("ACP confirmed account-disabled/Terms-of-Service refusal")
                        refusal = AcpError if banned else AcpSessionError
                        future.set_exception(refusal("ACP RPC rejected; operator recovery required"))
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

    async def _permission(self,rpc_id,params):
        from app import native_requests
        rid=None
        try:
            backend=self.permission_handlers.get(params.get("sessionId"))
            if backend is None:
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

    async def release_session(self, sid):
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
            self.session_locks.pop(sid, None)
            self.cost_totals.pop(sid, None)
            self.usage_totals.pop(sid, None)
            self.uncertain_sessions.discard(sid)
            self.models = set().union(*(self.published_models(v) for v in self.model_states.values()))
            if not self.sessions and self.process is not None:
                await self.close("ACP last owned session released")

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
            for _ in self._quarantined_slots:
                self.turn_semaphore.release()
            self._quarantined_slots.clear()


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
                            if subtype == "direct_message" and len(senders) == 1 and getattr(provenance, "ref", ""):
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
                                    and subtype in {"direct_message", "http_send"})
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
