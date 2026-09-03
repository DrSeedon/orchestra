"""#298 focused RED checks for additive route persistence migration."""

import sqlite3


# Captured from current main's sqlite_master before #298 route fields existed. This fixture is
# deliberately static: it must not call the future init_db() before the positive absence check.
LEGACY_SESSIONS_SQL = """
CREATE TABLE sessions (
    active_turn_id TEXT DEFAULT '', leftover TEXT DEFAULT '',
    id TEXT PRIMARY KEY NOT NULL, name TEXT NOT NULL, scope TEXT NOT NULL,
    cwd TEXT NOT NULL, model TEXT NOT NULL, system_prompt TEXT DEFAULT '',
    prompt_overlay TEXT, status TEXT DEFAULT 'starting', session_id TEXT,
    cost_usd REAL DEFAULT 0.0, worktree_path TEXT, branch TEXT,
    base_branch TEXT DEFAULT '', needs_switch INTEGER DEFAULT 0,
    is_orchestrator INTEGER DEFAULT 0, color TEXT DEFAULT '',
    mcp_servers_custom TEXT DEFAULT '', profile TEXT DEFAULT '',
    runtime_handoff TEXT DEFAULT '', history_import_source TEXT,
    last_summary TEXT DEFAULT '', created_at TEXT NOT NULL, finished_at TEXT,
    cli_pid INTEGER DEFAULT 0, cli_started_at INTEGER DEFAULT 0,
    context_pct INTEGER DEFAULT 0, context_tokens INTEGER DEFAULT 0,
    progress_pct INTEGER DEFAULT 0, progress_status TEXT DEFAULT '',
    backend_type TEXT DEFAULT 'claude', task_id TEXT DEFAULT '',
    description TEXT DEFAULT '', cost_usd_cached REAL DEFAULT 0.0,
    context_cost REAL DEFAULT 0.0, cost_reset_v1 INTEGER DEFAULT 0,
    total_turns INTEGER DEFAULT 0, total_input_tokens INTEGER DEFAULT 0,
    total_output_tokens INTEGER DEFAULT 0, total_cache_read_tokens INTEGER DEFAULT 0,
    total_cache_create_tokens INTEGER DEFAULT 0, total_tool_calls INTEGER DEFAULT 0,
    template_hash TEXT DEFAULT '', role TEXT DEFAULT 'worker',
    parent_id TEXT DEFAULT '', parent_name TEXT DEFAULT '', pipeline TEXT DEFAULT '',
    owned_dirs TEXT DEFAULT '', tg_topic INTEGER DEFAULT 0,
    session_id_history TEXT DEFAULT '[]', effort TEXT DEFAULT '',
    UNIQUE(name, scope)
)
"""


def test_t16_legacy_schema_migrates_route_fields_and_receipt_table(tmp_path, monkeypatch):
    """Use an explicit pre-routing SQL fixture under tmp_path; never the live DB."""
    from app import db

    legacy_db = tmp_path / "legacy-routing.db"
    monkeypatch.setattr(db, "DB_PATH", legacy_db)
    with sqlite3.connect(legacy_db) as raw:
        raw.executescript(LEGACY_SESSIONS_SQL)
        raw.execute(
            "INSERT INTO sessions (id,name,scope,cwd,model,system_prompt,status,created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                "legacy-session", "legacy", "/legacy", "/tmp", "gpt-5.6-luna",
                "legacy", "idle", "2026-08-24T00:00:00+00:00",
            ),
        )
        before_columns = {
            row[1] for row in raw.execute("PRAGMA table_info(sessions)").fetchall()
        }
        before_table = raw.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='routing_receipts'"
        ).fetchone()
    assert {"routing_metadata", "sol_receipt_id", "route_revision", "routing_status"}.isdisjoint(before_columns)
    assert before_table is None

    # The first db.init_db() call on this fixture is the migration under test.
    db.init_db()
    with db._conn() as connection:
        session_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(sessions)").fetchall()
        }
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert {"routing_metadata", "sol_receipt_id", "route_revision", "routing_status"} <= session_columns
    assert "routing_receipts" in tables
    hydrated = db.get_session("legacy-session")
    assert hydrated["routing_status"] == "legacy_unknown"
    hydrated.update({
        "routing_metadata": '{"sensitivity":"public"}',
        "sol_receipt_id": "",
        "route_revision": "r-test",
        "routing_status": "shadow",
    })
    db.save_session(hydrated)
    assert db.get_session("legacy-session")["route_revision"] == "r-test"
