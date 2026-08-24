"""#298 frozen RED acceptance for the server-owned worker routing tree.

These tests intentionally assert the future public seam through the existing MCP module, so
the pre-implementation failure is an assertion about missing behavior, not a collection error.
The oracle is immutable after the plan gate.
"""

from __future__ import annotations

import inspect

import pytest


def _pure_router():
    import importlib
    import importlib.util

    spec = importlib.util.find_spec("app.model_router")
    assert spec is not None, "#298 pure model_router module is missing"
    module = importlib.import_module("app.model_router")
    route = getattr(module, "evaluate_route", None)
    assert callable(route), "#298 pure evaluate_route seam is missing"
    return route


def _router(monkeypatch, **state):
    from app import mcp_stdio

    route = _public_router()
    provider = getattr(mcp_stdio, "_runtime_state_provider", None)
    assert callable(provider), "#298 private runtime state provider is missing"
    monkeypatch.setattr(
        mcp_stdio,
        "_runtime_state_provider",
        lambda: _runtime_state(**state),
    )
    return route


def _public_router():
    from app import mcp_stdio

    route = getattr(mcp_stdio, "route_worker", None)
    assert callable(route), "#298 route_worker server seam is missing"
    parameters = inspect.signature(route).parameters
    assert "runtime_state" not in parameters
    assert "route_state" not in parameters
    return route


def _runtime_state(**overrides):
    state = {
        "trusted_source": "test-fixture",
        "generation": 1,
        "trusted": True,
        "codex_exhausted": False,
        "codex_binding": False,
        "spark_quota_available": False,
        "ox_eligible": False,
        "ox_canary_green": False,
        "ox_zero_spend_proven": False,
    }
    state.update(overrides)
    return state


def _metadata(**overrides):
    data = {
        "task_id": "298-test",
        "scope": "public-test",
        "sensitivity": "public",
        "openness": "closed",
        "complexity": "deterministic",
        "oracle": {"kind": "command", "value": "pytest -q tests/test_t1.py"},
        "context_tokens": 20_000,
        "required_tools": ["read", "edit"],
        "requires_vision": False,
        "named_file_count": 1,
        "all_decisions_explicit": True,
    }
    data.update(overrides)
    return data


def test_t1_route_worker_has_server_owned_total_contract():
    public = _public_router()
    public_parameters = inspect.signature(public).parameters
    assert "task_metadata" in public_parameters
    assert "sol_authorized" in public_parameters
    route = _pure_router()
    parameters = inspect.signature(route).parameters
    assert "runtime_state" in parameters


@pytest.mark.parametrize(
    "metadata",
    [
        _metadata(openness="open", complexity="research"),
        _metadata(openness="open", complexity="architecture"),
        _metadata(openness="closed", complexity="security"),
    ],
)
def test_t2_sol_class_without_receipt_refuses_before_any_sol_call(metadata, monkeypatch):
    route = _router(monkeypatch)
    decision = route(task_metadata=metadata, sol_authorized=None)
    assert decision.code == "REFUSE_SOL_AUTH"
    assert decision.model is None
    assert decision.request_decision is True
    assert decision.sol_spawn_allowed is False


def test_t3_sol_class_valid_receipt_selects_sol_and_invalid_never_downgrades(monkeypatch):
    route = _router(monkeypatch)
    authorized = {
        "receipt_id": "sol-test-receipt",
        "task_id": "298-test",
        "scope": "public-test",
        "requester": "user",
        "granted_at": "2026-08-24T00:00:00Z",
        "expires_at": "2099-08-24T00:00:00Z",
        "reason": "explicit auxiliary Sol approval",
    }
    sol = route(
        task_metadata=_metadata(openness="open", complexity="research"),
        sol_authorized=authorized,
    )
    assert (sol.model, sol.runtime, sol.effort) == ("gpt-5.6-sol", "codex", "xhigh")

    invalid = dict(authorized, scope="other-scope")
    refused = route(
        task_metadata=_metadata(openness="open", complexity="research"),
        sol_authorized=invalid,
    )
    assert refused.code == "REFUSE_SOL_AUTH"
    assert refused.model not in {"gpt-5.6- luna", "gpt-5.6-luna", "stealth/ox-alpha"}


@pytest.mark.parametrize(
    ("metadata", "route_state", "expected_model", "expected_runtime"),
    [
        (
            _metadata(openness="open", complexity="creative", requires_vision=True),
            {},
            "claude-opus-5[1m]",
            "claude",
        ),
        (
            _metadata(context_tokens=90_000, required_tools=["read", "edit"]),
            {"codex_binding": True, "spark_quota_available": True},
            "gpt-5.3-codex-spark",
            "codex",
        ),
        (
            _metadata(),
            {"ox_eligible": True, "ox_canary_green": True, "ox_zero_spend_proven": True},
            "stealth/ox-alpha",
            "harness",
        ),
        (_metadata(), {}, "gpt-5.6-luna", "codex"),
    ],
)
def test_t4_total_model_matrix_selects_explicit_leaf(
    metadata, route_state, expected_model, expected_runtime, monkeypatch
):
    route = _router(monkeypatch, **route_state)
    decision = route(task_metadata=metadata, sol_authorized=None)
    assert (decision.model, decision.runtime) == (expected_model, expected_runtime)


def test_t5_disabled_fable_and_terra_are_explicit_refusals(monkeypatch):
    route = _router(monkeypatch)
    for requested in ("fable", "terra", "claude-fable-5[1m]", "gpt-5.6-terra"):
        decision = route(
            task_metadata=_metadata(requested_model=requested),
            sol_authorized=None,
        )
        assert decision.code == "REFUSE_DISABLED_MODEL"
        assert decision.model is None


def test_t6_spark_contract_is_one_attempt_and_handoff_is_not_retry(monkeypatch):
    route = _router(monkeypatch, codex_binding=True, spark_quota_available=True)
    decision = route(
        task_metadata=_metadata(context_tokens=90_000),
        sol_authorized=None,
    )
    assert decision.model == "gpt-5.3-codex-spark"
    assert decision.retry_policy == "one_attempt"
    assert decision.failure_handoff in {"luna", "sol_with_receipt"}


def test_t7_ox_guard_rejects_paid_or_unknown_cost_before_provider_post():
    from app.harness.llm import OpenRouterClient

    guard = getattr(OpenRouterClient, "admit_attempt", None)
    assert callable(guard), "#298 OpenRouter pre-POST admission seam is missing"
    for proof in (
        {},
        {"prompt": None, "completion": 0},
        {"prompt": False, "completion": 0},
        {"prompt": "0", "completion": 0},
        {"prompt": 1, "completion": 0},
        {"prompt": 0, "completion": 0, "image": None},
    ):
        assert guard(model="stealth/ox-alpha", price_proof=proof) is False
    assert guard(model="stealth/ox-alpha", price_proof={"prompt": 0, "completion": 0}) is True


def test_t8_scope_growth_reclassifies_before_next_turn(monkeypatch):
    route = _router(monkeypatch, selected_model="stealth/ox-alpha")
    decision = route(
        task_metadata=_metadata(scope_growth=True),
        sol_authorized=None,
    )
    assert decision.code in {"RECLASSIFY", "REFUSE_SOL_AUTH"}
    assert decision.model != "stealth/ox-alpha"


def test_t9_prompt_is_generated_mirror_of_server_contract():
    from app.pipeline import build_system_prompt

    prompt = build_system_prompt("default", "orchestrator")
    for anchor in (
        "sol_authorized",
        "REFUSE_SOL_AUTH",
        "gpt-5.3-codex-spark",
        "REFUSE_DISABLED_MODEL",
    ):
        assert anchor in prompt


def test_t10_caller_model_override_cannot_bypass_server_router(monkeypatch):
    route = _router(monkeypatch, ox_eligible=True, ox_canary_green=True)
    decision = route(
        task_metadata=_metadata(requested_model="sol"),
        sol_authorized=None,
    )
    assert decision.code in {"REFUSE_MODEL_OVERRIDE", "REFUSE_SOL_AUTH"}
    assert decision.model != "gpt-5.6-sol"


def test_t11_legacy_omitted_model_is_refused_not_implicit_sonnet():
    from app.routes.sessions import CreateSessionRequest

    field = CreateSessionRequest.model_fields["model"]
    assert field.is_required(), "legacy omitted model must be a visible refusal, not Sonnet"


def test_t12_invalid_metadata_refuses_before_sol_authorization(monkeypatch):
    route = _router(monkeypatch)
    decision = route(
        task_metadata=_metadata(openness="unknown", complexity="unknown"),
        sol_authorized=None,
    )
    assert decision.code == "REFUSE_METADATA"


def test_t13_codex_review_sol_requires_the_same_trusted_receipt():
    from app import mcp_stdio

    resolver = getattr(mcp_stdio, "_resolve_codex_review_model", None)
    assert callable(resolver)
    parameters = inspect.signature(resolver).parameters
    assert "sol_authorized" in parameters
    with pytest.raises(Exception, match="SOL_AUTH"):
        resolver("sol", sol_authorized=None)
