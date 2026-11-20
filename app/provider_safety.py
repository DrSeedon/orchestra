"""Canonical anti-ban & residential proxy egress safety layer for subscription OAuth providers.

Subscription OAuth CLIs (`claude`, `codex`, `grok`, `antigravity`) must never send
OAuth traffic directly from datacenter ASNs (e.g. Contabo AS51167), must never leak
worker tool traffic (`git`, `uv`, `npm`, `pip`, `curl`) into the residential proxy,
must never allow untrusted `.mcp.json` env overrides to hijack proxy/TLS/auth vars,
and must immediately trip a durable circuit-breaker on unambiguous account/ToS bans.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import math
import logging
import os
import re
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlparse

from app.models import is_provider_disabled, normalize_provider_key, set_provider_disabled

logger = logging.getLogger("orchestra.provider_safety")

SUBSCRIPTION_OAUTH_RUNTIMES: tuple[str, ...] = ("claude", "codex", "grok", "antigravity")

PROVIDER_PROXY_ENV_KEYS: dict[str, str] = {
    "claude": "CLAUDE_PROXY_URL",
    "codex": "CODEX_PROXY_URL",
    "grok": "GROK_PROXY_URL",
    "antigravity": "ANTIGRAVITY_PROXY_URL",
}

PROXY_ENV_VARS: tuple[str, ...] = (
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "ALL_PROXY",
    "GRPC_PROXY",
    "https_proxy",
    "http_proxy",
    "all_proxy",
    "grpc_proxy",
)

NO_PROXY_ENV_VARS: tuple[str, ...] = (
    "NO_PROXY",
    "no_proxy",
    "NO_GRPC_PROXY",
    "no_grpc_proxy",
)

SAFE_LOOPBACK_NO_PROXY: tuple[str, ...] = (
    "localhost",
    "127.0.0.1",
    "::1",
    "[::1]",
)

# Shell-tool proxy exclusion list for Codex `shell_environment_policy.exclude`
# and Claude `CLAUDE_ENV_FILE` so worker bash commands (`git`, `uv`, `npm`, `pip`, `curl`)
# never burn residential proxy bandwidth.
SHELL_TOOL_EXCLUDED_PROXY_VARS: tuple[str, ...] = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "GRPC_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "grpc_proxy",
)

BLOCKED_DATACENTER_ASNS: frozenset[int] = frozenset({
    51167,   # Contabo GmbH
    24940,   # Hetzner Online GmbH
    16276,   # OVH SAS
    14061,   # DigitalOcean, LLC
    9123,    # Timeweb
    16509,   # Amazon.com, Inc. (AWS)
    14618,   # Amazon.com, Inc. (AWS)
    15169,   # Google Cloud / Google LLC
    396982,  # Google Cloud Platform
    8075,    # Microsoft Corporation (Azure)
    20473,   # The Constant Company / Vultr / Choopa
    63949,   # Akamai / Linode
})

BLOCKED_DATACENTER_ORG_KEYWORDS: tuple[str, ...] = (
    "contabo",
    "hetzner",
    "digitalocean",
    "ovh",
    "timeweb",
    "choopa",
    "vultr",
    "linode",
    "amazon.com",
    "amazonaws",
    "google cloud",
    "microsoft corporation",
)

BLOCKED_COUNTRIES: frozenset[str] = frozenset({"RU", "BY"})

_VENDOR_DOMAIN_SUFFIXES: tuple[str, ...] = (
    "anthropic.com",
    "claude.ai",
    "claude.com",
    "openai.com",
    "chatgpt.com",
    "x.ai",
    "grok.com",
    "googleapis.com",
    "google.com",
    "gstatic.com",
)

# Untrusted `.mcp.json` / `extra_env` keys that must NEVER override provider transport,
# TLS roots, dynamic linker state, or subscription billing mode.
_SAFE_LOCAL_NO_PROXY_SUFFIXES: tuple[str, ...] = (
    ".local",
    ".localhost",
    ".internal",
    ".lan",
    ".home.arpa",
    ".test",
    ".invalid",
    ".corp",
    ".intranet",
)

_UNTRUSTED_EXTRA_ENV_LOWER_PREFIXES: tuple[str, ...] = (
    "ld_",
    "python",
    "node_",
    "ssl_",
    "antigravity_",
    "codex_",
    "claude_",
    "grok_",
)

_UNTRUSTED_EXTRA_ENV_LOWER_DENYLIST: frozenset[str] = frozenset({
    *(k.lower() for k in PROXY_ENV_VARS),
    *(k.lower() for k in NO_PROXY_ENV_VARS),
    "path",
    "home",
    "user",
    "logname",
    "env",
    "bash_env",
    "shell",
    "xdg_config_home",
    "xdg_cache_home",
    "xdg_data_home",
    "git_ssh_command",
    "orchestra_residential_proxy_url",
    "orchestra_upstream_proxy_port",
    "orchestra_disabled_providers",
    "orchestra_disabled_providers_file",
    "claude_proxy_url",
    "codex_proxy_url",
    "grok_proxy_url",
    "antigravity_proxy_url",
    "allow_datacenter_oauth_egress",
    "orchestra_enforce_provider_egress",
    "openai_base_url",
    "openai_api_base",
    "openai_api_key",
    "anthropic_base_url",
    "anthropic_api_key",
    "anthropic_auth_token",
    "orchestra_claude_credit_api_key",
    "gemini_api_key",
    "google_api_key",
    "google_application_credentials",
    "google_genai_use_vertexai",
    "requests_ca_bundle",
    "curl_ca_bundle",
    "agy_cli_disable_auto_update",
})

_PERMANENT_BAN_MARKERS: tuple[str, ...] = (
    "violation of terms of service",
    "has been disabled in this account",
    "account has been disabled",
    "your account has been disabled",
    "organization has been disabled",
    "account_deactivated",
    "account_suspended",
    "access_terminated",
    "user_banned",
)

_ALLOWED_PROXY_SCHEMES: frozenset[str] = frozenset({
    "http",
    "https",
    "socks5",
    "socks5h",
})

DEFAULT_EGRESS_VERIFY_TTL_SECONDS = 600.0
EGRESS_BLOCKED_CACHE_SECONDS = 300.0
EGRESS_TRANSIENT_FAILURE_BACKOFF_SECONDS = 60.0
DEFAULT_PROVIDER_ACTIVITY_WINDOW_SECONDS = 1800.0

_CLAUDE_BASH_CLEAN_SCRIPT = Path("/tmp/orchestra-claude-bash-clean.sh")


class ProviderDisabledError(RuntimeError):
    """Raised when a subscription OAuth provider is disabled by policy or circuit-breaker."""


class EgressSafetyError(RuntimeError):
    """Raised when subscription OAuth egress cannot be proven safe (Fail-Closed)."""


_egress_cache: dict[str, dict] = {}
_egress_locks_guard = threading.Lock()
_egress_locks: dict[tuple[int, str], asyncio.Lock] = {}

_activity_lock = threading.Lock()
_last_provider_activity_ts: dict[str, float] = {}
_unobserved_activity_since_ts: dict[str, float] = {}
_last_quota_observed_ts: dict[str, float] = {}
_activity_db_path: str = ""
_ACTIVITY_KV_PREFIX = "provider_activity:"

_incident_lock = threading.Lock()
_tripped_incidents_mem: set[tuple[str, str]] = set()


def _get_egress_lock(proxy_url: str) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    key = (id(loop), proxy_url)
    with _egress_locks_guard:
        lock = _egress_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _egress_locks[key] = lock
        return lock


def reset_provider_safety_state_for_tests() -> None:
    """Clear in-memory egress verification, activity, and incident caches in tests."""
    _egress_cache.clear()
    with _egress_locks_guard:
        _egress_locks.clear()
    with _activity_lock:
        _last_provider_activity_ts.clear()
        _unobserved_activity_since_ts.clear()
        _last_quota_observed_ts.clear()
        global _activity_db_path
        _activity_db_path = ""
    with _incident_lock:
        _tripped_incidents_mem.clear()


def _sync_activity_db_locked() -> None:
    global _activity_db_path
    try:
        from app import db
        current = str(getattr(db, "DB_PATH", ""))
        if _activity_db_path != current:
            _last_provider_activity_ts.clear()
            _unobserved_activity_since_ts.clear()
            _last_quota_observed_ts.clear()
            _activity_db_path = current
    except Exception:
        pass


def _load_activity_kv_locked(key: str) -> None:
    if key in _last_provider_activity_ts or key in _last_quota_observed_ts:
        return
    try:
        from app import db
        raw = db.kv_get(f"{_ACTIVITY_KV_PREFIX}{key}", "")
        if not raw:
            return
        data = json.loads(raw)
        if isinstance(data, dict):
            last_act = data.get("last_activity_at")
            unobs = data.get("unobserved_since")
            last_obs = data.get("last_quota_observed_at")
            if isinstance(last_act, (int, float)) and last_act > 0:
                _last_provider_activity_ts[key] = float(last_act)
            if isinstance(unobs, (int, float)) and unobs > 0:
                _unobserved_activity_since_ts[key] = float(unobs)
            if isinstance(last_obs, (int, float)) and last_obs > 0:
                _last_quota_observed_ts[key] = float(last_obs)
    except Exception:
        pass


def _persist_activity_kv_locked(key: str) -> None:
    try:
        from app import db
        payload = {
            "last_activity_at": _last_provider_activity_ts.get(key),
            "unobserved_since": _unobserved_activity_since_ts.get(key),
            "last_quota_observed_at": _last_quota_observed_ts.get(key),
        }
        db.kv_set(f"{_ACTIVITY_KV_PREFIX}{key}", json.dumps(payload))
    except Exception:
        pass


def record_provider_activity(provider: str) -> None:
    """Mark real worker/orchestrator turn activity for a subscription OAuth provider."""
    key = normalize_provider_key(provider)
    if key not in SUBSCRIPTION_OAUTH_RUNTIMES:
        return
    now = time.time()
    with _activity_lock:
        _sync_activity_db_locked()
        _load_activity_kv_locked(key)
        _last_provider_activity_ts[key] = now
        last_obs = _last_quota_observed_ts.get(key, 0.0)
        if now > last_obs + 60.0:
            prev_unobs = _unobserved_activity_since_ts.get(key, 0.0)
            if prev_unobs <= last_obs + 60.0:
                _unobserved_activity_since_ts[key] = now
        _persist_activity_kv_locked(key)


def record_provider_quota_observation(provider: str, observed_at: float) -> None:
    """Record a fresh quota snapshot timestamp, clearing pending unobserved activity."""
    key = normalize_provider_key(provider)
    if key not in SUBSCRIPTION_OAUTH_RUNTIMES:
        return
    with _activity_lock:
        _sync_activity_db_locked()
        _load_activity_kv_locked(key)
        ts = float(observed_at)
        if ts >= _last_quota_observed_ts.get(key, 0.0):
            _last_quota_observed_ts[key] = ts
            _unobserved_activity_since_ts.pop(key, None)
            _persist_activity_kv_locked(key)


def provider_activity_state(provider: str) -> dict[str, float | None]:
    """Return last recorded turn activity and unobserved streak start for a provider."""
    key = normalize_provider_key(provider)
    if key not in SUBSCRIPTION_OAUTH_RUNTIMES:
        return {"last_activity_at": None, "unobserved_since": None}
    with _activity_lock:
        _sync_activity_db_locked()
        _load_activity_kv_locked(key)
        return {
            "last_activity_at": _last_provider_activity_ts.get(key),
            "unobserved_since": _unobserved_activity_since_ts.get(key),
        }


def has_recent_provider_activity(
    provider: str,
    *,
    window_seconds: float = DEFAULT_PROVIDER_ACTIVITY_WINDOW_SECONDS,
    now: float | None = None,
) -> bool:
    """Return True if provider has a running session right now or had real turn activity recently."""
    key = normalize_provider_key(provider)
    if key not in SUBSCRIPTION_OAUTH_RUNTIMES:
        return False
    checked_at = time.time() if now is None else float(now)
    with _activity_lock:
        last_ts = _last_provider_activity_ts.get(key, 0.0)
    if last_ts > 0 and 0 <= (checked_at - last_ts) < window_seconds:
        return True
    try:
        from app.models import get_model_runtime
        from app.state import manager

        for session in list(manager.sessions.values()):
            status_val = getattr(getattr(session, "status", None), "value", None)
            if status_val != "running":
                continue
            runtime = normalize_provider_key(get_model_runtime(getattr(session, "model", "")))
            if runtime == key:
                return True
    except Exception:
        pass
    return False


def _is_dangerous_no_proxy_entry(item: str) -> bool:
    token = item.strip().lower()
    if not token or "*" in token or "/" in token:
        return True
    if token.startswith("["):
        if "]" not in token:
            return True
        ip_part = token[1 : token.index("]")]
        try:
            addr = ipaddress.ip_address(ip_part)
        except ValueError:
            return True
        return not (addr.is_loopback or (addr.is_private and not addr.is_global))
    if token.count(":") > 1:
        try:
            addr = ipaddress.ip_address(token)
        except ValueError:
            return True
        return not (addr.is_loopback or (addr.is_private and not addr.is_global))
    host = token.split(":", 1)[0]
    stripped = host.lstrip(".")
    if not stripped:
        return True
    try:
        addr = ipaddress.ip_address(stripped)
        return not (addr.is_loopback or (addr.is_private and not addr.is_global))
    except ValueError:
        pass
    if stripped == "localhost":
        return host.startswith(".")
    # Reject bare single-label TLDs/tokens such as `com`, `.com`, `ai`, `.local`.
    if "." not in stripped:
        return True
    for vendor in _VENDOR_DOMAIN_SUFFIXES:
        if stripped == vendor or stripped.endswith("." + vendor):
            return True
    if any(stripped.endswith(suf) for suf in _SAFE_LOCAL_NO_PROXY_SUFFIXES):
        return False
    # Fail closed on arbitrary public domains (`chatgpt.com`, `1e100.net`, `cloudflare.com`).
    return True


def sanitize_no_proxy(existing: str = "") -> str:
    """Build a safe NO_PROXY string keeping loopback + non-wildcard non-vendor local hosts."""
    kept: list[str] = []
    seen: set[str] = set()
    for raw_part in (existing or "").split(","):
        part = raw_part.strip()
        if not part or _is_dangerous_no_proxy_entry(part):
            continue
        low = part.lower()
        if low not in seen:
            kept.append(part)
            seen.add(low)
    for host in SAFE_LOOPBACK_NO_PROXY:
        low = host.lower()
        if low not in seen:
            kept.append(host)
            seen.add(low)
    return ",".join(kept)


def sanitize_extra_env(extra_env: Mapping[str, str] | None) -> dict[str, str]:
    """Strip untrusted transport, TLS-CA, linker, and auth-override keys from `.mcp.json` env."""
    if not extra_env:
        return {}
    cleaned: dict[str, str] = {}
    for k, v in extra_env.items():
        key_str = str(k)
        low = key_str.lower()
        if low in _UNTRUSTED_EXTRA_ENV_LOWER_DENYLIST or low.startswith(_UNTRUSTED_EXTRA_ENV_LOWER_PREFIXES):
            logger.warning("Stripped untrusted extra_env override key %r", key_str)
            continue
        cleaned[key_str] = str(v)
    return cleaned


def resolve_provider_proxy(
    provider: str,
    base_env: Mapping[str, str] | None = None,
) -> str:
    """Resolve the canonical residential proxy URL for a subscription OAuth provider.

    Precedence (strictly from trusted operator environment, never untrusted `.mcp.json`):
      1. `<PROVIDER>_PROXY_URL` (`CLAUDE_PROXY_URL`, `CODEX_PROXY_URL`, `GROK_PROXY_URL`, `ANTIGRAVITY_PROXY_URL`)
      2. `ORCHESTRA_RESIDENTIAL_PROXY_URL`
      3. Trusted operator `HTTPS_PROXY` / `HTTP_PROXY` (only if valid proxy URL)
    """
    key = normalize_provider_key(provider)
    if key not in SUBSCRIPTION_OAUTH_RUNTIMES:
        return ""
    env = os.environ if base_env is None else base_env
    specific_var = PROVIDER_PROXY_ENV_KEYS[key]
    for candidate_key in (
        specific_var,
        "ORCHESTRA_RESIDENTIAL_PROXY_URL",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "https_proxy",
        "http_proxy",
    ):
        raw = (env.get(candidate_key) or "").strip()
        if raw:
            parsed = urlparse(raw)
            if parsed.scheme.lower() not in _ALLOWED_PROXY_SCHEMES or not parsed.hostname or not parsed.port:
                raise EgressSafetyError(
                    f"Invalid proxy URL in {candidate_key} for provider {key!r}: "
                    "expected scheme://host:port"
                )
            return raw
    return ""


def ensure_claude_bash_clean_script() -> str:
    """Write a tiny 0644 script sourced via CLAUDE_ENV_FILE so Claude's Bash tool drops proxy vars."""
    content = (
        "# Managed by Orchestra provider_safety: prevent worker Bash tools from burning residential proxy\n"
        "unset HTTP_PROXY HTTPS_PROXY ALL_PROXY GRPC_PROXY "
        "http_proxy https_proxy all_proxy grpc_proxy\n"
    )
    try:
        if not _CLAUDE_BASH_CLEAN_SCRIPT.is_file() or _CLAUDE_BASH_CLEAN_SCRIPT.read_text(encoding="utf-8") != content:
            tmp = _CLAUDE_BASH_CLEAN_SCRIPT.with_name(f".{_CLAUDE_BASH_CLEAN_SCRIPT.name}.{os.getpid()}.tmp")
            tmp.write_text(content, encoding="utf-8")
            os.chmod(tmp, 0o644)
            os.replace(tmp, _CLAUDE_BASH_CLEAN_SCRIPT)
        return str(_CLAUDE_BASH_CLEAN_SCRIPT)
    except OSError:
        return ""


def build_provider_env(
    provider: str,
    base_env: Mapping[str, str] | None = None,
    *,
    extra_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Construct a sanitized, proxy-pinned subprocess environment for an OAuth CLI."""
    key = normalize_provider_key(provider)
    if key not in SUBSCRIPTION_OAUTH_RUNTIMES:
        raise ValueError(f"Unsupported subscription OAuth provider: {provider!r}")

    source_env = dict(os.environ if base_env is None else base_env)
    trusted_no_proxy = source_env.get("NO_PROXY") or source_env.get("no_proxy") or ""
    proxy_url = resolve_provider_proxy(key, source_env)

    # Clear all inherited proxy/no_proxy case variants before merging sanitized extra_env.
    for var in (*PROXY_ENV_VARS, *NO_PROXY_ENV_VARS):
        source_env.pop(var, None)

    source_env.update(sanitize_extra_env(extra_env))

    if key == "antigravity":
        for forbidden in (
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "GOOGLE_APPLICATION_CREDENTIALS",
            "GOOGLE_GENAI_USE_VERTEXAI",
        ):
            source_env.pop(forbidden, None)
    elif key == "claude":
        source_env["ANTHROPIC_API_KEY"] = ""
        source_env["ORCHESTRA_CLAUDE_CREDIT_API_KEY"] = ""
        source_env.pop("ANTHROPIC_AUTH_TOKEN", None)
        source_env.pop("ANTHROPIC_BASE_URL", None)
        source_env["DISABLE_NON_ESSENTIAL_MODEL_CALLS"] = "1"
        source_env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        source_env["DISABLE_AUTOUPDATER"] = "1"
        source_env["DISABLE_TELEMETRY"] = "1"
        source_env["DISABLE_ERROR_REPORTING"] = "1"
        source_env["CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING"] = "1"
        bash_clean = ensure_claude_bash_clean_script()
        if bash_clean and not source_env.get("CLAUDE_ENV_FILE"):
            source_env["CLAUDE_ENV_FILE"] = bash_clean
    elif key == "codex":
        source_env.pop("OPENAI_API_KEY", None)
        source_env.pop("OPENAI_BASE_URL", None)
        source_env.pop("OPENAI_API_BASE", None)

    safe_no_proxy = sanitize_no_proxy(trusted_no_proxy)
    if proxy_url:
        for var in PROXY_ENV_VARS:
            source_env[var] = proxy_url
        for var in NO_PROXY_ENV_VARS:
            source_env[var] = safe_no_proxy
    else:
        # Even without an active proxy, keep NO_PROXY sanitized so wildcard `*` never survives.
        if trusted_no_proxy:
            source_env["NO_PROXY"] = safe_no_proxy
            source_env["no_proxy"] = safe_no_proxy

    assert_safe_provider_env(key, source_env, expected_proxy=proxy_url)
    return source_env


def build_claude_sdk_env_overlay(
    base_env: Mapping[str, str] | None = None,
    *,
    config_dir: str | None = None,
) -> dict[str, str]:
    """Build the explicit `ClaudeAgentOptions.env` overlay dict.

    `claude-agent-sdk` merges `{**os.environ, **options.env}`, so clearing ambient
    API-key / proxy variables requires explicit empty-string overrides in `options.env`
    without copying unrelated host variables into `options.env`.
    """
    source_env = os.environ if base_env is None else base_env
    proxy_url = resolve_provider_proxy("claude", source_env)
    safe_no_proxy = sanitize_no_proxy(source_env.get("NO_PROXY") or source_env.get("no_proxy") or "")

    env: dict[str, str] = {}
    if proxy_url:
        for var in PROXY_ENV_VARS:
            env[var] = proxy_url
        for var in NO_PROXY_ENV_VARS:
            env[var] = safe_no_proxy
    else:
        for var in PROXY_ENV_VARS:
            if source_env.get(var):
                env[var] = ""
        if source_env.get("NO_PROXY") or source_env.get("no_proxy"):
            env["NO_PROXY"] = safe_no_proxy
            env["no_proxy"] = safe_no_proxy

    env["DISABLE_NON_ESSENTIAL_MODEL_CALLS"] = "1"
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    env["DISABLE_AUTOUPDATER"] = "1"
    env["DISABLE_TELEMETRY"] = "1"
    env["DISABLE_ERROR_REPORTING"] = "1"
    env["CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING"] = "1"
    env["ORCHESTRA_CLAUDE_CREDIT_API_KEY"] = ""
    env["ANTHROPIC_API_KEY"] = ""
    if source_env.get("ANTHROPIC_AUTH_TOKEN"):
        env["ANTHROPIC_AUTH_TOKEN"] = ""
    if source_env.get("ANTHROPIC_BASE_URL"):
        env["ANTHROPIC_BASE_URL"] = ""
    bash_clean = ensure_claude_bash_clean_script()
    if bash_clean and not source_env.get("CLAUDE_ENV_FILE"):
        env["CLAUDE_ENV_FILE"] = bash_clean
    if config_dir:
        env["CLAUDE_CONFIG_DIR"] = os.path.expanduser(config_dir)
    if proxy_url:
        assert_safe_provider_env("claude", env, expected_proxy=proxy_url)
    return env


def assert_safe_provider_env(
    provider: str,
    env: Mapping[str, str],
    *,
    expected_proxy: str | None = None,
) -> None:
    """Final launch-time assertion ensuring proxy/no_proxy invariants were not bypassed."""
    if expected_proxy:
        for var in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "https_proxy", "http_proxy", "all_proxy"):
            if env.get(var) != expected_proxy:
                raise EgressSafetyError(f"{provider}: {var} mismatch after env sanitization")
        for var in NO_PROXY_ENV_VARS:
            val = env.get(var, "")
            parts = [p.strip() for p in val.split(",") if p.strip()]
            low_parts = {p.lower() for p in parts}
            if (
                not {"localhost", "127.0.0.1", "::1"}.issubset(low_parts)
                or any(_is_dangerous_no_proxy_entry(p) for p in parts)
            ):
                raise EgressSafetyError(f"{provider}: unsafe {var}={val!r}")


async def _probe_tcp_port(host: str, port: int, timeout: float) -> None:
    _reader, writer = await asyncio.wait_for(
        asyncio.open_connection(host, port),
        timeout=timeout,
    )
    writer.close()
    try:
        await asyncio.wait_for(writer.wait_closed(), timeout=0.5)
    except Exception:
        pass


async def _check_local_proxy_listener(
    proxy_url: str,
    timeout: float = 2.0,
    *,
    env: Mapping[str, str] | None = None,
) -> None:
    """Verify local proxy TCP listener (+ upstream xray leg when chained) is accepting connections."""
    parsed = urlparse(proxy_url)
    host = parsed.hostname or ""
    port = parsed.port
    if not host or not port:
        raise EgressSafetyError(f"Invalid proxy endpoint in {proxy_url!r}")
    try:
        await _probe_tcp_port(host, port, timeout)
    except Exception as exc:
        raise EgressSafetyError(
            f"Residential proxy listener {host}:{port} is unreachable ({type(exc).__name__}: {exc})"
        ) from exc

    eff_env = os.environ if env is None else env
    raw_up = (eff_env.get("ORCHESTRA_UPSTREAM_PROXY_PORT") or "").strip()
    check_upstream = False
    upstream_port = 10809
    if raw_up:
        try:
            upstream_port = int(raw_up)
            check_upstream = upstream_port > 0
        except ValueError as exc:
            raise EgressSafetyError(f"Invalid ORCHESTRA_UPSTREAM_PROXY_PORT={raw_up!r}") from exc
    elif host in ("127.0.0.1", "localhost", "::1") and port == 18080:
        check_upstream = True

    if check_upstream and host in ("127.0.0.1", "localhost", "::1"):
        try:
            await _probe_tcp_port("127.0.0.1", upstream_port, timeout)
        except Exception as exc:
            raise EgressSafetyError(
                f"Upstream residential tunnel 127.0.0.1:{upstream_port} is unreachable ({type(exc).__name__}: {exc})"
            ) from exc


def invalidate_provider_egress_cache(proxy_url: str | None = None) -> None:
    """Drop cached egress verification on upstream tunnel/proxy failure."""
    if proxy_url:
        _egress_cache.pop(proxy_url, None)
    else:
        _egress_cache.clear()


def _parse_asn_number(raw_asn: object) -> int | None:
    if isinstance(raw_asn, int) and not isinstance(raw_asn, bool):
        return raw_asn
    if isinstance(raw_asn, str):
        m = re.search(r"\b(?:AS)?(\d{1,10})\b", raw_asn.strip(), re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return None
    return None


def _evaluate_egress_identity(identity: dict) -> None:
    ip = str(identity.get("ip") or "").strip()
    country = str(identity.get("country") or "").strip().upper()
    asn = _parse_asn_number(identity.get("asn"))
    org = str(identity.get("org") or "").strip()
    hosting = identity.get("hosting")

    if not ip:
        raise EgressSafetyError("Residential proxy egress check returned empty IP")
    try:
        parsed_ip = ipaddress.ip_address(ip)
    except ValueError as exc:
        raise EgressSafetyError(f"Residential proxy egress check returned invalid IP {ip!r}") from exc
    if not parsed_ip.is_global:
        raise EgressSafetyError(f"Residential proxy egress check returned non-global IP {ip}")
    if len(country) != 2 or not country.isalpha():
        raise EgressSafetyError(f"Residential proxy egress check missing valid ISO country for IP {ip}")
    if asn is None and not org:
        raise EgressSafetyError(f"Residential proxy egress check missing ASN/org metadata for IP {ip}")
    if country in BLOCKED_COUNTRIES:
        raise EgressSafetyError(
            f"Blocked egress country {country!r} on exit IP {ip} (RU/BY forbidden for OAuth)"
        )
    if asn in BLOCKED_DATACENTER_ASNS:
        raise EgressSafetyError(
            f"Blocked datacenter ASN AS{asn} ({org or 'datacenter'}) on exit IP {ip}"
        )
    if hosting is True:
        raise EgressSafetyError(
            f"Blocked hosting/datacenter exit IP {ip} (AS{asn or '?'} {org})"
        )
    org_lower = org.lower()
    for keyword in BLOCKED_DATACENTER_ORG_KEYWORDS:
        if keyword in org_lower:
            raise EgressSafetyError(
                f"Blocked datacenter network {org!r} (AS{asn or '?'}) on exit IP {ip}"
            )


async def _probe_proxy_egress_identity(proxy_url: str) -> dict:
    """Query lightweight IP/ASN JSON endpoint through the residential proxy (trust_env=False)."""
    import httpx

    errors: list[str] = []
    async with httpx.AsyncClient(proxy=proxy_url, trust_env=False, timeout=8.0) as client:
        # 1. ipwho.is — provides IP, country_code, connection.asn, connection.org
        try:
            resp = await client.get(
                "https://ipwho.is/",
                headers={"Accept": "application/json", "User-Agent": "curl/8.5.0"},
            )
            if resp.status_code == 200:
                payload = resp.json()
                if isinstance(payload, dict) and payload.get("success", True) is not False and payload.get("ip"):
                    conn = payload.get("connection") if isinstance(payload.get("connection"), dict) else {}
                    sec = payload.get("security") if isinstance(payload.get("security"), dict) else {}
                    return {
                        "ip": str(payload.get("ip") or ""),
                        "country": str(payload.get("country_code") or ""),
                        "asn": _parse_asn_number(conn.get("asn")),
                        "org": str(conn.get("org") or conn.get("isp") or ""),
                        "hosting": sec.get("hosting") if isinstance(sec.get("hosting"), bool) else None,
                        "source": "ipwho.is",
                    }
            errors.append(f"ipwho.is HTTP {resp.status_code}")
        except Exception as exc:
            errors.append(f"ipwho.is {type(exc).__name__}: {exc}")

        # 2. ipinfo.io/json — provides ip, country, org ("AS215294 Lumina broadband UAB")
        try:
            resp = await client.get(
                "https://ipinfo.io/json",
                headers={"Accept": "application/json", "User-Agent": "curl/8.5.0"},
            )
            if resp.status_code == 200:
                payload = resp.json()
                if isinstance(payload, dict) and payload.get("ip"):
                    org_raw = str(payload.get("org") or "")
                    return {
                        "ip": str(payload.get("ip") or ""),
                        "country": str(payload.get("country") or ""),
                        "asn": _parse_asn_number(org_raw),
                        "org": org_raw,
                        "hosting": None,
                        "source": "ipinfo.io",
                    }
            errors.append(f"ipinfo.io HTTP {resp.status_code}")
        except Exception as exc:
            errors.append(f"ipinfo.io {type(exc).__name__}: {exc}")

    raise EgressSafetyError(
        "Unable to verify residential proxy exit IP/ASN (" + "; ".join(errors) + ")"
    )


async def verify_provider_egress(
    provider: str,
    *,
    env: Mapping[str, str] | None = None,
    enforce_in_tests: bool = False,
) -> dict:
    """Fail-Closed preflight before launching or sending to a subscription OAuth provider.

    - Zero background timers: runs only on real demand.
    - Always checks disabled latch (`0 bytes`) and local TCP proxy listener (`<2ms`, `0 bytes` upstream).
    - Singleflight caches verified exit IP/ASN for `ORCHESTRA_EGRESS_VERIFY_TTL_SECONDS` (default 3600s).
    """
    key = normalize_provider_key(provider)
    if key not in SUBSCRIPTION_OAUTH_RUNTIMES:
        return {"ok": True, "provider": key or provider, "mode": "non_oauth"}

    effective_env = os.environ if env is None else env
    in_unforced_pytest = (
        not enforce_in_tests
        and bool(os.environ.get("PYTEST_CURRENT_TEST"))
        and effective_env.get("ORCHESTRA_ENFORCE_PROVIDER_EGRESS") != "1"
    )
    if in_unforced_pytest:
        from app.models import _disabled_providers_file

        env_disabled = {
            normalize_provider_key(v)
            for v in effective_env.get("ORCHESTRA_DISABLED_PROVIDERS", "").split(",")
            if v.strip()
        }
        if key in env_disabled or (_disabled_providers_file().exists() and is_provider_disabled(key)):
            raise ProviderDisabledError(
                f"Subscription OAuth provider {key!r} is disabled; refusing egress"
            )
        return {"ok": True, "provider": key, "mode": "pytest_bypass"}

    if is_provider_disabled(key):
        raise ProviderDisabledError(
            f"Subscription OAuth provider {key!r} is disabled; refusing egress"
        )

    proxy_url = resolve_provider_proxy(key, effective_env)
    if not proxy_url:
        if effective_env.get("ALLOW_DATACENTER_OAUTH_EGRESS") == "1":
            logger.warning(
                "ALLOW_DATACENTER_OAUTH_EGRESS=1 active: allowing unproxied OAuth egress for %s",
                key,
            )
            return {"ok": True, "provider": key, "mode": "datacenter_override"}
        raise EgressSafetyError(
            f"Refusing subscription OAuth egress for {key!r}: no residential proxy configured "
            f"(set {PROVIDER_PROXY_ENV_KEYS[key]} or ORCHESTRA_RESIDENTIAL_PROXY_URL)"
        )

    # Local TCP socket check: catches a dead tinyproxy/xray in <2ms with 0 residential bytes.
    await _check_local_proxy_listener(proxy_url, env=effective_env)

    try:
        ttl = float(effective_env.get("ORCHESTRA_EGRESS_VERIFY_TTL_SECONDS") or DEFAULT_EGRESS_VERIFY_TTL_SECONDS)
    except ValueError:
        ttl = DEFAULT_EGRESS_VERIFY_TTL_SECONDS

    now = time.monotonic()
    cached = _egress_cache.get(proxy_url)
    if cached is not None:
        age = now - cached["ts"]
        if cached["status"] == "verified" and age < ttl:
            return cached["result"]
        if cached["status"] == "blocked" and age < EGRESS_BLOCKED_CACHE_SECONDS:
            raise EgressSafetyError(cached["error"])
        if cached["status"] == "transient_error" and age < EGRESS_TRANSIENT_FAILURE_BACKOFF_SECONDS:
            raise EgressSafetyError(cached["error"])

    async with _get_egress_lock(proxy_url):
        now = time.monotonic()
        cached = _egress_cache.get(proxy_url)
        if cached is not None:
            age = now - cached["ts"]
            if cached["status"] == "verified" and age < ttl:
                return cached["result"]
            if cached["status"] == "blocked" and age < EGRESS_BLOCKED_CACHE_SECONDS:
                raise EgressSafetyError(cached["error"])
            if cached["status"] == "transient_error" and age < EGRESS_TRANSIENT_FAILURE_BACKOFF_SECONDS:
                raise EgressSafetyError(cached["error"])

        try:
            identity = await _probe_proxy_egress_identity(proxy_url)
        except EgressSafetyError as exc:
            _egress_cache[proxy_url] = {
                "status": "transient_error",
                "ts": time.monotonic(),
                "error": str(exc),
            }
            raise

        try:
            _evaluate_egress_identity(identity)
        except EgressSafetyError as exc:
            _egress_cache[proxy_url] = {
                "status": "blocked",
                "ts": time.monotonic(),
                "error": str(exc),
            }
            raise

        result = {
            "ok": True,
            "provider": key,
            "mode": "verified_proxy",
            "ip": identity["ip"],
            "country": identity["country"],
            "asn": identity["asn"],
            "org": identity["org"],
            "source": identity["source"],
        }
        _egress_cache[proxy_url] = {
            "status": "verified",
            "ts": time.monotonic(),
            "result": result,
        }
        logger.info(
            "Verified residential proxy egress for %s: ip=%s country=%s asn=AS%s (%s)",
            key,
            identity["ip"],
            identity["country"],
            identity["asn"] or "?",
            identity["org"] or identity["source"],
        )
        return result


def _extract_error_text(value: object) -> str:
    """Extract error-relevant fields without scanning unrelated assistant prose."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        # Avoid false positives on assistant prose when a terminal dict carries `response`.
        error_keys = {"error", "errors", "message", "detail", "details", "code", "type", "status",
                      "codexErrorInfo", "data", "cause", "innerError", "errorInfo"}
        def structured_error(node, depth=0):
            if depth > 12:
                return None
            if isinstance(node, dict):
                return {k: structured_error(v, depth + 1) for k, v in node.items()
                        if k in error_keys}
            if isinstance(node, list):
                return [structured_error(v, depth + 1) for v in node[:64]]
            return node if isinstance(node, (str, int, float, bool)) or node is None else None
        focused = {k: structured_error(v) for k, v in value.items() if k in error_keys}
        target = focused if focused else {k: v for k, v in value.items() if k != "response"}
        try:
            return json.dumps(target, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(target)
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def is_account_ban_payload(value: object, *, status_code: int | None = None) -> str | None:
    """Return short sanitized ban reason if payload unambiguously indicates an account/ToS ban."""
    if status_code == 429:
        return None
    text = _extract_error_text(value).strip()
    if not text:
        return None
    lower = text.lower()
    for marker in _PERMANENT_BAN_MARKERS:
        if marker in lower:
            snippet = re.sub(r"\s+", " ", text)[:240]
            try:
                from app.secret_mask import mask_secrets
                snippet = mask_secrets(snippet)
            except Exception:
                pass
            return snippet
    return None


def _record_durable_ban_incident(provider: str, reason: str) -> None:
    """Persist one deduplicated critical incident without failing on empty test DBs."""
    sig = reason[:120].lower()
    with _incident_lock:
        if (provider, sig) in _tripped_incidents_mem:
            return
        _tripped_incidents_mem.add((provider, sig))

    msg = f"CRITICAL provider circuit-breaker tripped: {provider} auto-disabled ({reason})"
    logger.critical("%s", msg)

    try:
        from app import db

        raw = db.kv_get("provider_ban_incidents", "[]")
        records = json.loads(raw) if raw else []
        if not isinstance(records, list):
            records = []
        if not any(isinstance(r, dict) and r.get("provider") == provider and r.get("sig") == sig for r in records):
            records.append({
                "provider": provider,
                "sig": sig,
                "reason": reason,
                "ts": time.time(),
            })
            db.kv_set("provider_ban_incidents", json.dumps(records[-50:], ensure_ascii=False))

        # Attach durable attention_event if an active orchestrator session exists in SQLite.
        with db._conn() as conn:
            row = conn.execute(
                "SELECT id FROM sessions WHERE role='orchestrator' AND status!='archived' "
                "ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if row and row["id"]:
            from app.attention import create_attention

            create_attention(str(row["id"]), msg[:300], kind="incident")
    except Exception as exc:
        logger.debug("Durable ban incident persistence skipped: %s", exc)


def trip_provider_circuit_breaker(provider: str, reason: str) -> None:
    """Atomically disable a banned provider and emit a deduplicated critical incident."""
    key = normalize_provider_key(provider)
    if key not in SUBSCRIPTION_OAUTH_RUNTIMES:
        return
    set_provider_disabled(key, True)
    _record_durable_ban_incident(key, reason[:240])


def classify_and_trip_if_banned(
    provider: str,
    *,
    status_code: int | None = None,
    payload: object = None,
) -> str | None:
    """Detect unambiguous account/ToS bans, trip durable circuit-breaker, and return 'credentials'."""
    reason = is_account_ban_payload(payload, status_code=status_code)
    if not reason:
        return None
    trip_provider_circuit_breaker(provider, reason)
    return "credentials"

ANTIGRAVITY_COOLDOWN_KV_KEY = "antigravity_quota_cooldown"
ANTIGRAVITY_COOLDOWN_FALLBACK_SECONDS = 1800
ANTIGRAVITY_COOLDOWN_BUFFER_SECONDS = 90
_ANTIGRAVITY_QUOTA_ERR_RE = re.compile(
    r"individual\s+quota\s+reached|quota\s+(?:limit\s+)?reached|quota\s+exhausted|resource_exhausted|\b429\b",
    re.IGNORECASE,
)
_ANTIGRAVITY_RESETS_IN_RE = re.compile(r"resets?\s+in\s+([^\n.;,]+)", re.IGNORECASE)
_ANTIGRAVITY_DURATION_PART_RE = re.compile(r"(\d+)\s*([dhms])", re.IGNORECASE)


def _format_krs_hhmm(ts: float) -> str:
    from datetime import datetime, timedelta, timezone

    krs = timezone(timedelta(hours=7))
    return datetime.fromtimestamp(float(ts), tz=krs).strftime("%H:%M")


def parse_antigravity_quota_cooldown(
    text: object, *, now: float | None = None
) -> tuple[bool, float | None, int | None]:
    """Detect Antigravity 5h/quota-reached errors and parse reset delay + 90s buffer."""
    raw = str(text or "").strip()
    if not raw or not _ANTIGRAVITY_QUOTA_ERR_RE.search(raw):
        return False, None, None
    now_ts = time.time() if now is None else float(now)
    reset_seconds = 0
    match = _ANTIGRAVITY_RESETS_IN_RE.search(raw)
    if match:
        tail = match.group(1)
        for amount_s, unit in _ANTIGRAVITY_DURATION_PART_RE.findall(tail):
            amount = int(amount_s)
            u = unit.lower()
            if u == "d":
                reset_seconds += amount * 86400
            elif u == "h":
                reset_seconds += amount * 3600
            elif u == "m":
                reset_seconds += amount * 60
            elif u == "s":
                reset_seconds += amount
    if reset_seconds <= 0:
        reset_seconds = ANTIGRAVITY_COOLDOWN_FALLBACK_SECONDS
    until_ts = now_ts + reset_seconds + ANTIGRAVITY_COOLDOWN_BUFFER_SECONDS
    return True, until_ts, reset_seconds


def antigravity_cooldown_message(until_ts: float) -> str:
    return (
        f"⛔ Antigravity 5h лимит исчерпан — антибан-стоп до "
        f"{_format_krs_hhmm(until_ts)} КРС (переключите на gpt-6.2-sol)"
    )


def get_antigravity_cooldown(*, now: float | None = None) -> dict | None:
    """Return active Antigravity cooldown info or None when expired/absent."""
    try:
        from app import db
        raw = db.kv_get(ANTIGRAVITY_COOLDOWN_KV_KEY)
    except Exception:
        return None
    if not raw:
        return None
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    until_raw = payload.get("until")
    try:
        until_ts = float(until_raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(until_ts):
        return None
    now_ts = time.time() if now is None else float(now)
    if now_ts >= until_ts:
        return None
    remaining = max(1, int(math.ceil(until_ts - now_ts)))
    return {
        "active": True,
        "until": until_ts,
        "until_krs": _format_krs_hhmm(until_ts),
        "remaining_seconds": remaining,
        "reason": str(payload.get("reason") or ""),
        "tripped_at": payload.get("tripped_at"),
        "message": antigravity_cooldown_message(until_ts),
    }


def trip_antigravity_cooldown(
    raw_message: object,
    *,
    until_ts: float | None = None,
    now: float | None = None,
) -> dict:
    """Persist Antigravity 5h cooldown breaker to SQLite KV without touching Google again."""
    now_ts = time.time() if now is None else float(now)
    parsed_until = until_ts
    if parsed_until is None:
        _, parsed_until, _ = parse_antigravity_quota_cooldown(raw_message, now=now_ts)
    if parsed_until is None or parsed_until <= now_ts:
        parsed_until = (
            now_ts
            + ANTIGRAVITY_COOLDOWN_FALLBACK_SECONDS
            + ANTIGRAVITY_COOLDOWN_BUFFER_SECONDS
        )
    existing = get_antigravity_cooldown(now=now_ts)
    if existing and float(existing["until"]) > parsed_until:
        parsed_until = float(existing["until"])
    record = {
        "until": parsed_until,
        "tripped_at": now_ts,
        "reason": str(raw_message or "Individual quota reached")[:300],
    }
    try:
        from app import db
        db.kv_set(ANTIGRAVITY_COOLDOWN_KV_KEY, json.dumps(record, ensure_ascii=False))
    except Exception as exc:
        logger.debug("Antigravity cooldown kv_set skipped: %s", exc)
    return {
        "active": True,
        "until": parsed_until,
        "until_krs": _format_krs_hhmm(parsed_until),
        "remaining_seconds": max(1, int(math.ceil(parsed_until - now_ts))),
        "reason": record["reason"],
        "tripped_at": now_ts,
        "message": antigravity_cooldown_message(parsed_until),
    }


def clear_antigravity_cooldown() -> None:
    try:
        from app import db
        db.kv_set(ANTIGRAVITY_COOLDOWN_KV_KEY, "")
    except Exception as exc:
        logger.debug("Antigravity cooldown clear skipped: %s", exc)

