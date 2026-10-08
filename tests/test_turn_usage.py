import sqlite3
import time
from datetime import datetime, timezone

import pytest


@pytest.fixture
def usage_db(tmp_path, monkeypatch):
    db_path = tmp_path / "turn-usage.db"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    from app.db import init_db

    init_db()
    return db_path


def test_turn_usage_requires_durable_event_id_and_deduplicates(usage_db):
    from app.db import _conn, turn_usage_add

    common = {
        "session_id": "session-1",
        "runtime": "claude",
        "model": "claude-opus-5[1m]",
        "ok": True,
        "stop_reason": "end_turn",
        "cost_usd": 1.25,
        "input_tokens": 100,
        "output_tokens": 20,
        "cache_read_tokens": 80,
        "cache_create_tokens": 5,
        "quota_five_hour_pct": 12.3456789,
        "quota_seven_day_pct": 41,
        "quota_primary_pct": None,
        "quota_sampled_at": "2026-07-29T08:00:00+00:00",
        "turn_duration_ms": 120_000,
        "api_duration_ms": 10_000,
        "reasoning_tokens": 45,
    }

    assert turn_usage_add(event_id="", **common) is False
    assert turn_usage_add(event_id="result-uuid-1", **common) is True
    assert turn_usage_add(
        event_id="result-uuid-1",
        **{**common, "cost_usd": 99.0},
    ) is False

    with _conn() as conn:
        rows = conn.execute("SELECT * FROM turn_usage").fetchall()
    assert len(rows) == 1
    assert rows[0]["event_id"] == "result-uuid-1"
    assert rows[0]["cost_usd"] == 1.25
    assert rows[0]["cache_read_tokens"] == 80
    assert rows[0]["quota_five_hour_pct"] == 12.3456789
    assert rows[0]["quota_seven_day_pct"] == 41
    assert rows[0]["quota_primary_pct"] is None
    assert rows[0]["quota_sampled_at"] == "2026-07-29T08:00:00+00:00"
    assert rows[0]["turn_duration_ms"] == 120_000
    assert rows[0]["api_duration_ms"] == 10_000
    assert rows[0]["reasoning_tokens"] == 45
    assert rows[0]["scope"] == ""
    assert rows[0]["task_id"] == ""


def test_turn_usage_timing_migration_adds_nullable_columns_once(tmp_path, monkeypatch):
    from app import db

    path = tmp_path / "legacy-turn-usage.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE turn_usage (event_id TEXT PRIMARY KEY, ts TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO turn_usage(event_id, ts) VALUES ('old-turn', '2026-10-01T00:00:00+00:00')"
        )

    assert db.ensure_turn_usage_timing_schema() == 11
    assert db.ensure_turn_usage_timing_schema() == 0
    with db._conn() as conn:
        row = conn.execute("SELECT * FROM turn_usage WHERE event_id='old-turn'").fetchone()
    assert row["turn_duration_ms"] is None
    assert row["api_duration_ms"] is None
    assert row["reasoning_tokens"] is None
    assert row["billing_mode"] == "subscription"


def test_turn_usage_timing_migration_is_a_noop_before_table_creation(tmp_path, monkeypatch):
    from app import db

    path = tmp_path / "not-initialized.db"
    monkeypatch.setattr(db, "DB_PATH", path)

    assert db.ensure_turn_usage_timing_schema() == 0


@pytest.mark.parametrize(
    (
        "runtime", "model", "turn_duration_ms", "api_duration_ms",
        "reasoning_tokens", "duration_basis", "provider_api_duration_ms",
        "model_estimate_duration_ms", "tool_duration_sum_ms",
        "tool_union_duration_ms", "tool_intervals_count", "tool_intervals_missing",
    ),
    [
        ("claude", "claude-sonnet-5-5", 120_000, 10_000, 45, "api", 10_000, None, None, None, None, None),
        ("codex", "gpt-5.6-sol", 60_000, 20_000, None, "model_estimate", None, 20_000, 100_000, 80_000, 2, 0),
    ],
)
def test_terminal_turn_persists_generation_timing_for_each_runtime(
    usage_db, monkeypatch, runtime, model, turn_duration_ms, api_duration_ms,
    reasoning_tokens, duration_basis, provider_api_duration_ms,
    model_estimate_duration_ms, tool_duration_sum_ms, tool_union_duration_ms,
    tool_intervals_count, tool_intervals_missing,
):
    import app.session_turns as session_turns
    from app.db import _conn
    from app.events import AgentEvent
    from app.session import AgentSession

    monkeypatch.setattr("app.bg_jobs.bg_manager", None)
    monkeypatch.setattr(
        session_turns,
        "_cached_quota_snapshot",
        lambda *_args, **_kwargs: {
            "state": {
                "quota_five_hour_pct": None,
                "quota_seven_day_pct": None,
                "quota_primary_pct": None,
                "quota_sampled_at": None,
            },
            "display": (),
        },
    )
    session = AgentSession(
        id=f"timing-{runtime}",
        name=f"timing-{runtime}",
        scope="/test",
        cwd="/tmp",
        model=model,
        backend_type=runtime,
    )
    session._log = lambda *_args, **_kwargs: None
    session._persist = lambda: None
    session._spawn_bg = lambda coro: coro.close()
    session._hibernate.schedule = lambda: None
    session._submit_db_write = lambda operation, *args, **kwargs: operation(*args, **kwargs)
    event = AgentEvent("turn_end", "", metadata={
        "event_id": f"timing-event-{runtime}",
        "session_id": "provider-native-session",
        "ok": True,
        "stop_reason": "end_turn",
        "cost_usd": 0.0,
        "input_tokens": 100,
        "output_tokens": 500,
        "cache_read": 0,
        "cache_create": 0,
        "turn_duration_ms": turn_duration_ms,
        "api_duration_ms": api_duration_ms,
        "reasoning_tokens": reasoning_tokens,
        "duration_basis": duration_basis,
        "provider_api_duration_ms": provider_api_duration_ms,
        "model_estimate_duration_ms": model_estimate_duration_ms,
        "tool_duration_sum_ms": tool_duration_sum_ms,
        "tool_union_duration_ms": tool_union_duration_ms,
        "tool_intervals_count": tool_intervals_count,
        "tool_intervals_missing": tool_intervals_missing,
    })

    session._turns.handle_turn_end(event)

    with _conn() as conn:
        row = conn.execute(
            "SELECT runtime, turn_duration_ms, api_duration_ms, reasoning_tokens, "
            "duration_basis, provider_api_duration_ms, model_estimate_duration_ms, "
            "tool_duration_sum_ms, tool_union_duration_ms, tool_intervals_count, "
            "tool_intervals_missing "
            "FROM turn_usage WHERE event_id=?",
            (f"timing-event-{runtime}",),
        ).fetchone()
    assert tuple(row) == (
        runtime, turn_duration_ms, api_duration_ms, reasoning_tokens, duration_basis,
        provider_api_duration_ms, model_estimate_duration_ms, tool_duration_sum_ms,
        tool_union_duration_ms, tool_intervals_count, tool_intervals_missing,
    )


def test_cached_quota_state_selects_fresh_runtime_window(monkeypatch):
    from app.routes import system
    from app.session_turns import _cached_quota_state

    sampled_ts = 1785312000.0
    sampled_at = datetime.fromtimestamp(sampled_ts, timezone.utc).isoformat()
    monkeypatch.setattr(system, "_usage_cache", {
        "data": {
            "five_hour": {"utilization": 12.5},
            "seven_day": {"utilization": 41},
        },
        "ts": sampled_ts,
        "token": None,
    })
    monkeypatch.setattr(system, "_codex_usage_cache", {
        "data": {
            "primary": {"utilization": 63},
            "spark": {"primary": {"utilization": 9}},
        },
        "ts": sampled_ts,
    })
    monkeypatch.setattr(system, "_grok_usage_cache", {
        "data": {"primary": {"utilization": 27}},
        "ts": sampled_ts,
    })

    assert _cached_quota_state(
        "claude", "claude-opus-5[1m]", now=sampled_ts + 30,
    ) == {
        "quota_five_hour_pct": 12.5,
        "quota_seven_day_pct": 41,
        "quota_primary_pct": None,
        "quota_sampled_at": sampled_at,
    }
    assert _cached_quota_state(
        "codex", "gpt-5.6-sol", now=sampled_ts + 30,
    )["quota_primary_pct"] == 63
    assert _cached_quota_state(
        "codex", "gpt-5.3-codex-spark", now=sampled_ts + 30,
    )["quota_primary_pct"] == 9
    assert _cached_quota_state(
        "grok", "grok-4.5", now=sampled_ts + 30,
    )["quota_primary_pct"] == 27


@pytest.mark.parametrize("cache_data,cache_ts", [
    (None, time.time()),
    ({"primary": {"utilization": 88}}, time.time() - 301),
])
def test_cached_quota_state_returns_null_without_fresh_data(
    usage_db, monkeypatch, cache_data, cache_ts,
):
    from app.routes import system
    from app.db import _conn, turn_usage_add
    from app.session_turns import _cached_quota_state

    monkeypatch.setattr(system, "_codex_usage_cache", {
        "data": cache_data,
        "ts": cache_ts,
    })

    quota_state = _cached_quota_state("codex", "gpt-5.6-sol")
    assert quota_state == {
        "quota_five_hour_pct": None,
        "quota_seven_day_pct": None,
        "quota_primary_pct": None,
        "quota_sampled_at": None,
    }
    assert turn_usage_add(
        event_id="turn-without-quota",
        session_id="session-1",
        runtime="codex",
        model="gpt-5.6-sol",
        ok=True,
        stop_reason="end_turn",
        cost_usd=0.1,
        input_tokens=10,
        output_tokens=2,
        cache_read_tokens=5,
        cache_create_tokens=0,
        **quota_state,
    )
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM turn_usage WHERE event_id = 'turn-without-quota'"
        ).fetchone()
    assert row["quota_five_hour_pct"] is None
    assert row["quota_seven_day_pct"] is None
    assert row["quota_primary_pct"] is None
    assert row["quota_sampled_at"] is None




def test_turn_usage_records_collection_start_without_claiming_history(usage_db):
    from app.db import turn_usage_add
    from app.usage_analytics import build_usage_analytics

    observed_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    turn_usage_add(
        event_id="turn-1",
        session_id="session-1",
        runtime="codex",
        model="gpt-5.6-sol",
        ok=False,
        stop_reason="error",
        cost_usd=0.5,
        input_tokens=40,
        output_tokens=10,
        cache_read_tokens=20,
        cache_create_tokens=0,
        ts=observed_at,
    )

    telemetry = build_usage_analytics(days=7)["reliability"]["turn_usage"]

    assert telemetry["collector_ready"] is True
    assert telemetry["recorded_rows"] == 1
    assert telemetry["observed_from"] == observed_at
    assert telemetry["historical_rows_unknown"] is True
