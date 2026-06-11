"""P4 regression contract: CostTracker extraction must not change a single number.

Written against the PRE-split delta-based logic; must stay green after the move.
"""

from datetime import datetime, timezone

import pytest


@pytest.fixture
def session(monkeypatch):
    from unittest.mock import MagicMock
    monkeypatch.setattr("app.session.save_session", MagicMock())
    monkeypatch.setattr("app.session.add_log", MagicMock(return_value=1))
    from app.session import AgentSession
    return AgentSession(
        id="cost-001", name="w1", scope="/test", cwd="/tmp",
        model="claude-sonnet-4-6", created_at=datetime.now(timezone.utc),
    )


def _apply(session, meta):
    # post-split the method lives on CostTracker; pre-split on the session
    if hasattr(session, "_cost"):
        return session._cost.apply_turn_result(meta)
    return session._apply_turn_result(meta)


def _update_ctx(session, meta):
    if hasattr(session, "_cost"):
        return session._cost.update_context_from_turn(meta)
    return session._update_context_from_turn(meta)


def test_delta_cost_accumulates(session):
    ok, sr, nt = _apply(session, {"ok": True, "stop_reason": "end_turn", "num_turns": 2,
                                  "cost_usd": 0.10, "session_id": "s1",
                                  "input_tokens": 100, "output_tokens": 50})
    assert (ok, sr, nt) == (True, "end_turn", 2)
    assert session.cost_usd == pytest.approx(0.10)
    assert session._turn_cost == pytest.approx(0.10)

    _apply(session, {"ok": True, "stop_reason": "end_turn", "num_turns": 1,
                     "cost_usd": 0.25, "session_id": "s1"})
    # cumulative 0.25 → delta 0.15
    assert session.cost_usd == pytest.approx(0.25)
    assert session._turn_cost == pytest.approx(0.15)
    assert session.total_turns == 3
    assert session.total_input_tokens == 100
    assert session.total_output_tokens == 50


def test_session_id_change_resets_baseline(session):
    _apply(session, {"ok": True, "stop_reason": "end_turn", "num_turns": 1,
                     "cost_usd": 0.20, "session_id": "s1"})
    # new session_id (after compact) → SDK cost counter restarts from 0
    _apply(session, {"ok": True, "stop_reason": "end_turn", "num_turns": 1,
                     "cost_usd": 0.05, "session_id": "s2"})
    assert session.session_id == "s2"
    assert session.cost_usd == pytest.approx(0.25)  # 0.20 + 0.05 (not negative delta)
    assert session._context_cost == pytest.approx(0.05)  # reset on new sid


def test_negative_delta_clamped(session):
    _apply(session, {"ok": True, "stop_reason": "end_turn", "num_turns": 1,
                     "cost_usd": 0.30, "session_id": "s1"})
    _apply(session, {"ok": True, "stop_reason": "end_turn", "num_turns": 1,
                     "cost_usd": 0.10, "session_id": "s1"})  # cumulative went DOWN (SDK quirk)
    assert session.cost_usd == pytest.approx(0.30)  # max(0, delta)


def test_cached_cost_tracked_separately(session):
    _apply(session, {"ok": True, "stop_reason": "end_turn", "num_turns": 1,
                     "cost_usd": 0.10, "cost_usd_cached": 0.04, "session_id": "s1"})
    _apply(session, {"ok": True, "stop_reason": "end_turn", "num_turns": 1,
                     "cost_usd": 0.20, "cost_usd_cached": 0.09, "session_id": "s1"})
    assert session.cost_usd_cached == pytest.approx(0.09)


def test_failed_turn_flags(session):
    ok, sr, nt = _apply(session, {"ok": False, "stop_reason": "error", "num_turns": 0,
                                  "errors": ["boom"], "session_id": "s1"})
    assert ok is False
    assert session._last_turn_ok is False
    assert session._last_stop_reason == "error"


def test_context_update(session):
    _update_ctx(session, {"context_pct": 42, "context_tokens": 84000,
                          "max_tokens": 200000, "cache_hit": 1,
                          "cache_read": 1000, "cache_create": 50})
    assert session._last_context["percentage"] == 42
    assert session._last_context["total_tokens"] == 84000
    assert session._last_context["max_tokens"] == 200000
    assert session._last_context["cache_hit"] == 1


def test_context_zero_pct_keeps_previous(session):
    _update_ctx(session, {"context_pct": 42, "context_tokens": 84000})
    _update_ctx(session, {"context_pct": 0, "context_tokens": 0})
    # zero pct means "no data this turn" — previous percentage survives
    assert session._last_context["percentage"] == 42
