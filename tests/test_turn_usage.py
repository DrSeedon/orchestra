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
        "quota_five_hour_pct": 12.5,
        "quota_seven_day_pct": 41,
        "quota_primary_pct": None,
        "quota_sampled_at": "2026-07-29T08:00:00+00:00",
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
    assert rows[0]["quota_five_hour_pct"] == 12.5
    assert rows[0]["quota_seven_day_pct"] == 41
    assert rows[0]["quota_primary_pct"] is None
    assert rows[0]["quota_sampled_at"] == "2026-07-29T08:00:00+00:00"
    assert rows[0]["scope"] == ""
    assert rows[0]["task_id"] == ""


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


def test_runtime_quota_formatting_selects_only_own_windows(monkeypatch):
    from app.routes import system
    from app.session_turns import _cached_quota_snapshot, _format_limits

    sampled_ts = 2_000_000_000.0
    monkeypatch.setattr(system, "_usage_cache", {
        "data": {
            "five_hour": {"utilization": 88},
            "seven_day": {"utilization": 100},
        },
        "ts": sampled_ts,
        "token": None,
    })
    monkeypatch.setattr(system, "_codex_usage_cache", {
        "data": {
            "primary": {"utilization": 33, "window_minutes": 300},
            "secondary": {"utilization": 44, "window_minutes": 10080},
            "spark": {
                "primary": {"utilization": 9, "window_minutes": 300},
                "secondary": {"utilization": 10, "window_minutes": 10080},
            },
        },
        "ts": sampled_ts,
    })

    claude = _format_limits(_cached_quota_snapshot(
        "claude", "claude-opus-5[1m]", now=sampled_ts + 1,
    ), now=sampled_ts + 1)
    codex = _format_limits(_cached_quota_snapshot(
        "codex", "gpt-5.6-sol", now=sampled_ts + 1,
    ), now=sampled_ts + 1)
    spark = _format_limits(_cached_quota_snapshot(
        "codex", "gpt-5.3-codex-spark", now=sampled_ts + 1,
    ), now=sampled_ts + 1)

    assert claude == " | Claude 5h:88% Claude 7d:100%"
    assert codex == " | Codex 5h:33% Codex 7d:44%"
    assert spark == " | Spark 5h:9% Spark 7d:10%"


@pytest.mark.parametrize(
    ("runtime", "model"),
    [
        ("claude", "claude-opus-5[1m]"),
        ("codex", "gpt-5.6-sol"),
        ("codex", "gpt-5.3-codex-spark"),
    ],
)
def test_stale_runtime_cache_has_no_turn_end_quota_suffix(monkeypatch, runtime, model):
    from app.routes import system
    from app.session_turns import _cached_quota_snapshot, _format_limits

    monkeypatch.setattr(system, "_usage_cache", {
        "data": {"five_hour": {"utilization": 88}}, "ts": 1_999_999_699.0,
    })
    monkeypatch.setattr(system, "_codex_usage_cache", {
        "data": {
            "primary": {"utilization": 33},
            "spark": {"primary": {"utilization": 9}},
        },
        "ts": 1_999_999_699.0,
    })

    snapshot = _cached_quota_snapshot(runtime, model, now=2_000_000_000.0)

    assert snapshot["state"]["quota_sampled_at"] is None
    assert _format_limits(snapshot, now=2_000_000_000.0) == ""


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


def test_turn_usage_migrates_existing_rows_with_unknown_quota(tmp_path, monkeypatch):
    db_path = tmp_path / "old-turn-usage.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE turn_usage (
                id INTEGER PRIMARY KEY,
                event_id TEXT NOT NULL UNIQUE,
                ts TEXT NOT NULL,
                session_id TEXT NOT NULL,
                scope TEXT NOT NULL DEFAULT '',
                task_id TEXT NOT NULL DEFAULT '',
                runtime TEXT NOT NULL,
                model TEXT NOT NULL,
                ok INTEGER NOT NULL,
                stop_reason TEXT NOT NULL,
                cost_usd REAL NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                cache_read_tokens INTEGER NOT NULL,
                cache_create_tokens INTEGER NOT NULL
            )
        """)
        conn.execute("""
            INSERT INTO turn_usage
            (event_id, ts, session_id, runtime, model, ok, stop_reason,
             cost_usd, input_tokens, output_tokens,
             cache_read_tokens, cache_create_tokens)
            VALUES ('old-turn', '2026-07-29T08:00:00+00:00', 'session-1',
                    'codex', 'gpt-5.6-sol', 1, 'end_turn', 1, 10, 2, 5, 0)
        """)
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    from app.db import init_db

    init_db()

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        columns = {row[1] for row in conn.execute("PRAGMA table_info(turn_usage)")}
        row = conn.execute(
            "SELECT * FROM turn_usage WHERE event_id = 'old-turn'"
        ).fetchone()
    assert {
        "quota_five_hour_pct",
        "quota_seven_day_pct",
        "quota_primary_pct",
        "quota_sampled_at",
    } <= columns
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
