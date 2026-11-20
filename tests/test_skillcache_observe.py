from datetime import datetime, timezone
import json

import pytest

from app import db
from app.skillcache.observe import TraceProjection, observe


@pytest.fixture
def journal(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "private.db")
    db.init_db()
    with db._conn() as conn:
        conn.execute(
            "INSERT INTO sessions(id,name,scope,cwd,model,created_at) VALUES (?,?,?,?,?,?)",
            ("s", "test", "scope", str(tmp_path), "fixture", datetime.now(timezone.utc).isoformat()),
        )


def log(invocation, seq, kind, *, tool_id="same-provider-id"):
    raw = {"window": "confidential-window"}
    return db.add_log("s", datetime.now(timezone.utc), kind,
                      json.dumps({"count": 1}) if kind == "tool_result" else "private display text",
                      tool_use_id=tool_id, tool_name="read_calendar", tool_is_error=False,
                      tool_raw_input=raw, invocation_id=invocation, invocation_seq=seq)


def end(invocation, events, reason=None, ok=True):
    db.turn_usage_add(event_id=f"provider-{invocation}", session_id="s",
                      runtime="codex", model="test", ok=ok, stop_reason="end_turn", cost_usd=None,
                      input_tokens=10, output_tokens=1, cache_read_tokens=0, cache_create_tokens=0,
                      invocation_id=invocation, invocation_events=events, invocation_exclusion=reason)


def trace(invocation, record=False):
    return observe(invocation, skill="calendar", request_shape={"window": "another private value"},
                   projections={"read_calendar": TraceProjection(frozenset({"window"}), frozenset({"count"}))},
                   success=lambda _: True, record=record)


def test_linkage_is_independent_of_provider_id_and_db_write_order(journal):
    log("steered", 1, "tool")
    log("clean", 2, "tool_result")
    log("steered", 2, "tool_result")
    end("steered", 2, "steered")
    end("clean", 2)
    assert trace("clean")["eligible"] is False
    log("clean", 1, "tool")
    clean = trace("clean", record=True)
    assert clean["eligible"]
    assert clean["usage_ref"] == "provider-clean"
    assert len(clean["actions"]) == 1
    assert "confidential" not in str(clean) and "private" not in str(clean)
    assert trace("steered") == {"eligible": False, "reason": "steered"}
    with db._conn() as conn:
        assert tuple(conn.execute("SELECT id, usage_ref, eligible FROM sc_invocation").fetchone()) == (
            "clean", "provider-clean", 1,
        )
        assert conn.execute("SELECT COUNT(*) FROM sc_event WHERE invocation_id='clean'").fetchone()[0] == 2


def test_missing_result_and_overlapping_calls_fail_closed(journal):
    end("unpaired", 1)
    log("unpaired", 1, "tool")
    assert not trace("unpaired")["eligible"]
    end("overlap", 4)
    log("overlap", 1, "tool", tool_id="a")
    log("overlap", 2, "tool", tool_id="b")
    log("overlap", 3, "tool_result", tool_id="a")
    log("overlap", 4, "tool_result", tool_id="b")
    assert not trace("overlap")["eligible"]

