"""SQLite storage for sessions and logs."""

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "orchestra.db"


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
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
                is_orchestrator INTEGER DEFAULT 0,
                color TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                finished_at TEXT,
                UNIQUE(name, scope)
            );
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                ts TEXT NOT NULL,
                type TEXT NOT NULL,
                content TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_logs_session ON logs(session_id, id DESC);
            CREATE INDEX IF NOT EXISTS idx_sessions_scope ON sessions(scope, is_orchestrator, status);

            CREATE TABLE IF NOT EXISTS inbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                sender TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_inbox_session ON inbox(session_id, status);

            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                name TEXT NOT NULL,
                scope TEXT NOT NULL,
                status TEXT DEFAULT 'queued',
                error TEXT,
                created_at TEXT NOT NULL,
                finished_at TEXT
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
                type TEXT NOT NULL CHECK (type IN ('timer','file','command','ssh','run')),
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
                active_agents INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage_snapshots(ts);
        """)
        _migrate(c)


def _migrate(c) -> None:
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
    if "cost_reset_v1" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN cost_reset_v1 INTEGER DEFAULT 0")
        c.execute("UPDATE sessions SET cost_usd = 0, cost_usd_cached = 0, cost_reset_v1 = 1")
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
    if "total_tool_calls" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN total_tool_calls INTEGER DEFAULT 0")
    try:
        c.execute("DROP TABLE IF EXISTS tm_par_sequence")
    except Exception:
        pass
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
        except Exception:
            pass
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
        except Exception:
            pass
    c.execute("CREATE INDEX IF NOT EXISTS idx_tm_tasks_yougile ON tm_tasks(yougile_task_id)")
    task_cols = {row[1] for row in c.execute("PRAGMA table_info(tm_tasks)").fetchall()}
    if task_cols and "priority" not in task_cols:
        c.execute("ALTER TABLE tm_tasks ADD COLUMN priority INTEGER NOT NULL DEFAULT 2")
    client_cols = {row[1] for row in c.execute("PRAGMA table_info(tm_clients)").fetchall()}
    if client_cols and "journal_yougile_id" not in client_cols:
        c.execute("ALTER TABLE tm_clients ADD COLUMN journal_yougile_id TEXT DEFAULT ''")


def save_session(s: dict) -> None:
    s.setdefault("context_pct", 0)
    s.setdefault("context_tokens", 0)
    s.setdefault("progress_pct", 0)
    s.setdefault("progress_status", "")
    s.setdefault("backend_type", "claude")
    s.setdefault("task_id", "")
    s.setdefault("description", "")
    s.setdefault("cost_usd_cached", 0.0)
    s.setdefault("total_turns", 0)
    s.setdefault("total_input_tokens", 0)
    s.setdefault("total_output_tokens", 0)
    s.setdefault("total_tool_calls", 0)
    with _conn() as c:
        c.execute("""
            INSERT INTO sessions (id, name, scope, cwd, model, system_prompt,
                status, session_id, cost_usd, worktree_path, branch, is_orchestrator,
                color, created_at, finished_at, context_pct, context_tokens,
                progress_pct, progress_status, backend_type, task_id, description,
                cost_usd_cached,
                total_turns, total_input_tokens, total_output_tokens, total_tool_calls)
            VALUES (:id, :name, :scope, :cwd, :model, :system_prompt,
                :status, :session_id, :cost_usd, :worktree_path, :branch, :is_orchestrator,
                :color, :created_at, :finished_at, :context_pct, :context_tokens,
                :progress_pct, :progress_status, :backend_type, :task_id, :description,
                :cost_usd_cached,
                :total_turns, :total_input_tokens, :total_output_tokens, :total_tool_calls)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                system_prompt=excluded.system_prompt,
                status=excluded.status,
                session_id=excluded.session_id,
                cost_usd=excluded.cost_usd,
                cost_usd_cached=excluded.cost_usd_cached,
                worktree_path=excluded.worktree_path,
                branch=excluded.branch,
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
                total_tool_calls=excluded.total_tool_calls
        """, s)


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


def rename_session(session_id: str, new_name: str) -> None:
    with _conn() as c:
        c.execute("UPDATE sessions SET name = ? WHERE id = ?", (new_name, session_id))


def delete_session(session_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


def archive_session(session_id: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE sessions SET status='archived', finished_at=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), session_id),
        )


def add_log(session_id: str, ts: datetime, type: str, content: str) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO logs (session_id, ts, type, content) VALUES (?, ?, ?, ?)",
            (session_id, ts.isoformat(), type, content),
        )
        return cur.lastrowid


def get_logs(session_id: str, after_id: int = 0, limit: int = 5000) -> list[dict]:
    with _conn() as c:
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


def get_logs_before(session_id: str, before_id: int, limit: int = 500) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM logs WHERE session_id = ? AND id < ? ORDER BY id DESC LIMIT ?",
            (session_id, before_id, limit),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]


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


def get_orchestrators() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM sessions WHERE is_orchestrator = 1 "
            "AND status IN ('starting', 'running', 'idle')"
        ).fetchall()
        return [dict(r) for r in rows]


def get_resumable_orchestrators() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM sessions WHERE is_orchestrator = 1 "
            "AND session_id IS NOT NULL AND status IN ('running', 'idle')"
        ).fetchall()
        return [dict(r) for r in rows]


def mark_stale_sessions(exclude_ids: list[str]) -> int:
    with _conn() as c:
        if exclude_ids:
            placeholders = ",".join("?" * len(exclude_ids))
            cur = c.execute(
                f"UPDATE sessions SET status = 'error' "
                f"WHERE status = 'running' AND is_orchestrator = 0 "
                f"AND id NOT IN ({placeholders})",
                exclude_ids,
            )
        else:
            cur = c.execute(
                "UPDATE sessions SET status = 'error' "
                "WHERE status = 'running' AND is_orchestrator = 0"
            )
        return cur.rowcount


def add_inbox(session_id: str, sender: str, message: str) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO inbox (session_id, sender, message, created_at) VALUES (?, ?, ?, ?)",
            (session_id, sender, message, datetime.now(timezone.utc).isoformat()),
        )
        return cur.lastrowid


def get_inbox(session_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM inbox WHERE session_id = ? AND status = 'pending' ORDER BY id ASC",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def ack_inbox(inbox_id: int) -> None:
    with _conn() as c:
        c.execute("UPDATE inbox SET status = 'delivered' WHERE id = ?", (inbox_id,))


def add_job(job_id: str, job_type: str, name: str, scope: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO jobs (id, type, name, scope, created_at) VALUES (?, ?, ?, ?, ?)",
            (job_id, job_type, name, scope, datetime.now(timezone.utc).isoformat()),
        )


def update_job(job_id: str, status: str, error: str | None = None) -> None:
    with _conn() as c:
        finished = datetime.now(timezone.utc).isoformat() if status in ("succeeded", "failed", "timed_out") else None
        c.execute(
            "UPDATE jobs SET status = ?, error = ?, finished_at = ? WHERE id = ?",
            (status, error, finished, job_id),
        )


def get_jobs(scope: str | None = None, status: str | None = None) -> list[dict]:
    with _conn() as c:
        query = "SELECT * FROM jobs"
        params = []
        clauses = []
        if scope:
            clauses.append("scope = ?")
            params.append(scope)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at DESC LIMIT 20"
        return [dict(r) for r in c.execute(query, params).fetchall()]


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


def bg_claim_trigger(job_id: str) -> bool:
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


def bg_get_active_for_scope(scope: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM bg_jobs WHERE target_scope=? AND status IN ('active','triggering')",
            (scope,),
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


# ── Usage Snapshots ──

def usage_save_snapshot(five_hour_pct: float, seven_day_pct: float,
                        five_hour_resets_at: str, seven_day_resets_at: str,
                        total_cost_usd: float, active_agents: int) -> None:
    with _conn() as c:
        c.execute(
            """INSERT INTO usage_snapshots
               (ts, five_hour_pct, seven_day_pct, five_hour_resets_at,
                seven_day_resets_at, total_cost_usd, active_agents)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (datetime.now(timezone.utc).isoformat(),
             five_hour_pct, seven_day_pct,
             five_hour_resets_at or "", seven_day_resets_at or "",
             total_cost_usd, active_agents),
        )


def usage_get_history(hours: int = 24) -> list[dict]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM usage_snapshots WHERE ts > ? ORDER BY ts ASC",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]


def usage_cleanup_old(days: int = 30) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _conn() as c:
        cur = c.execute("DELETE FROM usage_snapshots WHERE ts < ?", (cutoff,))
        return cur.rowcount
