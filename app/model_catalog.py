"""OpenRouter model catalog (#366).

Fetches https://openrouter.ai/api/v1/models, normalizes it to the fields the
dashboard filters need, caches the result in SQLite kv (`model_catalog_cache`)
and registers every eligible cached model into the shared registry via
`app.models.register_model`. Only deterministic `:free` text routes with tool
support are eligible for Harness; zero token prices alone are not a free-route
contract because providers may charge per request, image, song, or other unit.

Registration-order guarantee: `apply_model_catalog()` is re-applied at the tail
of every registry rebuild (`fetch_models_from_proxy`, `refresh_models`), so an
enterprise-mode clear can never silently drop the catalog.
"""

import json
import logging
import os
import sqlite3
import time

import httpx

logger = logging.getLogger(__name__)

CATALOG_KV_KEY = "model_catalog_cache"
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

# Dropped-model counter of the last apply_model_catalog() run. Exposed through
# refresh_catalog() so a silently-eaten catalog is visible in the API response.
_LAST_APPLY_STATS = {
    "eligible": 0, "available": 0, "registered": 0, "retained_stale": 0, "dropped": 0,
}


def normalize_catalog_model(raw: dict) -> dict | None:
    """OpenRouter raw entry -> normalized dict; None for entries without an id."""
    model_id = str(raw.get("id") or "").strip()
    if not model_id:
        return None

    pricing = raw.get("pricing") or {}

    def _per_mtok(value) -> float:
        try:
            return round(abs(float(value)) * 1_000_000, 6)
        except (TypeError, ValueError):
            return 0.0

    arch = raw.get("architecture") or {}
    params = sorted({str(p) for p in (raw.get("supported_parameters") or []) if p})
    input_modalities = [str(m) for m in (arch.get("input_modalities") or [])]
    output_modalities = [str(m) for m in (arch.get("output_modalities") or [])]
    is_free = model_id.endswith(":free")
    supports_tools = "tools" in params
    harness_eligible = (
        is_free
        and supports_tools
        and "text" in input_modalities
        and "text" in output_modalities
    )
    try:
        context_length = int(raw.get("context_length") or 200000)
    except (TypeError, ValueError):
        context_length = 200000
    return {
        "id": model_id,
        "name": str(raw.get("name") or model_id),
        "context_length": max(context_length, 1),
        "price_prompt": _per_mtok(pricing.get("prompt")),
        "price_completion": _per_mtok(pricing.get("completion")),
        "input_modalities": input_modalities,
        "output_modalities": output_modalities,
        "supports_tools": supports_tools,
        "supported_parameters": params,
        "is_free": is_free,
        "harness_eligible": harness_eligible,
        "available": True,
    }


def catalog_cache_payload() -> dict:
    from app.db import kv_get

    try:
        data = json.loads(kv_get(CATALOG_KV_KEY, "{}"))
    except json.JSONDecodeError:
        data = {}
    except sqlite3.OperationalError:
        return {"fetched_at": None, "models": []}
    if not isinstance(data, dict):
        data = {}
    models = data.get("models")
    return {
        "fetched_at": data.get("fetched_at"),
        "models": models if isinstance(models, list) else [],
    }


def cached_catalog() -> list[dict]:
    return catalog_cache_payload()["models"]


def _cached_harness_eligible(model: dict) -> bool:
    """Read both the current cache schema and the pre-hardening schema safely.

    Old rows did not persist output modalities or the eligibility bit. They came from
    OpenRouter's text catalog, so exact `:free` + advertised tools is the conservative
    migration; optional request parameters stay disabled until a fresh catalog arrives.
    """
    if "harness_eligible" in model:
        return model.get("harness_eligible") is True
    return (
        str(model.get("id") or "").endswith(":free")
        and model.get("supports_tools") is True
        and "text" in (model.get("input_modalities") or [])
    )


def apply_model_catalog() -> int:
    """Register every cached catalog model into the shared registry.

    Idempotent: already-registered ids are refreshed in place, including live
    capabilities/context for manifest fallbacks. Returns registrations this run;
    per-model failures are counted in `_LAST_APPLY_STATS['dropped']`.
    """
    from app.models import MODEL_SPECS, ModelSpec, SELECTABLE_MODEL_SPECS, register_model

    manifest = {spec.id: spec for spec in SELECTABLE_MODEL_SPECS}
    eligible = {
        norm["id"]: norm for norm in cached_catalog()
        if _cached_harness_eligible(norm)
    }
    registered = dropped = 0
    for norm in eligible.values():
        declared = manifest.get(norm["id"])
        spec = ModelSpec(
            id=norm["id"],
            name=norm["name"],
            runtime="harness",
            provider="openrouter",
            context_length=int(norm["context_length"]),
            price_input=float(norm["price_prompt"]),
            price_output=float(norm["price_completion"]),
            supported_parameters=tuple(
                norm.get("supported_parameters")
                or (declared.supported_parameters if declared else ("tools",))
            ),
            default_dashboard=(declared.default_dashboard if declared else False),
            default_agents=(declared.default_agents if declared else False),
            available=bool(norm.get("available", True)),
        )
        try:
            register_model(spec, replace=norm["id"] in MODEL_SPECS)
            registered += 1
        except (ValueError, TypeError) as exc:
            dropped += 1
            logger.warning("catalog model %s dropped: %s", norm["id"], exc)

    _LAST_APPLY_STATS.update(
        eligible=len(eligible),
        available=sum(1 for norm in eligible.values() if norm.get("available", True)),
        registered=registered,
        retained_stale=sum(1 for norm in eligible.values() if not norm.get("available", True)),
        dropped=dropped,
    )
    return registered


async def refresh_catalog() -> dict:
    """Fetch the OpenRouter catalog, cache it, register it. Raises on fetch error."""
    api_key = (
        os.environ.get("OPENROUTER_API_KEY")
        or os.environ.get("OPENROUTER_KEY", "")
    )
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    try:
        async with httpx.AsyncClient(timeout=30, proxy=proxy_url) as client:
            resp = await client.get(OPENROUTER_MODELS_URL, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("OpenRouter catalog fetch failed: %s", exc)
        raise ValueError(f"catalog fetch failed: {exc}") from exc

    normalized: list[dict] = []
    seen: set[str] = set()
    for raw in data.get("data") or []:
        entry = normalize_catalog_model(raw if isinstance(raw, dict) else {})
        if entry is not None and entry["id"] not in seen:
            seen.add(entry["id"])
            normalized.append(entry)

    # Keep structurally valid routes that vanished as unavailable compatibility records.
    # A persisted session can then open and switch away, while admission rejects new work.
    active_ids = {entry["id"] for entry in normalized}
    retained_stale: list[dict] = []
    for old in cached_catalog():
        if old.get("id") in active_ids or not _cached_harness_eligible(old):
            continue
        stale = dict(old)
        stale["available"] = False
        retained_stale.append(stale)

    from app.db import kv_set

    kv_set(CATALOG_KV_KEY, json.dumps({
        "fetched_at": time.time(), "models": normalized + retained_stale,
    }))
    registered = apply_model_catalog()
    result = {
        "fetched": len(normalized),
        "eligible": _LAST_APPLY_STATS["eligible"],
        "available": _LAST_APPLY_STATS["available"],
        "registered": registered,
        "retained_stale": _LAST_APPLY_STATS["retained_stale"],
        "dropped": _LAST_APPLY_STATS["dropped"],
    }
    logger.info(
        "OpenRouter catalog refreshed: fetched=%(fetched)s eligible=%(eligible)s "
        "available=%(available)s registered=%(registered)s "
        "retained_stale=%(retained_stale)s dropped=%(dropped)s" % result
    )
    return result
