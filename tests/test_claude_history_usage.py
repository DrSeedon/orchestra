import json
import sqlite3

import pytest

from app.db import init_db


@pytest.fixture
def history_db(tmp_path, monkeypatch):
    db_path = tmp_path / "claude-history.sqlite3"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    init_db()
    return db_path


def _assistant(message_id, *, output=0, timestamp="2026-10-21T10:00:00Z", model="sonnet"):
    return {
        "type": "assistant",
        "timestamp": timestamp,
        "cwd": "/work/project",
        "message": {
            "id": message_id,
            "model": model,
            "usage": {
                "input_tokens": 3,
                "output_tokens": output,
                "cache_read_input_tokens": 5,
                "cache_creation_input_tokens": 7,
            },
        },
    }


def test_history_deduplicates_by_message_id_using_last_record(tmp_path):
    from app.claude_history_usage import history_totals, read_history

    project = tmp_path / "projects" / "encoded-project"
    project.mkdir(parents=True)
    history_file = project / "session.jsonl"
    earlier_chunk = _assistant("message-1", output=2)
    earlier_chunk["uuid"] = "chunk-uuid-1"
    earlier_chunk["message"]["usage"].update({
        "input_tokens": 1,
        "cache_read_input_tokens": 3,
        "cache_creation_input_tokens": 4,
    })
    final_chunk = _assistant("message-1", output=11)
    final_chunk["uuid"] = "chunk-uuid-2"
    final_chunk["message"]["usage"].update({
        "input_tokens": 10,
        "cache_read_input_tokens": 12,
        "cache_creation_input_tokens": 13,
    })
    history_file.write_text(
        json.dumps(earlier_chunk) + "\n" + json.dumps(final_chunk) + "\n",
        encoding="utf-8",
    )

    rows, stats = read_history(tmp_path / "projects")

    assert stats == {"files": 1, "messages": 1, "malformed_lines": 0}
    assert history_totals(rows) == [{
        "day": "2026-10-21", "project": "/work/project", "model": "sonnet",
        "message_count": 1, "input_tokens": 10, "output_tokens": 11,
        "cache_read_tokens": 12, "cache_write_tokens": 13,
    }]


def test_collect_is_idempotent_and_deleted_files_keep_imported_history(history_db, tmp_path):
    from app.claude_history_usage import collect_history_usage

    project = tmp_path / "projects" / "encoded-project"
    project.mkdir(parents=True)
    history_file = project / "session.jsonl"
    history_file.write_text(json.dumps(_assistant("message-1", output=11)) + "\n")

    assert collect_history_usage(tmp_path / "projects")["stored_messages"] == 1
    assert collect_history_usage(tmp_path / "projects")["stored_messages"] == 1
    history_file.unlink()
    assert collect_history_usage(tmp_path / "projects")["stored_messages"] == 0

    with sqlite3.connect(history_db) as connection:
        count, output = connection.execute(
            "SELECT COUNT(*), SUM(output_tokens) FROM claude_history_usage_messages"
        ).fetchone()
    assert (count, output) == (1, 11)


def test_existing_schema_gets_collector_table_idempotently(history_db):
    with sqlite3.connect(history_db) as connection:
        connection.execute("DROP TABLE claude_history_usage_messages")

    init_db(history_db)

    with sqlite3.connect(history_db) as connection:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            ("claude_history_usage_messages",),
        ).fetchone()
    assert table is not None


def test_malformed_jsonl_is_skipped_and_reported(caplog, tmp_path):
    from app.claude_history_usage import read_history

    project = tmp_path / "projects" / "encoded-project"
    project.mkdir(parents=True)
    (project / "session.jsonl").write_text(
        "{bad json\n" + json.dumps(_assistant("message-1", output=4)) + "\n"
    )

    rows, stats = read_history(tmp_path / "projects")

    assert stats["malformed_lines"] == 1
    assert stats["messages"] == 1
    assert "skipped 1 malformed JSONL line" in caplog.text
    assert next(iter(rows.values()))[4] == 4


def test_usage_analytics_exposes_project_level_history_difference(history_db):
    from datetime import datetime, timezone

    from app.db import turn_usage_add
    from app.usage_analytics import build_usage_analytics

    now = datetime.now(timezone.utc).replace(microsecond=0)
    with sqlite3.connect(history_db) as connection:
        connection.execute(
            """INSERT INTO sessions (id, name, scope, cwd, model, created_at)
               VALUES ('session-1', 'worker', '/work/project', '/work/project',
                       'sonnet', ?)""",
            (now.isoformat(),),
        )
        connection.execute(
            """INSERT INTO claude_history_usage_messages
               (message_id, day, project, model, input_tokens, output_tokens,
                cache_read_tokens, cache_write_tokens)
               VALUES ('message-1', ?, '/work/project', 'sonnet', 10, 30, 5, 20)""",
            (now.date().isoformat(),),
        )
    assert turn_usage_add(
        event_id="event-1", ts=now.isoformat(), session_id="session-1",
        scope="/work/project", task_id="", runtime="claude", model="sonnet",
        ok=True, stop_reason="end_turn", cost_usd=0.0, input_tokens=7,
        output_tokens=20, cache_read_tokens=3, cache_create_tokens=12,
    )

    payload = build_usage_analytics(days=1, now=now)

    assert payload["claude_history_comparison"] == [{
        "day": now.date().isoformat(), "project": "/work/project",
        "claude_history": {
            "message_count": 1, "input_tokens": 10, "output_tokens": 30,
            "cache_read_tokens": 5, "cache_write_tokens": 20,
        },
        "orchestra": {
            "message_count": 1, "input_tokens": 7, "output_tokens": 20,
            "cache_read_tokens": 3, "cache_write_tokens": 12,
        },
        "difference": {
            "input_tokens": 3, "output_tokens": 10, "cache_read_tokens": 2,
            "cache_write_tokens": 8, "message_count": 0,
        },
    }]
