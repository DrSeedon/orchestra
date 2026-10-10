from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

from app import error_watch as watch


def _event(message, minute=0, source="journalctl", scope=None):
    timestamp = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc) + timedelta(minutes=minute)
    event = {"source": source, "ts": timestamp.isoformat(), "message": message}
    if scope is not None:
        event["scope"] = scope
    return event


def test_normalization_merges_volatile_values_and_logger_prefixes():
    a = "WARNING:app.manager:task sync failed for [katya-work-orchestrator] /home/kesha/worktrees/a 123"
    b = "task sync failed for [other-work-orchestrator] /srv/orchestra/worktrees/b 998"
    assert watch.normalize_signature(a) == watch.normalize_signature(b)
    assert watch.normalize_signature("[designer] listen task exited") == "[SESSION] listen task exited"


def test_distinct_causes_remain_distinct():
    left = watch.normalize_signature("connect failed: FileNotFoundError: no such file")
    right = watch.normalize_signature("native Codex compact failed: FileNotFoundError: no such file")
    assert left != right


def test_normalization_removes_credentials_urls_and_email_addresses():
    message = "request failed https://example.invalid/path?token=longsecretvalue123 user=owner@example.invalid"
    result = watch.normalize_signature(message)
    assert "longsecretvalue123" not in result
    assert "owner@example.invalid" not in result
    assert "<URL>" in result
    assert "<EMAIL>" in result


def test_threshold_and_quota_noise_classification():
    events = [_event("quota rate_limit blocked", i) for i in range(3)]
    events += [_event("database transaction failed: Locked", i) for i in range(2)]
    candidates, noise = watch.aggregate(events, datetime.now(timezone.utc), threshold=3)
    assert candidates == []
    assert noise[0]["count"] == 3
    assert noise[0]["noise"] == "quota/rate limit"
    assert watch.classify_noise(watch.normalize_signature("command exited with code 143")) == "expected command termination"
    assert watch.classify_noise(watch.normalize_signature("Merge operation x: FAILED — DIFF TOO LARGE: 2720 insertions (limit 2000).")) == "merge gate refusal"
    assert watch.classify_noise(watch.normalize_signature("Exit code 1")) == "agent command exit code"
    assert watch.classify_noise(watch.normalize_signature("This app tool requires a non-empty string link_id argument")) == "external app tool argument"
    missing = "File does not exist. Note: your current working directory is /home/kesha/x."
    assert watch.classify_noise(watch.normalize_signature(missing)) == "agent read of missing file"


def test_normal_listener_end_is_noise_but_running_failure_is_actionable():
    idle = "WARNING:app.session:[session-a] listen task exited without exception (silent death), status=AgentStatus.IDLE"
    waiting = "[session-b] listen task exited without exception (silent death), status=AgentStatus.WAITING"
    assert watch.classify_noise(watch.normalize_signature(idle)) == "normal per-turn listener completion"
    assert watch.classify_noise(watch.normalize_signature(waiting)) == "normal per-turn listener completion"
    event = _event("listen task exited unexpectedly while RUNNING")
    candidates, noise = watch.aggregate([event], datetime.now(timezone.utc), threshold=10)
    assert len(candidates) == 1
    assert candidates[0]["count"] == 1
    assert noise == []


def test_journal_logger_and_root_handler_lines_count_as_one_event():
    stamp = "2026-09-27T12:00:00+00:00"
    events = [
        {"source": "journalctl", "ts": stamp, "message": "[session-a] listen task exited without exception (silent death), status=AgentStatus.IDLE"},
        {"source": "journalctl", "ts": stamp, "message": "WARNING:app.session:[session-a] listen task exited without exception (silent death), status=AgentStatus.IDLE"},
        {"source": "journalctl", "ts": stamp, "message": "[session-b] listen task exited without exception (silent death), status=AgentStatus.IDLE"},
    ]
    _candidates, noise = watch.aggregate(events, datetime.now(timezone.utc), threshold=1)
    assert noise[0]["count"] == 2


def test_post_fix_count_uses_deduplicated_logger_events():
    stamp = "2026-09-27T12:00:00+00:00"
    message = "task sync failed for [session-a]"
    events = [
        {"source": "journalctl", "ts": stamp, "message": message},
        {"source": "journalctl", "ts": stamp, "message": "WARNING:app.manager:" + message},
    ]
    signature = watch.normalize_signature(message)
    result = watch.post_fix_verdict(
        watch.deduplicate_events(events), signature,
        datetime.fromisoformat("2026-09-27T11:00:00+00:00"), 24,
    )
    assert result["count"] == 1


def test_scan_deduplicates_repeated_runs_without_new_events(tmp_path, monkeypatch, capsys):
    events = [_event("database transaction failed: Locked", i) for i in range(3)]
    monkeypatch.setattr(watch, "collect_db_events", lambda *_: [])
    monkeypatch.setattr(watch, "collect_journal_events", lambda *_: events)
    monkeypatch.setattr(watch, "_existing_refs", lambda _signature: [])
    args = SimpleNamespace(
        db=str(tmp_path / "orchestra.db"), window_hours=168, threshold=3,
        dry_run=False,
    )
    watch.scan(args)
    first = capsys.readouterr().out
    watch.scan(args)
    second = capsys.readouterr().out
    assert first.startswith("ERROR-WATCH: new findings")
    assert "3 раз" in first
    assert second == "No new error-watch findings\n"


def test_known_error_series_suppress_baseline_and_alert_on_new_growth(tmp_path, monkeypatch, capsys):
    series = [
        ("/usr/bin/python: No module named pytest", ("V-783",)),
        ("transport_timeout: Message delivery outcome is ambiguous: ReadTimeout", ("V-778", "V-782")),
    ]
    current = {"events": []}
    monkeypatch.setattr(watch, "collect_db_events", lambda *_: [])
    monkeypatch.setattr(watch, "collect_journal_events", lambda *_: current["events"])

    for index, (message, tasks) in enumerate(series):
        args = SimpleNamespace(
            db=str(tmp_path / f"{index}.db"), window_hours=168, threshold=10,
            dry_run=False,
        )
        scope = str(Path(watch.__file__).resolve().parents[1]) if "No module named pytest" in message else None
        current["events"] = [_event(message, i, scope=scope) for i in range(10)]
        watch.scan(args)
        assert capsys.readouterr().out == "No new error-watch findings\n"

        current["events"] = [_event(message, i, scope=scope) for i in range(11)]
        watch.scan(args)
        growth = capsys.readouterr().out
        assert "11 раз" in growth
        assert all(task in growth for task in tasks)

        watch.scan(args)
        assert capsys.readouterr().out == "No new error-watch findings\n"

        current["events"] = [_event(message, i, scope=scope) for i in range(9)]
        watch.scan(args)
        assert capsys.readouterr().out == "No new error-watch findings\n"

        current["events"] = [_event(message, i, scope=scope) for i in range(11)]
        watch.scan(args)
        growth_after_decline = capsys.readouterr().out
        assert "11 раз" in growth_after_decline
        assert all(task in growth_after_decline for task in tasks)


def test_post_fix_verdict_reports_recurrence_and_open_window():
    start = datetime(2026, 9, 27, 11, 0, tzinfo=timezone.utc)
    events = [_event("ImportError: cannot import name '_fire_sync'", 30)]
    assert watch.post_fix_verdict(events, watch.normalize_signature(events[0]["message"]), start, 24)["count"] == 1
    empty = watch.post_fix_verdict([], "some error", datetime.now(timezone.utc), 24)
    assert empty["verdict"] == "не повторилась пока; окно наблюдения не завершено"


def test_pytest_known_series_is_scoped_to_orchestra_for_noise_and_post_fix(tmp_path, monkeypatch, capsys):
    message = "/usr/bin/python: No module named pytest"
    signature = watch.normalize_signature(message)
    orchestra_scope = str(Path(watch.__file__).resolve().parents[1])
    foreign_scope = str(tmp_path / "seedon")
    assert watch._ORCHESTRA_SCOPE == orchestra_scope
    events = [
        _event(message, scope=orchestra_scope),
        _event(message, minute=1, scope=foreign_scope),
    ]

    assert watch._known_series_counts(events)[signature] == 1
    candidates, noise = watch.aggregate(events, datetime.now(timezone.utc), threshold=1)
    assert [(item["signature"], item["count"]) for item in candidates] == [(signature, 1)]
    assert [(item["noise"], item["count"]) for item in noise] == [
        ("pytest missing outside Orchestra scope", 1),
    ]

    started = datetime(2026, 9, 27, 11, 0, tzinfo=timezone.utc)
    assert watch.post_fix_verdict(events, signature, started, 24)["count"] == 1

    current = {"events": events}
    watch_args = SimpleNamespace(
        db=str(tmp_path / "orchestra.db"), window_hours=168, threshold=1, dry_run=True,
    )
    monkeypatch.setattr(watch, "collect_db_events", lambda *_: [])
    monkeypatch.setattr(watch, "collect_journal_events", lambda *_: current["events"])
    watch.scan(watch_args)
    output = json.loads(capsys.readouterr().out)
    assert output["signals"] == []
    assert output["noise_by_class"] == {"pytest missing outside Orchestra scope": 1}


def test_collect_db_events_keeps_session_scope(tmp_path):
    db_path = tmp_path / "orchestra.db"
    stamp = "2026-10-10T08:45:59+00:00"
    foreign_scope = str(tmp_path / "seedon")
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            "CREATE TABLE sessions (id TEXT PRIMARY KEY, name TEXT, scope TEXT);"
            "CREATE TABLE logs (ts TEXT, type TEXT, content TEXT, tool_is_error INTEGER, session_id TEXT);"
        )
        connection.executemany(
            "INSERT INTO sessions VALUES (?, ?, ?)",
            [
                ("orchestra-worker", "worker", str(Path(watch.__file__).resolve().parents[1])),
                ("seedon-worker", "tender-triage", foreign_scope),
            ],
        )
        connection.executemany(
            "INSERT INTO logs VALUES (?, 'error', '/usr/bin/python: No module named pytest', 1, ?)",
            [(stamp, "orchestra-worker"), (stamp, "seedon-worker")],
        )

    events = watch.collect_db_events(
        db_path, datetime(2026, 10, 10, tzinfo=timezone.utc),
    )
    assert {event["scope"] for event in events} == {
        str(Path(watch.__file__).resolve().parents[1]), foreign_scope,
    }


def test_completed_post_fix_window_reports_absence():
    start = datetime.now(timezone.utc) - timedelta(hours=25)
    result = watch.post_fix_verdict([], "some error", start, 24)
    assert result["complete"] is True
    assert result["verdict"] == "не повторилась за окно 24 ч"


def test_record_fix_persists_task_commit_and_process_start(tmp_path, capsys):
    args = SimpleNamespace(
        db=str(tmp_path / "orchestra.db"), signature="ImportError: path /tmp/x 42",
        task="V-636", commit="9035836a", started_at="2026-09-27T04:49:07+00:00",
        window_hours=168,
    )
    watch.record_fix(args)
    capsys.readouterr()
    state = watch._load_state(tmp_path / "error_watch.json")
    entry = state["fixes"][watch.normalize_signature(args.signature)]
    assert entry == {
        "task": "V-636", "commit": "9035836a",
        "started_at": "2026-09-27T04:49:07+00:00", "window_hours": 168,
    }
