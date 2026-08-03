"""SQLite storage for sessions and logs."""

import json
import logging
import math
import os
import sqlite3
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger("db")

_DEFAULT_DB_PATH = Path(__file__).parent.parent / "data" / "orchestra.db"


def _resolve_db_path() -> Path:
    """Путь к БД: ORCHESTRA_DB_PATH из env (если задан) или дефолт data/orchestra.db.

    Позволяет разным worktree/веткам и тестам держать свою БД, не блокируя
    друг друга через SQLite-лок при параллельной работе.
    """
    override = os.getenv("ORCHESTRA_DB_PATH", "").strip()
    if not override:
        return _DEFAULT_DB_PATH
    p = Path(override)
    return p if p.is_absolute() else (Path(__file__).parent.parent / p)


DB_PATH = _resolve_db_path()


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    # WAL: readers don't block writers — essential when many agents log concurrently
    conn.execute("PRAGMA journal_mode=WAL")
    # 5s busy timeout: retry on locked DB instead of raising immediately
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                scope TEXT NOT NULL,
                cwd TEXT NOT NULL,
                model TEXT NOT NULL,
                system_prompt TEXT DEFAULT '',
                status TEXT DEFAULT 'starting',
                session_id TEXT,
                cost_usd REAL DEFAULT 0.0,
                worktree_path TEXT,
                branch TEXT,
                base_branch TEXT DEFAULT '',
                needs_switch INTEGER DEFAULT 0,
                is_orchestrator INTEGER DEFAULT 0,
                color TEXT DEFAULT '',
                mcp_servers_custom TEXT DEFAULT '',
                profile TEXT DEFAULT '',
                runtime_handoff TEXT DEFAULT '',
                last_summary TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                finished_at TEXT,
                UNIQUE(name, scope)
            );
            CREATE TABLE IF NOT EXISTS profiles (
                name TEXT PRIMARY KEY,
                config_dir TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                ts TEXT NOT NULL,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                event_id TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_logs_session ON logs(session_id, id DESC);
            CREATE INDEX IF NOT EXISTS idx_sessions_scope ON sessions(scope, is_orchestrator, status);

            CREATE TABLE IF NOT EXISTS subagents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                task_id TEXT NOT NULL,
                sdk_session_id TEXT DEFAULT '',
                tool_use_id TEXT DEFAULT '',
                description TEXT DEFAULT '',
                task_type TEXT DEFAULT '',
                status TEXT DEFAULT 'running',
                total_tokens INTEGER DEFAULT 0,
                tool_uses INTEGER DEFAULT 0,
                duration_ms INTEGER DEFAULT 0,
                last_tool_name TEXT DEFAULT '',
                output_file TEXT DEFAULT '',
                summary TEXT DEFAULT '',
                raw_json TEXT DEFAULT '',
                started_at TEXT NOT NULL,
                ended_at TEXT,
                UNIQUE(session_id, task_id)
            );
            CREATE INDEX IF NOT EXISTS idx_subagents_session ON subagents(session_id);

            CREATE TABLE IF NOT EXISTS test_lock (
                scope TEXT PRIMARY KEY,
                holder TEXT NOT NULL,
                reason TEXT DEFAULT '',
                acquired_at TEXT NOT NULL
            );
        """)
        c.executescript("""
            CREATE TABLE IF NOT EXISTS tm_projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                prefix TEXT NOT NULL DEFAULT 'TASK',
                scope TEXT UNIQUE,
                yougile_project_id TEXT,
                yougile_board_id TEXT,
                yougile_enabled INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(prefix)
            );
            CREATE TABLE IF NOT EXISTS tm_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                par_number INTEGER NOT NULL,
                project_id TEXT NOT NULL REFERENCES tm_projects(id),
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                price_rub INTEGER NOT NULL DEFAULT 0 CHECK (price_rub >= 0),
                paid_rub INTEGER NOT NULL DEFAULT 0 CHECK (paid_rub >= 0),
                status TEXT NOT NULL DEFAULT 'backlog',
                assignee TEXT NOT NULL DEFAULT '',
                yougile_task_id TEXT UNIQUE,
                sync_revision INTEGER NOT NULL DEFAULT 0,
                worker_session_id TEXT,
                git_commits TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                paid_at TEXT,
                CHECK (status IN ('backlog','new','in_progress','done','paid','cancelled'))
            );
            CREATE INDEX IF NOT EXISTS idx_tm_tasks_status ON tm_tasks(status);
            CREATE INDEX IF NOT EXISTS idx_tm_tasks_project ON tm_tasks(project_id, status);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_tm_tasks_par_project ON tm_tasks(project_id, par_number);
            CREATE INDEX IF NOT EXISTS idx_tm_tasks_yougile ON tm_tasks(yougile_task_id);
            CREATE TABLE IF NOT EXISTS tm_clients (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                project_id TEXT NOT NULL REFERENCES tm_projects(id),
                balance_rub INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tm_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                client_id TEXT NOT NULL REFERENCES tm_clients(id),
                amount_rub INTEGER NOT NULL CHECK (amount_rub > 0),
                date TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tm_payment_allocations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_id INTEGER NOT NULL REFERENCES tm_payments(id),
                task_id INTEGER NOT NULL REFERENCES tm_tasks(id),
                amount_rub INTEGER NOT NULL CHECK (amount_rub > 0),
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tm_alloc_payment ON tm_payment_allocations(payment_id);
            CREATE INDEX IF NOT EXISTS idx_tm_alloc_task ON tm_payment_allocations(task_id);
            CREATE TABLE IF NOT EXISTS tm_sync_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER REFERENCES tm_tasks(id),
                direction TEXT NOT NULL DEFAULT 'push',
                action TEXT NOT NULL,
                sync_revision INTEGER,
                payload TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                error TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                completed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_tm_sync_task ON tm_sync_log(task_id);
        """)
        c.executescript("""
            CREATE TABLE IF NOT EXISTS bg_jobs (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                config TEXT NOT NULL DEFAULT '{}',
                message TEXT NOT NULL DEFAULT '',
                target_session_id TEXT NOT NULL,
                target_name TEXT NOT NULL,
                target_scope TEXT NOT NULL,
                created_by_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active','triggering','triggered','expired','cancelled','failed')),
                error TEXT,
                expires_at TEXT NOT NULL,
                trigger_at TEXT,
                created_at TEXT NOT NULL,
                triggered_at TEXT,
                last_output TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_bg_jobs_session ON bg_jobs(target_session_id, status);
            CREATE INDEX IF NOT EXISTS idx_bg_jobs_scope ON bg_jobs(target_scope, status);
        """)
        c.executescript("""
            CREATE TABLE IF NOT EXISTS usage_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                five_hour_pct REAL DEFAULT 0,
                seven_day_pct REAL DEFAULT 0,
                five_hour_resets_at TEXT,
                seven_day_resets_at TEXT,
                total_cost_usd REAL DEFAULT 0,
                active_agents INTEGER DEFAULT 0,
                provider_usage TEXT NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage_snapshots(ts);

            CREATE TABLE IF NOT EXISTS voice_costs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                session_name TEXT NOT NULL,
                scope TEXT NOT NULL,
                duration_sec REAL NOT NULL,
                cost_usd REAL NOT NULL,
                model TEXT NOT NULL DEFAULT 'nova-3',
                file_id TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tool_errors (
                id INTEGER PRIMARY KEY,
                ts TEXT DEFAULT CURRENT_TIMESTAMP,
                session_name TEXT,
                scope TEXT,
                tool_name TEXT,
                error_text TEXT,
                runtime TEXT NOT NULL DEFAULT 'unknown',
                tool_use_id TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS merge_operations (
                operation_id TEXT PRIMARY KEY,
                operation_type TEXT NOT NULL DEFAULT 'merge',
                session_id TEXT NOT NULL,
                scope TEXT NOT NULL,
                worker_name TEXT NOT NULL,
                request_json TEXT NOT NULL,
                request_hash TEXT NOT NULL,
                dedupe_fingerprint TEXT NOT NULL,
                accepted_worker_branch TEXT NOT NULL,
                accepted_worker_head TEXT NOT NULL,
                accepted_base_branch TEXT NOT NULL DEFAULT '',
                accepted_task_id TEXT NOT NULL DEFAULT '',
                accepted_needs_switch INTEGER NOT NULL DEFAULT 0,
                state TEXT NOT NULL,
                commit_point TEXT NOT NULL DEFAULT 'NOT_REACHED',
                result_json TEXT NOT NULL,
                result_hash TEXT NOT NULL,
                terminal_worker_branch TEXT NOT NULL DEFAULT '',
                terminal_worker_head TEXT NOT NULL DEFAULT '',
                terminal_base_branch TEXT NOT NULL DEFAULT '',
                terminal_task_id TEXT NOT NULL DEFAULT '',
                terminal_needs_switch INTEGER NOT NULL DEFAULT 0,
                owner_token TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                resolved_at TEXT,
                resolution_outcome TEXT NOT NULL DEFAULT '',
                resolution_evidence_hash TEXT NOT NULL DEFAULT '',
                resolution_actor TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_merge_operations_fingerprint
                ON merge_operations(dedupe_fingerprint);
            CREATE INDEX IF NOT EXISTS idx_merge_operations_request
                ON merge_operations(session_id, request_hash, finished_at);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_merge_operations_active_session
                ON merge_operations(session_id)
                WHERE resolved_at IS NULL
                  AND state IN ('PENDING','RUNNING','PARTIAL','UNKNOWN');

            CREATE TABLE IF NOT EXISTS turn_usage (
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
                cache_create_tokens INTEGER NOT NULL,
                quota_five_hour_pct REAL,
                quota_seven_day_pct REAL,
                quota_primary_pct REAL,
                quota_sampled_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_turn_usage_ts ON turn_usage(ts);
            CREATE INDEX IF NOT EXISTS idx_turn_usage_session ON turn_usage(session_id, ts);

            CREATE TABLE IF NOT EXISTS improvement_rules (
                id INTEGER PRIMARY KEY,
                rule_text TEXT,
                source_signal TEXT,
                proposed_by TEXT,
                proposed_at TEXT DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'proposed'
                    CHECK (status IN ('proposed','active','retired')),
                approved_at TEXT,
                retired_at TEXT,
                target_file TEXT
            );
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS kv (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        _migrate(c)


def kv_get(key: str, default: str = "") -> str:
    with _conn() as c:
        row = c.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def _reconstruct_costs(c) -> None:
    import re as _re
    sessions = c.execute("SELECT id FROM sessions").fetchall()
    for s in sessions:
        logs = c.execute(
            "SELECT content FROM logs WHERE session_id=? AND type='status' "
            "AND (content LIKE 'turn ended%$%' OR content LIKE 'turn done%$%') ORDER BY id ASC",
            (s["id"],),
        ).fetchall()
        prev = 0.0
        real_cost = 0.0
        for l in logs:
            m = _re.search(r'\$(\d+\.?\d*)', l["content"])
            if not m:
                continue
            val = float(m.group(1))
            if val == 0:
                continue
            if val < prev:
                real_cost += prev
            prev = val
        real_cost += prev
        c.execute("UPDATE sessions SET cost_usd=?, cost_usd_cached=0, cost_reset_v1=1 WHERE id=?",
                  (round(real_cost, 4), s["id"]))


def _migrate(c) -> None:
    # Additive ALTER TABLE migrations — safe to re-run (IF NOT EXISTS / column check).
    # Never drop columns: old Orchestra versions reading the same DB must still work.
    cols = {row[1] for row in c.execute("PRAGMA table_info(sessions)").fetchall()}
    if "color" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN color TEXT DEFAULT ''")
    if "context_pct" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN context_pct INTEGER DEFAULT 0")
    if "context_tokens" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN context_tokens INTEGER DEFAULT 0")
    if "progress_pct" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN progress_pct INTEGER DEFAULT 0")
    if "progress_status" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN progress_status TEXT DEFAULT ''")
    if "backend_type" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN backend_type TEXT DEFAULT 'claude'")
    if "task_id" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN task_id TEXT DEFAULT ''")
    if "description" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN description TEXT DEFAULT ''")
    if "cost_usd_cached" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN cost_usd_cached REAL DEFAULT 0.0")
    if "context_cost" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN context_cost REAL DEFAULT 0.0")
    if "cost_reset_v1" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN cost_reset_v1 INTEGER DEFAULT 0")
        _reconstruct_costs(c)
    proj_cols = {row[1] for row in c.execute("PRAGMA table_info(tm_projects)").fetchall()}
    if proj_cols and "yougile_enabled" not in proj_cols:
        c.execute("ALTER TABLE tm_projects ADD COLUMN yougile_enabled INTEGER NOT NULL DEFAULT 0")
        c.execute("UPDATE tm_projects SET yougile_enabled = 1 WHERE id = 'parsing-hub'")
    if proj_cols and "prefix" not in proj_cols:
        c.execute("ALTER TABLE tm_projects ADD COLUMN prefix TEXT NOT NULL DEFAULT 'TASK'")
        c.execute("UPDATE tm_projects SET prefix = 'PAR' WHERE id = 'parsing-hub'")
        c.execute("UPDATE tm_projects SET prefix = 'ORC' WHERE id = 'orchestra'")
    if "total_turns" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN total_turns INTEGER DEFAULT 0")
    if "total_input_tokens" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN total_input_tokens INTEGER DEFAULT 0")
    if "total_output_tokens" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN total_output_tokens INTEGER DEFAULT 0")
    if "total_cache_read_tokens" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN total_cache_read_tokens INTEGER DEFAULT 0")
    if "total_cache_create_tokens" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN total_cache_create_tokens INTEGER DEFAULT 0")
    if "total_tool_calls" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN total_tool_calls INTEGER DEFAULT 0")
    if "template_hash" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN template_hash TEXT DEFAULT ''")
    if "mcp_servers_custom" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN mcp_servers_custom TEXT DEFAULT ''")
    bg_ddl = c.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='bg_jobs'"
    ).fetchone()
    if bg_ddl and "type IN ('timer'" in bg_ddl[0]:
        _bg_cols = ("id", "type", "config", "message", "target_session_id", "target_name",
                    "target_scope", "created_by_name", "status", "error", "expires_at",
                    "trigger_at", "created_at", "triggered_at", "last_output")
        _bg_col_list = ", ".join(_bg_cols)
        c.execute("ALTER TABLE bg_jobs RENAME TO bg_jobs_old")
        c.execute("""
            CREATE TABLE bg_jobs (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                config TEXT NOT NULL DEFAULT '{}',
                message TEXT NOT NULL DEFAULT '',
                target_session_id TEXT NOT NULL,
                target_name TEXT NOT NULL,
                target_scope TEXT NOT NULL,
                created_by_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active','triggering','triggered','expired','cancelled','failed')),
                error TEXT,
                expires_at TEXT NOT NULL,
                trigger_at TEXT,
                created_at TEXT NOT NULL,
                triggered_at TEXT,
                last_output TEXT NOT NULL DEFAULT ''
            )
        """)
        c.execute(f"INSERT INTO bg_jobs ({_bg_col_list}) SELECT {_bg_col_list} FROM bg_jobs_old")
        c.execute("DROP TABLE bg_jobs_old")
        c.execute("CREATE INDEX IF NOT EXISTS idx_bg_jobs_session ON bg_jobs(target_session_id, status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_bg_jobs_scope ON bg_jobs(target_scope, status)")
    try:
        c.execute("DROP TABLE IF EXISTS tm_par_sequence")
    except Exception as e:
        logger.warning(f"migration: tm_par_sequence drop failed: {e}", exc_info=True)
    for old_name in ("_tm_tasks_old", "tm_tasks_old"):
        old_exists = c.execute(f"SELECT 1 FROM sqlite_master WHERE type='table' AND name='{old_name}'").fetchone()
        if old_exists:
            c.execute("DROP TABLE IF EXISTS tm_tasks")
            c.execute(f"ALTER TABLE {old_name} RENAME TO tm_tasks")
            break
    try:
        auto_idx = [r[1] for r in c.execute("PRAGMA index_list(tm_tasks)").fetchall()
                    if r[1].startswith("sqlite_autoindex")]
    except Exception:
        auto_idx = []
    needs_recreate = False
    for idx in auto_idx:
        try:
            info = c.execute(f"PRAGMA index_info({idx})").fetchall()
            if [r[2] for r in info] == ["par_number"]:
                needs_recreate = True
                break
        except Exception as e:
            logger.warning(f"migration: index_info({idx}) probe failed: {e}", exc_info=True)
    if needs_recreate:
        c.execute("ALTER TABLE tm_tasks RENAME TO _tm_tasks_old")
        c.execute("""CREATE TABLE tm_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            par_number INTEGER NOT NULL,
            project_id TEXT NOT NULL REFERENCES tm_projects(id),
            title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            price_rub INTEGER NOT NULL DEFAULT 0 CHECK (price_rub >= 0),
            paid_rub INTEGER NOT NULL DEFAULT 0 CHECK (paid_rub >= 0),
            status TEXT NOT NULL DEFAULT 'backlog', assignee TEXT NOT NULL DEFAULT '',
            yougile_task_id TEXT UNIQUE, sync_revision INTEGER NOT NULL DEFAULT 0,
            worker_session_id TEXT, git_commits TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            completed_at TEXT, paid_at TEXT,
            CHECK (status IN ('backlog','new','in_progress','done','paid','cancelled'))
        )""")
        c.execute("INSERT INTO tm_tasks SELECT * FROM _tm_tasks_old")
        c.execute("DROP TABLE _tm_tasks_old")
    c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_tm_tasks_par_project ON tm_tasks(project_id, par_number)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tm_tasks_status ON tm_tasks(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_tm_tasks_project ON tm_tasks(project_id, status)")
    for tbl in ("tm_payment_allocations", "tm_sync_log"):
        try:
            schema = c.execute(f"SELECT sql FROM sqlite_master WHERE name='{tbl}' AND type='table'").fetchone()
            if schema and "tm_tasks_old" in schema[0]:
                old_name = f"_{tbl}_fix"
                c.execute(f"ALTER TABLE {tbl} RENAME TO {old_name}")
                create_sql = schema[0].replace('"tm_tasks_old"', 'tm_tasks').replace("tm_tasks_old", "tm_tasks")
                c.execute(create_sql)
                c.execute(f"INSERT INTO {tbl} SELECT * FROM {old_name}")
                c.execute(f"DROP TABLE {old_name}")
        except Exception as e:
            logger.warning(f"migration: {tbl} tm_tasks_old reference fix failed: {e}", exc_info=True)
    c.execute("CREATE INDEX IF NOT EXISTS idx_tm_tasks_yougile ON tm_tasks(yougile_task_id)")
    task_cols = {row[1] for row in c.execute("PRAGMA table_info(tm_tasks)").fetchall()}
    if task_cols and "priority" not in task_cols:
        # 0=critical, 1=high, 2=medium (default), 3=low — existing tasks land at medium
        c.execute("ALTER TABLE tm_tasks ADD COLUMN priority INTEGER NOT NULL DEFAULT 2")
    client_cols = {row[1] for row in c.execute("PRAGMA table_info(tm_clients)").fetchall()}
    if client_cols and "journal_yougile_id" not in client_cols:
        c.execute("ALTER TABLE tm_clients ADD COLUMN journal_yougile_id TEXT DEFAULT ''")
    if task_cols:
        max_price = c.execute("SELECT MAX(price_rub) FROM tm_tasks").fetchone()[0] or 0
        if 0 < max_price < 1000:
            # Schema changed from "thousands" to exact kopeks — multiply all money
            # columns by 1000 to bring old data in line with the new unit
            c.execute("UPDATE tm_tasks SET price_rub = price_rub * 1000, paid_rub = paid_rub * 1000")
            c.execute("UPDATE tm_payment_allocations SET amount_rub = amount_rub * 1000")
            c.execute("UPDATE tm_payments SET amount_rub = amount_rub * 1000")
            c.execute("UPDATE tm_clients SET balance_rub = balance_rub * 1000")
    if "role" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN role TEXT DEFAULT 'worker'")
        c.execute("UPDATE sessions SET role = 'orchestrator' WHERE is_orchestrator = 1")
    if "parent_id" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN parent_id TEXT DEFAULT ''")
    if "parent_name" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN parent_name TEXT DEFAULT ''")
    if "pipeline" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN pipeline TEXT DEFAULT ''")
        c.execute("UPDATE sessions SET is_orchestrator = 1 WHERE role IN ('orchestrator', 'sub-orchestrator')")
    if "profile" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN profile TEXT DEFAULT ''")
    if "owned_dirs" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN owned_dirs TEXT DEFAULT ''")
    if "tg_topic" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN tg_topic INTEGER DEFAULT 0")
    if "session_id_history" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN session_id_history TEXT DEFAULT '[]'")
    if "effort" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN effort TEXT DEFAULT ''")
    if "runtime_handoff" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN runtime_handoff TEXT DEFAULT ''")
    if "last_summary" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN last_summary TEXT DEFAULT ''")
    if "base_branch" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN base_branch TEXT DEFAULT ''")
    if "needs_switch" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN needs_switch INTEGER DEFAULT 0")
    log_cols = {row[1] for row in c.execute("PRAGMA table_info(logs)").fetchall()}
    if log_cols and "event_id" not in log_cols:
        c.execute("ALTER TABLE logs ADD COLUMN event_id TEXT NOT NULL DEFAULT ''")
    c.execute(
        """CREATE INDEX IF NOT EXISTS idx_logs_event_id
           ON logs(event_id)
           WHERE event_id <> ''"""
    )
    usage_cols = {row[1] for row in c.execute("PRAGMA table_info(usage_snapshots)").fetchall()}
    if usage_cols and "provider_usage" not in usage_cols:
        c.execute("ALTER TABLE usage_snapshots ADD COLUMN provider_usage TEXT NOT NULL DEFAULT '{}'")
    tool_error_cols = {
        row[1] for row in c.execute("PRAGMA table_info(tool_errors)").fetchall()
    }
    if tool_error_cols and "runtime" not in tool_error_cols:
        c.execute(
            "ALTER TABLE tool_errors ADD COLUMN runtime TEXT NOT NULL DEFAULT 'unknown'"
        )
    if tool_error_cols and "tool_use_id" not in tool_error_cols:
        c.execute(
            "ALTER TABLE tool_errors ADD COLUMN tool_use_id TEXT NOT NULL DEFAULT ''"
        )
    c.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_tool_errors_identity
           ON tool_errors(runtime, tool_use_id)
           WHERE tool_use_id <> ''"""
    )
    turn_usage_cols = {
        row[1] for row in c.execute("PRAGMA table_info(turn_usage)").fetchall()
    }
    if turn_usage_cols and "scope" not in turn_usage_cols:
        c.execute(
            "ALTER TABLE turn_usage ADD COLUMN scope TEXT NOT NULL DEFAULT ''"
        )
    if turn_usage_cols and "task_id" not in turn_usage_cols:
        c.execute(
            "ALTER TABLE turn_usage ADD COLUMN task_id TEXT NOT NULL DEFAULT ''"
        )
    if turn_usage_cols and "quota_five_hour_pct" not in turn_usage_cols:
        c.execute("ALTER TABLE turn_usage ADD COLUMN quota_five_hour_pct REAL")
    if turn_usage_cols and "quota_seven_day_pct" not in turn_usage_cols:
        c.execute("ALTER TABLE turn_usage ADD COLUMN quota_seven_day_pct REAL")
    if turn_usage_cols and "quota_primary_pct" not in turn_usage_cols:
        c.execute("ALTER TABLE turn_usage ADD COLUMN quota_primary_pct REAL")
    if turn_usage_cols and "quota_sampled_at" not in turn_usage_cols:
        c.execute("ALTER TABLE turn_usage ADD COLUMN quota_sampled_at TEXT")
    # Идемпотентный сид профиля 'personal' (config_dir="" → env процесса, как сегодня).
    # INSERT OR IGNORE: повторная миграция не падает и не перетирает существующую строку.
    c.execute("INSERT OR IGNORE INTO profiles (name, config_dir) VALUES ('personal', '')")
    collector_started_at = datetime.now(timezone.utc).isoformat()
    c.execute(
        """INSERT OR IGNORE INTO kv(key, value)
           VALUES ('tool_error_collector_started_at', ?)""",
        (collector_started_at,),
    )
    c.execute(
        """INSERT OR IGNORE INTO kv(key, value)
           VALUES ('turn_usage_collector_started_at', ?)""",
        (collector_started_at,),
    )


def save_session(
    s: dict,
    *,
    _connection: sqlite3.Connection | None = None,
) -> None:
    s.setdefault("context_pct", 0)
    s.setdefault("context_tokens", 0)
    s.setdefault("progress_pct", 0)
    s.setdefault("progress_status", "")
    s.setdefault("backend_type", "claude")
    s.setdefault("task_id", "")
    s.setdefault("description", "")
    s.setdefault("cost_usd_cached", 0.0)
    s.setdefault("context_cost", 0.0)
    s.setdefault("total_turns", 0)
    s.setdefault("total_input_tokens", 0)
    s.setdefault("total_output_tokens", 0)
    s.setdefault("total_cache_read_tokens", 0)
    s.setdefault("total_cache_create_tokens", 0)
    s.setdefault("total_tool_calls", 0)
    s.setdefault("template_hash", "")
    s.setdefault("role", "worker")
    s.setdefault("parent_id", "")
    s.setdefault("parent_name", "")
    s.setdefault("pipeline", "")
    s.setdefault("profile", "")
    s.setdefault("mcp_servers_custom", "")
    s.setdefault("owned_dirs", "")
    s.setdefault("tg_topic", 0)
    s.setdefault("session_id_history", "[]")
    s.setdefault("effort", "")
    s.setdefault("runtime_handoff", "")
    s.setdefault("last_summary", "")
    s.setdefault("base_branch", "")
    s.setdefault("needs_switch", 0)
    connection_scope = (
        nullcontext(_connection) if _connection is not None else _conn()
    )
    with connection_scope as c:
        c.execute("""
            INSERT INTO sessions (id, name, scope, cwd, model, system_prompt,
                status, session_id, cost_usd, worktree_path, branch, base_branch,
                needs_switch, is_orchestrator,
                color, created_at, finished_at, context_pct, context_tokens,
                progress_pct, progress_status, backend_type, task_id, description,
                cost_usd_cached, context_cost,
                total_turns, total_input_tokens, total_output_tokens,
                total_cache_read_tokens, total_cache_create_tokens, total_tool_calls,
                template_hash, role, parent_id, parent_name, mcp_servers_custom, pipeline,
                profile, owned_dirs, tg_topic, session_id_history, effort, runtime_handoff,
                last_summary)
            VALUES (:id, :name, :scope, :cwd, :model, :system_prompt,
                :status, :session_id, :cost_usd, :worktree_path, :branch, :base_branch,
                :needs_switch, :is_orchestrator,
                :color, :created_at, :finished_at, :context_pct, :context_tokens,
                :progress_pct, :progress_status, :backend_type, :task_id, :description,
                :cost_usd_cached, :context_cost,
                :total_turns, :total_input_tokens, :total_output_tokens,
                :total_cache_read_tokens, :total_cache_create_tokens, :total_tool_calls,
                :template_hash, :role, :parent_id, :parent_name, :mcp_servers_custom, :pipeline,
                :profile, :owned_dirs, :tg_topic, :session_id_history, :effort,
                :runtime_handoff, :last_summary)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                model=excluded.model,
                system_prompt=excluded.system_prompt,
                status=excluded.status,
                session_id=excluded.session_id,
                cost_usd=excluded.cost_usd,
                cost_usd_cached=excluded.cost_usd_cached,
                context_cost=excluded.context_cost,
                worktree_path=excluded.worktree_path,
                branch=excluded.branch,
                base_branch=excluded.base_branch,
                needs_switch=excluded.needs_switch,
                cwd=excluded.cwd,
                color=excluded.color,
                finished_at=excluded.finished_at,
                context_pct=excluded.context_pct,
                context_tokens=excluded.context_tokens,
                progress_pct=excluded.progress_pct,
                progress_status=excluded.progress_status,
                backend_type=excluded.backend_type,
                task_id=excluded.task_id,
                description=excluded.description,
                total_turns=excluded.total_turns,
                total_input_tokens=excluded.total_input_tokens,
                total_output_tokens=excluded.total_output_tokens,
                total_cache_read_tokens=excluded.total_cache_read_tokens,
                total_cache_create_tokens=excluded.total_cache_create_tokens,
                total_tool_calls=excluded.total_tool_calls,
                template_hash=excluded.template_hash,
                role=excluded.role,
                parent_id=excluded.parent_id,
                parent_name=excluded.parent_name,
                mcp_servers_custom=excluded.mcp_servers_custom,
                pipeline=excluded.pipeline,
                profile=excluded.profile,
                owned_dirs=excluded.owned_dirs,
                tg_topic=excluded.tg_topic,
                session_id_history=excluded.session_id_history,
                effort=excluded.effort,
                runtime_handoff=excluded.runtime_handoff,
                last_summary=excluded.last_summary
        """, s)


def publish_ready_session(s: dict) -> None:
    """Atomically replace one archived identity with a fully prepared session."""
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        if c.execute("SELECT 1 FROM sessions WHERE id=?", (s["id"],)).fetchone():
            raise sqlite3.IntegrityError(f"session id already exists: {s['id']}")
        c.execute(
            "DELETE FROM sessions WHERE name=? AND scope=? AND status='archived'",
            (s["name"], s["scope"]),
        )
        save_session(s, _connection=c)


def update_session_lifecycle(
    session_id: str,
    *,
    branch: str,
    base_branch: str,
    task_id: str,
    needs_switch: bool,
) -> bool:
    """Persist the Git lifecycle snapshot for loaded and detached sessions alike."""
    with _conn() as c:
        cur = c.execute(
            """UPDATE sessions
               SET branch=?, base_branch=?, task_id=?, needs_switch=?
               WHERE id=? AND status != 'archived'""",
            (branch, base_branch, task_id, int(needs_switch), session_id),
        )
        return cur.rowcount == 1


def change_scope(session_id: str, old_scope: str, new_scope: str, new_cwd: str) -> dict:
    """Move an orchestrator's session to a new scope in one transaction.

    Migrates session.scope+cwd, and (best-effort) tm_projects.scope, active
    bg_jobs.target_scope, and test_lock.scope from old_scope to new_scope.
    session_id (Claude resume token) is left intact — context survives.

    Rejected if another session with the same name already lives in new_scope
    (UNIQUE(name, scope)). tm_projects/test_lock migration is skipped on UNIQUE
    collision (target already taken) but the session move still succeeds.
    """
    with _conn() as c:
        row = c.execute("SELECT name FROM sessions WHERE id=?", (session_id,)).fetchone()
        if not row:
            return {"error": f"session not found: {session_id}"}
        name = row["name"]
        clash = c.execute(
            "SELECT 1 FROM sessions WHERE name=? AND scope=? AND id!=? AND status!='archived'",
            (name, new_scope, session_id),
        ).fetchone()
        if clash:
            return {"error": f"session '{name}' already exists in scope '{new_scope}'"}

        cur = c.execute(
            "UPDATE sessions SET scope=?, cwd=? WHERE id=? AND scope=?",
            (new_scope, new_cwd, session_id, old_scope),
        )
        if cur.rowcount == 0:
            return {"error": f"session no longer in scope '{old_scope}' (stale or concurrent move)"}

        tm_migrated = False
        target_taken = c.execute("SELECT 1 FROM tm_projects WHERE scope=?", (new_scope,)).fetchone()
        if not target_taken:
            cur = c.execute("UPDATE tm_projects SET scope=? WHERE scope=?", (new_scope, old_scope))
            tm_migrated = cur.rowcount > 0

        c.execute(
            "UPDATE bg_jobs SET target_scope=? WHERE target_scope=? AND status IN ('active','triggering')",
            (new_scope, old_scope),
        )

        lock_target_taken = c.execute("SELECT 1 FROM test_lock WHERE scope=?", (new_scope,)).fetchone()
        if not lock_target_taken:
            c.execute("UPDATE test_lock SET scope=? WHERE scope=?", (new_scope, old_scope))

        return {"ok": True, "scope": new_scope, "cwd": new_cwd, "tm_project_migrated": tm_migrated}


def get_session(session_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None


def get_session_by_name(name: str, scope: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM sessions WHERE name = ? AND scope = ? AND status != 'archived'",
            (name, scope),
        ).fetchone()
        return dict(row) if row else None


# ── Профили Claude (CLAUDE_CONFIG_DIR per-session) ──

def list_profiles() -> list[dict]:
    """Все профили, отсортированы по имени: ``[{"name":..., "config_dir":...}]``."""
    with _conn() as c:
        rows = c.execute(
            "SELECT name, config_dir FROM profiles ORDER BY name"
        ).fetchall()
        return [{"name": r["name"], "config_dir": r["config_dir"]} for r in rows]


def get_profile(name: str) -> dict | None:
    """Один профиль по имени или ``None``, если не найден."""
    with _conn() as c:
        row = c.execute(
            "SELECT name, config_dir FROM profiles WHERE name = ?", (name,)
        ).fetchone()
        return {"name": row["name"], "config_dir": row["config_dir"]} if row else None


def upsert_profile(name: str, config_dir: str) -> None:
    """Создать профиль или обновить его ``config_dir`` (по конфликту имени)."""
    with _conn() as c:
        c.execute(
            "INSERT INTO profiles (name, config_dir) VALUES (?, ?) "
            "ON CONFLICT(name) DO UPDATE SET config_dir = excluded.config_dir",
            (name, config_dir),
        )


def delete_profile(name: str) -> None:
    """Удалить профиль. Сид-профиль ``personal`` удалять запрещено."""
    if name == "personal":
        raise ValueError("Профиль 'personal' является сид-профилем и не может быть удалён")
    with _conn() as c:
        c.execute("DELETE FROM profiles WHERE name = ?", (name,))


def get_all_sessions(scope: str | None = None, include_archived: bool = False) -> list[dict]:
    with _conn() as c:
        archived_filter = "" if include_archived else " AND status != 'archived'"
        if scope:
            rows = c.execute(
                f"SELECT * FROM sessions WHERE scope = ?{archived_filter} ORDER BY created_at DESC", (scope,)
            ).fetchall()
        else:
            rows = c.execute(
                f"SELECT * FROM sessions WHERE 1=1{archived_filter} ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def get_last_turn_map() -> dict[str, str]:
    """{session_id: last 'turn ended' log ts} for cache-timer display. One query."""
    with _conn() as c:
        rows = c.execute(
            "SELECT session_id, MAX(ts) AS last_ts FROM logs "
            "WHERE type='status' AND content LIKE 'turn ended%' "
            "GROUP BY session_id"
        ).fetchall()
        return {r["session_id"]: r["last_ts"] for r in rows}


def delete_session(session_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


def delete_archived_session(name: str, scope: str) -> None:
    """Free the UNIQUE(name, scope) slot held by an archived row before re-spawn.

    get_session_by_name filters archived out, so the archived row is invisible to
    callers — this deletes it explicitly (name+scope scoped, never name-only).
    """
    with _conn() as c:
        c.execute(
            "DELETE FROM sessions WHERE name=? AND scope=? AND status='archived'",
            (name, scope),
        )


def archive_session(session_id: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE sessions SET status='archived', finished_at=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), session_id),
        )


def add_log(
    session_id: str,
    ts: datetime,
    type: str,
    content: str,
    event_id: str = "",
) -> int:
    """ИНВАРИАНТ: строки logs неизменяемы — только этот INSERT и оптовый DELETE по
    возрасту в cleanup_old_logs. Ни одного UPDATE. На этом стоит зеркало журнала в
    браузере (#8): сохранённая строка не может стать неверной, только исчезнуть.
    Появится первый UPDATE logs (например, редактирование сообщения) — зеркало начнёт
    врать МОЛЧА; чинить придётся get_logs_sync и клиентское хранилище вместе.
    """
    with _conn() as c:
        cur = c.execute(
            """INSERT INTO logs (session_id, ts, type, content, event_id)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, ts.isoformat(), type, content, event_id),
        )
        return cur.lastrowid


# Sub-agent telemetry columns that upsert may set. Text cols use NULLIF-COALESCE
# (empty from a progress event must NOT wipe a value set by start/end). Numeric
# cols take the incoming value when > 0 (TaskUsage is cumulative → latest wins,
# never summed — session total already counts subagents, see backend_claude).
_SA_TEXT = ("sdk_session_id", "tool_use_id", "description", "task_type",
            "status", "last_tool_name", "output_file", "summary", "raw_json", "ended_at")
_SA_NUM = ("total_tokens", "tool_uses", "duration_ms")


def subagent_upsert(session_id: str, task_id: str, **fields) -> None:
    """Insert or update one sub-agent row (keyed by session_id+task_id).

    start creates the row; progress/end update only the fields they carry.
    Empty text / zero numbers never overwrite an existing value.
    Explicit starts keep the earliest known lifecycle timestamp.
    """
    started_at = fields.get("started_at") or datetime.now(timezone.utc).isoformat()
    cols = ["session_id", "task_id", "started_at"]
    vals = [session_id, task_id, started_at]
    updates = [
        "started_at=CASE WHEN julianday(excluded.started_at) < "
        "julianday(subagents.started_at) THEN excluded.started_at "
        "ELSE subagents.started_at END"
    ]
    for k in _SA_TEXT:
        if k in fields and fields[k] is not None:
            cols.append(k); vals.append(fields[k])
            updates.append(f"{k}=COALESCE(NULLIF(excluded.{k}, ''), subagents.{k})")
    for k in _SA_NUM:
        if k in fields and fields[k]:
            cols.append(k); vals.append(int(fields[k]))
            updates.append(f"{k}=MAX(excluded.{k}, subagents.{k})")
    if fields.get("ended_at") and not fields.get("duration_ms"):
        # local_bash notifications carry no TaskUsage. Preserve SDK duration
        # when present; otherwise derive wall time from the persisted lifecycle.
        updates.append(
            "duration_ms=CASE WHEN subagents.duration_ms > 0 "
            "THEN subagents.duration_ms ELSE MAX(0, CAST("
            "(julianday(excluded.ended_at) - julianday(subagents.started_at)) "
            "* 86400000 AS INTEGER)) END"
        )
    placeholders = ", ".join("?" for _ in cols)
    set_clause = ", ".join(updates) if updates else "task_id=task_id"
    with _conn() as c:
        c.execute(
            f"INSERT INTO subagents ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(session_id, task_id) DO UPDATE SET {set_clause}",
            vals,
        )


def get_subagents(session_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM subagents WHERE session_id = ? ORDER BY started_at ASC",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_subagent(session_id: str, task_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM subagents WHERE session_id = ? AND task_id = ?",
            (session_id, task_id),
        ).fetchone()
        return dict(row) if row else None


def get_logs(session_id: str, after_id: int = 0, limit: int = 5000, conn=None) -> list[dict]:
    c = conn or _conn()
    try:
        if after_id > 0:
            rows = c.execute(
                "SELECT * FROM logs WHERE session_id = ? AND id > ? ORDER BY id ASC LIMIT ?",
                (session_id, after_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]
        else:
            rows = c.execute(
                "SELECT * FROM logs WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
            return [dict(r) for r in reversed(rows)]
    finally:
        if conn is None:
            c.close()


def get_logs_before(session_id: str, before_id: int, limit: int = 500) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM logs WHERE session_id = ? AND id < ? ORDER BY id DESC LIMIT ?",
            (session_id, before_id, limit),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]


_SYNC_COLS = "id, session_id, ts, type, content, event_id"


def _cap_content(row: dict, cap: int) -> dict:
    """Обрезать content до cap БАЙТ (не символов) и пометить обрезку.

    Байты, а не символы: бюджет клиентского зеркала считается в байтах, а кириллица
    в UTF-8 даёт 2 байта на символ — по символам потолок уехал бы вдвое. Срез может
    разрубить символ пополам, поэтому errors="ignore".
    """
    raw = (row.get("content") or "").encode()
    if len(raw) <= cap:
        return row
    row["content"] = raw[:cap].decode(errors="ignore")
    row["trunc"] = len(raw)  # исходная длина в байтах — её показывает кнопка «загрузить целиком»
    return row


def get_logs_sync(after_id: int = 0, tail: int = 20, cap: int = 16384) -> dict:
    """Журнал всех сессий всех проектов одним ответом — для зеркала в браузере.

    after_id == 0 — холодный старт: последние ``tail`` строк на каждую сессию.
    after_id > 0  — инкремент: всё, что появилось после этой отметки.

    ``live_sessions`` — полный список сессий БЕЗ фильтров, по ``{id, name, scope}``.
    Логи висят на sessions(id) с ON DELETE CASCADE (и foreign_keys=ON), поэтому
    удалённая сессия уносит свой журнал, и клиент обязан это повторить. Отсюда же
    требование к вызывающему: пустой список означает сбой, а не «сессий нет» — по нему
    нельзя вычищать зеркало.

    Имя и scope нужны не для красоты: после F5 браузер знает, какого агента показывать,
    но не знает его session_id, а логи ключуются именно по нему. Сохранённая карта
    имя+scope → id даёт показать историю до первого сетевого ответа.
    """
    with _conn() as c:
        max_log_id = c.execute("SELECT COALESCE(MAX(id), 0) FROM logs").fetchone()[0]
        live = [{"id": r["id"], "name": r["name"], "scope": r["scope"]}
                for r in c.execute("SELECT id, name, scope FROM sessions")]
        if after_id > 0:
            rows = c.execute(
                f"SELECT {_SYNC_COLS} FROM logs WHERE id > ? ORDER BY id ASC",
                (after_id,),
            ).fetchall()
        else:
            rows = c.execute(
                f"""WITH ranked AS (
                        SELECT {_SYNC_COLS},
                               ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY id DESC) rn
                        FROM logs
                    )
                    SELECT {_SYNC_COLS} FROM ranked WHERE rn <= ? ORDER BY id ASC""",
                (tail,),
            ).fetchall()
        return {
            "max_log_id": max_log_id,
            "live_sessions": live,
            "logs": [_cap_content(dict(r), cap) for r in rows],
        }


def get_stats(scope: str | None = None) -> dict:
    with _conn() as c:
        where = "WHERE scope = ?" if scope else ""
        params = (scope,) if scope else ()
        total = c.execute(f"SELECT COUNT(*) FROM sessions {where}", params).fetchone()[0]
        active = c.execute(
            f"SELECT COUNT(*) FROM sessions {where + ' AND ' if where else 'WHERE '}"
            "status IN ('running', 'starting')",
            params,
        ).fetchone()[0]
        archived = c.execute(
            f"SELECT COUNT(*) FROM sessions {where + ' AND ' if where else 'WHERE '}"
            "status = 'archived'",
            params,
        ).fetchone()[0]
        cost = c.execute(
            f"SELECT COALESCE(SUM(cost_usd), 0) FROM sessions {where}", params
        ).fetchone()[0]
        logs_where = (
            f"WHERE session_id IN (SELECT id FROM sessions {where})"
            if where else ""
        )
        total_logs = c.execute(
            f"SELECT COUNT(*) FROM logs {logs_where}", params
        ).fetchone()[0]
        agg = c.execute(
            f"""SELECT COALESCE(SUM(total_turns), 0),
                       COALESCE(SUM(total_input_tokens), 0),
                       COALESCE(SUM(total_output_tokens), 0),
                       COALESCE(SUM(total_tool_calls), 0)
                FROM sessions {where}""",
            params,
        ).fetchone()
        return {
            "total_sessions": total,
            "active": active,
            "archived": archived,
            "total_cost_usd": round(cost, 4),
            "total_logs": total_logs,
            "total_turns": agg[0],
            "total_input_tokens": agg[1],
            "total_output_tokens": agg[2],
            "total_tool_calls": agg[3],
        }


def cleanup_old_logs(days: int = 7) -> int:
    """REMOVED by owner decision — agent history is research data, never delete it.

    Kept as a loud tombstone: this function used to drop `logs` older than 7 days on a
    6-hour timer, which silently destroyed every diary older than a week while `sessions`
    rows survived since May. Any caller is a bug.
    """
    raise RuntimeError(
        "cleanup_old_logs is disabled: agent logs must never be deleted. "
        "If disk pressure is real, export to files first and ask the owner."
    )


# ── Background Jobs ──

def bg_save_job(job: dict) -> None:
    with _conn() as c:
        c.execute("""
            INSERT INTO bg_jobs (id, type, config, message, target_session_id,
                target_name, target_scope, created_by_name, status, expires_at,
                trigger_at, created_at, last_output)
            VALUES (:id, :type, :config, :message, :target_session_id,
                :target_name, :target_scope, :created_by_name, :status, :expires_at,
                :trigger_at, :created_at, :last_output)
        """, job)


def bg_replace_job(job: dict, replace_key: str) -> list[str]:
    """Atomically cancel an earlier keyed job and insert its replacement."""
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        rows = c.execute(
            "SELECT id FROM bg_jobs "
            "WHERE status IN ('active','triggering') "
            "AND json_extract(config, '$.replace_key')=?",
            (replace_key,),
        ).fetchall()
        replaced_ids = [row["id"] for row in rows]
        if replaced_ids:
            placeholders = ",".join("?" for _ in replaced_ids)
            c.execute(
                f"UPDATE bg_jobs SET status='cancelled' "
                f"WHERE id IN ({placeholders})",
                replaced_ids,
            )
        c.execute("""
            INSERT INTO bg_jobs (id, type, config, message, target_session_id,
                target_name, target_scope, created_by_name, status, expires_at,
                trigger_at, created_at, last_output)
            VALUES (:id, :type, :config, :message, :target_session_id,
                :target_name, :target_scope, :created_by_name, :status, :expires_at,
                :trigger_at, :created_at, :last_output)
        """, job)
        c.execute("COMMIT")
        return replaced_ids


def bg_cron_should_fire(job_id: str) -> bool:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        row = c.execute(
            "SELECT 1 FROM bg_jobs WHERE id=? AND status='active' AND expires_at >= ?",
            (job_id, now),
        ).fetchone()
        return row is not None


def bg_cron_record_fire(job_id: str) -> None:
    # IMMEDIATE lock: prevents two scheduler ticks from recording the same fire
    # (cron jobs can fire again while the previous trigger is still being processed)
    with _conn() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT config, status FROM bg_jobs WHERE id=?", (job_id,)).fetchone()
        if not row or row["status"] != "active":
            c.execute("ROLLBACK")
            return
        try:
            cfg = json.loads(row["config"])
        except (json.JSONDecodeError, TypeError):
            cfg = {}
        now_iso = datetime.now(timezone.utc).isoformat()
        cfg["last_fired_at"] = now_iso
        cfg["fire_count"] = cfg.get("fire_count", 0) + 1
        c.execute(
            "UPDATE bg_jobs SET config=?, last_output=? WHERE id=? AND status='active'",
            (json.dumps(cfg), f"fired #{cfg['fire_count']} at {now_iso}", job_id),
        )
        c.execute("COMMIT")


def bg_claim_trigger(job_id: str) -> bool:
    # Atomic CAS: only one concurrent checker can move job to 'triggering' —
    # multiple scheduler ticks could race here without this guard
    with _conn() as c:
        cur = c.execute(
            "UPDATE bg_jobs SET status='triggering', triggered_at=? WHERE id=? AND status='active'",
            (datetime.now(timezone.utc).isoformat(), job_id),
        )
        return cur.rowcount > 0


def bg_finish_trigger(job_id: str, last_output: str = "") -> None:
    with _conn() as c:
        c.execute(
            "UPDATE bg_jobs SET status='triggered', last_output=? WHERE id=?",
            (last_output[-3000:], job_id),
        )


def bg_fail_job(job_id: str, error: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE bg_jobs SET status='failed', error=? WHERE id=? AND status IN ('active','triggering')",
            (error[:1000], job_id),
        )


def bg_fail_job_if_active(job_id: str, error: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE bg_jobs SET status='failed', error=? WHERE id=? AND status='active'",
            (error[:1000], job_id),
        )


def bg_cancel_job(job_id: str) -> bool:
    with _conn() as c:
        cur = c.execute(
            "UPDATE bg_jobs SET status='cancelled' WHERE id=? AND status='active'",
            (job_id,),
        )
        return cur.rowcount > 0


def bg_expire_job(job_id: str) -> bool:
    with _conn() as c:
        cur = c.execute(
            "UPDATE bg_jobs SET status='expired' WHERE id=? AND status='active'",
            (job_id,),
        )
        return cur.rowcount > 0


def bg_update_output(job_id: str, output: str) -> None:
    with _conn() as c:
        c.execute("UPDATE bg_jobs SET last_output=? WHERE id=?", (output[-3000:], job_id))


def bg_update_config(job_id: str, config: dict, output: str = "") -> bool:
    with _conn() as c:
        cur = c.execute(
            "UPDATE bg_jobs SET config=?, last_output=? "
            "WHERE id=? AND status='triggering'",
            (json.dumps(config), output[-3000:], job_id),
        )
        return cur.rowcount > 0


def bg_get_jobs(scope: str | None = None, session_id: str | None = None,
                active_only: bool = False) -> list[dict]:
    with _conn() as c:
        clauses, params = [], []
        if scope:
            clauses.append("target_scope = ?")
            params.append(scope)
        if session_id:
            clauses.append("target_session_id = ?")
            params.append(session_id)
        if active_only:
            clauses.append("status IN ('active','triggering')")
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        rows = c.execute(
            f"SELECT * FROM bg_jobs {where} ORDER BY created_at DESC LIMIT 50", params
        ).fetchall()
        return [dict(r) for r in rows]


def bg_cancel_by_session(session_id: str) -> int:
    with _conn() as c:
        cur = c.execute(
            "UPDATE bg_jobs SET status='cancelled' WHERE target_session_id=? AND status='active'",
            (session_id,),
        )
        return cur.rowcount


def bg_get_active_all() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM bg_jobs WHERE status IN ('active','triggering')"
        ).fetchall()
        return [dict(r) for r in rows]


def bg_expire_overdue() -> list[str]:
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        rows = c.execute(
            "SELECT id FROM bg_jobs WHERE status='active' AND expires_at < ?", (now,)
        ).fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            placeholders = ",".join("?" * len(ids))
            c.execute(f"UPDATE bg_jobs SET status='expired' WHERE id IN ({placeholders})", ids)
        stale = c.execute(
            "SELECT id FROM bg_jobs WHERE status='triggering' AND triggered_at < ?",
            ((datetime.now(timezone.utc).replace(second=0, microsecond=0)).isoformat(),),
        ).fetchall()
        return ids + [r["id"] for r in stale]


def bg_reset_stale_triggering(max_age_seconds: int = 120) -> list[str]:
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)).isoformat()
    with _conn() as c:
        rows = c.execute(
            "SELECT id FROM bg_jobs WHERE status='triggering' AND triggered_at < ?", (cutoff,)
        ).fetchall()
        ids = [r["id"] for r in rows]
        if ids:
            placeholders = ",".join("?" * len(ids))
            c.execute(f"UPDATE bg_jobs SET status='active' WHERE id IN ({placeholders})", ids)
        return ids


def bg_reset_wake_triggering() -> list[str]:
    """Wake batches are safe to replay because each target turn is revalidated."""
    with _conn() as c:
        rows = c.execute(
            "SELECT id FROM bg_jobs WHERE status='triggering' "
            "AND json_extract(config, '$.action')='wake_subscription_limited'"
        ).fetchall()
        ids = [row["id"] for row in rows]
        if ids:
            placeholders = ",".join("?" * len(ids))
            c.execute(
                f"UPDATE bg_jobs SET status='active' WHERE id IN ({placeholders})",
                ids,
            )
        return ids


def bg_count_active(scope: str) -> int:
    with _conn() as c:
        return c.execute(
            "SELECT COUNT(*) FROM bg_jobs WHERE target_scope=? AND status IN ('active','triggering')",
            (scope,),
        ).fetchone()[0]


def bg_cleanup_old(max_age_hours: int = 24) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
    with _conn() as c:
        cur = c.execute(
            "DELETE FROM bg_jobs WHERE status IN ('triggered','expired','cancelled','failed') AND created_at < ?",
            (cutoff,),
        )
        return cur.rowcount


def tool_error_add(
    session_name: str,
    scope: str,
    tool_name: str,
    error_text: str,
    *,
    runtime: str = "unknown",
    tool_use_id: str = "",
) -> bool:
    """Atomically record one bounded tool failure; return false on replay."""
    with _conn() as c:
        cursor = c.execute(
            """INSERT OR IGNORE INTO tool_errors
               (session_name, scope, tool_name, error_text, runtime, tool_use_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                session_name,
                scope,
                tool_name or "unknown",
                str(error_text or "")[:4000],
                runtime or "unknown",
                tool_use_id or "",
            ),
        )
        return cursor.rowcount == 1


def tool_errors_summary(days: int = 7) -> list[dict]:
    """Return tool error counts and ranked distinct errors for the recent period."""
    with _conn() as c:
        rows = c.execute(
            """SELECT tool_name, error_text, COUNT(*) AS error_count
               FROM tool_errors
               WHERE datetime(ts) >= datetime('now', ?)
               GROUP BY tool_name, error_text
               ORDER BY error_count DESC, error_text ASC""",
            (f"-{days} days",),
        ).fetchall()

    tools: dict[str, dict] = {}
    for row in rows:
        item = tools.setdefault(
            row["tool_name"],
            {"tool_name": row["tool_name"], "error_count": 0, "top_errors": []},
        )
        item["error_count"] += row["error_count"]
        item["top_errors"].append(row["error_text"])
    return sorted(tools.values(), key=lambda item: (-item["error_count"], item["tool_name"]))


def tool_errors_recent(limit: int = 50) -> list[dict]:
    """Return the most recently recorded tool errors, newest first."""
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM tool_errors ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def turn_usage_add(
    *,
    event_id: str,
    session_id: str,
    scope: str = "",
    task_id: str = "",
    runtime: str,
    model: str,
    ok: bool,
    stop_reason: str,
    cost_usd: float,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_create_tokens: int,
    quota_five_hour_pct: float | None = None,
    quota_seven_day_pct: float | None = None,
    quota_primary_pct: float | None = None,
    quota_sampled_at: str | None = None,
    ts: str | None = None,
) -> bool:
    """Persist one provider-identified terminal turn; return false on replay."""
    if not event_id:
        return False
    quota_pcts = (
        quota_five_hour_pct,
        quota_seven_day_pct,
        quota_primary_pct,
    )
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 100
        for value in quota_pcts
        if value is not None
    ):
        raise ValueError("quota percentages must be finite numbers from 0 to 100")
    if any(value is not None for value in quota_pcts) and not quota_sampled_at:
        raise ValueError("quota_sampled_at is required with quota percentages")
    if all(value is None for value in quota_pcts):
        quota_sampled_at = None
    observed_at = ts or datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        cursor = c.execute(
            """INSERT OR IGNORE INTO turn_usage
               (event_id, ts, session_id, scope, task_id,
                runtime, model, ok, stop_reason,
                cost_usd, input_tokens, output_tokens,
                cache_read_tokens, cache_create_tokens,
                quota_five_hour_pct, quota_seven_day_pct,
                quota_primary_pct, quota_sampled_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                observed_at,
                session_id,
                scope,
                task_id,
                runtime,
                model,
                int(bool(ok)),
                stop_reason,
                max(0.0, float(cost_usd or 0)),
                max(0, int(input_tokens or 0)),
                max(0, int(output_tokens or 0)),
                max(0, int(cache_read_tokens or 0)),
                max(0, int(cache_create_tokens or 0)),
                quota_five_hour_pct,
                quota_seven_day_pct,
                quota_primary_pct,
                quota_sampled_at,
            ),
        )
        return cursor.rowcount == 1


def rule_propose(
    rule_text: str,
    source_signal: str,
    proposed_by: str,
    target_file: str = "",
) -> int:
    """Create a proposed improvement rule and return its database id."""
    with _conn() as c:
        cursor = c.execute(
            """INSERT INTO improvement_rules
               (rule_text, source_signal, proposed_by, target_file)
               VALUES (?, ?, ?, ?)""",
            (rule_text, source_signal, proposed_by, target_file),
        )
        return cursor.lastrowid


def rule_approve(rule_id: int) -> None:
    """Mark an improvement rule active and record its approval time."""
    with _conn() as c:
        c.execute(
            """UPDATE improvement_rules
               SET status = 'active', approved_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (rule_id,),
        )


def rule_retire(rule_id: int) -> None:
    """Mark an improvement rule retired and record its retirement time."""
    with _conn() as c:
        c.execute(
            """UPDATE improvement_rules
               SET status = 'retired', retired_at = CURRENT_TIMESTAMP
               WHERE id = ?""",
            (rule_id,),
        )


def rule_list(status: str | None = None) -> list[dict]:
    """Return all improvement rules, optionally filtered by status."""
    query = "SELECT * FROM improvement_rules"
    params: tuple[str, ...] = ()
    if status is not None:
        query += " WHERE status = ?"
        params = (status,)
    query += " ORDER BY proposed_at DESC, id DESC"
    with _conn() as c:
        rows = c.execute(query, params).fetchall()
        return [dict(row) for row in rows]


# ── Usage Snapshots ──

def voice_cost_add(session_name: str, scope: str, duration_sec: float,
                   cost_usd: float, file_id: str, model: str = "nova-3") -> None:
    with _conn() as c:
        c.execute(
            """INSERT INTO voice_costs
               (ts, session_name, scope, duration_sec, cost_usd, model, file_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (datetime.now(timezone.utc).isoformat(), session_name, scope,
             duration_sec, cost_usd, model, file_id),
        )


def voice_cost_total_usd() -> float:
    with _conn() as c:
        return float(c.execute(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM voice_costs"
        ).fetchone()[0])


def usage_save_snapshot(five_hour_pct: float, seven_day_pct: float,
                        five_hour_resets_at: str, seven_day_resets_at: str,
                        total_cost_usd: float, active_agents: int,
                        providers: dict | None = None) -> None:
    with _conn() as c:
        c.execute(
            """INSERT INTO usage_snapshots
               (ts, five_hour_pct, seven_day_pct, five_hour_resets_at,
                seven_day_resets_at, total_cost_usd, active_agents, provider_usage)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (datetime.now(timezone.utc).isoformat(),
             five_hour_pct, seven_day_pct,
             five_hour_resets_at or "", seven_day_resets_at or "",
             total_cost_usd, active_agents,
             json.dumps(providers or {}, ensure_ascii=False)),
        )


def _usage_providers_from_row(row: dict) -> dict:
    providers = json.loads(row.pop("provider_usage", "{}") or "{}")
    if providers:
        return providers
    windows = []
    if row.get("five_hour_resets_at") or row.get("five_hour_pct"):
        windows.append({
            "id": "five_hour", "label": "5h",
            "utilization": row.get("five_hour_pct", 0),
            "window_minutes": 300,
            "resets_at": row.get("five_hour_resets_at") or None,
        })
    if row.get("seven_day_resets_at") or row.get("seven_day_pct"):
        windows.append({
            "id": "seven_day", "label": "7d",
            "utilization": row.get("seven_day_pct", 0),
            "window_minutes": 10080,
            "resets_at": row.get("seven_day_resets_at") or None,
        })
    return {"anthropic": {"label": "Claude", "windows": windows}} if windows else {}


def usage_get_history(hours: int = 24, step_minutes: int = 5) -> list[dict]:
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=hours)).isoformat()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM usage_snapshots WHERE ts > ? ORDER BY ts ASC",
            (cutoff,),
        ).fetchall()
        raw = []
        for db_row in rows:
            row = dict(db_row)
            row["providers"] = _usage_providers_from_row(row)
            raw.append(row)
    if not raw:
        return []
    step = timedelta(minutes=step_minutes)
    start = datetime.fromisoformat(raw[0]["ts"]).replace(tzinfo=timezone.utc)
    grid: list[dict] = []
    ri = 0
    t = start
    prev = raw[0]
    while t <= now:
        # Step-forward interpolation: for each grid point, use the last known
        # snapshot at or before that time — matches "last-value" chart semantics
        while ri < len(raw) - 1:
            next_ts = datetime.fromisoformat(raw[ri + 1]["ts"]).replace(tzinfo=timezone.utc)
            if next_ts > t:
                break
            ri += 1
            prev = raw[ri]
        grid.append({**prev, "ts": t.isoformat()})
        t += step
    if grid[-1].get("id") != raw[-1].get("id"):
        grid.append(raw[-1])
    return grid


# ── Test Lock ──

def acquire_test_lock(scope: str, holder: str, reason: str = "") -> tuple[bool, str | None]:
    """Захватить глобальный тест-лок для scope.

    Возвращает (ok, current_holder):
    - (True, None)   — лок свободен, захвачен
    - (True, holder) — лок уже за этим же holder (идемпотентно), reason обновлён
    - (False, name)  — занят другим, name = текущий держатель
    """
    now = datetime.now(timezone.utc).isoformat()
    with _conn() as c:
        row = c.execute("SELECT holder FROM test_lock WHERE scope = ?", (scope,)).fetchone()
        if row is not None:
            if row["holder"] == holder:
                c.execute("UPDATE test_lock SET reason = ?, acquired_at = ? WHERE scope = ?",
                          (reason, now, scope))
                return True, holder
            return False, row["holder"]
        c.execute(
            "INSERT INTO test_lock (scope, holder, reason, acquired_at) VALUES (?, ?, ?, ?)",
            (scope, holder, reason, now),
        )
        return True, None


def release_test_lock(scope: str, holder: str) -> bool:
    """Освободить лок. True — освобождён (был за этим holder); False — не держатель / лок свободен."""
    with _conn() as c:
        cur = c.execute("DELETE FROM test_lock WHERE scope = ? AND holder = ?", (scope, holder))
        return cur.rowcount > 0


def get_test_lock(scope: str) -> dict | None:
    """Текущий держатель лока для scope или None."""
    with _conn() as c:
        row = c.execute("SELECT * FROM test_lock WHERE scope = ?", (scope,)).fetchone()
        return dict(row) if row else None
