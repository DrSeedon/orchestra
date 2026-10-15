"""Durable, owner-decided follow-up task cards proposed by orchestrators."""

from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
import uuid

from app import db


def ensure_schema(connection: sqlite3.Connection | None = None) -> None:
    ddl = """
    CREATE TABLE IF NOT EXISTS task_proposals (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        summary TEXT NOT NULL,
        project TEXT NOT NULL,
        model TEXT NOT NULL,
        quota_pool TEXT NOT NULL CHECK(quota_pool IN ('Claude','Codex')),
        status TEXT NOT NULL DEFAULT 'proposed'
            CHECK(status IN ('proposed','approving','approved','rejected')),
        created_at TEXT NOT NULL,
        decided_at TEXT NOT NULL DEFAULT '',
        approval_delivery_id TEXT NOT NULL UNIQUE,
        decision_action TEXT NOT NULL DEFAULT '',
        decision_message TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_task_proposals_session_created
        ON task_proposals(session_id, created_at DESC);
    """
    if connection is None:
        with db._conn() as owned:
            owned.executescript(ddl)
            _ensure_decision_columns(owned)
    else:
        connection.executescript(ddl)
        _ensure_decision_columns(connection)


def _ensure_decision_columns(connection: sqlite3.Connection) -> None:
    columns = {row[1] for row in connection.execute("PRAGMA table_info(task_proposals)").fetchall()}
    if "decision_action" not in columns:
        connection.execute("ALTER TABLE task_proposals ADD COLUMN decision_action TEXT NOT NULL DEFAULT ''")
    if "decision_message" not in columns:
        connection.execute("ALTER TABLE task_proposals ADD COLUMN decision_message TEXT NOT NULL DEFAULT ''")
    connection.execute(
        """UPDATE task_proposals
           SET decision_action='approve',
               decision_message='владелец одобрил: ' || title || ' — ' || summary
           WHERE status='approving' AND decision_action=''"""
    )


def _check_text(value: str, label: str, max_length: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")
    value = value.strip()
    if not value:
        raise ValueError(f"{label} is required")
    if len(value) > max_length:
        raise ValueError(f"{label} must be at most {max_length} characters")
    return value


def create(
    session_id: str, *, title: str, summary: str, project: str,
    model: str, quota_pool: str,
) -> dict:
    title = _check_text(title, "title", 160)
    summary = _check_text(summary, "summary", 600)
    project = _check_text(project, "project", 120)
    model = _check_text(model, "model", 120)
    quota_pool = _check_text(quota_pool, "quota_pool", 20)
    if quota_pool not in {"Claude", "Codex"}:
        raise ValueError("quota_pool must be Claude or Codex")
    proposal_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    delivery_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"orchestra-task-proposal:{proposal_id}:approval"))
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        actor = connection.execute(
            "SELECT id,name,scope,role,is_orchestrator,status FROM sessions WHERE id=?",
            (session_id,),
        ).fetchone()
        if actor is None or actor["status"] == "archived":
            raise ValueError("proposing session is not active")
        if not (actor["is_orchestrator"] or actor["role"] in {"orchestrator", "sub-orchestrator"}):
            raise PermissionError("Only orchestrator sessions may propose follow-up tasks")
        connection.execute(
            """INSERT INTO task_proposals(
                   id,session_id,title,summary,project,model,quota_pool,status,
                   created_at,approval_delivery_id)
               VALUES(?,?,?,?,?,?,?,'proposed',?,?)""",
            (proposal_id, session_id, title, summary, project, model, quota_pool, now, delivery_id),
        )
        row = connection.execute("SELECT * FROM task_proposals WHERE id=?", (proposal_id,)).fetchone()
    return dict(row)


def list_for_session(session_id: str) -> list[dict]:
    ensure_schema()
    with db._conn() as connection:
        rows = connection.execute(
            "SELECT * FROM task_proposals WHERE session_id=? ORDER BY created_at DESC,id DESC",
            (session_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get(proposal_id: str, *, connection: sqlite3.Connection | None = None) -> dict | None:
    if connection is not None:
        row = connection.execute("SELECT * FROM task_proposals WHERE id=?", (proposal_id,)).fetchone()
        return dict(row) if row else None
    with db._conn() as owned:
        return get(proposal_id, connection=owned)


def format_decision_message(proposal: dict, *, action: str, reason: str = "") -> str:
    if action == "approve":
        message = f"владелец одобрил: {proposal['title']} — {proposal['summary']}"
    elif action == "reject":
        message = f"владелец отклонил: {proposal['title']}"
    else:
        raise ValueError("action must be approve or reject")
    if reason:
        message += f"\nПричина / указания владельца: {reason}"
    return message


def begin_decision(proposal_id: str, *, action: str, reason: str = "") -> dict | None:
    """Reserve one owner decision and bind retries to its original message."""
    if action not in {"approve", "reject"}:
        raise ValueError("action must be approve or reject")
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT * FROM task_proposals WHERE id=?", (proposal_id,)).fetchone()
        if row is None:
            return None
        message = format_decision_message(dict(row), action=action, reason=reason)
        if row["status"] == "proposed":
            connection.execute(
                """UPDATE task_proposals SET status='approving',decision_action=?,decision_message=?
                   WHERE id=? AND status='proposed'""",
                (action, message, proposal_id),
            )
            row = connection.execute("SELECT * FROM task_proposals WHERE id=?", (proposal_id,)).fetchone()
        elif row["status"] == "approving":
            pass
        else:
            return dict(row)
        return dict(row)


def finish_decision(proposal_id: str, *, delivered: bool) -> dict | None:
    now = datetime.now(timezone.utc).isoformat()
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT * FROM task_proposals WHERE id=?", (proposal_id,)).fetchone()
        if row is None:
            return None
        if row["status"] == "approving":
            status = ("approved" if row["decision_action"] == "approve" else "rejected") if delivered else "proposed"
            action = row["decision_action"] if delivered else ""
            message = row["decision_message"] if delivered else ""
            connection.execute(
                """UPDATE task_proposals
                   SET status=?,decided_at=?,decision_action=?,decision_message=?
                   WHERE id=? AND status='approving'""",
                (status, now if delivered else "", action, message, proposal_id),
            )
        row = connection.execute("SELECT * FROM task_proposals WHERE id=?", (proposal_id,)).fetchone()
        return dict(row) if row else None


def rotate_unsent_decision(proposal_id: str, previous_delivery_id: str) -> dict | None:
    """A known-unsent decision may change its text only under a fresh delivery ID."""
    delivery_id = str(uuid.uuid4())
    with db._conn() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """UPDATE task_proposals SET approval_delivery_id=?
               WHERE id=? AND status='approving' AND approval_delivery_id=?""",
            (delivery_id, proposal_id, previous_delivery_id),
        )
        row = connection.execute("SELECT * FROM task_proposals WHERE id=?", (proposal_id,)).fetchone()
        return dict(row) if row else None
