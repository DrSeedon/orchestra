import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest


def _usage_row(event_id, *, billing_mode, cost_usd, ts):
    from app.db import turn_usage_add

    return turn_usage_add(
        event_id=event_id,
        session_id="credit-worker",
        runtime="claude",
        model="claude-sonnet-5-5[1m]",
        billing_mode=billing_mode,
        ok=True,
        stop_reason="end_turn",
        cost_usd=cost_usd,
        input_tokens=10,
        output_tokens=2,
        cache_read_tokens=0,
        cache_create_tokens=0,
        ts=ts,
    )


@pytest.fixture
def credit_db(tmp_path, monkeypatch):
    from app import db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "claude-api-credits.db")
    db.init_db()
    db.ensure_turn_usage_timing_schema()
    return db


def test_credit_balance_estimate_counts_only_api_credit_turn_usage(
    credit_db, monkeypatch,
):
    from app import claude_api_credits as credits

    monkeypatch.setenv(credits.API_KEY_ENV, "test-api-key")
    monkeypatch.setenv(credits.FALLBACK_FLAG_ENV, "1")
    start = datetime.fromisoformat(credits.BALANCE_BASELINE_AT)
    _usage_row("credit-turn", billing_mode="api_credit", cost_usd=0.25,
               ts=(start + timedelta(minutes=1)).isoformat())
    _usage_row("subscription-turn", billing_mode="subscription", cost_usd=5.0,
               ts=(start + timedelta(minutes=2)).isoformat())

    status = credits.credit_status(now=start + timedelta(minutes=3))

    assert status["available"] is True
    assert status["remaining_usd"] == pytest.approx(credits.BALANCE_BASELINE_USD - 0.25)
    assert status["tracked_spend_usd"] == pytest.approx(0.25)
    assert status["expires_at"] == credits.CREDITS_EXPIRE_AT
    assert credits.API_KEY_ENV not in status
    assert "test-api-key" not in repr(status)


def test_credit_fallback_flag_expiry_and_unknown_spend_fail_closed(
    credit_db, monkeypatch,
):
    from app import claude_api_credits as credits

    monkeypatch.setenv(credits.API_KEY_ENV, "test-api-key")
    start = datetime.fromisoformat(credits.BALANCE_BASELINE_AT)
    monkeypatch.setenv(credits.FALLBACK_FLAG_ENV, "0")
    assert credits.credit_status(now=start)["reason"] == "disabled"

    monkeypatch.setenv(credits.FALLBACK_FLAG_ENV, "1")
    expired = datetime.fromisoformat(credits.CREDITS_EXPIRE_AT)
    assert credits.credit_status(now=expired)["reason"] == "expired"

    _usage_row("unpriced-credit-turn", billing_mode="api_credit", cost_usd=None,
               ts=(start + timedelta(minutes=1)).isoformat())
    with credit_db._conn() as connection:
        connection.execute(
            "UPDATE turn_usage SET cost_unaccounted=1 WHERE event_id='unpriced-credit-turn'"
        )
    status = credits.credit_status(now=start + timedelta(minutes=2))
    assert status["available"] is False
    assert status["remaining_usd"] is None
    assert status["reason"] == "unknown_usage"


def test_zero_estimated_credit_and_provider_exhaustion_disable_fallback(
    credit_db, monkeypatch,
):
    from app import claude_api_credits as credits

    monkeypatch.setenv(credits.API_KEY_ENV, "test-api-key")
    monkeypatch.setenv(credits.FALLBACK_FLAG_ENV, "1")
    start = datetime.fromisoformat(credits.BALANCE_BASELINE_AT)
    _usage_row("spend-credit-grant", billing_mode="api_credit",
               cost_usd=credits.BALANCE_BASELINE_USD + 1,
               ts=(start + timedelta(minutes=1)).isoformat())
    assert credits.credit_status(now=start + timedelta(minutes=2))["reason"] == "exhausted"

    credits.mark_credits_exhausted()
    with credit_db._conn() as connection:
        connection.execute("DELETE FROM turn_usage")
    assert credits.credit_status(now=start + timedelta(minutes=3))["reason"] == "exhausted"


@pytest.mark.asyncio
async def test_closed_claude_subscription_selects_api_credit_route_only_with_credits(
    credit_db, monkeypatch,
):
    from app import claude_api_credits, quota_gate

    start = datetime(2026, 10, 6, 7, tzinfo=timezone.utc)
    now = start + timedelta(hours=90)
    monkeypatch.setattr(quota_gate.time, "time", lambda: now.timestamp())
    monkeypatch.setenv(claude_api_credits.API_KEY_ENV, "test-api-key")
    monkeypatch.setenv(claude_api_credits.FALLBACK_FLAG_ENV, "1")
    monkeypatch.setattr(claude_api_credits, "credit_status", lambda **_: {
        "available": True, "remaining_usd": 12.0, "reason": "available",
    })

    async def observation(**_):
        return {
            "providers": {"anthropic": {"label": "Claude", "windows": [{
                "id": "seven_day", "window_minutes": 10080,
                "utilization": 99.0,
                "resets_at": (start + timedelta(days=7)).isoformat(),
            }]}},
            "observed_at_by_provider": {"anthropic": now.timestamp() - 1},
        }

    decision = await quota_gate.get_worker_admission(
        "claude-sonnet-5-5[1m]", observation_loader=observation,
    )
    assert decision.state == "available"
    assert decision.billing_mode == "api_credit"
    assert "subscription quota is closed" in decision.reason

    monkeypatch.setattr(claude_api_credits, "credit_status", lambda **_: {
        "available": False, "remaining_usd": 0.0, "reason": "exhausted",
    })
    blocked = await quota_gate.get_worker_admission(
        "claude-sonnet-5-5[1m]", observation_loader=observation,
    )
    assert blocked.state == "blocked"
    assert blocked.billing_mode == "subscription"
    assert "API credits exhausted" in blocked.reason


def test_subscription_and_orchestrator_cli_env_never_receives_credit_key(
    monkeypatch,
):
    import app.backend_claude as backend_module

    captured = {}

    class FakeClient:
        def __init__(self, *, options):
            self.options = options

    monkeypatch.setattr(backend_module, "ClaudeSDKClient", FakeClient)
    monkeypatch.setattr(backend_module.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setenv("ORCHESTRA_CLAUDE_CREDIT_API_KEY", "private-test-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ambient-api-key-must-be-cleared")

    subscription = backend_module.ClaudeBackend(
        model="claude-sonnet-5-5[1m]", cwd="/tmp", is_orchestrator=False,
    )._make_client()
    captured["subscription"] = subscription.options.env
    orchestrator = backend_module.ClaudeBackend(
        model="claude-sonnet-5-5[1m]", cwd="/tmp", is_orchestrator=True,
    )._make_client()
    captured["orchestrator"] = orchestrator.options.env

    for env in captured.values():
        assert env["ORCHESTRA_CLAUDE_CREDIT_API_KEY"] == ""
        assert env["ANTHROPIC_API_KEY"] == ""
        assert "private-test-key" not in repr(env)
        assert "ambient-api-key-must-be-cleared" not in repr(env)

    with pytest.raises(ValueError, match="orchestrators"):
        backend_module.ClaudeBackend(
            model="claude-sonnet-5-5[1m]", cwd="/tmp",
            is_orchestrator=True, billing_mode="api_credit",
        )


def test_api_credit_route_gets_the_key_only_in_its_cli_env(monkeypatch):
    import app.backend_claude as backend_module
    from app.claude_api_credits import API_KEY_ENV

    class FakeClient:
        def __init__(self, *, options):
            self.options = options

    monkeypatch.setattr(backend_module, "ClaudeSDKClient", FakeClient)
    monkeypatch.setattr(backend_module.shutil, "which", lambda _: "/usr/bin/claude")
    monkeypatch.setenv(API_KEY_ENV, "private-test-key")
    client = backend_module.ClaudeBackend(
        model="claude-sonnet-5-5[1m]", cwd="/tmp", is_orchestrator=False,
        billing_mode="api_credit",
    )._make_client()
    assert client.options.env["ANTHROPIC_API_KEY"] == "private-test-key"
    assert client.options.env[API_KEY_ENV] == ""


def test_session_switches_persistent_backend_to_the_admitted_billing_route(monkeypatch, tmp_path):
    from app import claude_api_credits
    from app.session import AgentSession

    monkeypatch.setattr(claude_api_credits, "credit_status", lambda: {"available": True})

    class FakeBackend:
        def __init__(self, billing_mode):
            self.billing_mode = billing_mode
            self.disconnected = False

        async def disconnect(self):
            self.disconnected = True

        async def connect(self):
            return None

    session = AgentSession(
        id="credit-route-session", name="credit-route-worker",
        scope="/scope", cwd=str(tmp_path), model="claude-sonnet-5-5[1m]",
        role="worker", pipeline="",
    )
    subscription_backend = FakeBackend("subscription")
    session._backend = subscription_backend
    created = []

    def build(**kwargs):
        backend = FakeBackend(kwargs["billing_mode"])
        created.append(backend)
        return backend

    monkeypatch.setattr(session, "_make_backend", build)
    monkeypatch.setattr(session, "_refresh_skills", AsyncMock())
    monkeypatch.setattr(session, "_refresh_codex_project_doc", AsyncMock())
    backend = asyncio.run(
        session._ensure_backend(billing_mode="api_credit", activate=False)
    )
    assert subscription_backend.disconnected is True
    assert backend is created[0]
    assert backend.billing_mode == session._billing_mode == "api_credit"

    subscription_backend = asyncio.run(
        session._ensure_backend(billing_mode="subscription", activate=False)
    )
    assert backend.disconnected is True
    assert subscription_backend is created[1]
    assert subscription_backend.billing_mode == session._billing_mode == "subscription"


def test_agent_session_passes_billing_route_to_claude_factory(monkeypatch):
    import app.session as session_module
    from app.session import AgentSession

    session = AgentSession(
        id="credit-route-session", name="credit-route-worker",
        scope="/scope", cwd="/tmp", model="claude-sonnet-5-5[1m]",
        role="worker",
    )
    built = []
    monkeypatch.setattr(session_module, "build_backend", lambda runtime, context: built.append((runtime, context)) or object())

    session._make_backend(billing_mode="api_credit")
    assert built[0][0] == "claude"
    assert built[0][1].billing_mode == "api_credit"

    session.is_orchestrator = True
    with pytest.raises(ValueError, match="Claude API credits"):
        session._make_backend(billing_mode="api_credit")


def test_api_credit_error_detector_matches_provider_billing_refusal_only():
    from app.claude_api_credits import is_credit_exhaustion_error
    from app.backend_claude import ClaudeBackend
    from claude_agent_sdk.types import ResultMessage

    assert is_credit_exhaustion_error(
        "Your credit balance is too low to access the Anthropic API."
    )
    assert is_credit_exhaustion_error(
        "Credit balance too low · Add funds: https://platform.claude.com/settings/billing"
    )
    assert not is_credit_exhaustion_error("rate limit exceeded")
    assert not is_credit_exhaustion_error("subscription quota is exhausted")
    result = ResultMessage(
        subtype="error_during_execution", duration_ms=1, duration_api_ms=1,
        is_error=True, num_turns=0, session_id="api-credit-session",
        errors=["Your credit balance is too low to access the Anthropic API."],
    )
    api_events = ClaudeBackend(
        model="claude-sonnet-5-5[1m]", cwd="/tmp", billing_mode="api_credit",
    )._convert(result)
    subscription_events = ClaudeBackend(
        model="claude-sonnet-5-5[1m]", cwd="/tmp", billing_mode="subscription",
    )._convert(result)
    assert api_events[-1].metadata["api_credit_exhausted"] is True
    assert subscription_events[-1].metadata["api_credit_exhausted"] is False


@pytest.mark.asyncio
async def test_usage_analytics_exposes_credit_status_only_in_owner_mode(monkeypatch):
    from app import limit_wake
    import app.routes.system as system
    import app.usage_analytics as analytics

    monkeypatch.setattr(system, "get_usage", AsyncMock(return_value={}))
    monkeypatch.setattr(analytics, "build_usage_analytics", lambda **_: {})
    monkeypatch.setattr(system, "build_quota_map", AsyncMock(return_value={"data_available": False}))
    monkeypatch.setattr(system, "is_owner_mode", lambda: False)
    monkeypatch.setattr(limit_wake, "wake_status", lambda: {})
    hidden = await system.usage_analytics_endpoint()
    assert hidden["claude_api_credits"]["reason"] == "owner_mode_only"
    assert hidden["claude_api_credits"]["remaining_usd"] is None

    from app import claude_api_credits

    monkeypatch.setattr(system, "is_owner_mode", lambda: True)
    monkeypatch.setattr(claude_api_credits, "credit_status", lambda: {
        "available": True, "remaining_usd": 1.25, "expires_at": "2026-11-04T00:00:00+00:00",
    })
    visible = await system.usage_analytics_endpoint()
    assert visible["claude_api_credits"]["remaining_usd"] == 1.25
    assert visible["claude_api_credits"]["expires_at"] == "2026-11-04T00:00:00+00:00"
