"""Hub pool capacity for the dashboard: remaining limits of the MultiCode hub accounts.

The hub relay lists every pooled account with its e-mail and id; the dashboard needs only the
active account's windows and the pool's usable capacity. `summarize_relay_limits` builds the answer from a
whitelist, so an identifier or e-mail the relay adds later cannot reach the browser.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
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


def usage_threshold() -> float:
    """Strict ceiling for every reported window; default permits spending up to the provider limit."""
    try:
        value = float(os.environ.get("MULTICODE_HUB_POOL_THRESHOLD_PCT", "100"))
        if 0 < value <= 100:
            return value
    except ValueError:
        pass
    logger.warning("Invalid MULTICODE_HUB_POOL_THRESHOLD_PCT; using 100")
    return 100.0


def _usable(account: dict, threshold: float) -> bool | None:
    """None means unknown capacity; absent provider windows are not invented requirements."""
    if account.get("rejected"):
        return False
    windows = account.get("windows")
    if not isinstance(windows, list) or not windows:
        return None
    values = [_number(window.get("used_pct")) if isinstance(window, dict) else None
              for window in windows]
    if any(value is None or value < 0 for value in values):
        return None
    return all(value < threshold for value in values)


def provider_for_model(model: str) -> str | None:
    from app.backend_hub import HUB_MODELS
    from app.models import resolve_model

    try:
        instance = HUB_MODELS.get(resolve_model(model), (None, None))[0]
    except (AttributeError, TypeError, ValueError):
        return None
    return {"claudeAgent": "claude", "codex": "codex"}.get(instance)


def alternative_model(model: str) -> str:
    return "hubsonnet" if provider_for_model(model) == "codex" else "hubsol"


async def hub_admission(model: str):
    """Share the dashboard cache and the session admission/error contract."""
    from dataclasses import replace
    from app.quota_gate import evaluate_worker_admission

    base = evaluate_worker_admission(model, {}, {})
    provider = provider_for_model(model)
    if provider is None:
        return base
    pool = await get_hub_pool()
    block = pool.get("providers", {}).get(provider)
    if not pool.get("available") or block is None:
        reason = f"Hub {provider} pool unavailable; capacity was not checked (turn allowed)"
        logger.warning(reason)
        return replace(base, state="unknown", reason=reason, reason_key="hub_pool_unavailable")
    usable = block["usable"]
    threshold = block["threshold_pct"]
    reason = (f"Hub {provider} pool has {usable}/{block['accounts']} usable accounts "
              f"(every reported window must be below {threshold:g}%)")
    if block.get("unknown", 0):
        reason += f"; {block['unknown']} accounts have unknown window data and do not count as usable"
    if not usable:
        reason += f"; use model='{alternative_model(model)}'"
    return replace(base, state="available" if usable else "blocked",
                   provider=f"hub_{provider}", provider_label=f"Hub {provider}", gated=True,
                   utilization=threshold if not usable else None, limit_pct=threshold,
                   reason=reason, reason_key="hub_pool_capacity",
                   valid_until=time.time() + max(1, CACHE_TTL - pool.get("cached_age_s", 0)))


async def require_hub_capacity(model: str) -> str | None:
    """Refuse exhausted hub pools, return a visible warning when the relay is unavailable."""
    if provider_for_model(model) is None:
        return None
    from app.quota_gate import require_worker_admission

    decision = await hub_admission(model)
    require_worker_admission(decision)
    return decision.reason if decision.state == "unknown" else None


def _summarize_provider(block: dict) -> dict:
    threshold = usage_threshold()
    accounts = [a for a in (block.get("ids") or []) if isinstance(a, dict)]
    capacity = [_usable(account, threshold) for account in accounts]
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
        "usable": sum(state is True for state in capacity),
        "unknown": sum(state is None for state in capacity),
        "threshold_pct": threshold,
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
