import asyncio
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.db import init_db


def _seed_session(conn, session_id: str, model: str, backend_type: str) -> None:
    conn.execute(
        """INSERT INTO sessions
           (id, name, scope, cwd, model, backend_type, created_at)
           VALUES (?, ?, '/scope', '/scope', ?, ?, ?)""",
        (
            session_id,
            session_id,
            model,
            backend_type,
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def _seed_turn(
    conn,
    session_id: str,
    ts: datetime,
    cost: float = 1.0,
    event_id: str = "",
) -> None:
    conn.execute(
        """INSERT INTO logs (session_id, ts, type, content, event_id)
           VALUES (?, ?, 'status', ?, ?)""",
        (
            session_id,
            ts.isoformat(),
            f"turn ended (end_turn, 1 turns, ${cost:.2f} turn, $1.00 ctx)",
            event_id,
        ),
    )


def _set_turn_collector_start(conn, started_at: datetime) -> None:
    conn.execute(
        """UPDATE kv SET value = ?
           WHERE key = 'turn_usage_collector_started_at'""",
        (started_at.isoformat(),),
    )


@pytest.fixture
def usage_db(tmp_path, monkeypatch):
    db_path = tmp_path / "usage-analytics.db"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    init_db()
    return db_path


@pytest.mark.parametrize(("hour", "minute"), [(0, 30), (12, 0)])
def test_daily_usage_applies_provider_cache_ttl(usage_db, hour, minute):
    from app.usage_analytics import daily_usage

    today = datetime.now(timezone.utc).date()
    clock = datetime.combine(today, datetime.min.time(), timezone.utc).replace(
        hour=hour, minute=minute
    )
    base = clock.replace(hour=0, minute=5)
    with sqlite3.connect(usage_db) as conn:
        conn.row_factory = sqlite3.Row
        _seed_session(conn, "claude", "claude-opus-5[1m]", "claude")
        _seed_session(conn, "codex", "gpt-5.6-sol", "codex")
        for session_id in ("claude", "codex"):
            _seed_turn(conn, session_id, base)
            _seed_turn(conn, session_id, base + timedelta(minutes=31))
            _seed_turn(conn, session_id, base + timedelta(minutes=92))
        conn.create_function(
            "date",
            -1,
            lambda value, *_: (
                clock.date().isoformat()
                if value == "now"
                else datetime.fromisoformat(value).date().isoformat()
            ),
        )

        rows = daily_usage(days=1, conn=conn)

    assert len(rows) == 1
    row = rows[0]
    assert row["turns"] == 6
    assert row["cost_usd"] == 6.0
    assert row["cold_starts"] == 3
    assert row["cache_hit_pct"] == 25
    assert row["providers"]["claude"] == {
        "turns": 3,
        "cost_usd": 3.0,
        "priced_turns": 3,
        "unaccounted_turns": 0,
        "comparable_turns": 2,
        "cold_starts": 1,
        "cache_hit_pct": 50,
        "cache_ttl_seconds": 3600,
        "cache_ttl_approximate": False,
    }
    assert row["providers"]["codex"] == {
        "turns": 3,
        "cost_usd": 3.0,
        "priced_turns": 3,
        "unaccounted_turns": 0,
        "comparable_turns": 2,
        "cold_starts": 2,
        "cache_hit_pct": 0,
        "cache_ttl_seconds": 1800,
        "cache_ttl_approximate": True,
    }


def test_daily_usage_keeps_legacy_keys_and_types(usage_db):
    from app.usage_analytics import daily_usage

    now = datetime.now(timezone.utc).replace(microsecond=0)
    with sqlite3.connect(usage_db) as conn:
        _seed_session(conn, "legacy-gpt", "gpt-5.6-sol", "")
        _seed_turn(conn, "legacy-gpt", now - timedelta(minutes=2), cost=0.25)

    row = daily_usage(days=1)[0]

    assert {"day", "turns", "cost_usd", "cold_starts", "cache_hit_pct"} <= row.keys()
    assert isinstance(row["day"], str)
    assert isinstance(row["turns"], int)
    assert isinstance(row["cost_usd"], float)
    assert isinstance(row["cold_starts"], int)
    assert row["cache_hit_pct"] is None or isinstance(row["cache_hit_pct"], int)
    assert row["providers"]["codex"]["cache_ttl_seconds"] == 1800


def test_provider_bucket_prefers_explicit_runtime_and_never_defaults_to_claude(
    usage_db,
):
    from app.usage_analytics import daily_usage

    now = datetime.now(timezone.utc).replace(microsecond=0)
    with sqlite3.connect(usage_db) as conn:
        _seed_session(conn, "retired-opencode", "gpt-misleading-name", "opencode")
        _seed_session(conn, "unclassified", "vendor/new-model", "retired-runtime")
        _seed_session(conn, "legacy-claude", "claude-sonnet-4-6", "")
        for session_id in ("retired-opencode", "unclassified", "legacy-claude"):
            _seed_turn(conn, session_id, now - timedelta(minutes=2))

    providers = daily_usage(days=1)[0]["providers"]

    assert "opencode" not in providers
    assert providers["unknown"]["turns"] == 2
    assert providers["unknown"]["cache_ttl_seconds"] == 0
    assert providers["claude"]["turns"] == 1


def test_daily_usage_empty_database_returns_legacy_empty_list(usage_db):
    from app.usage_analytics import daily_usage

    assert daily_usage(days=7) == []


def test_analytics_date_windows_use_expression_indexes(usage_db):
    queries = (
        (
            "turn_usage",
            "SELECT id FROM turn_usage WHERE date(ts) >= date('now', '-6 days')",
            "idx_turn_usage_day",
        ),
        (
            "logs",
            "SELECT id FROM logs WHERE type='status' "
            "AND content LIKE '%turn ended%' "
            "AND date(ts) >= date('now', '-6 days')",
            "idx_logs_turn_end_day",
        ),
        (
            "subagents",
            "SELECT id FROM subagents "
            "WHERE date(started_at) >= date('now', '-6 days')",
            "idx_subagents_started_day",
        ),
        (
            "tool_errors",
            "SELECT id FROM tool_errors WHERE date(ts) >= date('now', '-6 days')",
            "idx_tool_errors_day",
        ),
        (
            "voice_costs",
            "SELECT id FROM voice_costs WHERE date(ts) >= date('now', '-6 days')",
            "idx_voice_costs_day",
        ),
    )
    with sqlite3.connect(usage_db) as connection:
        for table, sql, index in queries:
            plan = " ".join(
                row[3] for row in connection.execute("EXPLAIN QUERY PLAN " + sql)
            )
            assert index in plan, f"{table} query plan did not use {index}: {plan}"


def test_today_window_excludes_yesterday_boundary_date(usage_db):
    from app.usage_analytics import daily_usage

    with sqlite3.connect(usage_db) as conn:
        _seed_session(conn, "boundary", "claude-opus-5[1m]", "claude")
        conn.execute(
            """INSERT INTO logs (session_id, ts, type, content)
               VALUES ('boundary', datetime('now', 'start of day', '-1 minute'),
                       'status', 'turn ended (end_turn, 1 turns, $9.00 turn)')"""
        )
        conn.execute(
            """INSERT INTO logs (session_id, ts, type, content)
               VALUES ('boundary', datetime('now'),
                       'status', 'turn ended (end_turn, 1 turns, $2.00 turn)')"""
        )

    rows = daily_usage(days=1)

    assert len(rows) == 1
    assert rows[0]["cost_usd"] == 2.0
    assert rows[0]["turns"] == 1


def test_analytics_snapshot_has_one_consistent_provider_breakdown(usage_db):
    from app.usage_analytics import build_usage_analytics

    now = datetime.now(timezone.utc).replace(microsecond=0)
    with sqlite3.connect(usage_db) as conn:
        _set_turn_collector_start(conn, now - timedelta(days=1))
        _seed_session(conn, "claude-a", "claude-opus-5[1m]", "claude")
        _seed_session(conn, "codex-a", "gpt-5.6-sol", "codex")
        conn.execute(
            "UPDATE sessions SET task_id='1', cost_usd=6, total_turns=3, "
            "total_tool_calls=4 WHERE id='claude-a'"
        )
        for index, cost in enumerate((1.0, 2.0, 3.0)):
            event_id = f"result-{index}"
            ts = now - timedelta(hours=3 - index)
            _seed_turn(conn, "claude-a", ts, cost, event_id=event_id)
            conn.execute(
                """INSERT INTO turn_usage
                   (event_id, ts, session_id, scope, task_id, runtime, model, ok,
                    stop_reason, cost_usd, input_tokens, output_tokens,
                    cache_read_tokens, cache_create_tokens)
                   VALUES (?, ?, 'claude-a', '/scope', '1', 'claude',
                           'claude-opus-5[1m]', 1, 'end_turn', ?, 1, 1, 0, 0)""",
                (event_id, ts.isoformat(), cost),
            )
        for index, cost in enumerate((4.0, 5.0)):
            _seed_turn(conn, "codex-a", now - timedelta(minutes=50 - index * 10), cost)
        conn.execute(
            """INSERT INTO tm_projects (id, name, prefix, scope, created_at)
               VALUES ('p', 'Project', 'PRJ', '/scope', ?)""",
            (now.isoformat(),),
        )
        conn.execute(
            """INSERT INTO tm_tasks
               (par_number, project_id, title, status, created_at, updated_at, completed_at)
               VALUES (1, 'p', 'Linked task', 'done', ?, ?, ?)""",
            (now.isoformat(), now.isoformat(), now.isoformat()),
        )
        conn.execute(
            """INSERT INTO subagents
               (session_id, task_id, task_type, status, total_tokens, tool_uses,
                duration_ms, started_at, ended_at)
               VALUES ('claude-a', 'sub-1', 'local_agent', 'completed', 1200, 2, 3000, ?, ?)""",
            (now.isoformat(), now.isoformat()),
        )
        conn.execute(
            """INSERT INTO voice_costs
               (ts, session_name, scope, duration_sec, cost_usd, model, file_id)
               VALUES (?, 'claude-a', '/scope', 30, 0.01, 'nova-3', 'voice-1')""",
            (now.isoformat(),),
        )
        conn.execute(
            """INSERT INTO tool_errors
               (ts, session_name, scope, tool_name, error_text, runtime, tool_use_id)
               VALUES (?, 'claude-a', '/scope', 'Read', 'file not found', 'claude', 'tool-1')""",
            (now.isoformat(),),
        )

    capacity = {
        "anthropic": {"seven_day": {"utilization": 45}},
        "codex": {"primary": {"utilization": 33}},
    }
    payload = build_usage_analytics(days=7, capacity=capacity, now=now)

    assert payload["capacity"] == capacity
    assert payload["summary"]["observed_cost_usd"] == 15.0
    assert payload["summary"]["agent_turns"] == 5
    assert payload["summary"]["completed_tasks"] == 1
    assert payload["summary"]["linked_completed_tasks"] == 1
    assert payload["summary"]["fully_observed_linked_tasks"] == 1
    assert payload["summary"]["fully_costed_linked_tasks"] == 1
    assert payload["summary"]["task_cost_coverage_complete"] is True
    assert payload["summary"]["cost_per_linked_task"] == 6.0
    assert payload["providers"]["claude"]["cost_usd"] == 6.0
    assert payload["providers"]["codex"]["cost_usd"] == 9.0
    assert sum(item["cost_usd"] for item in payload["daily"]) == 15.0
    assert sum(item["cost_usd"] for item in payload["models"]) == 15.0
    assert sum(item["cost_usd"] for item in payload["agents"]) == 15.0
    assert payload["reliability"]["subagents"]["completed"] == 1
    assert payload["reliability"]["voice"]["cost_usd"] == 0.01
    assert payload["reliability"]["tool_errors"]["collector_ready"] is True
    assert payload["reliability"]["tool_errors"]["recorded_rows"] == 1
    assert payload["reliability"]["tool_errors"]["coverage_complete"] is False
    assert payload["reliability"]["tool_errors"]["collector_started_at"]
    assert payload["reliability"]["tool_errors"]["items"] == [{
        "runtime": "claude",
        "tool_name": "Read",
        "count": 1,
        "last_error": "file not found",
        "last_seen": now.isoformat(),
    }]
    assert payload["reliability"]["turn_usage"]["collector_ready"] is True
    assert payload["reliability"]["turn_usage"]["recorded_rows"] == 3
    assert payload["reliability"]["turn_usage"]["coverage_complete"] is False
    assert payload["reliability"]["turn_usage"]["collector_started_at"]
    assert payload["reliability"]["turn_usage"]["historical_rows_unknown"] is True


def test_background_bash_is_counted_apart_from_real_subagents(usage_db):
    """`subagent_start` carries two different entities: background Bash tasks
    (task_type=local_bash) and real delegated subagents (local_agent/codex).
    Live DB had 1557 bash vs 4 subagents in one week — counting them together
    overstated delegation ~390x."""
    from app.usage_analytics import build_usage_analytics

    now = datetime.now(timezone.utc).replace(microsecond=0)
    with sqlite3.connect(usage_db) as conn:
        _seed_session(conn, "claude-a", "claude-opus-5[1m]", "claude")
        rows = [
            ("bash-1", "local_bash", "completed"),
            ("bash-2", "local_bash", "completed"),
            ("bash-3", "local_bash", "failed"),
            ("agent-1", "local_agent", "completed"),
            ("agent-2", "codex", "failed"),
            ("legacy-1", "", "completed"),
        ]
        for task_id, task_type, status in rows:
            conn.execute(
                """INSERT INTO subagents
                   (session_id, task_id, task_type, status, started_at, ended_at)
                   VALUES ('claude-a', ?, ?, ?, ?, ?)""",
                (task_id, task_type, status, now.isoformat(), now.isoformat()),
            )

    reliability = build_usage_analytics(days=7, capacity={}, now=now)["reliability"]

    assert reliability["subagents"]["completed"] == 1
    assert reliability["subagents"]["failed"] == 1
    assert reliability["background_tasks"]["completed"] == 2
    assert reliability["background_tasks"]["failed"] == 1
    # unknown task_type is neither claimed as delegation nor silently dropped
    assert reliability["subagents"]["unclassified"] == 1


def test_subagent_counts_survive_unknown_status(usage_db):
    from app.usage_analytics import build_usage_analytics

    now = datetime.now(timezone.utc).replace(microsecond=0)
    with sqlite3.connect(usage_db) as conn:
        _seed_session(conn, "claude-a", "claude-opus-5[1m]", "claude")
        conn.execute(
            """INSERT INTO subagents
               (session_id, task_id, task_type, status, started_at)
               VALUES ('claude-a', 'a1', 'local_agent', 'interrupted', ?)""",
            (now.isoformat(),),
        )

    reliability = build_usage_analytics(days=7, capacity={}, now=now)["reliability"]

    assert reliability["subagents"]["completed"] == 0
    assert reliability["subagents"]["total"] == 1


def test_analytics_snapshot_reports_retention_and_empty_task_cost(usage_db):
    from app.usage_analytics import build_usage_analytics

    now = datetime.now(timezone.utc).replace(microsecond=0)
    with sqlite3.connect(usage_db) as conn:
        _seed_session(conn, "only", "claude-opus-5[1m]", "claude")
        _seed_turn(conn, "only", now - timedelta(days=2), 1.0)

    payload = build_usage_analytics(days=30, capacity={}, now=now)

    assert payload["period"]["complete"] is False
    assert payload["period"]["observed_from"]
    assert payload["period"]["observed_to"]
    assert payload["summary"]["completed_tasks"] == 0
    assert payload["summary"]["linked_completed_tasks"] == 0
    assert payload["summary"]["cost_per_linked_task"] is None


def test_task_cost_uses_event_time_task_linkage_not_cumulative_session(usage_db):
    from app.usage_analytics import build_usage_analytics

    now = datetime.now(timezone.utc).replace(microsecond=0)
    with sqlite3.connect(usage_db) as conn:
        _set_turn_collector_start(conn, now - timedelta(days=1))
        _seed_session(conn, "reused", "gpt-5.6-sol", "codex")
        conn.execute(
            "UPDATE sessions SET task_id='2', cost_usd=100 WHERE id='reused'"
        )
        conn.execute(
            """INSERT INTO tm_projects (id, name, prefix, scope, created_at)
               VALUES ('p', 'Project', 'PRJ', '/scope', ?)""",
            (now.isoformat(),),
        )
        for par_number in (1, 2):
            conn.execute(
                """INSERT INTO tm_tasks
                   (par_number, project_id, title, status, created_at,
                    updated_at, completed_at)
                   VALUES (?, 'p', ?, 'done', ?, ?, ?)""",
                (
                    par_number,
                    f"Task {par_number}",
                    now.isoformat(),
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            conn.execute(
                """INSERT INTO turn_usage
                   (event_id, ts, session_id, scope, runtime, model, task_id, ok,
                    stop_reason, cost_usd, input_tokens, output_tokens,
                    cache_read_tokens, cache_create_tokens)
                   VALUES (?, ?, 'reused', '/scope', 'codex', 'gpt-5.6-sol', ?, 1,
                           'end_turn', ?, 1, 1, 0, 0)""",
                (
                    f"turn-{par_number}",
                    now.isoformat(),
                    str(par_number),
                    float(par_number + 1),
                ),
            )

    summary = build_usage_analytics(days=7, now=now)["summary"]

    assert summary["completed_tasks"] == 2
    assert summary["linked_completed_tasks"] == 2
    assert summary["fully_observed_linked_tasks"] == 2
    assert summary["fully_costed_linked_tasks"] == 2
    assert summary["task_cost_coverage_complete"] is True
    assert summary["linked_task_cost_usd"] == 5.0
    assert summary["cost_per_linked_task"] == 2.5


def test_task_cost_is_hidden_when_task_predates_turn_collector(usage_db):
    from app.usage_analytics import build_usage_analytics

    now = datetime.now(timezone.utc).replace(microsecond=0)
    with sqlite3.connect(usage_db) as conn:
        collector_start = now - timedelta(hours=1)
        _set_turn_collector_start(conn, collector_start)
        _seed_session(conn, "rollout", "gpt-5.6-sol", "codex")
        conn.execute(
            """INSERT INTO tm_projects (id, name, prefix, scope, created_at)
               VALUES ('p', 'Project', 'PRJ', '/scope', ?)""",
            ((now - timedelta(hours=2)).isoformat(),),
        )
        conn.execute(
            """INSERT INTO tm_tasks
               (par_number, project_id, title, status, created_at,
                updated_at, completed_at)
               VALUES (1, 'p', 'Spans rollout', 'done', ?, ?, ?)""",
            (
                (now - timedelta(hours=2)).isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )
        conn.execute(
            """INSERT INTO turn_usage
               (event_id, ts, session_id, scope, runtime, model, task_id, ok,
                stop_reason, cost_usd, input_tokens, output_tokens,
                cache_read_tokens, cache_create_tokens)
               VALUES ('post-rollout', ?, 'rollout', '/scope', 'codex',
                       'gpt-5.6-sol', '1', 1, 'end_turn', 4, 1, 1, 0, 0)""",
            ((now - timedelta(minutes=30)).isoformat(),),
        )

    summary = build_usage_analytics(days=1, now=now)["summary"]

    assert summary["completed_tasks"] == 1
    assert summary["linked_completed_tasks"] == 1
    assert summary["fully_observed_linked_tasks"] == 0
    assert summary["fully_costed_linked_tasks"] == 0
    assert summary["task_cost_coverage_complete"] is False
    assert summary["linked_task_cost_usd"] is None
    assert summary["cost_per_linked_task"] is None


def test_tool_error_zero_is_only_known_after_full_collector_coverage(usage_db):
    from app.usage_analytics import build_usage_analytics

    with sqlite3.connect(usage_db) as conn:
        conn.execute(
            """UPDATE kv
               SET value = datetime('now', '-10 days')
               WHERE key IN (
                   'tool_error_collector_started_at',
                   'turn_usage_collector_started_at'
               )"""
        )

    reliability = build_usage_analytics(days=7)["reliability"]

    assert reliability["tool_errors"]["recorded_rows"] == 0
    assert reliability["tool_errors"]["coverage_complete"] is True
    assert reliability["turn_usage"]["coverage_complete"] is True


def test_rollups_use_event_time_provider_and_model_after_runtime_switch(usage_db):
    from app.usage_analytics import build_usage_analytics

    now = datetime.now(timezone.utc).replace(microsecond=0)
    with sqlite3.connect(usage_db) as conn:
        _seed_session(conn, "switched", "gpt-5.6-sol", "codex")
        _seed_turn(
            conn,
            "switched",
            now,
            cost=3.0,
            event_id="claude-result",
        )
        conn.execute(
            """INSERT INTO turn_usage
               (event_id, ts, session_id, scope, task_id, runtime, model, ok,
                stop_reason, cost_usd, input_tokens, output_tokens,
                cache_read_tokens, cache_create_tokens)
               VALUES ('claude-result', ?, 'switched', '/scope', '', 'claude',
                       'claude-opus-5[1m]', 1, 'end_turn', 3, 1, 1, 0, 0)""",
            (now.isoformat(),),
        )

    payload = build_usage_analytics(days=1)

    assert payload["providers"]["claude"]["cost_usd"] == 3.0
    assert "codex" not in payload["providers"]
    assert payload["models"] == [{
        "model": "claude-opus-5[1m]",
        "provider": "claude",
        "turns": 1,
        "priced_turns": 1,
        "unaccounted_turns": 0,
        "cost_usd": 3.0,
        "cost_share_pct": 100.0,
    }]


def test_structured_auto_continue_segment_is_in_period_rollup(usage_db):
    from app.usage_analytics import build_usage_analytics

    now = datetime.now(timezone.utc).replace(microsecond=0)
    with sqlite3.connect(usage_db) as conn:
        _seed_session(conn, "long", "gpt-5.6-sol", "codex")
        conn.execute(
            """INSERT INTO turn_usage
               (event_id, ts, session_id, scope, task_id, runtime, model, ok,
                stop_reason, cost_usd, input_tokens, output_tokens,
                cache_read_tokens, cache_create_tokens)
               VALUES ('max-turns-segment', ?, 'long', '/scope', '', 'codex',
                       'gpt-5.6-sol', 1, 'max_turns', 7, 1, 1, 0, 0)""",
            (now.isoformat(),),
        )

    payload = build_usage_analytics(days=1)

    assert payload["summary"]["observed_cost_usd"] == 7.0
    assert payload["summary"]["agent_turns"] == 1
    assert payload["providers"]["codex"]["cost_usd"] == 7.0


def test_analytics_preserves_unknown_cost_in_every_rollup(usage_db):
    from app.usage_analytics import build_usage_analytics

    now = datetime.now(timezone.utc).replace(microsecond=0)
    with sqlite3.connect(usage_db) as conn:
        _seed_session(conn, "unpriced", "gpt-unpriced", "codex")
        conn.execute(
            """INSERT INTO turn_usage
               (event_id, ts, session_id, scope, task_id, runtime, model, ok,
                stop_reason, cost_usd, cost_unaccounted, input_tokens,
                output_tokens, cache_read_tokens, cache_create_tokens)
               VALUES ('unpriced-turn', ?, 'unpriced', '/scope', '', 'codex',
                       'gpt-unpriced', 1, 'end_turn', NULL, 1, 10, 2, 0, 0)""",
            (now.isoformat(),),
        )

    payload = build_usage_analytics(days=1, now=now)

    assert payload["summary"]["observed_cost_usd"] is None
    assert payload["summary"]["priced_turns"] == 0
    assert payload["summary"]["unaccounted_turns"] == 1
    for row in (
        payload["providers"]["codex"],
        payload["models"][0],
        payload["agents"][0],
        payload["daily"][0],
        payload["daily"][0]["providers"]["codex"],
    ):
        assert row["cost_usd"] is None
        assert row["priced_turns"] == 0
        assert row["unaccounted_turns"] == 1
    assert payload["agents"][0]["cost_per_turn"] is None
    assert payload["agents"][0]["cost_per_priced_turn"] is None


def test_measured_zero_cost_remains_zero_not_unknown(usage_db):
    from app.usage_analytics import build_usage_analytics

    now = datetime.now(timezone.utc).replace(microsecond=0)
    with sqlite3.connect(usage_db) as conn:
        _seed_session(conn, "measured-zero", "gpt-free", "codex")
        conn.execute(
            """INSERT INTO turn_usage
               (event_id, ts, session_id, scope, task_id, runtime, model, ok,
                stop_reason, cost_usd, cost_unaccounted, input_tokens,
                output_tokens, cache_read_tokens, cache_create_tokens)
               VALUES ('measured-zero', ?, 'measured-zero', '/scope', '',
                       'codex', 'gpt-free', 1, 'end_turn', 0.0, 0,
                       10, 2, 0, 0)""",
            (now.isoformat(),),
        )

    payload = build_usage_analytics(days=1, now=now)

    assert payload["summary"]["observed_cost_usd"] == 0.0
    assert payload["summary"]["priced_turns"] == 1
    assert payload["summary"]["unaccounted_turns"] == 0
    for row in (
        payload["providers"]["codex"],
        payload["models"][0],
        payload["agents"][0],
        payload["daily"][0],
    ):
        assert row["cost_usd"] == 0.0
        assert row["priced_turns"] == 1
        assert row["unaccounted_turns"] == 0
    assert payload["agents"][0]["cost_per_turn"] == 0.0
    assert payload["agents"][0]["cost_per_priced_turn"] == 0.0


def test_cost_average_uses_only_priced_turns_and_marks_partial_group(usage_db):
    from app.usage_analytics import build_usage_analytics

    now = datetime.now(timezone.utc).replace(microsecond=0)
    with sqlite3.connect(usage_db) as conn:
        _seed_session(conn, "mixed", "gpt-5.6-sol", "codex")
        for event_id, cost, unaccounted in (
            ("paid", 2.0, 0),
            ("measured-zero", 0.0, 0),
            ("unknown", None, 1),
        ):
            conn.execute(
                """INSERT INTO turn_usage
                   (event_id, ts, session_id, scope, task_id, runtime, model, ok,
                    stop_reason, cost_usd, cost_unaccounted, input_tokens,
                    output_tokens, cache_read_tokens, cache_create_tokens)
                   VALUES (?, ?, 'mixed', '/scope', '', 'codex',
                           'gpt-5.6-sol', 1, 'end_turn', ?, ?, 10, 2, 0, 0)""",
                (event_id, now.isoformat(), cost, unaccounted),
            )

    payload = build_usage_analytics(days=1, now=now)
    agent = payload["agents"][0]

    assert agent["cost_usd"] == 2.0
    assert agent["priced_turns"] == 2
    assert agent["unaccounted_turns"] == 1
    assert agent["cost_per_turn"] is None
    assert agent["cost_per_priced_turn"] == 1.0
    for row in (
        payload["daily"][0],
        payload["daily"][0]["providers"]["codex"],
        payload["providers"]["codex"],
        payload["models"][0],
    ):
        assert row["cost_usd"] == 2.0
        assert row["priced_turns"] == 2
        assert row["unaccounted_turns"] == 1
    assert payload["summary"]["observed_cost_usd"] == 2.0
    assert payload["summary"]["priced_turns"] == 2
    assert payload["summary"]["unaccounted_turns"] == 1


def test_model_speed_prefers_api_duration_and_leaves_untimed_history_empty(usage_db):
    from app.db import turn_usage_add
    from app.usage_analytics import build_usage_analytics

    now = datetime.now(timezone.utc).replace(microsecond=0)
    common = {
        "session_id": "speed-session",
        "scope": "/scope",
        "ok": True,
        "stop_reason": "end_turn",
        "cost_usd": 0.0,
        "input_tokens": 100,
        "cache_read_tokens": 0,
        "cache_create_tokens": 0,
        "ts": (now - timedelta(minutes=5)).isoformat(),
    }
    assert turn_usage_add(
        event_id="claude-speed",
        runtime="claude",
        model="claude-sonnet-5-5",
        output_tokens=500,
        turn_duration_ms=120_000,
        api_duration_ms=10_000,
        reasoning_tokens=45,
        **common,
    )
    assert turn_usage_add(
        event_id="codex-speed",
        runtime="codex",
        model="gpt-5.6-sol",
        output_tokens=200,
        turn_duration_ms=60_000,
        api_duration_ms=20_000,
        duration_basis="model_estimate",
        model_estimate_duration_ms=20_000,
        provider_api_duration_ms=None,
        tool_duration_sum_ms=130_000,
        tool_union_duration_ms=40_000,
        tool_intervals_count=2,
        tool_intervals_missing=0,
        reasoning_tokens=None,
        **common,
    )
    assert turn_usage_add(
        event_id="legacy-speed",
        runtime="codex",
        model="gpt-5.6-luna",
        output_tokens=999,
        turn_duration_ms=None,
        api_duration_ms=None,
        reasoning_tokens=None,
        **common,
    )
    assert turn_usage_add(
        event_id="incomplete-speed",
        runtime="codex",
        model="gpt-5.6-terra",
        output_tokens=1_500,
        turn_duration_ms=10_000,
        api_duration_ms=None,
        duration_basis="incomplete",
        tool_intervals_missing=1,
        reasoning_tokens=None,
        **common,
    )

    payload = build_usage_analytics(days=1, now=now)
    speeds = payload["model_speeds"]
    hour = {(row["runtime"], row["model"]): row for row in speeds["current"]["last_hour"]}

    assert hour[("claude", "claude-sonnet-5-5")]["median_tokens_per_second"] == 50.0
    assert hour[("claude", "claude-sonnet-5-5")]["duration_basis"] == "api"
    assert hour[("codex", "gpt-5.6-sol")]["median_tokens_per_second"] == 10.0
    assert hour[("codex", "gpt-5.6-sol")]["duration_basis"] == "model_estimate"
    assert ("codex", "gpt-5.6-luna") not in hour
    assert ("codex", "gpt-5.6-terra") not in hour


@pytest.mark.asyncio
async def test_analytics_api_exposes_model_speed_fields(usage_db, monkeypatch):
    from app import db
    from app.routes import system

    now = datetime.now(timezone.utc).replace(microsecond=0)
    db.turn_usage_add(
        event_id="api-speed",
        session_id="api-speed-session",
        scope="/scope",
        runtime="claude",
        model="claude-opus-5",
        ok=True,
        stop_reason="end_turn",
        cost_usd=0.0,
        input_tokens=100,
        output_tokens=900,
        cache_read_tokens=0,
        cache_create_tokens=0,
        turn_duration_ms=90_000,
        api_duration_ms=9_000,
        reasoning_tokens=200,
        ts=(now - timedelta(minutes=3)).isoformat(),
    )
    monkeypatch.setattr(system, "get_usage", AsyncMock(return_value={}))

    payload = await system.usage_analytics_endpoint(days=1)
    point = payload["model_speeds"]["current"]["last_hour"][0]

    assert point["model"] == "claude-opus-5"
    assert point["median_tokens_per_second"] == 100.0
    assert point["duration_basis"] == "api"
    assert point["samples"] == 1


@pytest.mark.asyncio
async def test_slow_analytics_does_not_block_event_loop_or_use_default_executor(
    monkeypatch,
):
    from app.routes import system

    started = threading.Event()
    release = threading.Event()
    executor_calls = []
    loop = asyncio.get_running_loop()
    original_run_in_executor = loop.run_in_executor

    def record_executor(executor, function, *args):
        executor_calls.append(executor)
        return original_run_in_executor(executor, function, *args)

    monkeypatch.setattr(loop, "run_in_executor", record_executor)

    def slow_snapshot(days, capacity):
        started.set()
        release.wait(1)
        return {}

    monkeypatch.setattr(
        "app.usage_analytics.build_usage_analytics", slow_snapshot
    )
    monkeypatch.setattr(system, "get_usage", AsyncMock(return_value={}))
    monkeypatch.setattr(system, "build_quota_map", AsyncMock(return_value={}))
    monkeypatch.setattr("app.limit_wake.wake_status", lambda: {})

    request = asyncio.create_task(system.usage_analytics_endpoint(days=7))
    try:
        deadline = loop.time() + 0.5
        while not started.is_set() and loop.time() < deadline:
            await asyncio.sleep(0.001)
        assert started.is_set()
        await asyncio.wait_for(asyncio.sleep(0.02), timeout=0.1)
        assert not request.done()
        assert executor_calls == [system._ANALYTICS_EXECUTOR]
    finally:
        release.set()
    await request


def test_unaccounted_linked_turn_hides_task_cost(usage_db):
    from app.usage_analytics import build_usage_analytics

    now = datetime.now(timezone.utc).replace(microsecond=0)
    with sqlite3.connect(usage_db) as conn:
        _set_turn_collector_start(conn, now - timedelta(days=1))
        _seed_session(conn, "linked-unpriced", "gpt-unpriced", "codex")
        conn.execute(
            """INSERT INTO tm_projects (id, name, prefix, scope, created_at)
               VALUES ('p-unpriced', 'Project', 'PRJ', '/scope', ?)""",
            (now.isoformat(),),
        )
        conn.execute(
            """INSERT INTO tm_tasks
               (par_number, project_id, title, status, created_at,
                updated_at, completed_at)
               VALUES (239, 'p-unpriced', 'Unpriced', 'done', ?, ?, ?)""",
            (now.isoformat(), now.isoformat(), now.isoformat()),
        )
        conn.execute(
            """INSERT INTO turn_usage
               (event_id, ts, session_id, scope, task_id, runtime, model, ok,
                stop_reason, cost_usd, cost_unaccounted, input_tokens,
                output_tokens, cache_read_tokens, cache_create_tokens)
               VALUES ('linked-unpriced', ?, 'linked-unpriced', '/scope', '239',
                       'codex', 'gpt-unpriced', 1, 'end_turn', NULL, 1,
                       10, 2, 0, 0)""",
            (now.isoformat(),),
        )

    summary = build_usage_analytics(days=1, now=now)["summary"]

    assert summary["linked_priced_turns"] == 0
    assert summary["linked_unaccounted_turns"] == 1
    assert summary["fully_observed_linked_tasks"] == 1
    assert summary["fully_costed_linked_tasks"] == 0
    assert summary["task_cost_coverage_complete"] is False
    assert summary["linked_task_cost_usd"] is None
    assert summary["cost_per_linked_task"] is None


@pytest.mark.asyncio
async def test_analytics_endpoint_combines_capacity_and_database_once(
    usage_db, monkeypatch
):
    from app.routes import system

    capacity = {
        "anthropic": {"five_hour": {"utilization": 10}},
        "codex": None,
        "orchestra": {"agents_count": 0},
        "voice_cost_usd": 0.0,
    }
    get_usage = AsyncMock(return_value=capacity)
    monkeypatch.setattr(system, "get_usage", get_usage)

    response = await system.usage_analytics_endpoint(days=7)

    get_usage.assert_awaited_once()
    assert response["capacity"] == capacity
    assert response["period"]["days"] == 7


@pytest.mark.asyncio
async def test_analytics_endpoint_fails_soft_when_capacity_is_unavailable(
    usage_db, monkeypatch
):
    from fastapi.responses import JSONResponse
    from app.routes import system

    monkeypatch.setattr(
        system,
        "get_usage",
        AsyncMock(return_value=JSONResponse({"error": "offline"}, status_code=500)),
    )

    response = await system.usage_analytics_endpoint(days=30)

    assert response["capacity"] == {}
    assert response["period"]["days"] == 30
