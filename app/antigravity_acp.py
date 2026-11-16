"""One application-owned ACP v1 stdio connection per canonical OAuth HOME.

No background starts, quota requests, auth retries or prompt replay. A failed owner
is latched until application shutdown/operator recovery. Profile flock also refuses
another app process, rather than creating competing daemons for the same account.
"""
from __future__ import annotations

import asyncio
import fcntl
import json
import os
import signal
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
        # Stable ACP configOptions are preferred; legacy models metadata remains
        # supported for installed CLI versions advertising session/set_model.
        option = next((o for o in result.get("configOptions", []) if
                       o.get("category") == "model" or o.get("id") == "model"), None)
        if option is not None:
            available = set()
            for entry in option.get("options", []):
                for row in ([entry] if "value" in entry else entry.get("options", [])):
                    if isinstance(row.get("value"), str):
                        available.add(row["value"])
            return {"config_id": option["id"], "current": option.get("currentValue"), "available": available}
        models = result.get("models") or {}
        return {"config_id": None, "current": models.get("currentModelId"),
                "available": {r["modelId"] for r in models.get("availableModels", [])
                              if isinstance(r, dict) and isinstance(r.get("modelId"), str)}}

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
                    oauth = next((m for m in methods if m.get("id") == "oauth-personal"
                                  and m.get("type", "agent") == "agent"), None)
                    if oauth is None:
                        raise AcpError("ACP cached personal OAuth method unavailable; no auth fallback")
                    await self.request("authenticate", {"methodId": oauth["id"]})
            except BaseException as exc:
                reason = str(exc) if isinstance(exc, AcpError) else "ACP startup failed; operator recovery required"
                await self.close(reason)
                raise AcpError(reason) from None

    async def _write(self, message):
        if self.failure or self.process is None or self.process.returncode is not None:
            raise AcpError(self.failure or "ACP daemon unavailable")
        payload = (json.dumps(message, ensure_ascii=False) + "\n").encode()
        if len(payload) > 1024 * 1024:
            raise AcpError("ACP message exceeds 1 MiB limit")
        async with self._write_lock:
            self.process.stdin.write(payload)
            await self.process.stdin.drain()

    async def notify(self, method, params):
        await self._write({"jsonrpc": "2.0", "method": method, "params": params})

    async def request(self, method, params, *, timeout=None):
        self._next_id += 1
        request_id = self._next_id
        future = self.loop.create_future()
        self._pending[request_id] = future
        try:
            async with asyncio.timeout(self.request_timeout if timeout is None else timeout):
                await self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
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
                if "method" in message:
                    method, params = message["method"], message.get("params") or {}
                    if "id" in message:
                        # No filesystem/terminal capability advertised. Permission
                        # requests fail closed; unknown client methods are bounded errors.
                        reply = {"jsonrpc": "2.0", "id": message["id"]}
                        if method == "session/request_permission":
                            reply["result"] = {"outcome": {"outcome": "cancelled"}}
                        else:
                            reply["error"] = {"code": -32601, "message": "Client method unsupported"}
                        await self._write(reply)
                    elif method == "session/update":
                        sid = params.get("sessionId")
                        update = params.get("update") or {}
                        if sid in self.sessions and update.get("sessionUpdate") == "config_option_update":
                            state = self.model_state(update)
                            if state["current"] is not None:
                                self.model_states[sid] = state
                                self.models = set().union(*(s["available"] for s in self.model_states.values()))
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
        tasks = [t for t in (self._reader, self._stderr) if t]
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


def ensure_interactive_input(model, provenance):
    """Execution boundary, independent of disabled-provider and worker policy."""
    from app.models import backend_for_model
    if is_consumer_model(model) and getattr(provenance, "origin", None) != "user":
        raise ValueError("antigravity_interactive_only: consumer ACP requires explicit user input")


def is_consumer_model(model):
    from app.models import backend_for_model
    try:
        return backend_for_model(model) == "antigravity"
    except (ValueError, TypeError, AttributeError):
        return False
