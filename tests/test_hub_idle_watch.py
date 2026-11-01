import datetime as dt

from scripts.hub_idle_watch import (
    _aware_datetime,
    idle_hub_workers,
    render_hub_idle,
    main,
)


def _session(name, model, status="idle", parent_id="orch", role="worker", scope="project-a"):
    return {
        "id": name,
        "name": name,
        "model": model,
        "status": status,
        "parent_id": parent_id,
        "role": role,
        "is_orchestrator": False,
        "scope": scope,
    }


def test_only_hub_workers_strictly_over_24h_idle_are_grouped_by_nearest_orchestrator():
    now = dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc)
    sessions = [
        _session("root", "gpt-6.1-terra", parent_id="", role="orchestrator"),
        _session("sub", "gpt-6-luna", parent_id="root", role="sub-orchestrator"),
        _session("edge", "hub-sol", parent_id="sub"),
        _session("old", "hub-sol", parent_id="root"),
        _session("root-edge", "hub-opus", parent_id="root"),
        _session("other-root", "gpt-6.1-terra", parent_id="", role="orchestrator", scope="project-b"),
        _session("other-edge", "hub-sol", parent_id="other-root", scope="project-b"),
        _session("never-ended", "hub-sol", parent_id="sub"),
        _session("after-wait", "hub-sol", parent_id="root"),
        _session("after-activity", "hub-sol", parent_id="root"),
        _session("after-restart", "hub-sol", parent_id="root"),
        _session("running", "hub-sol", status="running"),
        _session("waiting", "hub-sol", status="waiting"),
        _session("native", "gpt-6-luna"),
        _session("unknown-age", "hub-sol"),
    ]
    def event(age, event_type="status", content="turn ended (completed)"):
        return {
            "ts": (now - age).isoformat(),
            "type": event_type,
            "content": content,
        }

    ended = {
        "edge": [
            event(dt.timedelta(minutes=1440, seconds=1)),
            event(dt.timedelta(hours=1), content="context unknown (reason); compaction skipped"),
            event(dt.timedelta(minutes=30), content="auto-report skipped: explicit report"),
            event(dt.timedelta(minutes=10), content="⏹️ stopped (manual interrupt)"),
        ],
        "old": [event(dt.timedelta(minutes=1440))],
        "root-edge": [event(dt.timedelta(minutes=1440, seconds=1))],
        "other-edge": [event(dt.timedelta(minutes=1440, seconds=1))],
        "never-ended": [
            event(dt.timedelta(minutes=1440, seconds=1), content="⏹️ stopped (manual interrupt)")
        ],
        "after-wait": [
            event(dt.timedelta(days=3)),
            event(dt.timedelta(days=2), content="waiting for bg jobs"),
        ],
        "after-activity": [
            event(dt.timedelta(days=3)),
            event(dt.timedelta(days=2), "user_message", "continued work"),
        ],
        "after-restart": [
            event(dt.timedelta(days=3)),
            event(dt.timedelta(days=2), content="⏹️ stopped (server shutdown)"),
        ],
        "running": [event(dt.timedelta(days=3))],
        "waiting": [event(dt.timedelta(days=3))],
        "native": [event(dt.timedelta(days=3))],
    }
    owners = idle_hub_workers(sessions, ended, now)

    assert owners == {
        "other-root": [("other-edge", _aware_datetime(ended["other-edge"][0]["ts"]))],
        "root": [("root-edge", _aware_datetime(ended["root-edge"][0]["ts"]))],
        "sub": [
            ("edge", _aware_datetime(ended["edge"][0]["ts"])),
            ("never-ended", _aware_datetime(ended["never-ended"][0]["ts"])),
        ],
    }
    assert render_hub_idle(owners, now) == (
        "HUB_IDLE other-root: other-edge (1440.02 min)\n"
        "HUB_IDLE root: root-edge (1440.02 min)\n"
        "HUB_IDLE sub: edge (1440.02 min); never-ended (1440.02 min)"
    )


def test_empty_candidate_set_renders_nothing():
    now = dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc)
    assert render_hub_idle({}, now) == ""


def test_naive_log_timestamp_is_rejected():
    try:
        _aware_datetime("2026-10-31T12:00:00")
    except ValueError as exc:
        assert "no timezone" in str(exc)
    else:
        raise AssertionError("naive timestamps must not be treated as UTC")


def test_empty_orchestra_database_reports_error(tmp_path, monkeypatch, capsys):
    import sqlite3

    path = tmp_path / "empty.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("create table sessions (id, name, status, model, parent_id, role, is_orchestrator)")
        db.execute("create table logs (session_id, ts, type, content)")
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(path))
    monkeypatch.setattr("sys.argv", ["hub_idle_watch.py"])

    assert main() == 2
    assert "HUB_IDLE_ERROR" in capsys.readouterr().err


def test_database_with_empty_sessions_is_an_error(tmp_path, monkeypatch, capsys):
    import sqlite3

    path = tmp_path / "no-sessions.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("create table sessions (id, name, status, model, parent_id, role, is_orchestrator)")
        db.execute("create table logs (session_id, ts, type, content)")
        db.execute("insert into logs values ('orphan', '2026-10-31T00:00:00+00:00', 'status', 'turn ended')")
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(path))
    monkeypatch.setattr("sys.argv", ["hub_idle_watch.py"])

    assert main() == 2
    assert "HUB_IDLE_ERROR" in capsys.readouterr().err
