"""Hub pool capacity for the dashboard: remaining limits of the MultiCode hub accounts.

The hub relay lists every pooled account with its e-mail and id; the dashboard needs only the
active account's windows and the pool's size. `summarize_relay_limits` builds the answer from a
whitelist, so an identifier or e-mail the relay adds later cannot reach the browser.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

from app.hub_workspace import HubSsh, HubWorkspaceError

logger = logging.getLogger(__name__)

CACHE_TTL = 300.0          # a successful read is reused for 5 minutes
FAILURE_TTL = 60.0         # an unreachable hub is not retried on every dashboard poll
FETCH_TIMEOUT = 25.0
PROVIDERS = ("claude", "codex", "grok")
_RELAY_LIMITS_CMD = "curl -s --max-time 10 http://127.0.0.1:8080/relay/limits"

_cache: dict = {"payload": None, "ts": 0.0, "ttl": 0.0}
_lock: asyncio.Lock | None = None


def _unavailable(reason: str) -> dict:
    return {"available": False, "reason": reason, "providers": {}}


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value == value and abs(value) != float("inf") else None


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _summarize_provider(block: dict) -> dict:
    accounts = [a for a in (block.get("ids") or []) if isinstance(a, dict)]
    active_id = block.get("active_id")
    active = next((a for a in accounts if a.get("id") == active_id), None) or (accounts[0] if accounts else {})
    windows = []
    for window in active.get("windows") or []:
        if not isinstance(window, dict):
            continue
        used = _number(window.get("used_pct"))
        windows.append({
            "kind": _text(window.get("kind")),
            "label": _text(window.get("label")),
            "used_pct": used,
            "resets_at": _text(window.get("resets_at")),
            "window_minutes": _number(window.get("window_minutes")),
        })
    credits = active.get("reset_credits")
    reset_credits = None
    if isinstance(credits, dict):
        reset_credits = {
            "available": _number(credits.get("available")),
            "next_expires_at": _text(credits.get("next_expires_at")),
        }
    return {
        "accounts": len(accounts),
        "creds_loaded": sum(1 for a in accounts if a.get("creds_loaded") is True),
        "rejected": sum(1 for a in accounts if a.get("rejected")),
        "active_rejected": bool(active.get("rejected")),
        "cooldown_until": _text(active.get("cooldown_until")),
        "checked_at": _text(active.get("checked_at")),
        "windows": windows,
        "reset_credits": reset_credits,
    }


def summarize_relay_limits(raw: object) -> dict | None:
    """Redacted per-provider summary, or None when `raw` is not a relay-limits document."""
    providers = raw.get("providers") if isinstance(raw, dict) else None
    if not isinstance(providers, dict):
        return None
    return {
        "available": True,
        "reason": None,
        "providers": {p: _summarize_provider(providers[p]) for p in PROVIDERS
                      if isinstance(providers.get(p), dict)},
    }


async def _fetch_relay_limits() -> dict:
    hub = HubSsh.from_env()
    if hub is None:
        return _unavailable("not_configured")
    try:
        out = await asyncio.wait_for(hub.run(_RELAY_LIMITS_CMD, timeout=FETCH_TIMEOUT - 3), FETCH_TIMEOUT)
    except (HubWorkspaceError, asyncio.TimeoutError, OSError) as exc:
        logger.warning("hub pool fetch failed: %s", type(exc).__name__)
        return _unavailable("unreachable")
    try:
        summary = summarize_relay_limits(json.loads(out.decode("utf-8", "replace")))
    except ValueError:
        summary = None
    return summary or _unavailable("bad_response")


async def get_hub_pool(*, force: bool = False) -> dict:
    """Cached, redacted hub pool state; never raises."""
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    async with _lock:
        now = time.monotonic()
        if not force and _cache["payload"] is not None and now - _cache["ts"] < _cache["ttl"]:
            payload = _cache["payload"]
        else:
            payload = await _fetch_relay_limits()
            _cache.update(payload=payload, ts=time.monotonic(),
                          ttl=CACHE_TTL if payload["available"] else FAILURE_TTL)
        return {**payload, "cached_age_s": round(time.monotonic() - _cache["ts"])}
