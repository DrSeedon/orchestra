"""Durable-тег пользователя: единственное, что пережило портфельный слой.

Портфель (проекты, цели, ожидания, сторож застоя) снесён в V-576: 0 проектов,
0 целей, 0 ожиданий за всё время и ни одного вызова `project_goal`/`project_wait`
в проде. `notify_user` — наоборот, живой (17 вызовов, последний 11.09.2026), и его
durable-квитанция лежала внутри того же модуля. Здесь она и осталась.

Квитанция нужна не для красоты: `app/tg_bridge.py` по ней отличает настоящий тег
от текста `ATTENTION_DURABLE:...`, который модель может просто напечатать.
"""
from __future__ import annotations

from datetime import datetime, timezone
import sqlite3
import uuid

from app import db


KINDS = frozenset({"legacy", "incident", "reversal", "plan_change", "waiting"})


class AttentionError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _session(conn: sqlite3.Connection, session_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM sessions WHERE id=? AND status!='archived'", (session_id,)
    ).fetchone()
    if row is None:
        raise AttentionError(403, "session is not active")
    return row


def create_attention(session_id: str, reason: str, *, kind: str = "legacy") -> dict:
    reason = reason.strip()
    if not reason:
        raise AttentionError(422, "attention reason is required")
    if kind not in KINDS:
        raise AttentionError(422, f"attention kind must be {'|'.join(sorted(KINDS))}")
    event_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    with db._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        actor = _session(conn, session_id)
        if actor["role"] not in {"orchestrator", "sub-orchestrator"}:
            raise AttentionError(403, "attention is orchestrator-only")
        conn.execute(
            """INSERT INTO attention_events(
                   id,kind,reason,source_session_id,created_at)
               VALUES(?,?,?,?,?)""",
            (event_id, kind, reason, session_id, created_at),
        )
    return {
        "ok": True,
        "event_id": event_id,
        "kind": kind,
        "reason": reason,
        "created_at": created_at,
    }


def get_attention_event(event_id: str) -> dict | None:
    with db._conn() as conn:
        row = conn.execute(
            "SELECT * FROM attention_events WHERE id=?", (event_id,)
        ).fetchone()
        return dict(row) if row else None
