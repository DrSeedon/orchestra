"""Official agy CLI: isolated HOME, one NDJSON process per Orchestra turn."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import signal
import time
from datetime import datetime
from pathlib import Path

from app.antigravity_auth import (
    TOKEN_RELATIVE_PATH, atomic_private_write, private_directory, read_auth_snapshot,
)
from app.events import AgentEvent
from app.usage_contract import AggregateUsage, TurnUsage, UnknownContext

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
ANTIGRAVITY_BIN = os.environ.get("ANTIGRAVITY_BIN", "agy")
ANTIGRAVITY_AUTH_HOME = ROOT / "data/antigravity-auth-home"
ANTIGRAVITY_HOME_ROOT = ROOT / "data/antigravity-homes"
QUOTA_KEYS = ("gemini-weekly", "3p-weekly")
_probe_lock = asyncio.Lock()
_probe_cache: dict = {}


def cli_environment(home: Path) -> dict:
    """Keep the OAuth route explicit even when the service has other Google routes."""
    excluded = {"GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS",
                "GOOGLE_GENAI_USE_VERTEXAI"}
    return {**{key: value for key, value in os.environ.items() if key not in excluded},
            "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "XDG_DATA_HOME": str(home / ".local/share")}


def normalize_antigravity_quota(raw: object) -> dict:
    result = dict.fromkeys(QUOTA_KEYS)
    if not isinstance(raw, dict) or raw.get("status") != "SUCCESS":
        return result
    command = raw.get("command")
    data = command.get("data") if isinstance(command, dict) else None
    groups = data.get("groups") if isinstance(data, dict) else None
    if not isinstance(groups, list):
        return result
    seen = set()
    for group in groups:
        buckets = group.get("buckets") if isinstance(group, dict) else None
        for bucket in buckets if isinstance(buckets, list) else []:
            if not isinstance(bucket, dict):
                continue
            key = bucket.get("id")
            if not isinstance(key, str) or key not in result:
                continue
            if key in seen:
                result[key] = None
                continue
            seen.add(key)
            fraction = bucket.get("remaining_fraction")
            reset = bucket.get("reset_time")
            if (isinstance(fraction, bool) or not isinstance(fraction, (int, float))
                    or not math.isfinite(fraction) or not 0 <= fraction <= 1
                    or bucket.get("window") != "weekly"):
                continue
            if reset is not None:
                try:
                    if not isinstance(reset, str) or datetime.fromisoformat(
                        reset.replace("Z", "+00:00")
                    ).tzinfo is None:
                        continue
                except ValueError:
                    continue
            result[key] = {"remaining_fraction": fraction, "reset_time": reset}
    return result


def supported_version(value: str) -> bool:
    match = re.search(r"\b(\d+)\.(\d+)\.(\d+)\b", value)
    return bool(match and tuple(map(int, match.groups())) >= (1, 1, 12))


async def _cli(*args: str, home: Path) -> dict | str:
    """Bounded, noninteractive official CLI probe; never expose raw vendor stderr."""
    process = await asyncio.create_subprocess_exec(
        ANTIGRAVITY_BIN, *args, env=cli_environment(home),
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, start_new_session=True,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), 10)
    except BaseException:
        if process.returncode is None:
            os.killpg(process.pid, signal.SIGKILL)
        await process.wait()
        raise
    if process.returncode:
        # JSON failures are handled by the readiness adapter without echoing credentials.
        try:
            raw = json.loads(stdout)
        except (ValueError, UnicodeError):
            raise RuntimeError("Antigravity CLI probe failed") from None
        if isinstance(raw, dict):
            return raw
        raise RuntimeError("Antigravity CLI probe failed")
    if args == ("--version",):
        return stdout.decode(errors="replace").strip()
    result = json.loads(stdout)
    if not isinstance(result, dict):
        raise RuntimeError("Antigravity probe returned an invalid object")
    return result


def catalog_models(raw: dict) -> set[str]:
    if raw.get("status") != "SUCCESS":
        return set()
    command = raw.get("command", {})
    data = command.get("data", {}) if isinstance(command, dict) else {}
    rows = data.get("models", []) if isinstance(data, dict) else []
    return {row["id"] for row in rows if isinstance(row, dict)
            and isinstance(row.get("id"), str)} if isinstance(rows, list) else set()


def _publish_quota(quota: dict, observed: float, generation: str) -> None:
    from app.routes import system
    system._antigravity_usage_cache.update(data=quota, ts=observed, generation=generation)


async def fetch_antigravity_usage() -> dict:
    from app.routes import system

    async with _probe_lock:
        snapshot = read_auth_snapshot(ANTIGRAVITY_AUTH_HOME)
        cached = system._antigravity_usage_cache
        if (cached.get("generation") == snapshot.generation and cached.get("data")
                and 0 <= time.time() - cached.get("ts", 0) < 300):
            return cached["data"]
        raw = await _cli("--output-format", "json", "-p", "/quota",
                         home=ANTIGRAVITY_AUTH_HOME)
        quota = normalize_antigravity_quota(raw)
        if not any(quota.values()):
            raise RuntimeError("Antigravity quota unavailable")
        _publish_quota(quota, time.time(), snapshot.generation)
        return quota


async def antigravity_readiness(context):
    from app.runtime_registry import RuntimeReadinessResult

    try:
        snapshot = read_auth_snapshot(ANTIGRAVITY_AUTH_HOME)
    except (OSError, ValueError):
        return RuntimeReadinessResult(False, False, "Antigravity OAuth credential missing")
    key = (str(ANTIGRAVITY_BIN), str(ANTIGRAVITY_AUTH_HOME), snapshot.generation)
    async with _probe_lock:
        cached = _probe_cache.get(key)
        if cached is None or time.monotonic() - cached[0] >= 30:
            try:
                version = await _cli("--version", home=ANTIGRAVITY_AUTH_HOME)
                if not isinstance(version, str) or not supported_version(version):
                    return RuntimeReadinessResult(False, False, "Antigravity requires CLI >= 1.1.12")
                raw_quota = await _cli("--output-format", "json", "-p", "/quota",
                                       home=ANTIGRAVITY_AUTH_HOME)
                quota = normalize_antigravity_quota(raw_quota)
                if not all(quota.values()):
                    return RuntimeReadinessResult(False, False, "Antigravity authentication or quota probe failed")
                raw_catalog = await _cli("--output-format", "json", "models",
                                         home=ANTIGRAVITY_AUTH_HOME)
                models = catalog_models(raw_catalog)
                _publish_quota(quota, time.time(), snapshot.generation)
                cached = (time.monotonic(), models)
                _probe_cache[key] = cached
            except (OSError, ValueError, RuntimeError, TimeoutError):
                return RuntimeReadinessResult(False, False, "Antigravity CLI credential/catalog probe failed")
        available = context.model.removeprefix("antigravity/") in cached[1]
        return RuntimeReadinessResult(True, available,
                                      "" if available else "Requested Antigravity model is absent from live catalog")


class AntigravityBackend:
    def __init__(self, context):
        self.model = context.model.removeprefix("antigravity/")
        self.cwd = context.cwd
        self.system_prompt = context.system_prompt
        self.mcp_servers = context.mcp_servers
        self.context_limit = context.context_limit
        self.session_id = context.resume_session_id
        session = self.mcp_servers.get("orchestra", {}).get("env", {}).get("ORCHESTRA_SESSION_ID")
        if not isinstance(session, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", session):
            raise ValueError("Antigravity requires a trusted ORCHESTRA_SESSION_ID")
        self.home = Path(ANTIGRAVITY_HOME_ROOT) / session
        self._generation = None
        self._process = None
        self._task = None
        self._queue = asyncio.Queue()
        self._interrupted = False
        self._stderr_values = sorted({str(value) for cfg in self.mcp_servers.values()
                                      for value in cfg.get("env", {}).values() if value},
                                     key=len, reverse=True)
        self._secrets = sorted({str(value) for cfg in self.mcp_servers.values()
                                for key, value in cfg.get("env", {}).items()
                                if value and re.search(r"TOKEN|SECRET|PASSWORD|KEY|COOKIE|AUTH|DSN", key, re.I)},
                               key=len, reverse=True)

    @property
    def is_alive(self):
        return self._process is not None and self._process.returncode is None

    def _redact(self, text: object, *, all_env=False) -> str:
        result = str(text)
        for value in self._stderr_values if all_env else self._secrets:
            result = result.replace(value, "[redacted]")
        return re.sub(r"ya29\.[A-Za-z0-9_-]+", "[redacted]", result)

    async def connect(self):
        private_directory(self.home)
        atomic_private_write(self.home / ".gemini/config/agents/orchestra/agent.md", (
            "---\nname: orchestra\nmainAgent: true\nsubagent: false\ninheritMcp: true\n"
            "commandExecutionPolicy: always-proceed\n---\n" + self.system_prompt
        ).encode())
        atomic_private_write(self.home / ".gemini/antigravity-cli/settings.json", json.dumps({
            "useG1Credits": False,
            "permission": {"allow": ["command(*)", "read_file(*)", "write_file(*)", "mcp(*)"]}
        }).encode())
        atomic_private_write(self.home / ".gemini/config/config.json", json.dumps({
            "userSettings": {"useAiCredits": False}
        }).encode())
        atomic_private_write(self.home / ".gemini/config/mcp_config.json",
                             json.dumps({"mcpServers": self.mcp_servers}).encode())

    def _end(self, *, ok=False, reason="error", error=None, usage=None):
        aggregate = AggregateUsage.normalized(**{
            key: (usage or {}).get(key, 0) for key in
            ("input_tokens", "output_tokens", "cache_read_tokens")
        })
        typed = TurnUsage(aggregate, UnknownContext(
            self.context_limit, "Antigravity did not report current-context semantics"))
        metadata = {
            "session_id": self.session_id, "ok": ok, "stop_reason": reason,
            "cost_usd": 0.0, "cost_unaccounted": True,
            "input_tokens": aggregate.input_tokens, "output_tokens": aggregate.output_tokens,
            "cached_input_tokens": aggregate.cache_read_tokens,
            "cache_read": aggregate.cache_read_tokens, "cache_create": 0,
        }
        if error:
            metadata.update(model_error=error, errors=[error])
        return AgentEvent("turn_end", metadata=metadata, usage=typed)

    async def send(self, message):
        if self._task is not None and not self._task.done():
            raise RuntimeError("Antigravity turn is already active")
        self._queue = asyncio.Queue()
        self._interrupted = False
        try:
            snapshot = read_auth_snapshot(ANTIGRAVITY_AUTH_HOME)
            state_file = self.home / "orchestra-conversation.json"
            if self._generation is None and state_file.is_file():
                try:
                    state = json.loads(state_file.read_text())
                except (OSError, ValueError):
                    state = {}
                if not isinstance(state, dict):
                    state = {}
                if state.get("model") != self.model or state.get("generation") != snapshot.generation:
                    self.session_id = None
            if self._generation is not None and snapshot.generation != self._generation:
                self.session_id = None
            self._generation = snapshot.generation
            atomic_private_write(state_file, json.dumps({
                "generation": self._generation, "model": self.model,
                "conversation_id": self.session_id,
            }).encode())
            atomic_private_write(self.home / TOKEN_RELATIVE_PATH, snapshot.token)
            args = [ANTIGRAVITY_BIN, "--output-format", "stream-json", "--model", self.model,
                    "--agent", "orchestra", "--add-dir", self.cwd]
            if self.session_id:
                args.extend(["--conversation", self.session_id])
            args.extend(["-p", str(message)])
            self._process = await asyncio.create_subprocess_exec(
                *args, cwd=self.cwd, env=cli_environment(self.home),
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, start_new_session=True,
                limit=1024 * 1024,
            )
        except (OSError, ValueError) as exc:
            (self.home / TOKEN_RELATIVE_PATH).unlink(missing_ok=True)
            self._queue.put_nowait(AgentEvent("error", "Antigravity credential/startup failure: " + self._redact(exc)))
            self._queue.put_nowait(self._end(reason="credentials", error="credentials"))
            self._queue.put_nowait(None)
            return
        self._task = asyncio.create_task(self._consume())

    async def _stderr(self, process):
        # Drain all output even without newlines. Never log a partial unredacted value.
        retained = bytearray()
        while chunk := await process.stderr.read(4096):
            if len(retained) < 65536:
                retained.extend(chunk[:65536 - len(retained)])
        if retained:
            logger.debug("Antigravity stderr: %s", self._redact(retained.decode(errors="replace"), all_env=True))

    async def _consume(self):
        process = self._process
        stderr = asyncio.create_task(self._stderr(process))
        terminal = None
        tool_failed = False
        try:
            async for line in process.stdout:
                try:
                    raw = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                if not isinstance(raw, dict):
                    continue
                kind = raw.get("event")
                if kind == "init":
                    self.session_id = raw.get("conversation_id") or self.session_id
                elif kind == "step_update":
                    step = raw.get("step_update", {})
                    if step.get("step_type") == "agent_response" and step.get("text_delta"):
                        self._queue.put_nowait(AgentEvent("stream", self._redact(step["text_delta"])))
                    elif step.get("step_type") == "tool":
                        info = step.get("tool_info", {})
                        tool_id = f"agy-step-{step.get('step_index')}"
                        meta = {"tool_use_id": tool_id, "tool_name": step.get("tool_name", "tool")}
                        if step.get("state") == "ACTIVE":
                            meta["input"] = json.loads(self._redact(json.dumps(info.get("parameters", {}))))
                            self._queue.put_nowait(AgentEvent("tool_use", meta["tool_name"], meta))
                        elif step.get("state") in {"DONE", "ERROR"}:
                            failed = step.get("state") == "ERROR" or bool(info.get("error"))
                            tool_failed |= failed
                            value = info.get("error") if failed else info.get("output", "")
                            text = self._redact(value if isinstance(value, str) else json.dumps(value))
                            self._queue.put_nowait(AgentEvent("tool_result", text, {**meta, "is_error": failed}))
                            if failed:
                                self._queue.put_nowait(AgentEvent("error", text))
                elif kind == "result":
                    terminal = raw.get("result", {})
            await process.wait()
            await stderr
            if self._interrupted:
                end = self._end(reason="interrupt", error="interrupted")
            elif terminal is None:
                self._queue.put_nowait(AgentEvent("error", "Antigravity exited without a terminal result"))
                end = self._end(error="protocol")
            else:
                self.session_id = terminal.get("conversation_id") or self.session_id
                ok = terminal.get("status") == "SUCCESS" and process.returncode == 0
                reason, error = "end_turn", None
                if not ok:
                    text = self._redact(terminal.get("error") or "Antigravity turn failed")
                    lower = text.lower()
                    if any(word in lower for word in ("auth", "oauth", "token", "credential", "eligib", "location")):
                        error = "credentials"
                    elif "quota" in lower or "rate limit" in lower:
                        error = "quota"
                    else:
                        error = "model"
                    reason = error
                    self._queue.put_nowait(AgentEvent("error", text))
                if tool_failed:
                    ok, reason, error = False, "tool_error", error or "tool_error"
                if terminal.get("response"):
                    self._queue.put_nowait(AgentEvent("text", self._redact(terminal["response"])))
                end = self._end(ok=ok, reason=reason, error=error, usage=terminal.get("usage"))
                atomic_private_write(self.home / "orchestra-conversation.json", json.dumps({
                    "generation": self._generation, "model": self.model,
                    "conversation_id": self.session_id,
                }).encode())
            self._queue.put_nowait(end)
        except Exception as exc:
            self._queue.put_nowait(AgentEvent("error", "Antigravity stream failure: " + self._redact(exc)))
            self._queue.put_nowait(self._end(error="protocol"))
        finally:
            if process.returncode is None:
                os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
            if not stderr.done():
                stderr.cancel()
            await asyncio.gather(stderr, return_exceptions=True)
            (self.home / TOKEN_RELATIVE_PATH).unlink(missing_ok=True)
            self._queue.put_nowait(None)

    async def events(self):
        while (event := await self._queue.get()) is not None:
            yield event

    async def interrupt(self):
        if not self.is_alive:
            return False
        self._interrupted = True
        try:
            os.killpg(self._process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(self._process.wait(), 2)
        except TimeoutError:
            os.killpg(self._process.pid, signal.SIGKILL)
            await self._process.wait()
        if self._task:
            await self._task
        return True

    async def disconnect(self):
        await self.interrupt()
        if self._task:
            await self._task
