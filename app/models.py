"""Available models — single source of truth.

Hardcoded dicts are the fallback for dev mode. In enterprise (is_auth_enabled),
fetch_models_from_proxy() replaces them with proxy-only models.
"""

import logging
import os
import re
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_proxy_connected: bool = False


@dataclass(frozen=True)
class ModelSpec:
    id: str
    name: str
    runtime: str
    provider: str
    context_length: int = 200000
    price_input: float | None = None
    price_output: float | None = None

MODELS = {
    "claude-fable-5[1m]": "Fable 5 (1M)",
    "claude-opus-4-8[1m]": "Opus 4.8 (1M)",
    "claude-opus-4-6[1m]": "Opus 4.6 (1M)",
    "claude-sonnet-5[1m]": "Sonnet 5 (1M)",
    "claude-haiku-4-5": "Haiku 4.5",
    "gpt-5.3-codex-spark": "GPT-5.3 Codex Spark",
    "gpt-5.6-sol": "GPT-5.6 Sol",
    "gpt-5.6-terra": "GPT-5.6 Terra",
    "gpt-5.6-luna": "GPT-5.6 Luna",
    "gpt-5.5": "GPT-5.5",
    "gpt-5.4": "GPT-5.4",
    "gpt-5.4-mini": "GPT-5.4 Mini",
}

CONTEXT_LIMITS = {
    "claude-fable-5[1m]": 1000000,
    "claude-opus-4-8[1m]": 1000000,
    "claude-opus-4-6[1m]": 1000000,
    "claude-sonnet-5[1m]": 1000000,
    "claude-haiku-4-5": 200000,
    # Effective ChatGPT-auth Codex runtime budget. Public API window is larger, but
    # Orchestra's GPT workers run through Codex CLI and must use its runtime contract.
    "gpt-5.3-codex-spark": 128000,
    "gpt-5.6-sol": 258400,
    "gpt-5.6-terra": 258400,
    "gpt-5.6-luna": 258400,
    "gpt-5.5": 258400,
    "gpt-5.4": 258400,
    "gpt-5.4-mini": 258400,
}

# Short aliases let agents use "opus", "sonnet" etc. in spawn_worker without
# knowing the exact versioned model ID — reduces prompt brittleness on model upgrades
ALIASES = {
    "fable": "claude-fable-5[1m]",
    "fable5": "claude-fable-5[1m]",
    "claude-fable-5": "claude-fable-5[1m]",
    "claude-fable-5-1m": "claude-fable-5[1m]",
    "mythos": "claude-fable-5[1m]",
    "opus": "claude-opus-4-8[1m]",
    "opus4.8": "claude-opus-4-8[1m]",
    "claude-opus-4-8": "claude-opus-4-8[1m]",
    "claude-opus-4-8-1m": "claude-opus-4-8[1m]",
    "opus4.6": "claude-opus-4-6[1m]",
    "claude-opus-4-6": "claude-opus-4-6[1m]",
    "claude-opus-4-6-1m": "claude-opus-4-6[1m]",
    "sonnet": "claude-sonnet-5[1m]",
    "sonnet5": "claude-sonnet-5[1m]",
    "claude-sonnet-5-1m": "claude-sonnet-5[1m]",
    "claude-sonnet-4-6": "claude-sonnet-5[1m]",
    "claude-sonnet-4-5": "claude-sonnet-5[1m]",
    "haiku": "claude-haiku-4-5",
    "spark": "gpt-5.3-codex-spark",
    "codexspark": "gpt-5.3-codex-spark",
    "gpt5.3spark": "gpt-5.3-codex-spark",
    "gpt5.6": "gpt-5.6-sol",
    "gpt5.6sol": "gpt-5.6-sol",
    "gpt5.6terra": "gpt-5.6-terra",
    "gpt5.6luna": "gpt-5.6-luna",
    "codex": "gpt-5.6-sol",
    "gpt5.5": "gpt-5.5",
    "gpt5.4": "gpt-5.4",
    "gpt5.4mini": "gpt-5.4-mini",
    "gpt-5.4mini": "gpt-5.4-mini",
}

BACKENDS = {
    "claude-fable-5[1m]": "claude",
    "claude-opus-4-8[1m]": "claude",
    "claude-opus-4-6[1m]": "claude",
    "claude-sonnet-5[1m]": "claude",
    "claude-haiku-4-5": "claude",
    "gpt-5.3-codex-spark": "codex",
    "gpt-5.6-sol": "codex",
    "gpt-5.6-terra": "codex",
    "gpt-5.6-luna": "codex",
    "gpt-5.5": "codex",
    "gpt-5.4": "codex",
    "gpt-5.4-mini": "codex",
}


def cache_policy_for_runtime(runtime: str) -> dict[str, int | bool]:
    """Return cache-window metadata exposed to dashboard and MCP consumers."""
    if runtime == "codex":
        return {
            "cache_ttl_seconds": 1800,
            "cache_ttl_approximate": True,
        }
    return {
        "cache_ttl_seconds": 3600,
        "cache_ttl_approximate": False,
    }


# TOKEN_PRICES is for internal cost tracking only (subscription plan, not real API billing)
# Codex models intentionally absent — their prices live in backend_codex.py
TOKEN_PRICES = {
    "claude-fable-5[1m]": {"input": 10.0, "output": 50.0},
    "claude-opus-4-8[1m]": {"input": 5.0,  "output": 25.0},
    "claude-opus-4-6[1m]": {"input": 5.0,  "output": 25.0},
    "claude-sonnet-5[1m]": {"input": 2.0,  "output": 10.0},
    "claude-haiku-4-5":    {"input": 0.80, "output": 4.0},
}

DEFAULT_MODEL = "claude-sonnet-5[1m]"
MODEL_SPECS: dict[str, ModelSpec] = {}

_VERSION_RE = re.compile(r"[-.]v?\d[\d.]*$")


def _generate_aliases(model_id: str) -> list[str]:
    """Auto-generate short alias candidates for a model ID."""
    aliases = []
    if "/" in model_id:
        tail = model_id.rsplit("/", 1)[1]
        aliases.append(tail)
        stripped = _VERSION_RE.sub("", tail)
        if stripped and stripped != tail:
            aliases.append(stripped)
    return aliases


def _infer_backend(model_id: str) -> str:
    # gpt-* → Codex CLI, claude-* → Claude SDK, everything else (gemini, llama,
    # mistral, …) → the OpenCode daemon. The proxy serves these via provider/model
    # IDs (e.g. "gemini/gemini-2.5-flash") which start with the provider name,
    # never "gpt-"/"claude-".
    if model_id.startswith("gpt-"):
        return "codex"
    if model_id.startswith("claude-"):
        return "claude"
    return "opencode"


def _infer_provider(model_id: str) -> str:
    if "/" in model_id:
        return model_id.split("/", 1)[0]
    if model_id.startswith("gpt-"):
        return "openai"
    if model_id.startswith("claude-"):
        return "anthropic"
    return "unknown"


def register_model(spec: ModelSpec, *, replace: bool = False) -> None:
    """Register one explicit provider/model/runtime route and legacy lookup views."""
    if not spec.id:
        raise ValueError("model id must not be empty")
    if spec.id in MODEL_SPECS and not replace:
        raise ValueError(f"model '{spec.id}' is already registered")
    MODEL_SPECS[spec.id] = spec
    MODELS[spec.id] = spec.name
    CONTEXT_LIMITS[spec.id] = spec.context_length
    BACKENDS[spec.id] = spec.runtime
    if spec.price_input is not None or spec.price_output is not None:
        TOKEN_PRICES[spec.id] = {
            "input": float(spec.price_input or 0),
            "output": float(spec.price_output or 0),
        }


def unregister_model(model_id: str) -> None:
    MODEL_SPECS.pop(model_id, None)
    MODELS.pop(model_id, None)
    CONTEXT_LIMITS.pop(model_id, None)
    BACKENDS.pop(model_id, None)
    TOKEN_PRICES.pop(model_id, None)


def get_model_spec(model_id: str) -> ModelSpec:
    """Return an explicit route; synthesize a compatibility spec at the boundary."""
    if model_id in MODEL_SPECS:
        return MODEL_SPECS[model_id]
    prices = TOKEN_PRICES.get(model_id, {})
    return ModelSpec(
        id=model_id,
        name=MODELS.get(model_id, model_id),
        runtime=BACKENDS.get(model_id, _infer_backend(model_id)),
        provider=_infer_provider(model_id),
        context_length=CONTEXT_LIMITS.get(model_id, 200000),
        price_input=prices.get("input"),
        price_output=prices.get("output"),
    )


def _seed_model_specs() -> None:
    for model_id, name in list(MODELS.items()):
        prices = TOKEN_PRICES.get(model_id, {})
        MODEL_SPECS[model_id] = ModelSpec(
            id=model_id,
            name=name,
            runtime=BACKENDS[model_id],
            provider=_infer_provider(model_id),
            context_length=CONTEXT_LIMITS[model_id],
            price_input=prices.get("input"),
            price_output=prices.get("output"),
        )


_seed_model_specs()


def is_proxy_connected() -> bool:
    return _proxy_connected


async def fetch_models_from_proxy(enterprise_mode: bool = False) -> bool:
    """Fetch model list from upstream proxy and populate module-level dicts.

    enterprise_mode=True: CLEAR hardcoded models first, keep only proxy results.
    enterprise_mode=False: MERGE with existing hardcoded models (dev fallback).
    """
    global _proxy_connected
    base_url = os.environ.get("ANTHROPIC_BASE_URL", os.environ.get("UPSTREAM_API", "https://api.anthropic.com"))
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    url = f"{base_url.rstrip('/')}/v1/models"

    proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    try:
        async with httpx.AsyncClient(timeout=10, proxy=proxy_url) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning(f"fetch_models_from_proxy failed: {e}")
        _proxy_connected = False
        if enterprise_mode:
            MODELS.clear()
            CONTEXT_LIMITS.clear()
            TOKEN_PRICES.clear()
            BACKENDS.clear()
            MODEL_SPECS.clear()
            ALIASES.clear()
        return False

    models_list = data.get("data", [])
    if not models_list:
        logger.warning("fetch_models_from_proxy: empty model list")
        _proxy_connected = False
        if enterprise_mode:
            MODELS.clear()
            CONTEXT_LIMITS.clear()
            TOKEN_PRICES.clear()
            BACKENDS.clear()
            MODEL_SPECS.clear()
            ALIASES.clear()
        return False

    if enterprise_mode:
        MODELS.clear()
        CONTEXT_LIMITS.clear()
        TOKEN_PRICES.clear()
        BACKENDS.clear()
        MODEL_SPECS.clear()
        ALIASES.clear()

    added = 0
    for m in models_list:
        mid = m.get("id", "")
        if not mid:
            continue

        if "/" in mid:
            label = mid.rsplit("/", 1)[1].replace("-", " ").title()
        else:
            label = mid.replace("-", " ").title()

        ctx = m.get("context_length") or 200000

        pricing = m.get("pricing", {})
        prompt_price = float(pricing.get("prompt", "0")) * 1_000_000
        completion_price = float(pricing.get("completion", "0")) * 1_000_000

        backend = str(m.get("runtime") or m.get("backend") or _infer_backend(mid))
        provider = str(m.get("provider") or _infer_provider(mid))

        if mid not in MODELS:
            MODELS[mid] = label
            added += 1
        if mid not in CONTEXT_LIMITS:
            CONTEXT_LIMITS[mid] = ctx
        if mid not in TOKEN_PRICES and (prompt_price or completion_price):
            TOKEN_PRICES[mid] = {"input": round(prompt_price, 4), "output": round(completion_price, 4)}
        if mid not in BACKENDS:
            BACKENDS[mid] = backend
        if mid not in MODEL_SPECS:
            MODEL_SPECS[mid] = ModelSpec(
                id=mid,
                name=MODELS[mid],
                runtime=BACKENDS[mid],
                provider=provider,
                context_length=CONTEXT_LIMITS[mid],
                price_input=TOKEN_PRICES.get(mid, {}).get("input"),
                price_output=TOKEN_PRICES.get(mid, {}).get("output"),
            )

        for alias in _generate_aliases(mid):
            if alias not in ALIASES and alias != mid:
                ALIASES[alias] = mid

    _generate_semantic_aliases()
    _proxy_connected = True
    mode_label = "enterprise (proxy-only)" if enterprise_mode else "dev (merged)"
    logger.info(f"Loaded {len(models_list)} models from proxy ({added} new, {mode_label})")
    return True


# Semantic alias patterns: short name → match first model containing substring
_SEMANTIC_PATTERNS = [
    ("opus", "opus"),
    ("opus4.8", "opus-4-8"),
    ("sonnet", "sonnet"),
    ("haiku", "haiku"),
    ("fable", "fable"),
    ("gemini", "gemini"),
    ("gemini-flash", "gemini-2.5-flash"),
    ("llama", "llama"),
    ("mistral", "mistral"),
    ("gpt-mini", "gpt-4o-mini"),
]


def _generate_semantic_aliases():
    """Generate standard short aliases (opus, sonnet, etc.) from loaded models."""
    for alias, pattern in _SEMANTIC_PATTERNS:
        if alias in ALIASES:
            continue
        for mid in MODELS:
            if pattern in mid:
                ALIASES[alias] = mid
                break


async def refresh_models() -> None:
    """Startup helper — fetch models, enterprise-aware."""
    from app.auth import is_auth_enabled
    enterprise = is_auth_enabled()
    has_proxy = bool(os.environ.get("HTTPS_PROXY") or os.environ.get("ANTHROPIC_BASE_URL"))
    if not has_proxy:
        logger.info(f"No proxy configured, using {len(MODELS)} hardcoded models")
        return
    ok = await fetch_models_from_proxy(enterprise_mode=enterprise)
    if ok:
        logger.info(f"Models ready: {len(MODELS)} total (proxy_connected=True)")
    else:
        if enterprise:
            logger.warning(f"Proxy unreachable in enterprise mode — 0 models available")
        else:
            logger.warning(f"Proxy unreachable, using {len(MODELS)} hardcoded models")


def resolve_model(model: str) -> str:
    m = model.lower().strip()
    if m in ALIASES:
        return ALIASES[m]
    if m in MODELS:
        return m
    if MODELS:
        first = next(iter(MODELS))
        logger.warning(f"resolve_model: '{model}' not found in {len(MODELS)} models, fallback → '{first}'")
        return first
    return model


def backend_for_model(model: str) -> str:
    return get_model_spec(model).runtime


def available_models_block() -> str:
    """Prompt block listing all available models for spawn_worker."""
    lines = ["## Available models for spawn_worker(model=...)"]
    for model_id, label in MODELS.items():
        spec = get_model_spec(model_id)
        ctx = spec.context_length
        ctx_k = f"{ctx // 1000}k"
        alias_list = [a for a, m in ALIASES.items() if m == model_id]
        alias_str = f" (aliases: {', '.join(alias_list[:3])})" if alias_list else ""
        lines.append(
            f"- `{model_id}` — {label}, {ctx_k} context, "
            f"runtime: {spec.runtime}, provider: {spec.provider}{alias_str}"
        )
    return "\n".join(lines)
