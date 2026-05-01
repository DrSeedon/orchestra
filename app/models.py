"""Available models — single source of truth."""

MODELS = {
    "claude-opus-4-6[1m]": "Opus 4.6 (1M)",
    "claude-sonnet-4-6": "Sonnet 4.6",
    "claude-haiku-4-5": "Haiku 4.5",
}

ALIASES = {
    "opus": "claude-opus-4-6[1m]",
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5",
}

DEFAULT_MODEL = "claude-sonnet-4-6"


def resolve_model(model: str) -> str:
    m = model.lower().strip()
    if m in ALIASES:
        return ALIASES[m]
    if m in MODELS:
        return m
    return model
