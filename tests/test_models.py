import pytest

from app.models import BACKENDS, CONTEXT_LIMITS, DEFAULT_MODEL, MODELS, TOKEN_PRICES, resolve_model
from app.routes import sessions as sessmod


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        ("sol", "gpt-6-sol"),
        ("luna", "gpt-6-luna"),
    ],
)
def test_resolve_model_aliases(alias: str, expected: str) -> None:
    assert resolve_model(alias) == expected


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        ("sol", "gpt-6-sol"),
        ("luna", "gpt-6-luna"),
    ],
)
def test_create_session_request_resolves_model_alias(alias: str, expected: str) -> None:
    req = sessmod.CreateSessionRequest(name="w-child", cwd="/tmp", model=alias)
    assert req.model == expected


def test_sonnet_aliases_and_retired_ids_resolve_to_sonnet_55():
    model_id = "claude-sonnet-5-5[1m]"
    assert resolve_model("sonnet") == model_id
    assert resolve_model("claude-sonnet-5[1m]") == model_id
    assert resolve_model("claude-sonnet-4-6") == model_id
    assert resolve_model("claude-sonnet-4-5") == model_id
    assert resolve_model("sonnet5") == model_id
    assert resolve_model("sonnet5.5") == model_id
    assert resolve_model("claude-sonnet-5-5") == model_id
    assert model_id in MODELS
    assert "claude-sonnet-5[1m]" not in MODELS
    assert MODELS[model_id] == "Sonnet 5.5 (1M)"
    assert CONTEXT_LIMITS[model_id] == 1_000_000
    assert TOKEN_PRICES[model_id] == {"input": 2.0, "output": 10.0}
    assert BACKENDS[model_id] == "claude"
    assert DEFAULT_MODEL == model_id
