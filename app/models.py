"""Available models — single source of truth."""

MODELS = {
    "claude-opus-4-6[1m]": "Opus 4.6 (1M)",
    "claude-sonnet-4-6": "Sonnet 4.6",
    "claude-haiku-4-5": "Haiku 4.5",
    "gpt-5.5": "GPT-5.5",
    "gpt-5.4": "GPT-5.4",
    "gpt-5.4-mini": "GPT-5.4 Mini",
}

CONTEXT_LIMITS = {
    "claude-opus-4-6[1m]": 1000000,
    "claude-sonnet-4-6": 200000,
    "claude-haiku-4-5": 200000,
    "gpt-5.5": 258400,
    "gpt-5.4": 258400,
    "gpt-5.4-mini": 258400,
}

ALIASES = {
    "opus": "claude-opus-4-6[1m]",
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
}

BACKENDS = {
    "claude-opus-4-6[1m]": "claude",
    "claude-sonnet-4-6": "claude",
    "claude-haiku-4-5": "claude",
    "gpt-5.5": "codex",
    "gpt-5.4": "codex",
    "gpt-5.4-mini": "codex",
}

DEFAULT_MODEL = "claude-sonnet-4-6"


def resolve_model(model: str) -> str:
    m = model.lower().strip()
    if m in ALIASES:
        return ALIASES[m]
    if m in MODELS:
        return m
    return model


def backend_for_model(model: str) -> str:
    return BACKENDS.get(model, "claude")
