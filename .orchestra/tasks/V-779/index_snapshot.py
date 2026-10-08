from __future__ import annotations

import argparse
import sqlite3
import time


parser = argparse.ArgumentParser()
parser.add_argument("database")
database = parser.parse_args().database
indexes = (
    ("idx_turn_usage_day", "CREATE INDEX IF NOT EXISTS idx_turn_usage_day ON turn_usage(date(ts))"),
    (
        "idx_logs_turn_end_day",
        "DROP INDEX IF EXISTS idx_logs_turn_end_day",
    ),
    (
        "idx_logs_turn_end_day",
        "CREATE INDEX IF NOT EXISTS idx_logs_turn_end_day "
        "ON logs(date(ts), session_id, ts) "
        "WHERE type='status' AND content LIKE '%turn ended%'",
    ),
    (
        "idx_logs_last_turn",
        "CREATE INDEX IF NOT EXISTS idx_logs_last_turn "
        "ON logs(session_id, ts) WHERE type='status' AND content LIKE 'turn ended%'",
    ),
    (
        "idx_subagents_started_day",
        "CREATE INDEX IF NOT EXISTS idx_subagents_started_day ON subagents(date(started_at))",
    ),
    ("idx_tool_errors_day", "CREATE INDEX IF NOT EXISTS idx_tool_errors_day ON tool_errors(date(ts))"),
    ("idx_voice_costs_day", "CREATE INDEX IF NOT EXISTS idx_voice_costs_day ON voice_costs(date(ts))"),
)
with sqlite3.connect(database, timeout=60) as connection:
    for name, sql in indexes:
        started = time.perf_counter()
        connection.execute(sql)
        print(f"{name} seconds={time.perf_counter() - started:.3f}", flush=True)
