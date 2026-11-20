from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import acp_mux, backend_antigravity, db, limits_card, models, provider_safety, quota_gate, session_turns
from app.backend_antigravity import AntigravityBackend, estimate_antigravity_turn_usage
from app.events import AgentEvent, InjectedMessage, MessageProvenance
from app.runtime_registry import BackendBuildContext
from app.session import AgentSession
from app.tg_bridge import _format_limits_message_for_chat
from app.usage_analytics import daily_usage


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "wave14.db")
    db.init_db()
    monkeypatch.setattr(models, "is_provider_disabled", lambda _: False)
    provider_safety.clear_antigravity_cooldown()
    return tmp_path / "wave14.db"


def test_parse_and_persist_antigravity_cooldown(isolated_db):
    base = 1_763_622_420.0
    matched, until_ts, reset_s = provider_safety.parse_antigravity_quota_cooldown(
        "⚠ Individual quota reached. Please upgrade your subscription. Resets in 1h56m11s",
        now=base,
    )
    assert matched is True
    assert reset_s == 3600 + 56 * 60 + 11
    assert until_ts == base + reset_s + 90

    m2, u2, r2 = provider_safety.parse_antigravity_quota_cooldown("429 RESOURCE_EXHAUSTED", now=base)
    assert m2 is True and r2 == 1800 and u2 == base + 1890

    assert provider_safety.parse_antigravity_quota_cooldown("ordinary network glitch", now=base) == (False, None, None)

    info = provider_safety.trip_antigravity_cooldown("Individual quota reached. Resets in 1h00m00s", now=base)
    assert info["active"] is True
    assert "⛔ Antigravity 5h лимит исчерпан — антибан-стоп до " in info["message"]
    assert "КРС (переключите на gpt-6.2-sol)" in info["message"]
    loaded = provider_safety.get_antigravity_cooldown(now=base + 10)
    assert loaded is not None and loaded["until"] == info["until"]
    assert provider_safety.get_antigravity_cooldown(now=info["until"] + 1) is None


def test_quota_gate_blocks_antigravity_during_cooldown(isolated_db):
    now = 1_763_622_420.0
    provider_safety.trip_antigravity_cooldown("Individual quota reached. Resets in 30m", now=now)
    decision = quota_gate.evaluate_worker_admission(
        "antigravity/gemini-4-hydrogen-high",
        {"antigravity_gemini": {"label": "Antigravity Gemini", "seven_day": {"utilization": 50.0}}},
        {"antigravity_gemini": now},
        now=now + 5,
    )
    assert decision.state == "blocked"
    assert decision.reason_key == "antigravity_cooldown"
    assert "антибан-стоп" in decision.reason
    assert decision.alternatives == ({"provider": "codex", "model": "gpt-6.2-sol"},)


@pytest.mark.asyncio
async def test_antigravity_cooldown_blocks_send_and_mux_with_zero_google_calls(isolated_db, monkeypatch, tmp_path):
    now = time.time()
    provider_safety.trip_antigravity_cooldown("Individual quota reached. Resets in 45m", now=now)
    monkeypatch.setattr(backend_antigravity, "canonical_profile", lambda _="": tmp_path)

    ctx = BackendBuildContext(
        model="antigravity/gemini-4-hydrogen-high",
        provider="google-antigravity",
        cwd=str(tmp_path),
        system_prompt="",
        resume_session_id=None,
        mcp_servers={},
        is_orchestrator=False,
        scope=str(tmp_path),
        pipeline="default",
        role="worker",
        profile="",
        effort="high",
        context_limit=1_000_000,
    )
    backend = AntigravityBackend(ctx)
    egress_mock = AsyncMock(side_effect=AssertionError("must not check egress during cooldown"))
    monkeypatch.setattr(provider_safety, "verify_provider_egress", egress_mock)

    with pytest.raises(Exception, match="антибан-стоп"):
        await backend.send(InjectedMessage("hello", MessageProvenance("user", ("owner",)), "evt-1"))
    egress_mock.assert_not_awaited()

    with pytest.raises(Exception, match="антибан-стоп"):
        await acp_mux._check_quota()


def test_quota_cooldown_event_stops_session_without_retries(isolated_db, monkeypatch, tmp_path):
    from app.antigravity_acp import AcpQuotaCooldownError

    provider_safety.clear_antigravity_cooldown()
    s = AgentSession(
        id="s-agy-test",
        name="agy-test",
        scope=str(tmp_path),
        cwd=str(tmp_path),
        model="antigravity/gemini-4-neon-medium",
        backend_type="antigravity",
        role="orchestrator",
    )
    logs = []
    s._log = lambda kind, content, **kw: logs.append((kind, content))

    retry_mock = AsyncMock(side_effect=AssertionError("must not retry Antigravity quota cooldown"))
    monkeypatch.setattr(s, "_rate_limit_retry", retry_mock)

    s._rate_limit_retries = 0
    s._handle_event(
        AgentEvent(
            "error",
            "⛔ Antigravity 5h лимит исчерпан — антибан-стоп до 16:04 КРС (переключите на gpt-6.2-sol)",
            metadata={"antigravity_quota_cooldown": True, "cooldown_until": time.time() + 600},
        )
    )
    assert s._session_limit_hit is True
    assert s._rate_limit_retries == s.RATE_LIMIT_MAX_RETRIES
    retry_mock.assert_not_awaited()
    assert any("антибан-стоп" in msg for kind, msg in logs if kind == "error")

    err = AcpQuotaCooldownError(-32000, message="⛔ test", until_ts=time.time() + 100, reset_seconds=100)
    assert str(err) == "⛔ test"


def test_models_ban_xhigh_and_enforce_neon_orchestrator_only(isolated_db):
    assert models.resolve_model("agy-neon") == "antigravity/gemini-4-neon-medium"
    for retired in (
        "agy-neon-xhigh",
        "agy-hydrogen-xhigh",
        "antigravity/gemini-4-neon-xhigh",
        "antigravity/gemini-4-hydrogen-xhigh",
    ):
        with pytest.raises(ValueError, match="retired"):
            models._ensure_model_not_retired(retired)
        with pytest.raises(ValueError, match="retired"):
            models.ensure_spawn_allowed(retired, role="orchestrator", scope="/private/p")
        with pytest.raises(ValueError, match="retired"):
            models.ensure_dashboard_visible(retired)
    assert not acp_mux.MODEL.fullmatch("gemini-4-neon-xhigh")
    assert not acp_mux.MODEL.fullmatch("gemini-4-hydrogen-xhigh")

    models.ensure_spawn_allowed("antigravity/gemini-4-neon-medium", role="orchestrator", scope="/private/p")
    for non_orch in ("worker", "implementer", "full-cycle", ""):
        with pytest.raises(ValueError, match="orchestrator"):
            models.ensure_spawn_allowed("antigravity/gemini-4-neon-medium", role=non_orch, scope="/private/p")


def test_limits_command_includes_antigravity_within_telegram_caption_limit(isolated_db):
    now = datetime(2026, 11, 20, 7, 15, tzinfo=timezone.utc)
    iso = lambda mins: (now + timedelta(minutes=mins)).isoformat().replace("+00:00", "Z")
    usage = {
        "anthropic": {
            "five_hour": {"utilization": 42, "window_minutes": 300, "resets_at": iso(120)},
            "seven_day": {"utilization": 65, "window_minutes": 10080, "resets_at": iso(3000)},
        },
        "codex": {
            "primary": {"utilization": 15, "window_minutes": 300, "resets_at": iso(200)},
            "secondary": {"utilization": 33, "window_minutes": 10080, "resets_at": iso(5000)},
            "spark": {"primary": {"utilization": 10, "window_minutes": 300, "resets_at": iso(180)}},
        },
        "grok": {"primary": {"utilization": 5, "resets_at": iso(60)}},
        "quota_headroom": {"windows_left": 1.85, "rate": 0.12, "available_pct": 35.0, "locked_pct": 10.0},
        "antigravity_5h": {"gemini-5h": {"utilization": 94.5, "resets_at": iso(116)}},
        "antigravity": {
            "gemini-weekly": {"utilization": 71.85, "resets_at": iso(4000)},
            "gemini-argon-wtu-weekly": {"utilization": 8.0, "resets_at": iso(4000)},
            "3p-weekly": {"utilization": 0.0, "resets_at": iso(4000)},
        },
        "antigravity_gate": {
            "antigravity_gemini": {"state": "blocked"},
            "antigravity_argon": {"state": "available"},
            "antigravity_3p": {"state": "available"},
        },
        "antigravity_cooldown": {"until_krs": "16:13"},
    }
    text = _format_limits_message_for_chat(usage, now=now)
    assert len(text) <= 1024, f"Caption too long: {len(text)}"
    assert "Antigravity Gemini 5h" in text
    assert "Antigravity Gemini 7d" in text
    assert "Antigravity Argon 7d" in text
    assert "Claude/3P 7d" in text
    assert "cooldown до 16:13 КРС" in text
    card = limits_card.collect(usage, now=now)
    labels = [p["label"] for p in card["pools"]]
    assert "Agy Gemini · 5 часов" in labels
    assert "Agy Gemini · неделя" in labels


def test_antigravity_180k_compact_threshold(isolated_db, tmp_path):
    assert session_turns.ANTIGRAVITY_AUTO_COMPACT_TOKENS == 180_000
    s = AgentSession(
        id="s-agy-180k",
        name="agy-180k",
        scope=str(tmp_path),
        cwd=str(tmp_path),
        model="antigravity/gemini-4-neon-medium",
        backend_type="antigravity",
        role="orchestrator",
    )
    s._last_context["max_tokens"] = 1_000_000
    assert session_turns._auto_compact_threshold_pct(s) == 18
    s._last_context["total_tokens"] = 180_000
    logs = []
    s._log = lambda kind, msg, **kw: logs.append((kind, msg))
    s._turns.schedule_context_compaction(18)
    assert logs and "180,000" in logs[0][1] and "disabled by runtime policy" in logs[0][1]


def test_estimated_usage_and_db_accounting(isolated_db):
    base = 10_000.0
    cold = estimate_antigravity_turn_usage(
        "gemini-4-neon-medium",
        context_tokens=100_000,
        tool_calls=2,
        output_chars=800,
        thinking_chars=400,
        last_turn_at=base - 3600,
        now=base,
        quota_delta_pct=0.45,
    )
    assert cold["warm"] is False
    assert cold["api_calls"] == 3
    assert cold["input_tokens"] == 300_000
    assert cold["cache_read_tokens"] == 0
    assert cold["output_tokens"] == 300
    assert cold["cost_usd"] == pytest.approx(0.6036, abs=1e-6)
    assert cold["quota_delta_pct"] == 0.45

    warm = estimate_antigravity_turn_usage(
        "gemini-4-neon-medium",
        context_tokens=100_000,
        tool_calls=1,
        output_chars=400,
        last_turn_at=base - 120,
        now=base,
    )
    assert warm["warm"] is True
    assert warm["input_tokens"] == 0
    assert warm["cache_read_tokens"] == 200_000
    assert warm["cost_usd"] == pytest.approx(0.1012, abs=1e-6)

    db.turn_usage_add(
        event_id="agy-est-1",
        session_id="s-est",
        scope="/private/p",
        task_id="",
        runtime="antigravity",
        model="antigravity/gemini-4-neon-medium",
        billing_mode="subscription",
        ok=True,
        stop_reason="end_turn",
        cost_usd=cold["cost_usd"],
        cost_unaccounted=False,
        input_tokens=cold["input_tokens"],
        output_tokens=cold["output_tokens"],
        cache_read_tokens=cold["cache_read_tokens"],
        cache_create_tokens=0,
        normalized_usage=cold["normalized"],
        quota_seven_day_pct=71.85,
        quota_sampled_at="2026-11-20T07:30:00Z",
    )
    days_list = daily_usage(days=1)
    assert days_list, days_list
    day0 = days_list[-1]
    assert day0["cost_usd"] == pytest.approx(0.6036, abs=1e-4)
    agy_norm = day0["normalized_usage"].get("antigravity")
    assert agy_norm is not None and agy_norm["accuracy"] == "estimated"
    assert agy_norm["fresh_input"] == 300_000 and agy_norm["output"] == 300
