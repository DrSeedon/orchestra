"""SQLite storage for workers, logs, stats."""

import sqlite3
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "orchestra.db"


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS workers (
                name TEXT PRIMARY KEY,
                task TEXT NOT NULL,
                repo_path TEXT NOT NULL,
                branch TEXT DEFAULT '',
                model TEXT DEFAULT 'claude-sonnet-4-6',
                status TEXT DEFAULT 'pending',
                worktree_path TEXT DEFAULT '',
                session_id TEXT,
                cost_usd REAL DEFAULT 0.0,
                context_pct REAL DEFAULT 0.0,
                created_at TEXT NOT NULL,
                finished_at TEXT,
                system_prompt TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_name TEXT NOT NULL,
                ts TEXT NOT NULL,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                FOREIGN KEY (worker_name) REFERENCES workers(name)
            );
            CREATE INDEX IF NOT EXISTS idx_logs_worker ON logs(worker_name);
        """)
        try:
            c.execute("ALTER TABLE workers ADD COLUMN system_prompt TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        c.execute("""
            CREATE TABLE IF NOT EXISTS callbacks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_name TEXT NOT NULL,
                ts TEXT NOT NULL,
                message TEXT NOT NULL,
                read INTEGER DEFAULT 0
            )
        """)


def save_worker(w) -> None:
    with _conn() as c:
        c.execute("""
            INSERT OR REPLACE INTO workers (name, task, repo_path, branch, model, status,
                worktree_path, session_id, cost_usd, context_pct, created_at, finished_at, system_prompt)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (w.name, w.task, w.repo_path, w.branch, w.model, w.status.value,
              w.worktree_path, w.session_id, w.cost_usd, w.context_pct,
              w.created_at.isoformat(),
              datetime.utcnow().isoformat() if w.status.value in ('done', 'error', 'killed') else None,
              w.system_prompt or ''))


def add_log(worker_name: str, ts: datetime, type: str, content: str) -> None:
    with _conn() as c:
        c.execute("INSERT INTO logs (worker_name, ts, type, content) VALUES (?, ?, ?, ?)",
                  (worker_name, ts.isoformat(), type, content))


def get_all_workers() -> list[dict]:
    with _conn() as c:
        rows = c.execute("""
            SELECT w.*,
                (SELECT COUNT(*) FROM logs WHERE worker_name = w.name) as logs_count,
                (SELECT content FROM logs WHERE worker_name = w.name ORDER BY id DESC LIMIT 1) as last_log
            FROM workers w ORDER BY w.created_at DESC
        """).fetchall()
        return [dict(r) for r in rows]


def get_worker(name: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM workers WHERE name = ?", (name,)).fetchone()
        return dict(row) if row else None


def get_worker_logs(name: str, limit: int = 100) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT ts, type, content FROM logs WHERE worker_name = ? ORDER BY id DESC LIMIT ?",
            (name, limit)
        ).fetchall()
        return [dict(r) for r in reversed(rows)]


def delete_worker(name: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM logs WHERE worker_name = ?", (name,))
        c.execute("DELETE FROM workers WHERE name = ?", (name,))


def get_stats() -> dict:
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) FROM workers").fetchone()[0]
        active = c.execute("SELECT COUNT(*) FROM workers WHERE status IN ('working', 'spawning')").fetchone()[0]
        done = c.execute("SELECT COUNT(*) FROM workers WHERE status = 'done'").fetchone()[0]
        errors = c.execute("SELECT COUNT(*) FROM workers WHERE status = 'error'").fetchone()[0]
        total_cost = c.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM workers").fetchone()[0]
        total_logs = c.execute("SELECT COUNT(*) FROM logs").fetchone()[0]
        return {
            "total_workers": total, "active": active, "done": done,
            "errors": errors, "total_cost_usd": round(total_cost, 4),
            "total_logs": total_logs,
        }


def add_callback(worker_name: str, message: str) -> int:
    with _conn() as c:
        cur = c.execute("INSERT INTO callbacks (worker_name, ts, message) VALUES (?, ?, ?)",
                        (worker_name, datetime.utcnow().isoformat(), message))
        return cur.lastrowid


def get_unread_callbacks() -> list[dict]:
    with _conn() as c:
        rows = c.execute("SELECT * FROM callbacks WHERE read = 0 ORDER BY id").fetchall()
        return [dict(r) for r in rows]


def mark_callbacks_read() -> int:
    with _conn() as c:
        cur = c.execute("UPDATE callbacks SET read = 1 WHERE read = 0")
        return cur.rowcount


init_db()
