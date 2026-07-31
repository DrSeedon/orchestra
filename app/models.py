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


@dataclass(frozen=True)
class ProviderMetadata:
    """Accounting/cache/UI metadata keyed by runtime bucket."""

    id: str
    title: str
    ui_provider: str
    cache_ttl_seconds: int
    cache_ttl_approximate: bool
    legacy_model_prefixes: tuple[str, ...] = ()
    model_providers: tuple[str, ...] = ()


MODELS = {
    "claude-fable-5[1m]": "Fable 5 (1M)",
    "claude-opus-5[1m]": "Opus 5 (1M)",
    "claude-sonnet-5[1m]": "Sonnet 5 (1M)",
    "claude-haiku-4-5": "Haiku 4.5",
    "gpt-5.3-codex-spark": "GPT-5.3 Codex Spark",
    "gpt-5.6-sol": "GPT-5.6 Sol",
    "gpt-5.6-terra": "GPT-5.6 Terra",
    "gpt-5.6-luna": "GPT-5.6 Luna",
    "gpt-5.5": "GPT-5.5",
    "gpt-5.4": "GPT-5.4",
    "gpt-5.4-mini": "GPT-5.4 Mini",
    "grok-4.5": "Grok 4.5",
}

CONTEXT_LIMITS = {
    "claude-fable-5[1m]": 1000000,
    "claude-opus-5[1m]": 1000000,
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
    # Reported by the Grok runtime itself (initialize + session/new agree). The bundled
    # vendor README disagrees with the runtime on other numbers, so the runtime wins.
    "grok-4.5": 500000,
}

# Short aliases let agents use "opus", "sonnet" etc. in spawn_worker without
# knowing the exact versioned model ID — reduces prompt brittleness on model upgrades
ALIASES = {
    "fable": "claude-fable-5[1m]",
    "fable5": "claude-fable-5[1m]",
    "claude-fable-5": "claude-fable-5[1m]",
    "claude-fable-5-1m": "claude-fable-5[1m]",
    "mythos": "claude-fable-5[1m]",
    "opus": "claude-opus-5[1m]",
    "opus5": "claude-opus-5[1m]",
    "claude-opus-5": "claude-opus-5[1m]",
    "claude-opus-4-8[1m]": "claude-opus-5[1m]",
    "claude-opus-4-8": "claude-opus-5[1m]",
    "claude-opus-4-6[1m]": "claude-opus-5[1m]",
    "claude-opus-4-6": "claude-opus-5[1m]",
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
    "grok": "grok-4.5",
    "grok4.5": "grok-4.5",
    "grok-build": "grok-4.5",
}

BACKENDS = {
    "claude-fable-5[1m]": "claude",
    "claude-opus-5[1m]": "claude",
    "claude-sonnet-5[1m]": "claude",
    "claude-haiku-4-5": "claude",
    "gpt-5.3-codex-spark": "codex",
    "gpt-5.6-sol": "codex",
    "gpt-5.6-terra": "codex",
    "gpt-5.6-luna": "codex",
    "gpt-5.5": "codex",
    "gpt-5.4": "codex",
    "gpt-5.4-mini": "codex",
    "grok-4.5": "grok",
}

MODEL_PROVIDERS = {
    "claude-fable-5[1m]": "anthropic",
    "claude-opus-5[1m]": "anthropic",
    "claude-sonnet-5[1m]": "anthropic",
    "claude-haiku-4-5": "anthropic",
    "gpt-5.3-codex-spark": "openai",
    "gpt-5.6-sol": "openai",
    "gpt-5.6-terra": "openai",
    "gpt-5.6-luna": "openai",
    "gpt-5.5": "openai",
    "gpt-5.4": "openai",
    "gpt-5.4-mini": "openai",
    "grok-4.5": "x-ai",
}

# Runtime ids double as the accounting buckets emitted by usage analytics. The
# explicit `unknown` bucket is intentionally conservative: absence of evidence
# about a cache window must never acquire Claude's exact one-hour policy.
PROVIDER_METADATA: dict[str, ProviderMetadata] = {
    "claude": ProviderMetadata(
        id="claude",
        title="Claude Max",
        ui_provider="anthropic",
        cache_ttl_seconds=3600,
        cache_ttl_approximate=False,
        legacy_model_prefixes=("claude-",),
        model_providers=("anthropic",),
    ),
    "codex": ProviderMetadata(
        id="codex",
        title="Codex Pro",
        ui_provider="openai",
        cache_ttl_seconds=1800,
        cache_ttl_approximate=True,
        legacy_model_prefixes=("gpt-",),
        model_providers=("openai",),
    ),
    "grok": ProviderMetadata(
        id="grok",
        title="Grok",
        ui_provider="x-ai",
        cache_ttl_seconds=3600,
        cache_ttl_approximate=True,
        legacy_model_prefixes=("grok-",),
        model_providers=("x-ai",),
    ),
    "opencode": ProviderMetadata(
        id="opencode",
        title="OpenCode",
        ui_provider="openrouter",
        cache_ttl_seconds=0,
        cache_ttl_approximate=True,
        model_providers=("openrouter", "deepseek", "x-ai", "opencode"),
    ),
    "unknown": ProviderMetadata(
        id="unknown",
        title="Unknown",
        ui_provider="unknown",
        cache_ttl_seconds=0,
        cache_ttl_approximate=True,
        model_providers=("unknown",),
    ),
}


def cache_policy_for_runtime(runtime: str) -> dict[str, int | bool]:
    """Return cache-window metadata exposed to dashboard and MCP consumers."""
    metadata = PROVIDER_METADATA.get(runtime, PROVIDER_METADATA["unknown"])
    return {
        "cache_ttl_seconds": metadata.cache_ttl_seconds,
        "cache_ttl_approximate": metadata.cache_ttl_approximate,
    }


# TOKEN_PRICES is for internal cost tracking only (subscription plan, not real API billing)
# Codex models intentionally absent — their prices live in backend_codex.py
TOKEN_PRICES = {
    "claude-fable-5[1m]": {"input": 10.0, "output": 50.0},
    "claude-opus-5[1m]":   {"input": 5.0,  "output": 25.0},
    "claude-sonnet-5[1m]": {"input": 2.0,  "output": 10.0},
    "claude-haiku-4-5":    {"input": 0.80, "output": 4.0},
}

DEFAULT_MODEL = "claude-sonnet-5[1m]"
MODEL_SPECS: dict[str, ModelSpec] = {}

# These exact ids occur in persisted sessions but are no longer selectable.
# Keeping them outside MODELS prevents retired models from returning to the UI
# while making resume deterministic without any prefix inference.
COMPAT_MODEL_SPECS: dict[str, ModelSpec] = {
    "claude-sonnet-4-6": ModelSpec(
        id="claude-sonnet-4-6",
        name="Sonnet 4.6 (legacy)",
        runtime="claude",
        provider="anthropic",
        context_length=200000,
        price_input=3.0,
        price_output=15.0,
    ),
    "claude-sonnet-4-5": ModelSpec(
        id="claude-sonnet-4-5",
        name="Sonnet 4.5 (legacy)",
        runtime="claude",
        provider="anthropic",
        context_length=200000,
    ),
    "claude-opus-4-8[1m]": ModelSpec(
        id="claude-opus-4-8[1m]",
        name="Opus 4.8 (legacy, 1M)",
        runtime="claude",
        provider="anthropic",
        context_length=1000000,
        price_input=15.0,
        price_output=75.0,
    ),
    "claude-opus-4-8": ModelSpec(
        id="claude-opus-4-8",
        name="Opus 4.8 (legacy)",
        runtime="claude",
        provider="anthropic",
        context_length=1000000,
    ),
    "claude-opus-4-6[1m]": ModelSpec(
        id="claude-opus-4-6[1m]",
        name="Opus 4.6 (legacy, 1M)",
        runtime="claude",
        provider="anthropic",
        context_length=1000000,
        price_input=15.0,
        price_output=75.0,
    ),
    "claude-opus-4-6": ModelSpec(
        id="claude-opus-4-6",
        name="Opus 4.6 (legacy)",
        runtime="claude",
        provider="anthropic",
        context_length=1000000,
    ),
}

# The only proxy models observed on a registered deployment that omit both
# runtime and provider. Exact ids make this a reviewed compatibility contract,
# not another family-wide catch-all.
_REVIEWED_PROXY_ROUTES: dict[str, tuple[str, str]] = {
    **{
        model_id: (BACKENDS[model_id], MODEL_PROVIDERS[model_id])
        for model_id in MODELS
    },
    "deepseek/deepseek-v4-flash": ("opencode", "deepseek"),
    "deepseek/deepseek-v4-pro": ("opencode", "deepseek"),
}

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


def register_model(spec: ModelSpec, *, replace: bool = False) -> None:
    """Register one explicit provider/model/runtime route and legacy lookup views."""
    if not spec.id:
        raise ValueError("model id must not be empty")
    if not spec.provider or spec.provider == "unknown":
        raise ValueError(f"model '{spec.id}' must declare an explicit provider")
    from app.runtime_registry import get_runtime
    get_runtime(spec.runtime)
    if spec.runtime not in PROVIDER_METADATA:
        raise ValueError(
            f"model '{spec.id}' uses runtime '{spec.runtime}' without provider metadata"
        )
    if spec.provider not in PROVIDER_METADATA[spec.runtime].model_providers:
        allowed = ", ".join(PROVIDER_METADATA[spec.runtime].model_providers) or "(none)"
        raise ValueError(
            f"model '{spec.id}' provider '{spec.provider}' is not registered for "
            f"runtime '{spec.runtime}'; registered providers: {allowed}"
        )
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
    """Return an explicit selectable or persisted-session compatibility route."""
    if model_id in MODEL_SPECS:
        return MODEL_SPECS[model_id]
    if model_id in COMPAT_MODEL_SPECS:
        return COMPAT_MODEL_SPECS[model_id]
    registered = ", ".join(sorted(MODEL_SPECS)) or "(none)"
    compatibility = ", ".join(sorted(COMPAT_MODEL_SPECS))
    raise ValueError(
        f"unknown model '{model_id}'; registered models: {registered}; "
        f"persisted-session compatibility routes: {compatibility}"
    )


def _seed_model_specs() -> None:
    for model_id, name in list(MODELS.items()):
        prices = TOKEN_PRICES.get(model_id, {})
        MODEL_SPECS[model_id] = ModelSpec(
            id=model_id,
            name=name,
            runtime=BACKENDS[model_id],
            provider=MODEL_PROVIDERS[model_id],
            context_length=CONTEXT_LIMITS[model_id],
            price_input=prices.get("input"),
            price_output=prices.get("output"),
        )


_seed_model_specs()


def validate_model_registry() -> None:
    """Fail if model, runtime, provider, or legacy lookup views disagree."""
    from app.runtime_registry import get_runtime

    errors: list[str] = []
    for model_id, spec in {**COMPAT_MODEL_SPECS, **MODEL_SPECS}.items():
        if spec.id != model_id:
            errors.append(f"{model_id}: spec.id is '{spec.id}'")
        try:
            get_runtime(spec.runtime)
        except ValueError as exc:
            errors.append(f"{model_id}: {exc}")
        if spec.runtime not in PROVIDER_METADATA:
            errors.append(
                f"{model_id}: runtime '{spec.runtime}' has no provider metadata"
            )
        if not spec.provider or spec.provider == "unknown":
            errors.append(f"{model_id}: provider must be explicit")
        elif (
            spec.runtime in PROVIDER_METADATA
            and spec.provider not in PROVIDER_METADATA[spec.runtime].model_providers
        ):
            errors.append(
                f"{model_id}: provider '{spec.provider}' is not registered for "
                f"runtime '{spec.runtime}'"
            )
        if spec.context_length <= 0:
            errors.append(f"{model_id}: context_length must be positive")

    for model_id, spec in MODEL_SPECS.items():
        if MODELS.get(model_id) != spec.name:
            errors.append(f"{model_id}: MODELS view differs from ModelSpec")
        if BACKENDS.get(model_id) != spec.runtime:
            errors.append(f"{model_id}: BACKENDS view differs from ModelSpec")
        if CONTEXT_LIMITS.get(model_id) != spec.context_length:
            errors.append(f"{model_id}: CONTEXT_LIMITS view differs from ModelSpec")

    for provider_id, metadata in PROVIDER_METADATA.items():
        if provider_id != metadata.id:
            errors.append(
                f"provider metadata key '{provider_id}' differs from id '{metadata.id}'"
            )

    if errors:
        raise ValueError("invalid model/runtime/provider registry:\n- " + "\n- ".join(errors))


def provider_metadata_payload() -> dict[str, dict]:
    return {
        provider_id: {
            "id": metadata.id,
            "title": metadata.title,
            "ui_provider": metadata.ui_provider,
            "cache_ttl_seconds": metadata.cache_ttl_seconds,
            "cache_ttl_approximate": metadata.cache_ttl_approximate,
            "model_providers": list(metadata.model_providers),
        }
        for provider_id, metadata in PROVIDER_METADATA.items()
    }


def is_proxy_connected() -> bool:
    return _proxy_connected


def _clear_selectable_models() -> None:
    MODELS.clear()
    CONTEXT_LIMITS.clear()
    TOKEN_PRICES.clear()
    BACKENDS.clear()
    MODEL_SPECS.clear()
    ALIASES.clear()


def _proxy_model_spec(raw: dict) -> ModelSpec | None:
    model_id = str(raw.get("id") or "").strip()
    if not model_id:
        return None

    reviewed = _REVIEWED_PROXY_ROUTES.get(model_id)
    runtime = str(raw.get("runtime") or raw.get("backend") or "").strip()
    provider = str(raw.get("provider") or "").strip()
    if not runtime and reviewed:
        runtime = reviewed[0]
    if not provider and reviewed:
        provider = reviewed[1]
    if not runtime:
        raise ValueError(
            f"proxy model '{model_id}' must declare runtime/backend or have a "
            "reviewed exact route"
        )
    if not provider:
        raise ValueError(
            f"proxy model '{model_id}' must declare provider or have a reviewed exact route"
        )

    from app.runtime_registry import get_runtime
    get_runtime(runtime)
    if runtime not in PROVIDER_METADATA:
        raise ValueError(
            f"proxy model '{model_id}' uses runtime '{runtime}' without provider metadata"
        )
    if provider not in PROVIDER_METADATA[runtime].model_providers:
        allowed = ", ".join(PROVIDER_METADATA[runtime].model_providers) or "(none)"
        raise ValueError(
            f"proxy model '{model_id}' provider '{provider}' is not registered for "
            f"runtime '{runtime}'; registered providers: {allowed}"
        )

    context_length = int(raw.get("context_length") or 200000)
    if context_length <= 0:
        raise ValueError(
            f"proxy model '{model_id}' has invalid context_length={context_length}"
        )
    pricing = raw.get("pricing") or {}
    prompt_price = float(pricing.get("prompt", "0")) * 1_000_000
    completion_price = float(pricing.get("completion", "0")) * 1_000_000
    if "/" in model_id:
        default_name = model_id.rsplit("/", 1)[1].replace("-", " ").title()
    else:
        default_name = model_id.replace("-", " ").title()
    return ModelSpec(
        id=model_id,
        name=str(raw.get("name") or default_name),
        runtime=runtime,
        provider=provider,
        context_length=context_length,
        price_input=round(prompt_price, 4) if prompt_price else None,
        price_output=round(completion_price, 4) if completion_price else None,
    )


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
            _clear_selectable_models()
        return False

    models_list = data.get("data", [])
    if not models_list:
        logger.warning("fetch_models_from_proxy: empty model list")
        _proxy_connected = False
        if enterprise_mode:
            _clear_selectable_models()
        return False

    try:
        discovered = [
            spec for raw in models_list
            if (spec := _proxy_model_spec(raw)) is not None
        ]
    except (TypeError, ValueError, OverflowError) as exc:
        _proxy_connected = False
        raise ValueError(f"invalid proxy model registry: {exc}") from exc
    if not discovered:
        _proxy_connected = False
        raise ValueError("invalid proxy model registry: no model has a non-empty id")

    if enterprise_mode:
        _clear_selectable_models()

    added = 0
    for spec in discovered:
        if spec.id not in MODEL_SPECS:
            register_model(spec)
            added += 1
        for alias in _generate_aliases(spec.id):
            if alias not in ALIASES and alias != spec.id:
                ALIASES[alias] = spec.id

    _generate_semantic_aliases()
    validate_model_registry()
    _proxy_connected = True
    mode_label = "enterprise (proxy-only)" if enterprise_mode else "dev (merged)"
    logger.info(f"Loaded {len(discovered)} models from proxy ({added} new, {mode_label})")
    return True


# Semantic alias patterns: short name → match first model containing substring
_SEMANTIC_PATTERNS = [
    ("opus", "opus"),
    ("opus5", "opus-5"),
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
        validate_model_registry()
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
    validate_model_registry()


def resolve_model(model: str) -> str:
    m = model.lower().strip()
    if m in ALIASES:
        resolved = ALIASES[m]
        if resolved in MODEL_SPECS:
            return resolved
    if m in MODELS:
        return m
    registered = ", ".join(sorted(MODELS)) or "(none)"
    raise ValueError(f"unknown model '{model}'; registered models: {registered}")


def backend_for_model(model: str) -> str:
    return get_model_spec(model).runtime


def runtime_for_record(record: dict) -> str:
    """Resolve legacy rows without treating missing or invalid data as Claude."""
    runtime = record.get("backend_type") or record.get("runtime") or record.get("backend")
    if runtime:
        return str(runtime)
    model = record.get("model")
    if model:
        try:
            return backend_for_model(str(model))
        except ValueError:
            pass
    return "unknown"


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
