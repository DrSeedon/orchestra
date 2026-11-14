"""Official agy CLI: isolated HOME, one NDJSON process per Orchestra turn."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import signal
import sqlite3
import time
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path

from app.antigravity_auth import (
    TOKEN_RELATIVE_PATH, atomic_private_write, private_directory, read_auth_snapshot,
)
from app.events import AgentEvent
from app.usage_contract import (
    AggregateUsage, KnownContext, TurnUsage, UnknownContext, current_context,
)

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
ANTIGRAVITY_BIN = os.environ.get("ANTIGRAVITY_BIN", "agy")
ANTIGRAVITY_AUTH_HOME = ROOT / "data/antigravity-auth-home"
ANTIGRAVITY_HOME_ROOT = ROOT / "data/antigravity-homes"
QUOTA_KEYS = ("gemini-weekly", "3p-weekly")
FIVE_HOUR_QUOTA_KEYS = ("gemini-5h", "3p-5h")

# Official Google AI Studio / Vertex AI API-equivalent rates per 1M tokens
# (Nov 2026 promo through Nov 30, 2026: Carbon/Argon $2/$10, cached 95% off = $0.10;
# Hydrogen $1.50/$7.50, cached $0.075). Note: agy usage.output_tokens already includes
# thinking_tokens, and usage.input_tokens excludes cache_read_tokens.
ANTIGRAVITY_TOKEN_PRICES: dict[str, dict[str, float]] = {
    "gemini-4-carbon-high": {"input": 2.0, "cached": 0.10, "output": 10.0},
    "gemini-4-carbon-medium": {"input": 2.0, "cached": 0.10, "output": 10.0},
    "gemini-4-carbon-low": {"input": 2.0, "cached": 0.10, "output": 10.0},
    "gemini-pro-orchestrator": {"input": 2.0, "cached": 0.10, "output": 10.0},
    "gemini-4-argon-high": {"input": 2.0, "cached": 0.10, "output": 10.0},
    "gemini-4-argon-medium": {"input": 2.0, "cached": 0.10, "output": 10.0},
    "gemini-4-argon-low": {"input": 2.0, "cached": 0.10, "output": 10.0},
    "gemini-pro-orchestrator-argon": {"input": 2.0, "cached": 0.10, "output": 10.0},
    "gemini-4-hydrogen-xhigh": {"input": 1.5, "cached": 0.075, "output": 7.5},
    "gemini-4-hydrogen-high": {"input": 1.5, "cached": 0.075, "output": 7.5},
    "gemini-4-hydrogen-medium": {"input": 1.5, "cached": 0.075, "output": 7.5},
    "gemini-4-hydrogen-low": {"input": 1.5, "cached": 0.075, "output": 7.5},
    "gemini-3.8-flash-high": {"input": 0.30, "cached": 0.03, "output": 2.50},
    "gemini-3.8-flash-medium": {"input": 0.30, "cached": 0.03, "output": 2.50},
    "gemini-3.8-flash-low": {"input": 0.30, "cached": 0.03, "output": 2.50},
    "claude-opus-5-5-high": {"input": 4.0, "cached": 0.20, "output": 20.0},
    "claude-opus-5-5-medium": {"input": 4.0, "cached": 0.20, "output": 20.0},
    "claude-opus-5-5-low": {"input": 4.0, "cached": 0.20, "output": 20.0},
    "claude-sonnet-5-5-high": {"input": 2.0, "cached": 0.10, "output": 10.0},
    "claude-sonnet-5-5-medium": {"input": 2.0, "cached": 0.10, "output": 10.0},
    "claude-sonnet-5-5-low": {"input": 2.0, "cached": 0.10, "output": 10.0},
}


def _antigravity_cost(
    raw_model: str, input_tokens: int, cache_read_tokens: int, output_tokens: int
) -> float | None:
    prices = ANTIGRAVITY_TOKEN_PRICES.get(raw_model)
    if prices is None:
        return None
    fresh_in = max(0, input_tokens)
    cached_in = max(0, cache_read_tokens)
    out = max(0, output_tokens)
    return round(
        (fresh_in * prices["input"] + cached_in * prices["cached"] + out * prices["output"])
        / 1_000_000,
        6,
    )


def _protobuf_fields(data: bytes) -> dict[int, int | bytes]:
    """Decode the small metadata envelope without a generated protobuf dependency."""
    offset = 0

    def varint() -> int:
        nonlocal offset
        value = 0
        for shift in range(0, 70, 7):
            if offset >= len(data):
                break
            byte = data[offset]
            offset += 1
            if shift == 63 and byte > 1:
                break
            value |= (byte & 127) << shift
            if byte < 128:
                return value
        raise ValueError("invalid metadata varint")

    fields = {}
    while offset < len(data):
        tag = varint()
        field, wire = tag >> 3, tag & 7
        if not 0 < field < 2**29:
            raise ValueError("invalid metadata field")
        if wire == 0:
            fields[field] = varint()
        elif wire in {1, 2, 5}:
            length = varint() if wire == 2 else (8 if wire == 1 else 4)
            end = offset + length
            if end > len(data):
                raise ValueError("truncated metadata field")
            if wire == 2:
                fields[field] = data[offset:end]
            offset = end
        else:
            raise ValueError("unsupported metadata wire type")
    return fields


def _conversation_context(home: Path, conversation_id: str | None,
                          context_limit: int) -> KnownContext | UnknownContext:
    unknown = UnknownContext(
        context_limit, "Antigravity did not report current-context semantics")
    if not isinstance(conversation_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", conversation_id):
        return unknown
    database = home / ".gemini/antigravity-cli/conversations" / f"{conversation_id}.db"
    try:
        # mode=ro never creates a missing conversation; keep lock waits bounded.
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True,
                                     timeout=0.1)) as connection:
            row = connection.execute(
                "SELECT CASE WHEN length(data) <= 1048576 THEN data END "
                "FROM gen_metadata ORDER BY idx DESC LIMIT 1"
            ).fetchone()
        if not row or not isinstance(row[0], bytes):
            return unknown
        payload = row[0]
        for field in (1, 9, 10):
            payload = _protobuf_fields(payload)[field]
            if not isinstance(payload, bytes):
                return unknown
        context = _protobuf_fields(payload)
        used, maximum = context.get(1), context.get(4)
        if not isinstance(used, int) or not isinstance(maximum, int):
            return unknown
        return current_context(used, maximum)
    except (OSError, sqlite3.Error, KeyError, ValueError):
        return unknown


def _cumulative_value(value: object, *, integer=True) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        if not math.isfinite(value) or value < 0 or (integer and int(value) != value):
            return None
    except OverflowError:
        return None
    return int(value) if integer else value


_probe_lock = asyncio.Lock()
_probe_cache: dict = {}


_LOCAL_NO_PROXY = ("localhost", "127.0.0.1", "::1")


def _merge_no_proxy(existing: str) -> str:
    from app.provider_safety import sanitize_no_proxy

    return sanitize_no_proxy(existing)


def _is_account_disabled_payload(value: object) -> bool:
    from app.provider_safety import is_account_ban_payload

    return is_account_ban_payload(value) is not None


def _trip_antigravity_circuit_breaker(reason: str) -> None:
    from app.provider_safety import trip_provider_circuit_breaker

    trip_provider_circuit_breaker("antigravity", reason)


def cli_environment(home: Path) -> dict:
    """Keep the OAuth route explicit even when the service has other Google routes."""
    from app.provider_safety import build_provider_env

    env = build_provider_env("antigravity")
    env.update({
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_DATA_HOME": str(home / ".local/share"),
    })
    return env


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


def normalize_antigravity_five_hour_quota(raw: object) -> dict:
    result = dict.fromkeys(FIVE_HOUR_QUOTA_KEYS)
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
            if (
                isinstance(fraction, bool)
                or not isinstance(fraction, (int, float))
                or not math.isfinite(fraction)
                or not 0 <= fraction <= 1
                or bucket.get("window") != "5h"
            ):
                continue
            if reset is not None:
                try:
                    if (
                        not isinstance(reset, str)
                        or datetime.fromisoformat(reset.replace("Z", "+00:00")).tzinfo is None
                    ):
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
            if _is_account_disabled_payload(raw):
                _trip_antigravity_circuit_breaker("CLI probe returned account disabled / Terms of Service")
            return raw
        raise RuntimeError("Antigravity CLI probe failed")
    if args == ("--version",):
        return stdout.decode(errors="replace").strip()
    result = json.loads(stdout)
    if not isinstance(result, dict):
        raise RuntimeError("Antigravity probe returned an invalid object")
    if _is_account_disabled_payload(result):
        _trip_antigravity_circuit_breaker("CLI probe returned account disabled / Terms of Service")
    return result


def catalog_models(raw: dict) -> set[str]:
    if raw.get("status") != "SUCCESS":
        return set()
    command = raw.get("command", {})
    data = command.get("data", {}) if isinstance(command, dict) else {}
    rows = data.get("models", []) if isinstance(data, dict) else []
    return {row["id"] for row in rows if isinstance(row, dict)
            and isinstance(row.get("id"), str)} if isinstance(rows, list) else set()


def _publish_quota(
    quota: dict, observed: float, generation: str, five_hour: dict | None = None
) -> None:
    from app.routes import system
    system._antigravity_usage_cache.update(
        data=quota, five_hour=five_hour, ts=observed, generation=generation
    )


async def fetch_antigravity_usage() -> dict:
    from app.models import is_provider_disabled
    from app.provider_safety import verify_provider_egress
    from app.routes import system

    if is_provider_disabled("antigravity"):
        raise RuntimeError("Antigravity provider is disabled")
    await verify_provider_egress("antigravity")
    async with _probe_lock:
        if is_provider_disabled("antigravity"):
            raise RuntimeError("Antigravity provider is disabled")
        snapshot = read_auth_snapshot(ANTIGRAVITY_AUTH_HOME)
        cached = system._antigravity_usage_cache
        if (cached.get("generation") == snapshot.generation and cached.get("data")
                and 0 <= time.time() - cached.get("ts", 0) < 1800):
            return cached["data"]
        raw = await _cli("--output-format", "json", "-p", "/quota",
                         home=ANTIGRAVITY_AUTH_HOME)
        quota = normalize_antigravity_quota(raw)
        if not any(quota.values()):
            raise RuntimeError("Antigravity quota unavailable")
        _publish_quota(
            quota, time.time(), snapshot.generation, normalize_antigravity_five_hour_quota(raw)
        )
        return quota


_READINESS_CACHE_TTL_SECONDS = 1800.0


async def antigravity_readiness(context):
    from app.models import is_provider_disabled
    from app.provider_safety import EgressSafetyError, ProviderDisabledError, verify_provider_egress
    from app.runtime_registry import RuntimeReadinessResult

    if is_provider_disabled("antigravity"):
        return RuntimeReadinessResult(False, False, "Antigravity provider is disabled")
    try:
        await verify_provider_egress("antigravity")
    except (ProviderDisabledError, EgressSafetyError) as exc:
        return RuntimeReadinessResult(False, False, str(exc))
    try:
        snapshot = read_auth_snapshot(ANTIGRAVITY_AUTH_HOME)
    except (OSError, ValueError):
        return RuntimeReadinessResult(False, False, "Antigravity OAuth credential missing")
    key = (str(ANTIGRAVITY_BIN), str(ANTIGRAVITY_AUTH_HOME), snapshot.generation)
    async with _probe_lock:
        if is_provider_disabled("antigravity"):
            return RuntimeReadinessResult(False, False, "Antigravity provider is disabled")
        cached = _probe_cache.get(key)
        if cached is None or time.monotonic() - cached[0] >= _READINESS_CACHE_TTL_SECONDS:
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
                _publish_quota(quota, time.time(), snapshot.generation, normalize_antigravity_five_hour_quota(raw_quota))
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
        self._cumulative = {}
        self._baseline_key = None
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
            "---\n"
            "name: orchestra\n"
            "description: Orchestra session agent\n"
            "mainAgent: true\n"
            "subagent: false\n"
            "inheritMcp: true\n"
            "commandExecutionPolicy: eager  # commandExecutionPolicy: always-proceed\n"
            "tools:\n"
            "  - read_file\n"
            "  - edit_file\n"
            "  - write_file\n"
            "  - run_command\n"
            "  - manage_task\n"
            "  - search_web\n"
            "---\n\n"
            "# Agent System Instructions\n\n"
            + self.system_prompt
        ).encode())
        atomic_private_write(self.home / ".gemini/antigravity-cli/settings.json", json.dumps({
            "useG1Credits": False,
            "toolPermission": "always-proceed",
            "allowNonWorkspaceAccess": True,
            "permission": {"allow": ["command(*)", "read_file(*)", "write_file(*)", "mcp(*)"]}
        }).encode())
        atomic_private_write(self.home / ".gemini/config/config.json", json.dumps({
            "userSettings": {"useAiCredits": False}
        }).encode())
        atomic_private_write(self.home / ".gemini/config/mcp_config.json",
                             json.dumps({"mcpServers": self.mcp_servers}).encode())

    def _conversation_key(self):
        return self.session_id, self.model, self._generation

    def _save_conversation(self):
        atomic_private_write(self.home / "orchestra-conversation.json", json.dumps({
            "generation": self._generation, "model": self.model,
            "conversation_id": self.session_id, "cumulative": self._cumulative,
        }).encode())

    def _turn_deltas(self, terminal):
        """agy --conversation reports totals, including on unsuccessful terminals."""
        if self._baseline_key != self._conversation_key():
            self._cumulative = {}
            self._baseline_key = self._conversation_key()
        usage = terminal.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        values = {key: _cumulative_value(usage.get(key)) for key in (
            "input_tokens", "output_tokens", "cache_read_tokens", "thinking_tokens")}
        values.update(num_turns=_cumulative_value(terminal.get("num_turns")),
                      duration_seconds=_cumulative_value(terminal.get("duration_seconds"), integer=False))
        values = {key: value for key, value in values.items() if value is not None}
        baseline = {key: value for key, raw in self._cumulative.items()
                    if (value := _cumulative_value(raw, integer=key != "duration_seconds")) is not None}
        # Any decreasing counter marks a new CLI accounting epoch. Rebase the
        # entire vector together, rather than hiding new spend behind old totals.
        if any(value < baseline.get(key, 0) for key, value in values.items()):
            baseline = {}
        deltas = {key: value - baseline.get(key, 0) for key, value in values.items()}
        self._cumulative = {**baseline, **values}
        return deltas

    def _end(self, *, ok=False, reason="error", error=None, usage=None, terminal=None,
             context=None):
        aggregate = AggregateUsage.normalized(**{
            key: (usage or {}).get(key, 0) for key in
            ("input_tokens", "output_tokens", "cache_read_tokens")
        })
        typed = TurnUsage(aggregate, context or UnknownContext(
            self.context_limit, "Antigravity did not report current-context semantics"))
        cost = (
            _antigravity_cost(
                self.model,
                aggregate.input_tokens,
                aggregate.cache_read_tokens,
                aggregate.output_tokens,
            )
            if terminal is not None
            else None
        )
        metadata = {
            "session_id": self.session_id,
            "ok": ok,
            "stop_reason": reason,
            "cost_usd": cost if cost is not None else 0.0,
            "cost_unaccounted": cost is None,
            "input_tokens": aggregate.input_tokens,
            "output_tokens": aggregate.output_tokens,
            "cached_input_tokens": aggregate.cache_read_tokens,
            "cache_read": aggregate.cache_read_tokens,
            "cache_create": 0,
        }
        if terminal is not None:
            num_turns = _cumulative_value(terminal.get("num_turns")) or 0
            if ok and num_turns <= 0:
                num_turns = 1
            thinking = _cumulative_value((usage or {}).get("thinking_tokens"))
            duration_s = _cumulative_value(terminal.get("duration_seconds"), integer=False)
            metadata.update(
                event_id=f"agy:{self.session_id or self.home.name}:{uuid.uuid4().hex[:12]}",
                num_turns=num_turns,
                reasoning_tokens=thinking,
                turn_duration_ms=(
                    round(float(duration_s) * 1000)
                    if duration_s is not None
                    else None
                ),
            )
            if cost is not None:
                metadata.update(cost_usd_cached=cost, cost_is_delta=True)
        if error:
            metadata.update(model_error=error, errors=[error])
        return AgentEvent("turn_end", metadata=metadata, usage=typed)

    async def send(self, message):
        if self._task is not None and not self._task.done():
            raise RuntimeError("Antigravity turn is already active")
        self._queue = asyncio.Queue()
        self._interrupted = False
        try:
            from app.provider_safety import (
                EgressSafetyError,
                ProviderDisabledError,
                record_provider_activity,
                verify_provider_egress,
            )

            await verify_provider_egress("antigravity")
            record_provider_activity("antigravity")
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
                elif (state.get("conversation_id") == self.session_id
                      and isinstance(state.get("cumulative"), dict)):
                    self._cumulative = state["cumulative"]
                    self._baseline_key = self.session_id, self.model, snapshot.generation
            if self._generation is not None and snapshot.generation != self._generation:
                self.session_id = None
            self._generation = snapshot.generation
            if self._baseline_key != self._conversation_key():
                self._cumulative = {}
                self._baseline_key = self._conversation_key()
            self._save_conversation()
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
        except (OSError, ValueError, ProviderDisabledError, EgressSafetyError) as exc:
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
        assistant_response = False
        response_complete = False
        emitted_tools = {}
        completed_tools = set()
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
                    if step.get("step_type") == "agent_response":
                        delta = step.get("text_delta")
                        if isinstance(delta, str) and delta:
                            assistant_response |= bool(delta.strip())
                            self._queue.put_nowait(AgentEvent("stream", self._redact(delta)))
                        response_complete = assistant_response and step.get("state") == "DONE"
                    elif step.get("step_type") == "tool":
                        response_complete = False
                        info = step.get("tool_info", {})
                        conv = step.get("conversation_id") or self.session_id
                        tool_id = (f"agy-{conv}-step-{step.get('step_index')}" if conv
                                   else f"agy-step-{step.get('step_index')}")
                        state = step.get("state")
                        if state not in {"ACTIVE", "DONE", "ERROR"}:
                            continue
                        if tool_id not in emitted_tools:
                            name = step.get("tool_name") or info.get("name") or "tool"
                            args = info.get("parameters", {})
                            if not isinstance(args, dict):
                                args = {}
                            if (name == "call_mcp_tool"
                                    and isinstance(args.get("ServerName"), str) and args["ServerName"].strip()
                                    and isinstance(args.get("ToolName"), str) and args["ToolName"].strip()
                                    and isinstance(args.get("Arguments"), dict)):
                                name = f"mcp__{args['ServerName'].strip()}__{args['ToolName'].strip()}"
                                args = args["Arguments"]
                            elif name.startswith("mcp_") and not name.startswith("mcp__"):
                                # A server name can contain underscores; prefer the longest match.
                                for server in sorted(self.mcp_servers, key=len, reverse=True):
                                    prefix = f"mcp_{server}_"
                                    if name.startswith(prefix) and name[len(prefix):]:
                                        name = f"mcp__{server}__{name[len(prefix):]}"
                                        break
                            args = json.loads(self._redact(json.dumps(args, ensure_ascii=False)))
                            meta = {"tool_use_id": tool_id, "tool_name": name,
                                    "short_name": name.split("__", 2)[-1], "input": args}
                            emitted_tools[tool_id] = meta
                            self._queue.put_nowait(AgentEvent(
                                "tool_use", f"{name}: {json.dumps(args, ensure_ascii=False)}", meta))
                        meta = emitted_tools[tool_id]
                        if state in {"DONE", "ERROR"} and tool_id not in completed_tools:
                            completed_tools.add(tool_id)
                            failed = step.get("state") == "ERROR" or bool(info.get("error"))
                            value = (info.get("error") or info.get("output", "")) if failed else info.get("output", "")
                            text = self._redact(value if isinstance(value, str) else json.dumps(value))
                            self._queue.put_nowait(AgentEvent("tool_result", text, {**meta, "is_error": failed}))
                elif kind == "result":
                    result = raw.get("result")
                    terminal = result if isinstance(result, dict) else None
            await process.wait()
            await stderr
            deltas = context = None
            if terminal is not None:
                self.session_id = terminal.get("conversation_id") or self.session_id
                deltas = self._turn_deltas(terminal)
                context = _conversation_context(self.home, self.session_id, self.context_limit)
                self._save_conversation()
            if self._interrupted:
                end = self._end(reason="interrupt", error="interrupted", usage=deltas,
                                terminal=deltas, context=context)
            elif terminal is None:
                self._queue.put_nowait(AgentEvent("error", "Antigravity exited without a terminal result"))
                end = self._end(error="protocol")
            else:
                ok = terminal.get("status") == "SUCCESS" and process.returncode == 0
                response = terminal.get("response")
                if isinstance(response, str) and response.strip():
                    assistant_response = response_complete = True
                reason, error = "end_turn", None
                if not ok:
                    text = self._redact(terminal.get("error") or "Antigravity turn failed")
                    lower = text.lower()
                    is_permanent_ban = _is_account_disabled_payload(text)
                    if is_permanent_ban:
                        _trip_antigravity_circuit_breaker(text[:200])
                    if any(word in lower for word in (
                        "auth", "oauth", "token", "credential", "eligib", "location",
                        "terms of service", "disabled in this account", "account has been disabled",
                    )):
                        error = "credentials"
                    elif "quota" in lower or "rate limit" in lower:
                        error = "quota"
                    else:
                        error = "model"
                    # Retry errors may remain in this and later terminal results.
                    # Only output observed in THIS process can recover a failure;
                    # permanent account/ToS bans NEVER recover into ok=True.
                    if (
                        assistant_response
                        and not is_permanent_ban
                        and (error == "model" or response_complete)
                    ):
                        ok, error = True, None
                    else:
                        reason = error
                        self._queue.put_nowait(AgentEvent("error", text))
                if isinstance(response, str) and response:
                    self._queue.put_nowait(AgentEvent("text", self._redact(response)))
                end = self._end(ok=ok, reason=reason, error=error, usage=deltas,
                                terminal=deltas, context=context)
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
