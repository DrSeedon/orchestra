import pytest

from app.models import (
    ALIASES, BACKENDS, CONTEXT_LIMITS, DEFAULT_MODEL,
    MODELS, RETIRED_SELECTABLE_MODEL_IDS, SELECTABLE_MODEL_SPECS,
    TOKEN_PRICES, ensure_spawn_allowed,
    get_model_flags, get_model_spec, resolve_model,
)
from app.routes import sessions as sessmod


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        ("sol", "gpt-6.1-sol"),
        ("luna", "gpt-6-luna"),
    ],
)
def test_resolve_model_aliases(alias: str, expected: str) -> None:
    assert resolve_model(alias) == expected


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        ("sol", "gpt-6.1-sol"),
        ("luna", "gpt-6-luna"),
    ],
)
def test_create_session_request_resolves_model_alias(alias: str, expected: str) -> None:
    req = sessmod.CreateSessionRequest(name="w-child", cwd="/tmp", model=alias)
    assert req.model == expected


def test_sonnet_aliases_and_retired_ids_resolve_to_sonnet_55():
    model_id = "claude-sonnet-5-5[1m]"
    assert resolve_model("sonnet") == model_id
    with pytest.raises(ValueError, match="unknown model"):
        resolve_model("claude-sonnet-5[1m]")
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


def test_selectable_models_match_the_curated_catalog():
    expected = {
        "claude-opus-5-5[1m]", "claude-sonnet-5-5[1m]", "gpt-6-luna",
        "gpt-5.3-codex-spark", "grok-4.6", "claude-opus-4-6[1m]",
        "claude-haiku-5-5", "claude-fable-5-1[1m]", "gpt-6-astra",
        "gpt-6.1-sol", "GigaChat-2", "GigaChat-2-Max", "GigaChat-3-Ultra",
        "GigaChat-2-Pro", "GigaChat-3-Lightning", "GigaChat-3-Pro",
    }
    assert {spec.id for spec in SELECTABLE_MODEL_SPECS} == expected
    assert set(MODELS) == expected
    retired_ids = RETIRED_SELECTABLE_MODEL_IDS
    assert retired_ids.isdisjoint(ALIASES.values())
    assert retired_ids.isdisjoint(MODELS)
    assert get_model_flags("gpt-6-astra") == {"dashboard": True, "agents": False}
    assert get_model_flags("gpt-6.1-sol") == {"dashboard": True, "agents": False}
    assert resolve_model("grok") == "grok-4.6"
    assert resolve_model("sol") == "gpt-6.1-sol"


def test_haiku_55_replaces_haiku_45_in_the_selectable_registry():
    model_id = "claude-haiku-5-5"
    assert resolve_model("haiku") == model_id
    assert model_id in MODELS
    assert "claude-haiku-4-5" not in MODELS
    assert CONTEXT_LIMITS[model_id] == 1_000_000
    assert TOKEN_PRICES[model_id] == {"input": 0.10, "output": 0.50}
    with pytest.raises(ValueError, match="unknown model"):
        resolve_model("claude-haiku-4-5")


@pytest.mark.parametrize("model_id", ["gpt-6-astra", "gpt-6.1-sol"])
def test_astra_and_sol_are_manual_only_even_if_stored_flags_allow_agents(model_id, monkeypatch):
    monkeypatch.setattr(
        "app.models._load_model_flags",
        lambda: {model_id: {"agents": True, "dashboard": True}},
    )
    assert get_model_flags(model_id) == {"dashboard": True, "agents": False}
    with pytest.raises(ValueError, match="disabled for agents"):
        ensure_spawn_allowed(model_id)


def test_retired_models_keep_explicit_session_compatibility_without_becoming_selectable():
    import app.models as registry

    for model_id in (
        "gpt-5.6-luna", "gpt-5.6-sol", "gpt-6-sol", "gpt-5.6-terra",
        "gpt-5.5", "grok-4.5", "claude-opus-5[1m]", "claude-sonnet-5[1m]",
        "claude-opus-4-6",
    ):
        assert model_id in registry.COMPAT_MODEL_SPECS
        assert get_model_spec(model_id).id == model_id
        assert model_id not in MODELS
        with pytest.raises(ValueError, match="unknown model"):
            resolve_model(model_id)


def test_reducer_role_uses_the_selectable_luna_model():
    from app.pipeline import load_pipeline

    role = load_pipeline("default").roles["reducer"]
    assert role.model == "gpt-6-luna"
    assert resolve_model(role.model) == "gpt-6-luna"
