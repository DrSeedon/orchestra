"""Local ACP session broker for the Telegram bot. Only the profile owns vendor I/O."""

from __future__ import annotations

import asyncio
import base64
import errno
import hashlib
import json
import logging
import select
import time
import os
import re
import signal
import socket
import stat
import struct
import sys
import uuid
from pathlib import Path

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from app.backend_antigravity import _cumulative_value
from app.antigravity_acp import AcpError, AcpSessionError, cached_profile, get_profile, select_model
from app.native_requests import bind_session, profile_epoch
from app.provider_safety import record_provider_activity, verify_provider_egress

logger = logging.getLogger(__name__)
SOCKET_NAME = ".acp-mux.sock"
MAX_FRAME = 32 * 1024 * 1024
MAX_PROMPT_BYTES = 20 * 1024 * 1024
CLEAN_EXEC = Path("/usr/local/bin/agy-clean-exec")
CLEAN_SHELL = Path.home() / ".local/bin/agy-clean-shell"
SPAWNER = Path("/run/orchestra-agy/spawner.sock")
TOOL_EXEC = Path("/run/orchestra-agy/tool-exec.sock")
KILLSWITCH = Path("/run/orchestra-oauth-killswitch.ready")
MODEL = re.compile(
    r"(?:gemini-4-(?:neon|hydrogen)-(?:low|medium|high)"
    r"|gemini-4-carbon-(?:low|high)|gemini-pro-orchestrator-neon)"
)


def _trusted_peer(writer, home):
    sock = writer.get_extra_info("socket")
    credentials = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    pid, uid, _ = struct.unpack("3i", credentials)
    if uid != os.getuid() or pid <= 0:
        return False
    from app.backend_antigravity import canonical_profile
    if (os.environ.get("PYTEST_CURRENT_TEST") and home.is_relative_to(Path("/tmp"))
            and home.resolve() != canonical_profile()):
        return True
    try:
        fd = os.pidfd_open(pid)
        try:
            monitor = select.poll()
            monitor.register(fd, select.POLLIN)
            groups = Path(f"/proc/{pid}/cgroup").read_text().splitlines()
            return not monitor.poll(0) and any(
                line.split(":", 2)[-1] == "/system.slice/kesha-bot-vps.service"
                for line in groups
            )
        finally:
            os.close(fd)
    except OSError:
        return False


def _directory(home):
    info = home.lstat()
    if info.st_uid != os.getuid() or not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
        raise AcpError("ACP mux requires the private OAuth directory")


def _native_boundary():
    if (not KILLSWITCH.is_file() or not SPAWNER.is_socket() or not TOOL_EXEC.is_socket()
            or not all(os.access(path, os.X_OK) for path in (CLEAN_EXEC, CLEAN_SHELL))):
        raise AcpError("ACP kernel egress/tool boundary is unavailable")


async def _egress():
    _native_boundary()
    env = {**os.environ, "ALLOW_DATACENTER_OAUTH_EGRESS": "0", "AGY_ALLOW_WHEN_DISABLED": "0"}
    await verify_provider_egress("antigravity", env=env, enforce_in_tests=True)


def _mcp_servers(configs):
    if not isinstance(configs, list) or len(configs) > 32:
        raise AcpSessionError("Invalid ACP MCP server list")
    servers = []
    for config in configs:
        name, command = config["name"], config["command"]
        args, env = config["args"], config["env"]
        if not all(isinstance(v, str) and v for v in (name, command)):
            raise AcpSessionError("Invalid ACP MCP command")
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            raise AcpSessionError("Invalid ACP MCP arguments")
        # The bridge capability is scoped to the chat. External MCP env is
        # deliberately absent; no inherited credential/proxy overrides cross here.
        if not isinstance(env, dict) or not set(env) <= {"KESHA_BRIDGE_AUTH_FILE"}:
            raise AcpSessionError("Invalid ACP MCP environment")
        if env and (name != "kesha" or Path(command).name not in ("python", "python3")
                    or len(args) != 1 or Path(args[0]).name != "kesha_mcp_proxy.py"
                    or not all(isinstance(value, str) for value in env.values())):
            raise AcpSessionError("Invalid ACP Kesha bridge")
        home_dir = Path.home()
        base_env = {
            "HOME": str(home_dir),
            "XDG_CONFIG_HOME": str(home_dir / ".config"),
            "XDG_CACHE_HOME": str(home_dir / ".cache"),
            "XDG_DATA_HOME": str(home_dir / ".local" / "share"),
        }
        servers.append({"name": name, "command": str(CLEAN_EXEC), "args": [command, *args],
                        "env": [{"name": key, "value": value}
                                for key, value in {**base_env, **env}.items()]})
    return servers


def _owned_token(token):
    if not isinstance(token, str) or not re.fullmatch(r"[a-f0-9]{64}", token):
        raise AcpSessionError("Invalid ACP ownership token")
    return "kesha-mux:" + hashlib.sha256(token.encode()).hexdigest()


def _validate_prompt(blocks):
    if not isinstance(blocks, list) or not blocks or len(blocks) > 64:
        raise AcpSessionError("Invalid ACP prompt blocks")
    audio_bytes = 0
    for block in blocks:
        if not isinstance(block, dict):
            raise AcpSessionError("Invalid ACP prompt block")
        if (set(block) == {"type", "text"} and block["type"] == "text"
                and isinstance(block["text"], str) and len(block["text"]) <= 256 * 1024):
            continue
        if (set(block) != {"type", "data", "mimeType"} or block["type"] != "audio"
                or block["mimeType"] != "audio/ogg" or not isinstance(block["data"], str)):
            raise AcpSessionError("Invalid ACP audio block")
        data = block["data"]
        if len(data) % 4 or not re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", data):
            raise AcpSessionError("Invalid ACP audio encoding")
        if not base64.b64decode(data[:8], validate=True).startswith(b"OggS"):
            raise AcpSessionError("ACP audio is not Ogg")
        audio_bytes += len(data) // 4 * 3 - (len(data) - len(data.rstrip("=")))
        if audio_bytes > MAX_PROMPT_BYTES:
            raise AcpSessionError("ACP audio exceeds the 20 MiB prompt budget")


async def _check_quota():
    from app.provider_safety import get_antigravity_cooldown
    from app.routes.system import _antigravity_usage_cache

    cooldown = get_antigravity_cooldown()
    if cooldown is not None:
        raise AcpSessionError(cooldown["message"])
    for key in ("data", "five_hour"):
        values = _antigravity_usage_cache.get(key) or {}
        usage = values.get("gemini-weekly" if key == "data" else "gemini-5h")
        if isinstance(usage, dict):
            remaining = usage.get("remaining_fraction")
            if isinstance(remaining, (float, int)):
                if remaining <= 0.05:
                    raise AcpSessionError("ACP quota hard stop")
                continue
            usage = usage.get("used_percent", usage.get("utilization"))
        if isinstance(usage, (int, float)) and usage >= 95:
            raise AcpSessionError("ACP quota hard stop")


def _reserve_turn(home, event_id, origin, *, owner, sid):
    import sqlite3
    path = home / ".acp-mux-wakes.sqlite3"
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    os.close(fd)
    conn = sqlite3.connect(path)
    try:
        with conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS turn_admission (
                ticket TEXT PRIMARY KEY, binding TEXT NOT NULL, origin TEXT NOT NULL,
                started REAL NOT NULL
            )""")
            conn.execute("BEGIN IMMEDIATE")
            now = time.time()
            conn.execute("DELETE FROM turn_admission WHERE started <= ?", (now - 86400,))
            if origin == "owned_reminder" and conn.execute(
                    "SELECT COUNT(*) FROM turn_admission WHERE origin='owned_reminder'").fetchone()[0] >= 8:
                raise AcpSessionError("ACP owned reminder budget exhausted")
            ticket = hashlib.sha256(event_id.encode()).hexdigest()
            binding = hashlib.sha256(json.dumps([owner, sid, origin]).encode()).hexdigest()
            if conn.execute("INSERT OR IGNORE INTO turn_admission VALUES (?,?,?,?)",
                            (ticket, binding, origin, now)).rowcount != 1:
                raise AcpSessionError("ACP provenance ticket already used")
    finally:
        conn.close()


class Connection:
    def __init__(self, home, writer, *, fallback=False):
        self.home = home
        self.writer = writer
        self.fallback = fallback
        self.owner = None
        self.session_id = None
        self.prompt = None
        self.submitted = asyncio.Event()
        self.cancel_sent = False
        self.prompt_generation = None
        self.pending = {}
        self.disconnected = False
        self.closed_session = False
        self.origin = None
        self.steps = 0
        self.audio_allowed = False
        self.reported_usage = {}
        self.reported_cost = None

    def send(self, message):
        data = (json.dumps(message, ensure_ascii=False) + "\n").encode()
        if self.writer.is_closing():
            return
        if self.writer.transport.get_write_buffer_size() + len(data) > MAX_FRAME:
            self.writer.close()
            return
        self.writer.write(data)

    def update(self, update):
        kind = update.get("sessionUpdate")
        if kind == "agent_thought_chunk":
            text = (update.get("content") or {}).get("text")
            if isinstance(text, str):
                self.turn_thinking_chars = int(getattr(self, "turn_thinking_chars", 0) or 0) + len(text)
            return
        if kind == "agent_message_chunk":
            text = (update.get("content") or {}).get("text")
            if isinstance(text, str):
                self.turn_output_chars = int(getattr(self, "turn_output_chars", 0) or 0) + len(text)
        elif kind == "tool_call":
            self.turn_tool_calls = int(getattr(self, "turn_tool_calls", 0) or 0) + 1
        if kind == "usage_update":
            if isinstance(update.get("used"), (int, float)) and not isinstance(update.get("used"), bool):
                self.turn_context_used = int(update["used"])
            usage = update.get("usage")
            if isinstance(usage, dict):
                self.reported_usage = usage
            quota = update.get("quota")
            if isinstance(quota, dict):
                try:
                    from app.backend_antigravity import (
                        _publish_quota,
                        canonical_profile,
                        normalize_antigravity_five_hour_quota,
                        normalize_antigravity_quota,
                    )
                    if self.home == canonical_profile():
                        weekly = normalize_antigravity_quota(quota)
                        short = normalize_antigravity_five_hour_quota(quota)
                        if any(v is not None for v in (*weekly.values(), *short.values())):
                            epoch = getattr(self.owner, "epoch", "") or ""
                            _publish_quota(weekly, time.time(), epoch, short)
                except Exception as exc:
                    logger.debug("ACP mux quota publish skipped (%s)", type(exc).__name__)
            cost = update.get("cost")
            if isinstance(cost, dict) and cost.get("currency") == "USD":
                amount = _cumulative_value(cost.get("amount"), integer=False)
                if amount is not None:
                    self.reported_cost = amount
        self.send({"method": "session/update", "params": {"sessionId": self.session_id, "update": update}})

    async def relay(self, method, params):
        default = ({"result": {"outcome": {"outcome": "cancelled"}}}
                   if method == "session/request_permission"
                   else {"error": {"code": -32601, "message": "Filesystem RPC unavailable"}})
        if self.disconnected:
            return default
        rpc_id = uuid.uuid4().hex
        future = asyncio.get_running_loop().create_future()
        self.pending[rpc_id] = (method, future)
        try:
            self.send({"method": method, "id": rpc_id, "params": params})
            return await asyncio.wait_for(future, 3)
        except TimeoutError:
            return default
        finally:
            self.pending.pop(rpc_id, None)

    async def open(self, params):
        if self.origin is not None or params.get("origin") not in ("telegram", "owned_reminder"):
            raise AcpSessionError("ACP mux requires an admitted Telegram turn or owned reminder")
        owner_id = _owned_token(params.get("token"))
        cwd = Path(params["cwd"]).resolve(strict=True)
        if not cwd.is_dir():
            raise AcpSessionError("Invalid ACP session working directory")
        servers = _mcp_servers(params.get("mcpServers", []))
        sid = params.get("sessionId")
        if sid is not None and (not isinstance(sid, str) or not sid or len(sid) > 256):
            raise AcpSessionError("Invalid ACP session identity")
        self.owner_id, self.cwd, self.servers = owner_id, cwd, servers
        owner = cached_profile(self.home)
        if sid is not None:
            bind_session(owner or get_profile(self.home), sid, owner_id, resume=True)
        self.session_id, self.origin = sid, params["origin"]
        self.audio_allowed = bool(owner and not owner.failure
                                  and owner.capabilities.get("promptCapabilities", {}).get("audio") is True)
        return {"sessionId": sid, "audio": self.audio_allowed}

    async def attach(self):
        sid, owner_id = self.session_id, self.owner_id
        cwd, servers = self.cwd, self.servers
        owner = self.owner = get_profile(self.home)
        async with owner._setup_lock:
            if sid is not None:
                bind_session(owner, sid, owner_id, resume=True)
                if sid in owner.uncertain_sessions:
                    raise AcpSessionError("uncertain_session")
                if sid in owner.mux_leases:
                    raise AcpSessionError("ACP session busy")
            owner._check_settings()
            if self.fallback:
                executable = Path.home() / ".local/bin/agy.real"
                if executable.resolve() != Path("/usr/local/libexec/orchestra-agy-ipc.py"):
                    raise AcpError("ACP IPC executable unavailable")
                await owner.start(before_spawn=self._fallback_guard, executable=str(executable))
            else:
                await _egress()
                await owner.start()
            config_hash = hashlib.sha256(json.dumps([str(cwd), servers], sort_keys=True).encode()).digest()
            if sid is None or sid not in owner.sessions or owner.mux_config_hashes.get(sid) != config_hash:
                native_params = {"cwd": str(cwd), "mcpServers": servers}
                if sid is None:
                    result = await owner.request("session/new", native_params)
                    sid = result.get("sessionId")
                    if not isinstance(sid, str) or not sid or len(sid) > 256 or sid in owner.sessions:
                        raise AcpSessionError("ACP new session identity invalid")
                    bind_session(owner, sid, owner_id, require_unbound=True)
                    owner.usage_totals[sid] = dict.fromkeys(
                        ("input_tokens", "output_tokens", "cache_read_tokens"), 0)
                    owner.cost_totals[sid] = 0.0
                else:
                    if (owner.capabilities.get("sessionCapabilities") or {}).get("resume") is None:
                        raise AcpSessionError("ACP resume unsupported")
                    result = await owner.request("session/resume", {**native_params, "sessionId": sid})
                    if result.get("sessionId", sid) != sid:
                        raise AcpSessionError("ACP resume identity mismatch")
                owner.remember_model_state(sid, result)
                owner.sessions.add(sid)
                owner.mux_config_hashes[sid] = config_hash
            timer = owner.mux_idle_tasks.pop(sid, None)
            if timer:
                timer.cancel()
            owner.mux_leases.add(sid)
            self.session_id = sid
            self.prompt_generation = owner.transport_generation
            self.send({"method": "session/attached", "params": {"sessionId": sid}})

    async def _fallback_guard(self):
        # AcpProfile calls this with the cross-process flock held. A listener
        # that came up during the retry or process launch wins over fallback.
        _native_boundary()
        if not await _inactive_socket(self.home / SOCKET_NAME):
            raise AcpSessionError("ACP mux came online; retry on the next interactive turn")
        service = await asyncio.create_subprocess_exec(
            "/usr/bin/systemctl", "show", "--property=ActiveState", "--value", "orchestra.service",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            async with asyncio.timeout(2):
                output, _ = await service.communicate()
        finally:
            if service.returncode is None:
                service.kill()
                await service.wait()
        if service.returncode or output.strip() not in (b"inactive", b"failed"):
            raise AcpSessionError("Orchestra must be stopped for ACP fallback")
        await _egress()

    def prompt_written(self):
        self.submitted.set()
        self.send({"method": "session/submitted", "params": {"sessionId": self.session_id}})
        if self.disconnected:
            asyncio.create_task(self.cancel())

    async def before_prompt_write(self):
        if self.disconnected:
            raise AcpSessionError("ACP caller disconnected before submission")

    async def cancel(self):
        if (self.prompt is None or self.prompt.done() or self.cancel_sent
                or not self.submitted.is_set() or self.owner.transport_generation != self.prompt_generation):
            return
        self.cancel_sent = True
        try:
            await asyncio.wait_for(self.owner.notify("session/cancel", {"sessionId": self.session_id}), 2)
        except (TimeoutError, AcpError, OSError):
            self.cancel_sent = False
            logger.warning("ACP mux cancel could not be written")

    def account(self, result):
        """Report deltas for this native step. A resumed unknown baseline stays unknown."""
        sid, owner = self.session_id, self.owner
        usage = result.get("usage")
        if not isinstance(usage, dict):
            usage = self.reported_usage
        values = {key: value for key in ("input_tokens", "output_tokens", "cache_read_tokens")
                  if (value := _cumulative_value(usage.get(key))) is not None}
        baseline = owner.usage_totals.get(sid)
        accounting = {}
        if baseline is not None:
            accounting = {key: value - baseline[key] if value >= baseline[key] else value
                          for key, value in values.items() if key in baseline}
        if values:
            owner.usage_totals[sid] = {**(baseline or {}), **values}
        cost = self.reported_cost
        if cost is not None:
            previous = owner.cost_totals.get(sid)
            if previous is not None:
                accounting["cost_usd"] = round(cost - previous if cost >= previous else cost, 6)
            owner.cost_totals[sid] = cost
        if "cost_usd" not in accounting or "input_tokens" not in accounting:
            from app.backend_antigravity import estimate_antigravity_turn_usage

            est = estimate_antigravity_turn_usage(
                str(getattr(self, "turn_model", "") or ""),
                context_tokens=getattr(self, "turn_context_used", None),
                tool_calls=int(getattr(self, "turn_tool_calls", 0) or 0),
                output_chars=int(getattr(self, "turn_output_chars", 0) or 0),
                thinking_chars=int(getattr(self, "turn_thinking_chars", 0) or 0),
                last_turn_at=getattr(self, "last_turn_at", None),
                now=time.time(),
            )
            if est is not None:
                accounting.setdefault("input_tokens", est["input_tokens"])
                accounting.setdefault("cache_read_tokens", est["cache_read_tokens"])
                accounting.setdefault("output_tokens", est["output_tokens"])
                accounting.setdefault("cost_usd", est["cost_usd"])
                accounting["accuracy"] = est["accuracy"]
                accounting["context_tokens"] = est["context_tokens"]
                accounting["warm_cache"] = est["warm"]
        self.last_turn_at = time.time()
        return accounting

    async def run_prompt(self, rpc_id, params):
        sid, owner = self.session_id, self.owner
        try:
            model = params.get("model")
            if not isinstance(model, str) or not MODEL.fullmatch(model):
                raise AcpSessionError("Requested ACP model is outside the Kesha catalog")
            blocks = params.get("blocks")
            if not isinstance(blocks, list):
                raise AcpSessionError("Invalid prompt blocks")
            cached = cached_profile(self.home)
            if not cached or cached.capabilities.get("promptCapabilities", {}).get("audio") is not True:
                blocks = [block for block in blocks if not isinstance(block, dict) or block.get("type") != "audio"]
            _validate_prompt(blocks)
            if not any(block["type"] == "text" and block["text"].strip() for block in blocks):
                raise AcpSessionError("ACP requires a nonempty text prompt")
            await _check_quota()
            event = params.get("turnId")
            if not isinstance(event, str) or not re.fullmatch(r"[a-f0-9]{32}", event):
                raise AcpSessionError("ACP requires a one-use turn ticket")
            await self.before_prompt_write()
            _reserve_turn(self.home, event, params["origin"], owner=self.owner_id, sid=sid)
            if owner is None:
                await self.attach()
                sid, owner = self.session_id, self.owner
            if owner.capabilities.get("promptCapabilities", {}).get("audio") is not True:
                blocks = [block for block in blocks if block["type"] != "audio"]
            logger.info("ACP mux origin=%s model=%s sid_hash=%s", params["origin"], model,
                        hashlib.sha256(sid.encode()).hexdigest()[:12])
            async with owner.session_lock(sid), owner.turn_slot(self):
                if (sid in owner.uncertain_sessions or owner.failure
                        or owner.transport_generation != self.prompt_generation
                        or owner.epoch != profile_epoch(self.home)):
                    raise AcpSessionError("ACP session unavailable; no prompt replay")
                owner._check_settings()
                await _egress()
                await select_model(owner, sid, model)
                if self.disconnected:
                    raise AcpSessionError("ACP caller disconnected before submission")
                owner.listeners[sid] = self.update
                owner.client_request_handlers[sid] = self.relay
                self.reported_usage = {}
                self.reported_cost = None
                self.turn_model = model
                self.turn_context_used = None
                self.turn_output_chars = 0
                self.turn_thinking_chars = 0
                self.turn_tool_calls = 0
                record_provider_activity("antigravity")
                try:
                    result = await owner.request(
                        "session/prompt", {"sessionId": sid, "prompt": blocks},
                        before_write=self.before_prompt_write, on_written=self.prompt_written,
                    )
                finally:
                    record_provider_activity("antigravity")
                self.send({"id": rpc_id, "result": {"stopReason": result.get("stopReason"),
                                                    "accounting": self.account(result)}})
        except asyncio.CancelledError:
            if owner and self.submitted.is_set() and owner.transport_generation == self.prompt_generation:
                owner.uncertain_sessions.add(sid)
            raise
        except Exception as exc:
            from app.antigravity_acp import AcpQuotaCooldownError
            from app.provider_safety import get_antigravity_cooldown

            if isinstance(exc, AcpQuotaCooldownError):
                self.send({"id": rpc_id, "error": str(exc)})
                return
            if isinstance(exc, AcpSessionError) and "антибан-стоп" in str(exc):
                self.send({"id": rpc_id, "error": str(exc)})
                return
            if (cd := get_antigravity_cooldown()) is not None:
                self.send({"id": rpc_id, "error": cd["message"]})
                return
            if not isinstance(exc, AcpError):
                logger.error("ACP mux prompt failure (%s)", type(exc).__name__)
            uncertain = str(exc) == "uncertain_session" or bool(owner and sid in owner.uncertain_sessions)
            self.send({"id": rpc_id, "error": "uncertain_session" if uncertain else
                       "ACP turn refused or interrupted; no prompt replay"})
        finally:
            if owner and owner.listeners.get(sid) == self.update:
                owner.listeners.pop(sid)
                owner.client_request_handlers.pop(sid, None)

    def schedule_idle_release(self):
        owner, sid = self.owner, self.session_id
        async def release():
            await asyncio.sleep(300)
            while owner.mux_idle_tasks.get(sid) is asyncio.current_task():
                async with owner._setup_lock:
                    if sid in owner.mux_leases or sid not in owner.sessions:
                        return
                    if sid not in owner.uncertain_sessions:
                        await owner.release_session(sid)
                        return
                await asyncio.sleep(60)
        task = asyncio.create_task(release())
        old = owner.mux_idle_tasks.get(sid)
        if old:
            old.cancel()
        owner.mux_idle_tasks[sid] = task

        def done(finished):
            if owner.mux_idle_tasks.get(sid) is finished:
                owner.mux_idle_tasks.pop(sid)
            if not finished.cancelled() and finished.exception() is not None:
                logger.error("ACP mux idle release failed (%s)", type(finished.exception()).__name__)

        task.add_done_callback(done)

    async def serve(self, reader):
        try:
            if not _trusted_peer(self.writer, self.home):
                return
            while line := await reader.readline():
                if not self.audio_allowed and len(line) > 1024 * 1024:
                    raise ValueError("ACP mux frame exceeds negotiated capacity")
                msg = json.loads(line)
                if not isinstance(msg, dict):
                    continue
                rpc_id = msg.get("id")
                method, params = msg.get("method"), msg.get("params", {})
                if method is None:
                    pending = self.pending.get(rpc_id)
                    if pending is not None:
                        request_method, future = pending
                        if future.done():
                            continue
                        if request_method == "session/request_permission":
                            option = msg.get("optionId")
                            outcome = ({"outcome": "selected", "optionId": option}
                                       if isinstance(option, str) else {"outcome": "cancelled"})
                            future.set_result({"result": {"outcome": outcome}})
                        else:
                            future.set_result({"error": {"code": -32601, "message": "Filesystem RPC unavailable"}})
                    continue
                try:
                    if not isinstance(params, dict):
                        self.send({"id": rpc_id, "error": {"code": -32602, "message": "Invalid params"}})
                        continue
                    if method == "session/open":
                        result = await self.open(params)
                    elif self.origin is None or params.get("sessionId") != self.session_id:
                        raise AcpSessionError("ACP session is not attached to this connection")
                    elif method == "session/cancel":
                        # A steer can arrive before the first prompt is written.
                        if self.prompt and not self.prompt.done() and not self.submitted.is_set():
                            # Do not cancel setup. The client retries on the prompt-start notification.
                            result = {"submitted": False}
                        else:
                            await self.cancel()
                            result = {"submitted": self.submitted.is_set()}
                    elif self.prompt and not self.prompt.done():
                        raise AcpSessionError("ACP connection already has an active turn")
                    elif method == "session/prompt":
                        expected = "telegram" if self.steps else self.origin
                        if params.get("origin") != expected:
                            raise AcpSessionError("ACP prompt origin refused")
                        self.steps += 1
                        self.submitted.clear()
                        self.cancel_sent = False
                        self.prompt = asyncio.create_task(self.run_prompt(rpc_id, params))
                        continue
                    elif method == "session/close":
                        owner = cached_profile(self.home)
                        if owner is not None and self.session_id is not None:
                            async with owner._setup_lock:
                                bind_session(owner, self.session_id, self.owner_id, resume=True)
                                if self.session_id not in owner.mux_leases or self.owner is owner:
                                    await owner.release_session(self.session_id)
                        self.closed_session = True
                        result = {}
                    else:
                        raise AcpSessionError("Unsupported ACP mux operation")
                    self.send({"id": rpc_id, "result": result})
                except (AcpError, OSError, KeyError, RuntimeError, ValueError):
                    self.send({"id": rpc_id, "error": "ACP request refused; check provider and session state"})
                if self.closed_session or self.writer.is_closing():
                    break
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        finally:
            self.disconnected = True
            try:
                if self.prompt and not self.prompt.done():
                    await self.cancel()
                    try:
                        await asyncio.wait_for(asyncio.shield(self.prompt), 3)
                    except TimeoutError:
                        await self.cancel()
                        # Retain the profile task and its permit until the native
                        # terminal or watchdog. Local EOF is not proof of cancellation.
                        if self.fallback:
                            self.prompt.cancel()
                            await asyncio.gather(self.prompt, return_exceptions=True)
                        else:
                            await asyncio.shield(self.prompt)
            finally:
                if self.owner is not None and self.prompt_generation is not None:
                    self.owner.mux_leases.discard(self.session_id)
                    if not self.fallback and not self.closed_session:
                        self.schedule_idle_release()
                self.writer.close()
                try:
                    await asyncio.wait_for(self.writer.wait_closed(), 2)
                except (TimeoutError, OSError):
                    self.writer.transport.abort()


async def _inactive_socket(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return True
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
        raise AcpError("Unexpected ACP mux socket path")
    try:
        _, writer = await asyncio.wait_for(asyncio.open_unix_connection(path), 0.5)
    except OSError as error:
        if error.errno in (errno.ENOENT, errno.ECONNREFUSED):
            return True
        raise
    writer.close()
    await writer.wait_closed()
    return False


class AcpMux:
    def __init__(self, home):
        self.home = home
        self.path = home / SOCKET_NAME
        self.server = None
        self.connections = {}

    async def start(self):
        _directory(self.home)
        # Python 3.12 does not unlink Unix server sockets on close. Binding a
        # stale path is serialized across Orchestra processes with a socket lock.
        import fcntl
        self.fd = os.open(self.home / ".acp-mux-listener.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if not await _inactive_socket(self.path):
                raise AcpError("ACP mux listener already active")
            self.path.unlink(missing_ok=True)
            self.server = await asyncio.start_unix_server(self.accept, self.path, limit=MAX_FRAME,
                                                          start_serving=False)
            self.path.chmod(0o600)
            await self.server.start_serving()
        except BaseException:
            if self.server:
                self.server.close()
                await self.server.wait_closed()
                self.path.unlink(missing_ok=True)
            os.close(self.fd)
            raise

    def accept(self, reader, writer):
        if len(self.connections) >= 32:
            writer.close()
            return
        task = asyncio.create_task(Connection(self.home, writer).serve(reader))
        self.connections[task] = writer
        def done(finished):
            self.connections.pop(finished, None)
            if not finished.cancelled():
                error = finished.exception()
                if error is not None:
                    logger.error("ACP mux connection failed (%s)", type(error).__name__)
        task.add_done_callback(done)

    async def close(self):
        self.server.close()
        connections = list(self.connections.items())
        for _, writer in connections:
            writer.close()
        try:
            await asyncio.wait_for(self.server.wait_closed(), 3)
        except TimeoutError:
            for _, writer in connections:
                writer.transport.abort()
        if connections:
            _, remaining = await asyncio.wait([task for task, _ in connections], timeout=5)
            # A shutdown can retire the daemon, so bounded mux shutdown may
            # cancel its remaining tasks. AcpProfile closes immediately after.
            for task in remaining:
                task.cancel()
            await asyncio.gather(*(task for task, _ in connections), return_exceptions=True)
        self.path.unlink(missing_ok=True)
        os.close(self.fd)


async def _fallback(fd):
    from app.antigravity_acp import shutdown_profiles
    from app.backend_antigravity import canonical_profile
    from app.routes.system import hydrate_antigravity_quota
    hydrate_antigravity_quota()
    home = canonical_profile()
    _directory(home)
    reader, writer = await asyncio.open_unix_connection(sock=socket.socket(fileno=fd), limit=MAX_FRAME)
    connection = Connection(home, writer, fallback=True)
    loop = asyncio.get_running_loop()
    # Closing the control socket first lets the common cancellation path run.
    loop.add_signal_handler(signal.SIGTERM, writer.close)
    try:
        await connection.serve(reader)
    finally:
        await shutdown_profiles()


if __name__ == "__main__":
    os.environ["ALLOW_DATACENTER_OAUTH_EGRESS"] = "0"
    os.environ["AGY_ALLOW_WHEN_DISABLED"] = "0"
    os.environ["ORCHESTRA_AGY_SPAWNER_SOCK"] = str(SPAWNER)
    os.environ["ANTIGRAVITY_CLEAN_SHELL"] = str(CLEAN_SHELL)
    asyncio.run(_fallback(int(sys.argv[1])))
