"""Available models — single source of truth.

Hardcoded dicts are the fallback. On startup, fetch_models_from_proxy()
merges dynamic models from the upstream proxy's /v1/models endpoint.
"""

import logging
import os
import re

import httpx

logger = logging.getLogger(__name__)

MODELS = {
    "claude-fable-5[1m]": "Fable 5 (1M)",
    "claude-opus-4-8[1m]": "Opus 4.8 (1M)",
    "claude-opus-4-6[1m]": "Opus 4.6 (1M)",
    "claude-sonnet-4-6": "Sonnet 4.6",
    "claude-haiku-4-5": "Haiku 4.5",
    "gpt-5.5": "GPT-5.5",
    "gpt-5.4": "GPT-5.4",
    "gpt-5.4-mini": "GPT-5.4 Mini",
    "deepseek/deepseek-v4-pro": "DeepSeek V4 Pro (1M)",
    "deepseek/deepseek-v4-flash": "DeepSeek V4 Flash (1M)",
}

CONTEXT_LIMITS = {
    "claude-fable-5[1m]": 1000000,
    "claude-opus-4-8[1m]": 1000000,
    "claude-opus-4-6[1m]": 1000000,
    "claude-sonnet-4-6": 200000,
    "claude-haiku-4-5": 200000,
    "gpt-5.5": 258400,
    "gpt-5.4": 258400,
    "gpt-5.4-mini": 258400,
    "deepseek/deepseek-v4-pro": 1000000,
    "deepseek/deepseek-v4-flash": 1000000,
}

# Short aliases let agents use "opus", "sonnet" etc. in spawn_worker without
# knowing the exact versioned model ID — reduces prompt brittleness on model upgrades
ALIASES = {
    "fable": "claude-fable-5[1m]",
    "fable5": "claude-fable-5[1m]",
    "claude-fable-5": "claude-fable-5[1m]",
    "claude-fable-5-1m": "claude-fable-5[1m]",
    "mythos": "claude-fable-5[1m]",
    "opus": "claude-opus-4-6[1m]",
    "opus4.8": "claude-opus-4-8[1m]",
    "claude-opus-4-8": "claude-opus-4-8[1m]",
    "claude-opus-4-8-1m": "claude-opus-4-8[1m]",
    "opus4.6": "claude-opus-4-6[1m]",
    "claude-opus-4-6": "claude-opus-4-6[1m]",
    "claude-opus-4-6-1m": "claude-opus-4-6[1m]",
    "sonnet": "claude-sonnet-4-6",
    "claude-sonnet-4-5": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5",
    "gpt5.5": "gpt-5.5",
    "codex": "gpt-5.5",
    "gpt5.4": "gpt-5.4",
    "gpt5.4mini": "gpt-5.4-mini",
    "gpt-5.4mini": "gpt-5.4-mini",
    "deepseek": "deepseek/deepseek-v4-pro",
    "deepseek-pro": "deepseek/deepseek-v4-pro",
    "v4-pro": "deepseek/deepseek-v4-pro",
    "deepseek-v4-pro": "deepseek/deepseek-v4-pro",
    "deepseek-flash": "deepseek/deepseek-v4-flash",
    "v4-flash": "deepseek/deepseek-v4-flash",
    "deepseek-v4-flash": "deepseek/deepseek-v4-flash",
}

BACKENDS = {
    "claude-fable-5[1m]": "claude",
    "claude-opus-4-8[1m]": "claude",
    "claude-opus-4-6[1m]": "claude",
    "claude-sonnet-4-6": "claude",
    "claude-haiku-4-5": "claude",
    "gpt-5.5": "codex",
    "gpt-5.4": "codex",
    "gpt-5.4-mini": "codex",
    "deepseek/deepseek-v4-pro": "claude",
    "deepseek/deepseek-v4-flash": "claude",
}

# TOKEN_PRICES is for internal cost tracking only (subscription plan, not real API billing)
# Codex models intentionally absent — their prices live in backend_codex.py
TOKEN_PRICES = {
    "claude-fable-5[1m]": {"input": 10.0, "output": 50.0},
    "claude-opus-4-8[1m]": {"input": 15.0, "output": 75.0},
    "claude-opus-4-6[1m]": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-6":   {"input": 3.0,  "output": 15.0},
    "claude-haiku-4-5":    {"input": 0.80, "output": 4.0},
    "deepseek/deepseek-v4-pro":   {"input": 0.435, "output": 0.87},
    "deepseek/deepseek-v4-flash": {"input": 0.098, "output": 0.197},
}

DEFAULT_MODEL = "claude-sonnet-4-6"

# Version-like suffixes to strip when generating short aliases
_VERSION_RE = re.compile(r"[-.]v?\d[\d.]*$")


def _generate_aliases(model_id: str) -> list[str]:
    """Auto-generate short alias candidates for a model ID."""
    aliases = []
    # "deepseek/deepseek-v4-flash" → "deepseek-v4-flash"
    if "/" in model_id:
        tail = model_id.rsplit("/", 1)[1]
        aliases.append(tail)
        # strip version suffix: "deepseek-v4-flash" → "deepseek-flash" (only if different)
        stripped = _VERSION_RE.sub("", tail)
        if stripped and stripped != tail:
            aliases.append(stripped)
    return aliases


def _infer_backend(model_id: str) -> str:
    if model_id.startswith("gpt-"):
        return "codex"
    return "claude"


async def fetch_models_from_proxy() -> bool:
    """Fetch model list from upstream proxy and merge into module-level dicts.

    Returns True on success, False on failure (hardcoded fallback stays).
    """
    base_url = os.environ.get("UPSTREAM_API", "https://api.anthropic.com")
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    url = f"{base_url.rstrip('/')}/v1/models"

    proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")

    try:
        async with httpx.AsyncClient(timeout=10, proxy=proxy_url) as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning(f"fetch_models_from_proxy failed: {e}")
        return False

    models_list = data.get("data", [])
    if not models_list:
        logger.warning("fetch_models_from_proxy: empty model list")
        return False

    added = 0
    for m in models_list:
        mid = m.get("id", "")
        if not mid:
            continue

        # Display name: capitalize last segment
        if "/" in mid:
            label = mid.rsplit("/", 1)[1].replace("-", " ").title()
        else:
            label = mid.replace("-", " ").title()

        ctx = m.get("context_length") or 200000

        pricing = m.get("pricing", {})
        prompt_price = float(pricing.get("prompt", "0")) * 1_000_000
        completion_price = float(pricing.get("completion", "0")) * 1_000_000

        backend = _infer_backend(mid)

        # Merge — don't overwrite existing hardcoded entries
        if mid not in MODELS:
            MODELS[mid] = label
            added += 1
        if mid not in CONTEXT_LIMITS:
            CONTEXT_LIMITS[mid] = ctx
        if mid not in TOKEN_PRICES and (prompt_price or completion_price):
            TOKEN_PRICES[mid] = {"input": round(prompt_price, 4), "output": round(completion_price, 4)}
        if mid not in BACKENDS:
            BACKENDS[mid] = backend

        # Auto-generate aliases for new models
        for alias in _generate_aliases(mid):
            if alias not in ALIASES and alias != mid:
                ALIASES[alias] = mid

    logger.info(f"Loaded {len(models_list)} models from proxy ({added} new)")
    return True


async def refresh_models() -> None:
    """Startup helper — fetch models, log result."""
    ok = await fetch_models_from_proxy()
    if ok:
        logger.info(f"Models ready: {len(MODELS)} total")
    else:
        logger.warning(f"Proxy unreachable, using {len(MODELS)} hardcoded models")


def resolve_model(model: str) -> str:
    m = model.lower().strip()
    if m in ALIASES:
        return ALIASES[m]
    if m in MODELS:
        return m
    return model


def backend_for_model(model: str) -> str:
    return BACKENDS.get(model, "claude")


def available_models_block() -> str:
    """Prompt block listing all available models for spawn_worker."""
    lines = ["## Available models for spawn_worker(model=...)"]
    for model_id, label in MODELS.items():
        ctx = CONTEXT_LIMITS.get(model_id, 200000)
        ctx_k = f"{ctx // 1000}k"
        backend = BACKENDS.get(model_id, "claude")
        alias_list = [a for a, m in ALIASES.items() if m == model_id]
        alias_str = f" (aliases: {', '.join(alias_list[:3])})" if alias_list else ""
        lines.append(f"- `{model_id}` — {label}, {ctx_k} context, backend: {backend}{alias_str}")
    return "\n".join(lines)
