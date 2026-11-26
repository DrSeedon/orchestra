"""Native Codex speed policy and API-equivalent pricing."""

from typing import Literal

CodexSpeed = Literal["standard", "fast"]

# These local Codex subscription models advertise priority on our plan.
# https://learn.chatgpt.com/docs/pricing#speed-multipliers
CODEX_FAST_ALLOWANCE = {
    "gpt-6.2-sol": 2,
    "gpt-6.2-astra": 2,
    "gpt-6.1-terra": 2.5,
    "gpt-6-luna": 2.5,
}

# Fast API rates are double the applicable Standard rates for these models.
CODEX_FAST_API_MULTIPLIER = 2


def codex_speed_view(runtime: str, model: str, speed: str) -> dict:
    multiplier = CODEX_FAST_ALLOWANCE.get(model) if runtime == "codex" else None
    return {
        "codex_speed": "fast" if multiplier and speed == "fast" else "standard",
        "codex_fast_allowance_multiplier": multiplier,
    }
