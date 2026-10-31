"""Native manual Terra registration and callers; synthetic, no provider I/O."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import Response

from app import models, quota_gate
from app.backend_codex import (
    CODEX_CONTEXT_LIMITS, CODEX_REASONING_EFFORTS, CODEX_TOKEN_PRICES,
    CodexBackend, _codex_cost,
)
from app.routes.sessions import CreateSessionRequest
from app.routes.system import get_models_catalog, list_models

TERRA = "gpt-6.1-terra"


@pytest.fixture(autouse=True)
def isolated_flags():
    from app.db import init_db

    init_db()


@pytest.mark.parametrize("alias", ["terra", "gpt6.1terra", TERRA])
def test_alias_reaches_native_model_and_request(alias, tmp_path):
    assert models.resolve_model(alias) == TERRA
    assert CreateSessionRequest(name="manual", cwd=str(tmp_path), model=alias).model == TERRA
    spec = models.get_model_spec(models.resolve_model(alias))
    assert (spec.id, spec.name, spec.runtime, spec.provider) == (
        TERRA, "GPT-6.1 Terra", "codex", "openai",
    )
    assert models.backend_for_model(spec.id) == "codex"
    assert models.CONTEXT_LIMITS[TERRA] == CODEX_CONTEXT_LIMITS[TERRA] == 258400
    assert models.resolve_model("sol") == models.resolve_model("codex") == "gpt-6.1-sol"
    assert models.resolve_model("luna") == "gpt-6-luna"
    models.validate_model_registry()


@pytest.mark.asyncio
async def test_manual_catalog_visibility_and_flag_override_cannot_admit_agents():
    models.ensure_dashboard_visible(TERRA)
    assert models.get_model_flags(TERRA) == {"dashboard": True, "agents": False}
    entries = (await list_models(Response()))["models"]
    terra = next(entry for entry in entries if entry["id"] == TERRA)
    assert (terra["name"], terra["provider"], terra["runtime"], terra["backend"]) == (
        "GPT-6.1 Terra", "openai", "codex", "codex",
    )
    assert terra["context_length"] == 258400
    assert terra["capabilities"]["event_stream"] == "per_turn"
    assert models.set_model_flags(TERRA, agents=True) == {
        "dashboard": True, "agents": False,
    }
    catalog = (await get_models_catalog())["catalog"]
    assert next(entry for entry in catalog if entry["id"] == TERRA)["flags"] == {
        "dashboard": True, "agents": False,
    }
    with pytest.raises(ValueError, match="disabled for agents"):
        models.ensure_spawn_allowed(TERRA, model_reason="protected work")
    models.set_model_flags(TERRA, dashboard=False)
    assert TERRA not in {entry["id"] for entry in (await list_models(Response()))["models"]}
    with pytest.raises(ValueError, match="hidden from the dashboard"):
        models.ensure_dashboard_visible(TERRA)
    # A hidden manual model remains recoverable with the exact persisted identity.
    assert models.get_model_spec(TERRA).runtime == "codex"


@pytest.mark.parametrize("billing", ["subscription", "api_credit", "invalid"])
def test_old_flags_and_billing_do_not_open_terra_to_agents(monkeypatch, billing):
    monkeypatch.setattr(models, "_load_model_flags", lambda: {
        TERRA: {"dashboard": True, "agents": True},
    })
    assert models.get_model_flags(TERRA)["agents"] is False
    with pytest.raises(ValueError):
        models.ensure_spawn_allowed(TERRA, billing=billing, model_reason="protected work")


@pytest.mark.parametrize("tokens,expected", [
    ((1_000_000, 0, 0, 0), 1.0),
    ((1_000_000, 1_000_000, 0, 0), 0.05),
    ((1_000_000, 0, 1_000_000, 0), 1.25),
    ((0, 0, 0, 1_000_000), 5.0),
    ((1000, 700, 200, 10), 0.000435),
])
def test_standard_api_equivalent_prices_charge_each_token_once(tokens, expected):
    assert _codex_cost(TERRA, *tokens) == pytest.approx(expected)
    assert _codex_cost(TERRA, *tokens) == pytest.approx(
        _codex_cost("gpt-6.1-sol", *tokens) / 2,
    )
    # Persisted old Terra is still its own model, with its historical rates.
    assert models.get_model_spec("gpt-5.6-terra").id == "gpt-5.6-terra"
    assert CODEX_TOKEN_PRICES["gpt-5.6-terra"] == {
        "input": 2.0, "cached": 0.2, "write": 2.5, "output": 12.0,
    }
    with pytest.raises(ValueError, match="unknown model"):
        models.resolve_model("gpt-5.6-terra")


@pytest.mark.asyncio
@pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh", "max"])
async def test_recovered_terra_thread_sends_exact_model_and_existing_server_effort(effort):
    backend = CodexBackend(
        model=TERRA, cwd="/unused", resume_thread_id="synthetic-thread",
        reasoning_effort=effort, is_orchestrator=True,
    )
    backend._proc = SimpleNamespace(returncode=None)
    backend._request = AsyncMock(return_value={"turn": {"id": "synthetic-turn"}})
    await backend.send("continue")
    backend._request.assert_awaited_once_with("turn/start", {
        "threadId": "synthetic-thread", "input": [{"type": "text", "text": "continue"}],
        "model": TERRA, "effort": effort,
    })
    assert backend.session_id == "synthetic-thread"
    assert CODEX_REASONING_EFFORTS == {"low", "medium", "high", "xhigh", "max"}


def test_runtime_catalog_context_overrides_conservative_fallback(tmp_path, monkeypatch):
    from app import backend_codex

    backend = CodexBackend(model=TERRA, cwd=str(tmp_path))
    assert backend._model_context_window == 258400
    monkeypatch.setattr(backend_codex, "_base_codex_home", lambda: tmp_path)
    monkeypatch.setattr(backend_codex, "_carried_base_scalars", lambda: "")
    assert backend._handoff_context_window() == 258400
    # Synthetic metadata exercises the contract, not a claim about Terra's real window.
    monkeypatch.setattr(backend_codex, "_carried_base_scalars", lambda: "model_context_window = 400000")
    (tmp_path / "models_cache.json").write_text(json.dumps({"models": [{
        "slug": TERRA, "max_context_window": 300000,
        "effective_context_window_percent": 95,
    }]}))
    assert backend._handoff_context_window() == 285000
    backend._record_token_usage({"tokenUsage": {
        "total": {"inputTokens": 100}, "last": {"inputTokens": 100},
        "modelContextWindow": 289000,
    }})  # synthetic runtime telemetry wins
    assert backend._handoff_context_window() == 289000


@pytest.mark.parametrize("used,expected", [(0, "available"), (100, "blocked")])
def test_terra_inherits_sol_quota_pool_and_policy(used, expected):
    now = 1793400000
    providers = {"codex": {"windows": [{
        "id": "primary", "window_minutes": 10080,
        "utilization": used, "resets_at": now + 10080 * 60 / 2,
    }]}}
    decisions = [quota_gate.evaluate_worker_admission(
        model, providers, {"codex": now}, now=now,
    ) for model in (TERRA, "gpt-6.1-sol")]
    for decision in decisions:
        assert decision.provider == "codex"
        assert decision.lane == "sol"
        assert decision.state == expected
    assert decisions[0].limit_pct == decisions[1].limit_pct
    assert decisions[0].hard_limit_pct == decisions[1].hard_limit_pct
