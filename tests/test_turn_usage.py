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
    assert rows[0]["scope"] == ""
    assert rows[0]["task_id"] == ""


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
