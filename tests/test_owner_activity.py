import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.owner_activity import (
    Interval,
    allocate_intervals,
    group_sessions,
    presence_intervals,
    split_local_days,
)


UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]


def _at(base, seconds):
    return base + timedelta(seconds=seconds)


def _presence(event_id, token, event_type, scope, at, *, visible=True, focused=True):
    return {
        "event_id": event_id,
        "tab_token": token,
        "event_type": event_type,
        "scope": scope,
        "ts": at.isoformat(),
        "visible": visible,
        "focused": focused,
        "last_input_at": at.isoformat(),
    }


def test_input_event_policy_is_idle_transition_or_one_per_minute():
    script = """
const {shouldSendInputEvent} = require('./app/static/js/owner-activity-policy.js');
const checks = [
  [50000, 0, 0, false],
  [60000, 0, 0, true],
  [300000, 0, 250000, false],
  [300001, 0, 250000, true],
  [120000, 0, 60000, true],
];
for (const [now, previous, sent, expected] of checks) {
  if (shouldSendInputEvent(now, previous, sent) !== expected) process.exit(1);
}
"""
    result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr or result.stdout


def test_scope_switch_cuts_presence_at_event_second():
    base = datetime(2026, 9, 23, tzinfo=UTC)
    rows = [
        _presence("a", "tab", "focus", "/a", base),
        _presence("b", "tab", "scope", "/b", _at(base, 10)),
        _presence("c", "tab", "ping", "/b", _at(base, 60)),
    ]
    result = presence_intervals(rows, base, _at(base, 120))
    assert [(x.scope, (x.end - x.start).total_seconds()) for x in result] == [
        ("/a", 10), ("/b", 110),
    ]


def test_two_tabs_same_scope_are_union_not_sum():
    base = datetime(2026, 9, 23, tzinfo=UTC)
    rows = [
        _presence("a", "one", "focus", "/same", base),
        _presence("b", "two", "focus", "/same", _at(base, 5)),
    ]
    intervals = presence_intervals(rows, base, _at(base, 20))
    allocated = allocate_intervals(intervals, base, _at(base, 20))
    assert sum((x.end - x.start).total_seconds() for x in allocated) == 20


def test_overlapping_scopes_are_allocated_once_and_sum_to_union():
    base = datetime(2026, 9, 23, tzinfo=UTC)
    allocated = allocate_intervals([
        Interval(base, _at(base, 10), "/a", "presence", event_ts=base),
        Interval(_at(base, 5), _at(base, 15), "/b", "presence", event_ts=_at(base, 5)),
    ], base, _at(base, 20))
    assert sum((x.end - x.start).total_seconds() for x in allocated) == 15
    assert sum((x.end - x.start).total_seconds() for x in allocated if x.scope == "/a") == 5
    assert sum((x.end - x.start).total_seconds() for x in allocated if x.scope == "/b") == 10


def test_duplicate_presence_event_id_does_not_change_total(tmp_path, monkeypatch):
    from app import db
    from app.routes.owner_activity import PresenceEventRequest, activity_result, record_event

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "activity.db")
    db.init_db()
    base = datetime(2026, 9, 23, tzinfo=UTC)
    request = PresenceEventRequest(
        event_id="duplicate-event", tab_token="tab-token", event_type="focus",
        scope="/a", ts=base, visible=True, focused=True, last_input_at=base,
    )
    record_event(request)
    first = activity_result(base, _at(base, 60))
    assert record_event(request)["duplicate"] is True
    second = activity_result(base, _at(base, 60))
    assert first["seconds"] == second["seconds"] == 60


def test_krasnoyarsk_midnight_splits_session():
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Asia/Krasnoyarsk")
    start = datetime(2026, 9, 22, 16, 59, tzinfo=UTC)
    end = datetime(2026, 9, 22, 17, 1, tzinfo=UTC)
    chunks = split_local_days([Interval(start, end, "/a", "presence")], tz, start, end)
    sessions = group_sessions(chunks, tz=tz)
    assert [(row["day"], round(row["duration_sec"])) for row in sessions] == [
        ("2026-09-22", 60), ("2026-09-23", 60),
    ]


def test_backfill_accepts_only_owner_orchestrator_messages(tmp_path, monkeypatch):
    from app import db
    from app.events import MessageProvenance

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "activity.db")
    db.init_db()
    with db._conn() as connection:
        for sid, name, orchestrator in (("orch", "orch", 1), ("worker", "worker", 0), ("foreign", "foreign", 1)):
            connection.execute(
                """INSERT INTO sessions (id,name,scope,cwd,model,is_orchestrator,created_at)
                   VALUES (?,?,?,?,?,?,?)""",
                (sid, name, "/scope", "/scope", "test", orchestrator,
                 datetime.now(UTC).isoformat()),
            )
    ts = datetime(2026, 9, 23, tzinfo=UTC)
    db.add_log("orch", ts, "user_message", "owner", provenance=MessageProvenance("user", ("user",), "dashboard"))
    db.add_log("worker", ts, "user_message", "worker", provenance=MessageProvenance("user", ("user",), "dashboard"))
    db.add_log("foreign", ts, "user_message", "unknown", provenance=MessageProvenance("unknown", ("unknown",), "dashboard"))
    with db._conn() as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(owner_activity_events)")}
        rows = connection.execute("SELECT session_id FROM owner_activity_events").fetchall()
        metadata = connection.execute(
            "SELECT content_length, voice_duration_sec, source FROM owner_activity_events"
        ).fetchone()
    assert "content" not in columns
    assert [row[0] for row in rows] == ["orch"]
    assert metadata[0] == len("owner") and metadata[2] == "message"
