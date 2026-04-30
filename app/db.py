"""SQLite storage for sessions and logs."""

import sqlite3
from datetime import datetime
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
        """)


def save_session(s: dict) -> None:
    with _conn() as c:
        c.execute("""
            INSERT INTO sessions (id, name, scope, cwd, model, system_prompt,
                status, session_id, cost_usd, worktree_path, branch, is_orchestrator,
                created_at, finished_at)
            VALUES (:id, :name, :scope, :cwd, :model, :system_prompt,
                :status, :session_id, :cost_usd, :worktree_path, :branch, :is_orchestrator,
                :created_at, :finished_at)
            ON CONFLICT(id) DO UPDATE SET
                status=excluded.status,
                session_id=excluded.session_id,
                cost_usd=excluded.cost_usd,
                worktree_path=excluded.worktree_path,
                branch=excluded.branch,
                cwd=excluded.cwd,
                finished_at=excluded.finished_at
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


def get_logs(session_id: str, after_id: int = 0, limit: int = 200) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM logs WHERE session_id = ? AND id > ? ORDER BY id ASC LIMIT ?",
            (session_id, after_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


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
