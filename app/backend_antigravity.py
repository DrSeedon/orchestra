"""Passive Antigravity observations and session adapter for app-owned ACP."""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import math
import os
import re
import shutil
import signal
import sqlite3
import tempfile
import time
import uuid
from contextlib import closing
from datetime import datetime
from pathlib import Path

from app.antigravity_auth import (
    TOKEN_RELATIVE_PATH,
    atomic_private_write,
    private_directory,
)
from app.events import AgentEvent, InjectedMessage
from app.models import ANTIGRAVITY_NEON_RAW_MODELS, ANTIGRAVITY_NEON_TOKEN_PRICES
from app.usage_contract import (
    AggregateUsage, KnownContext, TurnUsage, UnknownContext, current_context,
)

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parents[1]
ANTIGRAVITY_BIN = os.environ.get("ANTIGRAVITY_BIN", "agy")
ANTIGRAVITY_AUTH_HOME = Path(os.environ.get("ANTIGRAVITY_AUTH_HOME", str(ROOT / "data/antigravity-auth-home")))
ANTIGRAVITY_HOME_ROOT = ROOT / "data/antigravity-homes"
ANTIGRAVITY_CLEAN_SHELL = os.environ.get(
    "ANTIGRAVITY_CLEAN_SHELL", "/home/kesha/.local/bin/agy-clean-shell"
)
ANTIGRAVITY_BASH_ENV = os.environ.get(
    "ANTIGRAVITY_BASH_ENV", "/home/kesha/.local/share/orchestra/agy-bash-clean-env.sh"
)
_CLEAN_SHELL_SNIPPET = (
    "unset HTTP_PROXY HTTPS_PROXY ALL_PROXY GRPC_PROXY "
    "http_proxy https_proxy all_proxy grpc_proxy NO_GRPC_PROXY no_grpc_proxy BASH_ENV\n"
)
QUOTA_KEYS = ("gemini-weekly", "gemini-argon-wtu-weekly", "3p-weekly")
FIVE_HOUR_QUOTA_KEYS = ("gemini-5h", "3p-5h")
QUOTA_BUCKETS = (
    ("antigravity_gemini", "Gemini", "gemini-weekly", "gemini-5h"),
    ("antigravity_argon", "Argon", "gemini-argon-wtu-weekly", "gemini-argon-wtu-5h"),
    ("antigravity_3p", "Claude/3P", "3p-weekly", "3p-5h"),
)
QUOTA_CACHE_TTL = 900.0
QUOTA_FORCE_COOLDOWN = 60.0

# Official Google AI Studio / Vertex AI API-equivalent rates per 1M tokens
# (Nov 2026 promo through Nov 30, 2026: Carbon/Argon $2/$10, cached 95% off = $0.10;
# Hydrogen $1.50/$7.50, cached $0.075). Note: agy usage.output_tokens already includes
# thinking_tokens, and usage.input_tokens excludes cache_read_tokens.
ANTIGRAVITY_TOKEN_PRICES: dict[str, dict[str, float]] = {
    **{raw: ANTIGRAVITY_NEON_TOKEN_PRICES for raw in ANTIGRAVITY_NEON_RAW_MODELS},
    "gemini-4-carbon-high": {"input": 2.0, "cached": 0.10, "output": 10.0},
    "gemini-4-carbon-medium": {"input": 2.0, "cached": 0.10, "output": 10.0},
    "gemini-4-carbon-low": {"input": 2.0, "cached": 0.10, "output": 10.0},
    "gemini-pro-orchestrator": {"input": 2.0, "cached": 0.10, "output": 10.0},
    "gemini-pro-orchestrator-g1-pro": {"input": 2.0, "cached": 0.10, "output": 10.0},
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


def estimate_antigravity_turn_usage(
    raw_model: str,
    *,
    context_tokens: int | None,
    tool_calls: int = 0,
    output_chars: int = 0,
    thinking_chars: int = 0,
    last_turn_at: float | None = None,
    now: float | None = None,
    quota_delta_pct: float | None = None,
) -> dict | None:
    """Estimate API-equivalent tokens and USD when ACP omits per-turn token counters."""
    try:
        ctx = int(context_tokens or 0)
    except (TypeError, ValueError):
        ctx = 0
    total_out_chars = max(0, int(output_chars or 0)) + max(0, int(thinking_chars or 0))
    if ctx <= 0 and total_out_chars <= 0:
        return None
    now_ts = time.time() if now is None else float(now)
    warm = last_turn_at is not None and (now_ts - float(last_turn_at)) < 1800.0
    api_calls = max(1, int(tool_calls or 0) + 1)
    prompt_total = max(0, ctx) * api_calls
    output_tokens = max(1, total_out_chars // 4) if total_out_chars > 0 else 0
    input_rate = 0.50 if warm else 2.00
    output_rate = 12.00
    cost_usd = round((prompt_total * input_rate + output_tokens * output_rate) / 1_000_000.0, 6)
    input_tokens = 0 if warm else prompt_total
    cache_read_tokens = prompt_total if warm else 0
    normalized = AggregateUsage.normalized(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_create_tokens=0,
        model_calls=api_calls,
        accuracy="estimated",
    ).derived()
    if quota_delta_pct is not None and math.isfinite(float(quota_delta_pct)):
        normalized["quota_delta_pct"] = round(float(quota_delta_pct), 4)
    normalized["warm_cache"] = bool(warm)
    normalized["context_tokens"] = ctx
    normalized["api_calls"] = api_calls
    normalized["cost_usd"] = cost_usd
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_create_tokens": 0,
        "prompt_total": prompt_total,
        "context_tokens": ctx,
        "api_calls": api_calls,
        "warm": bool(warm),
        "cost_usd": cost_usd,
        "quota_delta_pct": normalized.get("quota_delta_pct"),
        "normalized": normalized,
        "accuracy": "estimated",
    }


def _current_seven_day_utilization(model: str) -> float | None:
    try:
        from app.quota_gate import quota_bucket_for_model
        from app.routes.system import _antigravity_usage_cache
        bucket = quota_bucket_for_model("antigravity/" + model.removeprefix("antigravity/"))
        data = _antigravity_usage_cache.get("data") or {}
        if not isinstance(data, dict):
            return None
        key_map = {
            "antigravity_gemini": "gemini-weekly",
            "antigravity_argon": "gemini-argon-wtu-weekly",
            "antigravity_3p": "3p-weekly",
        }
        entry = data.get(key_map.get(bucket or "", ""))
        if isinstance(entry, dict) and isinstance(entry.get("utilization"), (int, float)):
            return float(entry["utilization"])
    except Exception:
        return None
    return None


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
    database = home / ".gemini/antigravity-acp/conversations" / f"{conversation_id}.db"
    if not database.is_file():
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
    """Keep the OAuth route explicit and strip proxy vars from child bash tools."""
    from app.provider_safety import build_provider_env

    home = Path(home)
    env = build_provider_env("antigravity")
    bash_env_path = (
        ANTIGRAVITY_BASH_ENV
        if Path(ANTIGRAVITY_BASH_ENV).is_file()
        else str(home / ".gemini/orchestra-clean-bash-env.sh")
    )
    env.update({
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_DATA_HOME": str(home / ".local/share"),
        "AGY_CLI_DISABLE_AUTO_UPDATE": "true",
        # A stale cached login must never open a browser or inherit another helper.
        # No auth URL is printed; rejected/expired login remains a terminal RPC.
        "BROWSER": "/usr/bin/true",
        "GEMINI_HOME": str(home / ".gemini"),
        "AGY_ACP_FORCE_FILE_STORAGE": "1",
        "BASH_ENV": bash_env_path,
    })
    if os.environ.get("ORCHESTRA_DISABLED_PROVIDERS_FILE"):
        env["ORCHESTRA_DISABLED_PROVIDERS_FILE"] = os.environ["ORCHESTRA_DISABLED_PROVIDERS_FILE"]
    if Path(ANTIGRAVITY_CLEAN_SHELL).is_file() and os.access(ANTIGRAVITY_CLEAN_SHELL, os.X_OK):
        env["SHELL"] = ANTIGRAVITY_CLEAN_SHELL
    return env


def _normalize_quota_windows(raw: object, keys: tuple[str, ...], window: str) -> dict:
    result = dict.fromkeys(keys)
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
                    or bucket.get("window") != window):
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


def normalize_antigravity_quota(raw: object) -> dict:
    return _normalize_quota_windows(raw, QUOTA_KEYS, "weekly")


def normalize_antigravity_five_hour_quota(raw: object) -> dict:
    argon_key = QUOTA_BUCKETS[1][3]
    windows = _normalize_quota_windows(raw, (*FIVE_HOUR_QUOTA_KEYS, argon_key), "5h")
    if windows[argon_key] is None:
        del windows[argon_key]
    return windows


def supported_version(value: str) -> bool:
    match = re.search(r"\b(\d+)\.(\d+)\.(\d+)\b", value)
    return bool(match and tuple(map(int, match.groups())) >= (1, 1, 12))


async def _cli(*args: str, home: Path):
    """Legacy probe entry point intentionally cannot launch account traffic."""
    raise RuntimeError("Antigravity probes are passive; use an explicit ACP turn")


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
    from app.routes.system import publish_antigravity_quota

    try:
        publish_antigravity_quota(quota, five_hour, observed, generation=generation)
    except (OSError, sqlite3.Error) as error:
        logger.warning("Could not persist ACP quota observation (%s)", type(error).__name__)


async def fetch_antigravity_usage() -> dict:
    """Return the last observation without refreshing it or its timestamp."""
    from app.routes import system
    return dict(system._antigravity_usage_cache.get("data") or dict.fromkeys(QUOTA_KEYS))


_ISOLATED_QUOTA_FILES = (
    ".gemini/oauth_creds.json",
    ".gemini/settings.json",
    ".gemini/antigravity-acp/oauth_creds.json",
    ".gemini/antigravity-acp/settings.json",
    ".gemini/antigravity-acp/installation_id",
    ".gemini/antigravity-cli/oauth_creds.json",
    ".gemini/antigravity-cli/settings.json",
    ".gemini/antigravity-cli/installation_id",
    ".gemini/config/config.json",
)


def _resolve_antigravity_bin(env: dict[str, str]) -> str:
    return (
        shutil.which(ANTIGRAVITY_BIN, path=env.get("PATH") or os.environ.get("PATH", ""))
        or shutil.which(ANTIGRAVITY_BIN, path="/home/kesha/.local/bin:/usr/local/bin:/usr/bin")
        or ANTIGRAVITY_BIN
    )


def _prepare_isolated_quota_home(home: Path, iso_home: Path) -> None:
    """Copy only auth/config files into a 0700 temp home without touching .orchestra-acp.lock."""
    os.chmod(iso_home, 0o700)
    for rel_dir in (
        ".gemini",
        ".gemini/antigravity-acp",
        ".gemini/antigravity-cli",
        ".gemini/config",
    ):
        d = iso_home / rel_dir
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o700)
    src_token = home / ".gemini/antigravity-acp/antigravity-oauth-token"
    dst_token = iso_home / ".gemini/antigravity-acp/antigravity-oauth-token"
    shutil.copy2(src_token, dst_token)
    os.chmod(dst_token, 0o600)
    dst_link = iso_home / TOKEN_RELATIVE_PATH
    dst_link.parent.mkdir(parents=True, exist_ok=True)
    dst_link.symlink_to(os.path.relpath(dst_token, dst_link.parent))
    for rel_file in _ISOLATED_QUOTA_FILES:
        src = home / rel_file
        if src.is_file():
            dst = iso_home / rel_file
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            os.chmod(dst, 0o600)


async def _run_antigravity_quota_probe(probe_home: Path) -> tuple[dict, dict]:
    from app.provider_safety import verify_provider_egress

    env = cli_environment(probe_home)
    await verify_provider_egress("antigravity", env=env)
    # Print mode has no ACP-only directory/telemetry flags. It reads the
    # legacy location, which must resolve to the same canonical token.
    acp_token = probe_home / ".gemini/antigravity-acp/antigravity-oauth-token"
    cli_token = probe_home / TOKEN_RELATIVE_PATH
    if cli_token.resolve() != acp_token.resolve():
        raise RuntimeError("Antigravity quota requires the shared CLI/ACP token store")
    agy_bin = _resolve_antigravity_bin(env)
    proc = await asyncio.create_subprocess_exec(
        agy_bin, "--print", "/quota", "--output-format", "json",
        cwd=str(probe_home), env=env, stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        output, _ = await asyncio.wait_for(proc.communicate(), timeout=12)
    finally:
        if proc.returncode is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=2)
            except TimeoutError:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await proc.wait()
    if len(output) > 1024 * 1024:
        raise RuntimeError("Antigravity quota report exceeds size limit")
    if proc.returncode and not output.strip():
        raise RuntimeError("Antigravity quota command returned no report")
    raw = json.loads(output)
    if _is_account_disabled_payload(raw):
        _trip_antigravity_circuit_breaker("Antigravity quota confirmed account-disabled/Terms-of-Service refusal")
        raise RuntimeError("Antigravity account disabled")
    if proc.returncode:
        raise RuntimeError("Antigravity quota command failed")
    weekly = normalize_antigravity_quota(raw)
    short = normalize_antigravity_five_hour_quota(raw)
    if not any(value is not None for value in (*weekly.values(), *short.values())):
        raise ValueError("Antigravity quota report contains no recognized windows")
    return weekly, short


async def probe_antigravity_quota() -> tuple[dict, dict] | None:
    """Read one quota report using the same profile and egress guards as ACP."""
    from app.antigravity_acp import get_profile
    from app.models import is_provider_disabled

    home = canonical_profile()
    if is_provider_disabled("antigravity") or not _has_cached_credentials(home):
        return None
    owner = get_profile(home)
    tmp_dir: tempfile.TemporaryDirectory[str] | None = None
    isolated_home: Path | None = None

    try:
        async with owner._start_lock:
            if is_provider_disabled("antigravity"):
                return None
            owner._check_settings()
            acp_token = home / ".gemini/antigravity-acp/antigravity-oauth-token"
            cli_token = home / TOKEN_RELATIVE_PATH
            if cli_token.resolve() != acp_token.resolve():
                raise RuntimeError("Antigravity quota requires the shared CLI/ACP token store")
            lock_fd: int | None = None
            isolated = owner.process is not None and owner.process.returncode is None
            if not isolated:
                lock_fd = os.open(
                    home / ".orchestra-acp.lock",
                    os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
                    0o600,
                )
                try:
                    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    os.close(lock_fd)
                    lock_fd = None
                    isolated = True
            if isolated:
                tmp_dir = tempfile.TemporaryDirectory(prefix="orch-agy-quota-")
                isolated_home = Path(tmp_dir.name)
                _prepare_isolated_quota_home(home, isolated_home)
            else:
                try:
                    return await _run_antigravity_quota_probe(home)
                finally:
                    if lock_fd is not None:
                        os.close(lock_fd)
        # Isolated mode: _start_lock and .orchestra-acp.lock are both free; run against temp copy.
        assert isolated_home is not None
        return await _run_antigravity_quota_probe(isolated_home)
    finally:
        if tmp_dir is not None:
            tmp_dir.cleanup()


def canonical_profile(profile: str = "") -> Path:
    # A configured profile owns its HOME; session identity must never own auth.
    if profile:
        from app.db import get_profile
        row = get_profile(profile)
        if row is not None and row.get("config_dir"):
            return Path(row["config_dir"]).expanduser().resolve()
        if profile == "personal" and (row is None or not row.get("config_dir")):
            return Path(ANTIGRAVITY_AUTH_HOME).resolve()
        raise ValueError("Antigravity profile has no canonical config_dir")
    return Path(ANTIGRAVITY_AUTH_HOME).resolve()


def _has_cached_credentials(home: Path) -> bool:
    # Presence only: status must not read, copy, refresh or authenticate tokens.
    return (home / ".gemini/antigravity-acp/antigravity-oauth-token").is_file()


async def antigravity_readiness(context):
    from app.models import is_provider_disabled
    from app.runtime_registry import RuntimeReadinessResult
    from app.antigravity_acp import cached_profile

    if is_provider_disabled("antigravity"):
        return RuntimeReadinessResult(False, False, "Antigravity provider is disabled")
    try:
        home = canonical_profile(context.profile)
    except ValueError as exc:
        return RuntimeReadinessResult(False, False, str(exc))
    owner = cached_profile(home)
    if owner and owner.failure and owner._permanent_failure:
        return RuntimeReadinessResult(False, False, owner.failure)
    credentials = _has_cached_credentials(home)
    available = bool(owner and context.model.removeprefix("antigravity/") in owner.models)
    return RuntimeReadinessResult(credentials, available,
        owner.failure if owner and owner.failure else
        ("" if available and credentials else "Antigravity cached credentials/catalog unknown; no probe performed"))


class AntigravityBackend:
    foreground_capabilities = {
        "wire_version":1,"permissions":"native offered options","questions":"interaction_* single choice only",
        "tools":"bounded merged snapshots; textual diff/resources; nontext marked unsupported",
        "ordered_segments":True,"mid_turn_injection":True,"automated_prompts":False,
        "profile_binding":"operator epoch; fixed account; no account-change detection",
        "credential_readiness":"file-store presence only; keyring not autodetected",
        "role_priority":"first-turn user context; systemPrompt.append unverified",
        "effort":"exact split model/thought selectors or combined variant, with ACK; no nearest fallback",
        "telegram":"primary topic durable cursor; ambiguous sends block for operator reconciliation",
    }
    def __init__(self, context):
        self.model = context.model.removeprefix("antigravity/")
        self.cwd = context.cwd
        self.system_prompt = context.system_prompt
        self.mcp_servers = context.mcp_servers
        self.context_limit = context.context_limit
        self.session_id = context.resume_session_id
        self.home = canonical_profile(context.profile)
        self._owner = None
        self.app_session_id = ""
        self.effort = getattr(context,"effort",None)
        self._turn_id = ""
        self._segment = None
        self._segment_index = 0
        self._assistant_reply = []
        self._task = None
        self._queue = asyncio.Queue()
        self._interrupted = False
        self._secrets = sorted({str(value) for cfg in self.mcp_servers.values()
                                for key, value in cfg.get("env", {}).items()
                                if value and re.search(r"TOKEN|SECRET|PASSWORD|KEY|COOKIE|AUTH|DSN", key, re.I)},
                               key=len, reverse=True)
        self._stderr_values = self._secrets
        self._generation = None
        self._cumulative = {}
        self._baseline_key = None
        self._context = None
        self._cost_total = None
        self._cost_baseline = None
        self._instructions_sent = False
        self._submission = None
        self._before_submit = None
        self._stream_finished = True
        self._steer_queue = []
        self._steer_event = None
        self._tool_idle_event = None
        self._accepting_steer = False

    @property
    def is_alive(self):
        # Registration is deliberately lazy: connect() never starts a CLI.
        return bool(self._owner and not self._owner.failure and self._owner.process
                    and self._owner.process.returncode is None)

    def _redact(self, text: object, *, all_env=False) -> str:
        result = str(text)
        for value in self._secrets:
            result = result.replace(value, "[redacted]")
        return re.sub(r"ya29\.[A-Za-z0-9_-]+", "[redacted]", result)

    async def connect(self):
        from app.antigravity_acp import get_profile
        self._owner = get_profile(self.home)

    def _conversation_key(self):
        return self.session_id, self.model, self._generation

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
             context=None, duration_ms=None):
        self._flush_segment()
        aggregate = AggregateUsage.normalized(accuracy="reported" if usage and all(k in usage for k in ("input_tokens", "output_tokens")) else "unknown", **{
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
            if terminal is not None and aggregate.accuracy == "reported"
            else None
        )
        metadata = {
            "session_id": self.session_id,
            "assistant_text": "".join(self._assistant_reply),
            "selected_model": getattr(self,"_selected_model",self.model),
            "profile_epoch": self._owner.epoch if self._owner else None,
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
                metadata.update(cost_usd_cached=cost, cost_is_delta=True, cost_kind="api_equivalent")
        else:
            metadata.update(
                event_id=f"agy:{self.session_id or self.home.name}:{(getattr(self, '_turn_id', '') or uuid.uuid4().hex)[:12]}",
                num_turns=1 if ok else 0,
                turn_duration_ms=duration_ms,
            )
        if self._cost_total is not None:
            # ACP cost is cumulative. Advance the shared baseline on success,
            # error and cancellation alike, so later turns never count it twice.
            self._owner.cost_totals[self.session_id] = self._cost_total
            if self._cost_baseline is not None:
                baseline = self._cost_baseline if self._cost_total >= self._cost_baseline else 0
                metadata.update(cost_usd=round(self._cost_total - baseline, 8),
                                cost_usd_cached=round(self._cost_total - baseline, 8),
                                cost_unaccounted=False, cost_is_delta=True)
        start_7d = getattr(self, "_turn_start_seven_day_pct", None)
        end_7d = _current_seven_day_utilization(self.model)
        quota_delta_pct = (
            round(end_7d - start_7d, 4)
            if isinstance(start_7d, (int, float)) and isinstance(end_7d, (int, float))
            else None
        )
        if quota_delta_pct is not None:
            metadata["quota_delta_pct"] = quota_delta_pct
        if metadata.get("cost_unaccounted"):
            ctx_tokens = context.tokens if isinstance(context, KnownContext) else getattr(getattr(self, "_context", None), "tokens", 0)
            est = estimate_antigravity_turn_usage(
                self.model,
                context_tokens=ctx_tokens,
                tool_calls=int(getattr(self, "_turn_tool_calls", 0) or 0),
                output_chars=sum(len(chunk) for chunk in getattr(self, "_assistant_reply", ())),
                thinking_chars=int(getattr(self, "_turn_thinking_chars", 0) or 0),
                last_turn_at=getattr(self, "_last_turn_completed_at", None),
                quota_delta_pct=quota_delta_pct,
            )
            if est is not None:
                metadata["estimated_usage"] = est
        if ok:
            self._last_turn_completed_at = time.time()
        if error:
            metadata.update(model_error=error, errors=[error])
        return AgentEvent("turn_end", metadata=metadata, usage=typed)

    def _has_open_tool(self) -> bool:
        tools = getattr(self, "_tools", None)
        if tools is None:
            return False
        return any(
            state.get("status") not in {"completed", "failed"}
            for state in tools.states.values()
        )

    def _fail_pending_steers(self, error: BaseException) -> None:
        while self._steer_queue:
            item = self._steer_queue.pop(0)
            fut = item.get("future")
            if fut is not None and not fut.done():
                fut.set_exception(error)

    async def send(self, message, *, before_submit=None):
        from app.antigravity_acp import AcpSessionError, ensure_interactive_input
        from app.provider_safety import get_antigravity_cooldown
        from app.session_state import DeliveryDeferred
        from app import db
        target = db.get_session(self.app_session_id) if getattr(self, "app_session_id", "") else None
        ensure_interactive_input("antigravity/" + self.model,
            message.provenance if isinstance(message, InjectedMessage) else None,
            target_session=target)
        cooldown = get_antigravity_cooldown()
        if cooldown is not None:
            raise AcpSessionError(cooldown["message"])
        msg_text = message.text if isinstance(message, InjectedMessage) else str(message)
        msg_explicit = isinstance(message, InjectedMessage) and message.provenance.origin == "user"
        msg_event_id = message.event_id if isinstance(message, InjectedMessage) else ""
        if self._task is not None and not self._task.done():
            if self._interrupted or not self._accepting_steer:
                raise DeliveryDeferred("Antigravity turn is ending; delivery deferred")
            steer_fut = asyncio.get_running_loop().create_future()
            steer_fut.add_done_callback(lambda f: None if f.cancelled() else f.exception())
            self._submission = steer_fut
            self._steer_queue.append({
                "text": msg_text,
                "before_submit": before_submit,
                "future": steer_fut,
                "explicit": msg_explicit,
                "event_id": msg_event_id,
            })
            if self._steer_event is not None:
                self._steer_event.set()
            return
        if self._owner is None:
            await self.connect()
        self._queue = asyncio.Queue()
        self._interrupted = False
        self._context = None
        self._cost_total = None
        self._cost_baseline = None
        self._reported_usage = None
        self._stream_finished = False
        self._steer_queue = []
        self._steer_event = asyncio.Event()
        self._tool_idle_event = asyncio.Event()
        self._tool_idle_event.set()
        self._accepting_steer = True
        self._turn_id = uuid.uuid4().hex
        self._segment = None
        self._segment_index = 0
        self._assistant_reply = []
        self._turn_thinking_chars = 0
        self._turn_tool_calls = 0
        self._turn_start_seven_day_pct = _current_seven_day_utilization(self.model)
        from app.acp_tools import ToolReducer
        self._tools = ToolReducer()
        self._before_submit = before_submit
        self._submission = asyncio.get_running_loop().create_future()
        self._submission.add_done_callback(lambda f: None if f.cancelled() else f.exception())
        self._task = asyncio.create_task(self._run(msg_text, explicit=msg_explicit, event_id=msg_event_id))
        self._task.add_done_callback(self._cancelled_before_run)

    def _settle_submission(self, error=None):
        if self._submission is not None and not self._submission.done():
            if error is None:
                self._submission.set_result(None)
            else:
                self._submission.set_exception(error)

    def _prompt_submitted(self):
        self._instructions_sent = True
        self._settle_submission()

    async def wait_for_submission(self):
        """Wait only for prompt write+drain, never for inference or terminal output."""
        try:
            await asyncio.shield(self._submission)
        except asyncio.CancelledError:
            # A cancelled waiter cannot leave a known-not-submitted prompt running.
            await self.interrupt()
            raise

    def _cancelled_before_run(self, task):
        if task is self._task and task.cancelled() and not self._stream_finished:
            self._stream_finished = True
            self._settle_submission(RuntimeError("ACP submission cancelled before task start"))
            self._queue.put_nowait(self._end(reason="interrupt", error="interrupted"))
            self._queue.put_nowait(None)

    def _flush_segment(self):
        if self._segment is None:return
        kind,item_id,parts=self._segment
        self._queue.put_nowait(AgentEvent(kind,self._redact("".join(parts)),metadata={"item_id":item_id}))
        self._segment=None

    def _update(self, update):
        kind=update.get("sessionUpdate");content=update.get("content") or {}
        if kind in {"agent_message_chunk","agent_thought_chunk"} and content.get("type")=="text":
            text=content.get("text")
            if not isinstance(text,str):return
            target="text" if kind=="agent_message_chunk" else "thinking"
            if self._segment is not None and self._segment[0]!=target:self._flush_segment()
            if self._segment is None:
                self._segment_index+=1
                self._segment=(target,"acp:"+str(self.session_id)+":"+self._turn_id+":"+str(self._segment_index),[])
            self._segment[2].append(text)
            if target=="text":
                self._assistant_reply.append(text)
            else:
                self._turn_thinking_chars = int(getattr(self, "_turn_thinking_chars", 0) or 0) + len(text)
            self._queue.put_nowait(AgentEvent("stream" if target=="text" else "thinking_stream",self._redact(text),metadata={"item_id":self._segment[1]}))
        elif kind=="config_option_update":
            if self._owner is not None and self.session_id:
                self._owner.remember_model_state(self.session_id, update)
        elif kind=="usage_update":
            # Optional vendor token totals use explicit counter names. Never infer
            # input/output from the ACP context fields used/size.
            if isinstance(update.get("usage"), dict):
                self._reported_usage = update["usage"]
            quota = update.get("quota")
            if isinstance(quota, dict) and self._owner.home == canonical_profile():
                weekly = normalize_antigravity_quota(quota)
                short = normalize_antigravity_five_hour_quota(quota)
                if any(v is not None for v in (*weekly.values(), *short.values())):
                    _publish_quota(weekly, time.time(), self._owner.epoch, short)
            if "used" in update or "size" in update:
                self._context=current_context(update.get("used"),update.get("size"))
            cost=update.get("cost") or {}
            if isinstance(cost,dict) and cost.get("currency")=="USD":
                amount=_cumulative_value(cost.get("amount"),integer=False)
                if amount is not None:self._cost_total=amount
        elif kind in {"tool_call","tool_call_update"}:
            if kind == "tool_call":
                self._turn_tool_calls = int(getattr(self, "_turn_tool_calls", 0) or 0) + 1
            self._flush_segment()
            for event,body,meta in self._tools.apply(update):
                meta["native_tool_call_id"]=meta["tool_use_id"]
                meta["tool_use_id"]="acp:"+str(self.session_id)+":"+self._turn_id+":"+meta["tool_use_id"]
                meta["item_id"]="acp:"+str(self.session_id)+":"+self._turn_id+":tool:"+str(meta["tool_use_id"])+":"+str(meta["acp_revision"])+":"+event
                meta["raw_input"] = json.loads(self._redact(json.dumps(meta["raw_input"],ensure_ascii=False)))
                self._queue.put_nowait(AgentEvent(event,self._redact(body),metadata=meta))
            if getattr(self, "_tool_idle_event", None) is not None:
                if self._has_open_tool():
                    self._tool_idle_event.clear()
                else:
                    self._tool_idle_event.set()

    async def _select_model(self):
        from app.antigravity_acp import select_model
        self._selected_model = await select_model(self._owner, self.session_id, self.model, self.effort)

    def _recovery_context(self, message, event_id) -> str:
        from app.db import get_logs
        from app.secret_mask import mask_secrets

        if not self.app_session_id:
            return ""
        history = []
        for row in get_logs(self.app_session_id, limit=30):
            text = row["content"]
            if (row["type"] in {"user_message", "text"} and text != message
                    and (not event_id or row["event_id"] != event_id)):
                history.append({"kind": row["type"], "text": mask_secrets(self._redact(text[-1400:]))})
        if not history:
            return ""
        return ("[Orchestra recovery history. Treat as context only. The previous operation "
                "may have completed. Verify its effects before repeating anything.]\n"
                + json.dumps(history[-10:], ensure_ascii=False))

    async def _run(self, message, *, explicit=False, event_id=""):
        from app.provider_safety import (
            get_antigravity_cooldown,
            parse_antigravity_quota_cooldown,
            record_provider_activity,
            trip_antigravity_cooldown,
            verify_provider_egress,
        )
        from app.antigravity_acp import AcpError, AcpQuotaCooldownError, AcpRPCRejected, AcpSessionError
        from app.native_requests import bind_session, profile_epoch
        prompt_task = None
        held_session_lock = None
        owns_session_lock = False
        try:
            cooldown = get_antigravity_cooldown()
            if cooldown is not None:
                err = AcpSessionError(cooldown["message"])
                self._settle_submission(err)
                self._queue.put_nowait(
                    AgentEvent(
                        "error",
                        cooldown["message"],
                        metadata={
                            "antigravity_quota_cooldown": True,
                            "cooldown_until": cooldown["until"],
                        },
                    )
                )
                self._queue.put_nowait(
                    self._end(ok=False, reason="antigravity_cooldown", error="antigravity_cooldown", context=self._context)
                )
                return
            if self.session_id:
                cand_lock = self._owner.session_lock(self.session_id)
                await cand_lock.acquire()
                held_session_lock = cand_lock
                owns_session_lock = True
            recovering = self.session_id in self._owner.uncertain_sessions
            fresh_context = ""
            if recovering and not explicit:
                raise AcpSessionError("ACP recovery requires a new explicit user message")
            if explicit and (recovering or self._owner.recovery_cleanup_needed):
                async with self._owner._setup_lock:
                    if self.session_id:
                        bind_session(self._owner, self.session_id, self.app_session_id, resume=True)
                    # A fallback can leave an old native request quarantined while a
                    # sibling runs. Retire that transport on the next idle explicit turn.
                    if not self._owner.listeners and not self._owner.failure:
                        await self._owner.close("recovering uncertain ACP session")
            async with self._owner.turn_slot(self):
                async with self._owner._setup_lock:
                    if self._owner.epoch!=profile_epoch(self.home):
                        raise AcpSessionError("ACP profile epoch changed; explicit recovery required")
                    if self.session_id:
                        bind_session(self._owner,self.session_id,self.app_session_id,resume=True)
                    await verify_provider_egress("antigravity")
                    await self._owner.start()
                    record_provider_activity("antigravity")
                    replace_session = recovering and self.session_id in self._owner.uncertain_sessions
                    if replace_session or self.session_id not in self._owner.sessions:
                        params = {"cwd": str(Path(self.cwd).resolve()),
                                  "mcpServers": self._acp_mcp_servers()}
                        method = "session/new"
                        if self.session_id and not replace_session:
                            caps = self._owner.capabilities.get("sessionCapabilities", {})
                            if caps.get("resume") is not None:
                                params["sessionId"] = self.session_id
                                method = "session/resume"
                            elif recovering:
                                replace_session = True
                            else:
                                raise AcpSessionError("ACP resume unsupported; explicit new session required")
                        if method == "session/resume":
                            try:
                                result = await self._owner.request(method, params)
                            except AcpRPCRejected as error:
                                # Only unsupported/missing checkpoint contracts allow
                                # a new native session. Auth/quota failures do not.
                                if not recovering or error.code not in (-32601, -32602):
                                    raise
                                replace_session = True
                                method = "session/new"
                                params.pop("sessionId")
                        if method == "session/new":
                            if replace_session:
                                fresh_context = self._recovery_context(message, event_id)
                                held_session_lock.release()
                                owns_session_lock = False
                                self._instructions_sent = False
                            result = await self._owner.request(method, params)
                        session_id = result.get("sessionId", self.session_id if method == "session/resume" else None)
                        if not isinstance(session_id, str) or not session_id:
                            raise AcpError("ACP session response missing sessionId")
                        if method == "session/new" and session_id in self._owner.sessions:
                            await self._owner.close("ACP session ID collision; transport identity is corrupt")
                            raise AcpError("ACP new session ID collision; refusing shared conversation")
                        if not owns_session_lock:
                            fresh_lock = self._owner.session_lock(session_id)
                            if fresh_lock.locked():
                                raise AcpError("ACP new session lock already held")
                            await fresh_lock.acquire()
                            held_session_lock = fresh_lock
                            owns_session_lock = True
                        elif session_id != self.session_id:
                            await self._owner.close("ACP resumed session identity is corrupt")
                            raise AcpError("ACP resumed session ID mismatch")
                        if replace_session and self.session_id in self._owner.uncertain_sessions:
                            self._owner.recovery_cleanup_needed = True
                        self.session_id = session_id
                        bind_session(self._owner,session_id,self.app_session_id,resume=(method!="session/new"))
                        self._owner.sessions.add(session_id)
                        self._owner.remember_model_state(session_id, result)
                        if method == "session/new":
                            self._owner.cost_totals[session_id] = 0.0
                            self._owner.usage_totals[session_id] = {}
                    await self._select_model()
                    self._cost_baseline = self._owner.cost_totals.get(self.session_id)
                    self._owner.listeners[self.session_id] = self._update
                    self._owner.permission_handlers[self.session_id] = self
                    if self._steer_event is None:
                        self._steer_event = asyncio.Event()
                    if self._tool_idle_event is None:
                        self._tool_idle_event = asyncio.Event()
                        if not self._has_open_tool():
                            self._tool_idle_event.set()
                    self._accepting_steer = True
                turn_started = time.monotonic()
                turn_deltas = None
                last_measured_terminal = None
                last_reason = "error"
                step_index = 0
                current_batch = [{
                    "text": message,
                    "before_submit": self._before_submit,
                    "future": self._submission,
                }]
                if self._steer_queue:
                    current_batch.extend(self._steer_queue)
                    self._steer_queue.clear()
                    if self._steer_event is not None:
                        self._steer_event.clear()
                try:
                    while True:
                        step_text = "\n\n".join(item["text"] for item in current_batch)
                        blocks = [{"type": "text", "text": step_text}]
                        prompt_caps = (getattr(self._owner, "capabilities", None) or {}).get("promptCapabilities") or {}
                        if prompt_caps.get("audio") and self.model.startswith("gemini-"):
                            from app.native_voice import build_inline_audio_blocks
                            uploads_dir = Path(__file__).resolve().parent.parent / "data" / "uploads"
                            blocks.extend(build_inline_audio_blocks(step_text, uploads_dir))
                        if step_index == 0:
                            if fresh_context:
                                blocks.insert(0, {"type": "text", "text": fresh_context})
                            if self.system_prompt and not self._instructions_sent:
                                # ACP v1 has no stable system-prompt method; deliver role instructions
                                # as explicit first-turn context, never a shared agent file in HOME.
                                blocks.insert(0, {"type": "text", "text": "[Orchestra role instructions]\n" + self.system_prompt})

                        self._reported_usage = None
                        batch_ref = current_batch

                        async def _batch_before_write(items=batch_ref):
                            for item in items:
                                cb = item.get("before_submit")
                                if cb is not None:
                                    await cb()

                        def _batch_on_written(items=batch_ref):
                            self._instructions_sent = True
                            for item in items:
                                fut = item.get("future")
                                if fut is not None and not fut.done():
                                    fut.set_result(None)

                        prompt_task = asyncio.create_task(self._owner.request("session/prompt", {
                            "sessionId": self.session_id, "prompt": blocks},
                            before_write=_batch_before_write, on_written=_batch_on_written))
                        try:
                            if not self._steer_queue:
                                steer_waiter = asyncio.create_task(self._steer_event.wait())
                                try:
                                    await asyncio.wait({prompt_task, steer_waiter}, return_when=asyncio.FIRST_COMPLETED)
                                finally:
                                    if not steer_waiter.done():
                                        steer_waiter.cancel()
                                    await asyncio.gather(steer_waiter, return_exceptions=True)

                            if self._steer_queue and not prompt_task.done():
                                # Brief grace for an open tool call to finish before issuing session/cancel.
                                if self._has_open_tool() and self._tool_idle_event is not None:
                                    tool_waiter = asyncio.create_task(self._tool_idle_event.wait())
                                    try:
                                        await asyncio.wait({prompt_task, tool_waiter}, timeout=3.0, return_when=asyncio.FIRST_COMPLETED)
                                    finally:
                                        if not tool_waiter.done():
                                            tool_waiter.cancel()
                                        await asyncio.gather(tool_waiter, return_exceptions=True)

                            if not prompt_task.done():
                                self._flush_segment()
                                from app.native_requests import cancel_turn
                                cancel_turn(self._owner, self._turn_id)
                                await asyncio.sleep(0)
                                try:
                                    async with asyncio.timeout(5):
                                        await self._owner.notify("session/cancel", {"sessionId": self.session_id})
                                        result = await asyncio.shield(prompt_task)
                                except Exception:
                                    if self._owner._write_lock.locked():
                                        await self._owner.close("ACP transport write stalled; outcome unknown, no replay")
                                    else:
                                        self._owner.uncertain_sessions.add(self.session_id)
                                    raise
                            else:
                                result = await asyncio.shield(prompt_task)
                        except asyncio.CancelledError:
                            self._interrupted = True
                            self._accepting_steer = False
                            from app.native_requests import cancel_turn
                            cancel_turn(self._owner, self._turn_id)
                            await asyncio.sleep(0)
                            if not prompt_task.done():
                                try:
                                    # Cancellation must also bound a write-lock/backpressure
                                    # wait; a queued cancel notification cannot hang forever.
                                    async with asyncio.timeout(2):
                                        await self._owner.notify("session/cancel", {"sessionId": self.session_id})
                                        await asyncio.shield(prompt_task)
                                except (Exception, asyncio.CancelledError):
                                    if self._owner._write_lock.locked():
                                        # Partial framed transport write blocks ALL sessions.
                                        await self._owner.close("ACP transport write stalled; outcome unknown, no replay")
                                    else:
                                        self._owner.uncertain_sessions.add(self.session_id)
                                        # A slow model cancel alone must not kill siblings.
                            for item in batch_ref:
                                fut = item.get("future")
                                if fut is not None and not fut.done():
                                    fut.set_exception(AcpError("ACP submission cancelled"))
                            raise
                        except Exception as step_exc:
                            err = step_exc if isinstance(step_exc, AcpError) else AcpError("ACP submission failed")
                            for item in batch_ref:
                                fut = item.get("future")
                                if fut is not None and not fut.done():
                                    fut.set_exception(err)
                            raise

                        last_reason = result.get("stopReason", "error")
                        counters = result.get("usage", getattr(self, "_reported_usage", None))
                        measured_terminal = {**result, "usage": counters} if isinstance(counters, dict) else None
                        if measured_terminal is not None:
                            last_measured_terminal = measured_terminal
                            baseline = self._owner.usage_totals.get(self.session_id)
                            self._baseline_key = self._conversation_key()
                            self._cumulative = dict(baseline or {})
                            measured = self._turn_deltas(measured_terminal)
                            self._owner.usage_totals[self.session_id] = dict(self._cumulative)
                            if baseline is not None:
                                if turn_deltas is None:
                                    turn_deltas = dict(measured)
                                else:
                                    for k, v in measured.items():
                                        turn_deltas[k] = turn_deltas.get(k, 0) + v

                        if self._steer_queue:
                            self._flush_segment()
                            current_batch = list(self._steer_queue)
                            self._steer_queue.clear()
                            self._steer_event.clear()
                            step_index += 1
                            continue
                        self._accepting_steer = False
                        break
                finally:
                    self._accepting_steer = False
                    self._owner.listeners.pop(self.session_id, None)
                    self._owner.permission_handlers.pop(self.session_id,None)
                    from app.native_requests import cancel_turn
                    cancel_turn(self._owner,self._turn_id)
                self._queue.put_nowait(self._end(ok=last_reason == "end_turn", reason=last_reason,
                    usage=turn_deltas, terminal=last_measured_terminal,
                    error=None if last_reason == "end_turn" else last_reason, context=self._context,
                    duration_ms=round((time.monotonic() - turn_started) * 1000)))
        except asyncio.CancelledError:
            self._accepting_steer = False
            cancel_err = AcpError("ACP submission cancelled")
            self._settle_submission(cancel_err)
            self._fail_pending_steers(cancel_err)
            self._queue.put_nowait(self._end(reason="interrupt", error="interrupted", context=self._context))
        except AcpQuotaCooldownError as exc:
            self._accepting_steer = False
            self._settle_submission(exc)
            self._fail_pending_steers(exc)
            self._queue.put_nowait(
                AgentEvent(
                    "error",
                    str(exc)[:280],
                    metadata={
                        "antigravity_quota_cooldown": True,
                        "cooldown_until": exc.until_ts,
                    },
                )
            )
            self._queue.put_nowait(
                self._end(ok=False, reason="antigravity_cooldown", error="antigravity_cooldown", context=self._context)
            )
        except Exception as exc:
            self._accepting_steer = False
            raw_exc = str(exc)
            is_quota, until_ts, _ = parse_antigravity_quota_cooldown(raw_exc)
            if is_quota:
                info = trip_antigravity_cooldown(raw_exc, until_ts=until_ts)
                cd_err = AcpQuotaCooldownError(message=info["message"], until_ts=info["until"])
                self._settle_submission(cd_err)
                self._fail_pending_steers(cd_err)
                self._queue.put_nowait(
                    AgentEvent(
                        "error",
                        info["message"],
                        metadata={
                            "antigravity_quota_cooldown": True,
                            "cooldown_until": info["until"],
                        },
                    )
                )
                self._queue.put_nowait(
                    self._end(ok=False, reason="antigravity_cooldown", error="antigravity_cooldown", context=self._context)
                )
                return
            acp_err = exc if isinstance(exc, AcpError) else AcpError("ACP submission failed")
            self._settle_submission(acp_err)
            self._fail_pending_steers(acp_err)
            # Raw server error bodies and stderr can contain OAuth material.
            # Only bounded, locally authored errors reach the event stream.
            # Only the transport reader/writer or definite ban owns profile close.
            # A late failed turn must not close a replacement transport generation.
            reason = str(exc) if isinstance(exc, AcpError) else type(exc).__name__
            self._queue.put_nowait(AgentEvent("error", "Antigravity ACP failure: " + reason[:280]))
            self._queue.put_nowait(self._end(error="protocol", context=self._context))
        finally:
            record_provider_activity("antigravity")
            self._accepting_steer = False
            if owns_session_lock and held_session_lock is not None:
                held_session_lock.release()
            if prompt_task is not None:
                if not prompt_task.done():
                    prompt_task.cancel()
                await asyncio.gather(prompt_task, return_exceptions=True)
            self._stream_finished = True
            self._queue.put_nowait(None)

    def _acp_mcp_servers(self):
        servers = []
        for name, config in self.mcp_servers.items():
            if "command" not in config:
                raise ValueError("Antigravity ACP currently requires stdio MCP servers")
            # Existing IPC tool boundary restores kesha's GID and scrubs provider proxies.
            clean = next((p for p in ("/home/kesha/.local/bin/agy-clean-exec", "/usr/local/bin/agy-clean-exec")
                          if Path(p).is_file() and os.access(p, os.X_OK)), None)
            args_in = list(config.get("args", []))
            env_dict = config.get("env", {}) or {}
            if name == "orchestra":
                _scope = str(env_dict.get("ORCHESTRA_SCOPE") or "").strip()
                _sender = str(env_dict.get("WORKER_NAME") or "").strip()
                _sid = str(env_dict.get("ORCHESTRA_SESSION_ID") or "").strip()
                if _scope and "--scope" not in args_in:
                    args_in.extend(["--scope", _scope])
                if _sender and "--sender" not in args_in:
                    args_in.extend(["--sender", _sender])
                if _sid and "--session-id" not in args_in:
                    args_in.extend(["--session-id", _sid])
            command = clean or config["command"]
            args = [config["command"], *args_in] if clean else args_in
            servers.append({"name": name, "command": command,
                "args": args, "env": [
                    {"name": key, "value": str(value)} for key, value in config.get("env", {}).items()]})
        return servers

    async def events(self):
        while (event := await self._queue.get()) is not None:
            yield event

    async def interrupt(self):
        if self._task is None or self._task.done():
            return False
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            self._cancelled_before_run(self._task)
        return True

    async def retarget_model(self, model):
        from app.antigravity_acp import AcpSessionError
        if self._task is not None and not self._task.done():
            raise AcpSessionError("Cannot retarget an active ACP turn")
        previous = self.model
        previous_effort = self.effort
        self.model = model.removeprefix("antigravity/")
        self.effort = None  # Exact target model suffix takes precedence on retarget.
        try:
            if self._owner and self.session_id in self._owner.sessions:
                async with self._owner._setup_lock:
                    await self._select_model()  # ACK before publishing the switch.
        except BaseException:
            self.model, self.effort = previous, previous_effort
            raise
        from app.models import get_model_spec
        self.context_limit = get_model_spec(model).context_length

    async def release(self):
        """Final archive/accepted handoff only; disconnect is also used for resume."""
        await self.interrupt()
        if self._owner and self.session_id:
            await self._owner.release_session(self.session_id)

    async def disconnect(self):
        # Temporary adapter detachment must preserve native idle/resume state.
        await self.interrupt()
