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
        model="claude-sonnet-5[1m]", created_at=datetime.now(timezone.utc),
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


def test_delta_cost_is_added_directly_across_resume(session):
    _apply(session, {"ok": True, "stop_reason": "end_turn", "num_turns": 1,
                     "cost_usd": 0.10, "cost_usd_cached": 0.10,
                     "cost_is_delta": True, "session_id": "s1"})
    _apply(session, {"ok": True, "stop_reason": "end_turn", "num_turns": 1,
                     "cost_usd": 0.03, "cost_usd_cached": 0.03,
                     "cost_is_delta": True, "session_id": "s1"})
    assert session.cost_usd == pytest.approx(0.13)
    assert session._turn_cost == pytest.approx(0.03)


def test_provider_baseline_survives_process_restart(session, tmp_path, monkeypatch):
    """A resumed native session subtracts its persisted provider total."""
    from app import db as dbmod
    from app.manager import SessionManager

    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "restart.db")
    dbmod.init_db()
    _apply(session, {
        "ok": True, "stop_reason": "end_turn", "num_turns": 1,
        "cost_usd": 0.15, "session_id": "native-sid",
    })
    dbmod.save_session(session._to_db_dict())

    resumed = SessionManager._hydrate_row(dbmod.get_session(session.id))
    _apply(resumed, {
        "ok": True, "stop_reason": "end_turn", "num_turns": 1,
        "cost_usd": 0.17, "session_id": "native-sid",
    })
    assert resumed._turn_cost == pytest.approx(0.02)
    assert resumed.cost_usd == pytest.approx(0.17)


def test_terminal_usage_keeps_baseline_and_usage_row_atomic(session, tmp_path, monkeypatch):
    from app import db as dbmod

    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "atomic.db")
    dbmod.init_db()
    session.session_id = "native-sid"
    session._last_cost = 0.15
    dbmod.save_session(session._to_db_dict())

    assert dbmod.turn_usage_add(
        event_id="turn-atomic", session_id=session.id, runtime="claude",
        model=session.model, ok=True, stop_reason="end_turn", cost_usd=0.02,
        input_tokens=1, output_tokens=1, cache_read_tokens=0,
        cache_create_tokens=0, native_session_id="native-sid",
        provider_cost_usd=0.17,
    )
    row = dbmod.get_session(session.id)
    assert row["provider_cost_baseline_usd"] == pytest.approx(0.17)


def test_persisted_baseline_after_missing_usage_row_is_bounded(session, tmp_path, monkeypatch):
    """Losing only the usage projection must not charge the prior cumulative total again."""
    from app import db as dbmod
    from app.manager import SessionManager

    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "missing-row.db")
    dbmod.init_db()
    _apply(session, {
        "ok": True, "stop_reason": "end_turn", "num_turns": 1,
        "cost_usd": 0.15, "session_id": "native-sid",
    })
    dbmod.save_session(session._to_db_dict())

    resumed = SessionManager._hydrate_row(dbmod.get_session(session.id))
    _apply(resumed, {
        "ok": True, "stop_reason": "end_turn", "num_turns": 1,
        "cost_usd": 0.16, "session_id": "native-sid",
    })
    assert resumed._turn_cost == pytest.approx(0.01)
    assert resumed._turn_cost >= 0


def test_context_update(session):
    _update_ctx(session, {"context_known": True,
                          "context_pct": 42, "context_tokens": 84000,
                          "max_tokens": 200000, "cache_hit": 1,
                          "cache_read": 1000, "cache_create": 50})
    assert session._last_context["percentage"] == 42
    assert session._last_context["total_tokens"] == 84000
    assert session._last_context["max_tokens"] == 200000
    assert session._last_context["cache_hit"] == 1


def test_explicit_unknown_context_clears_previous(session):
    _update_ctx(session, {"context_known": True, "context_pct": 42,
                          "context_tokens": 84000, "max_tokens": 200000})
    known, reason = _update_ctx(session, {
        "context_known": False,
        "context_pct": 0,
        "context_tokens": 0,
        "max_tokens": 200000,
        "context_unknown_reason": "missing current context",
    })

    assert known is False
    assert reason == "missing current context"
    assert session._last_context["percentage"] == 0
    assert session._last_context["known"] is False
