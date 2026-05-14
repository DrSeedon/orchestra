"""SQLite storage for sessions and logs."""

import sqlite3
from datetime import datetime, timezone
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
                scope TEXT UNIQUE,
                yougile_project_id TEXT,
                yougile_board_id TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tm_par_sequence (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                next_value INTEGER NOT NULL DEFAULT 1
            );
            INSERT OR IGNORE INTO tm_par_sequence (id, next_value) VALUES (1, 1);
            CREATE TABLE IF NOT EXISTS tm_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                par_number INTEGER NOT NULL UNIQUE,
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
                CHECK (status IN ('backlog','new','in_progress','done','paid','cancelled')),
                CHECK (paid_rub <= price_rub)
            );
            CREATE INDEX IF NOT EXISTS idx_tm_tasks_status ON tm_tasks(status);
            CREATE INDEX IF NOT EXISTS idx_tm_tasks_project ON tm_tasks(project_id, status);
            CREATE INDEX IF NOT EXISTS idx_tm_tasks_par ON tm_tasks(par_number);
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


def save_session(s: dict) -> None:
    s.setdefault("context_pct", 0)
    s.setdefault("context_tokens", 0)
    s.setdefault("progress_pct", 0)
    s.setdefault("progress_status", "")
    s.setdefault("backend_type", "claude")
    with _conn() as c:
        c.execute("""
            INSERT INTO sessions (id, name, scope, cwd, model, system_prompt,
                status, session_id, cost_usd, worktree_path, branch, is_orchestrator,
                color, created_at, finished_at, context_pct, context_tokens,
                progress_pct, progress_status, backend_type)
            VALUES (:id, :name, :scope, :cwd, :model, :system_prompt,
                :status, :session_id, :cost_usd, :worktree_path, :branch, :is_orchestrator,
                :color, :created_at, :finished_at, :context_pct, :context_tokens,
                :progress_pct, :progress_status, :backend_type)
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                system_prompt=excluded.system_prompt,
                status=excluded.status,
                session_id=excluded.session_id,
                cost_usd=excluded.cost_usd,
                worktree_path=excluded.worktree_path,
                branch=excluded.branch,
                cwd=excluded.cwd,
                color=excluded.color,
                finished_at=excluded.finished_at,
                context_pct=excluded.context_pct,
                context_tokens=excluded.context_tokens,
                progress_pct=excluded.progress_pct,
                progress_status=excluded.progress_status,
                backend_type=excluded.backend_type
        """, s)


def get_session(session_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None


def get_session_by_name(name: str, scope: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM sessions WHERE name = ? AND scope = ?", (name, scope)
        ).fetchone()
        return dict(row) if row else None


def get_all_sessions(scope: str | None = None) -> list[dict]:
    with _conn() as c:
        if scope:
            rows = c.execute(
                "SELECT * FROM sessions WHERE scope = ? ORDER BY created_at DESC", (scope,)
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM sessions ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def rename_session(session_id: str, new_name: str) -> None:
    with _conn() as c:
        c.execute("UPDATE sessions SET name = ? WHERE id = ?", (new_name, session_id))


def delete_session(session_id: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM sessions WHERE id = ?", (session_id,))


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
        return {
            "total_sessions": total,
            "active": active,
            "total_cost_usd": round(cost, 4),
            "total_logs": total_logs,
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
