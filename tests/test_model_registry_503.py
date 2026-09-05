import pytest

from app.backend_codex import CODEX_REASONING_EFFORTS, CODEX_TOKEN_PRICES, _codex_cost
from app.models import get_model_spec, resolve_model


@pytest.mark.parametrize("alias", ["astra", "gpt6astra"])
def test_gpt6_astra_aliases_resolve(alias: str) -> None:
    assert resolve_model(alias) == "gpt-6-astra"


def test_gpt6_astra_spec_and_price_are_registered() -> None:
    spec = get_model_spec("gpt-6-astra")
    assert spec.runtime == "codex"
    assert spec.provider == "openai"
    price = CODEX_TOKEN_PRICES[spec.id]
    assert price is not None
    assert all(value > 0 for value in price.values())


def test_gpt6_astra_cost_computation_is_nonzero() -> None:
    assert _codex_cost("gpt-6-astra", 1000, 700, 100, 50) > 0


def test_minimal_is_not_a_supported_codex_effort() -> None:
    assert "minimal" not in CODEX_REASONING_EFFORTS
