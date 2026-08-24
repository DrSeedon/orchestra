"""Mechanical regressions for owner-approved post-review #380 fixes."""

import json
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


DELIVERY_ID = "abcdefab-cdef-4abc-8def-abcdefabcdef"


def _session(session_id: str, name: str, *, role: str = "worker") -> dict:
    return {
        "id": session_id,
        "name": name,
        "scope": "/scope-380-review",
        "cwd": "/tmp",
        "model": "gpt-5.6-sol",
        "system_prompt": "",
        "status": "idle",
        "session_id": None,
        "cost_usd": 0.0,
        "worktree_path": "/tmp",
        "branch": f"task-380/{name}",
        "base_branch": "main",
        "needs_switch": 0,
        "task_id": "380",
        "role": role,
        "is_orchestrator": role == "orchestrator",
        "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    }


def _install_previous_schema(db) -> int:
    db.init_db()
    db.save_session(_session("target-review-380", "target-review-380"))
    with db._conn() as connection:
        log_id = connection.execute(
            """INSERT INTO logs(session_id, ts, type, content)
               VALUES ('target-review-380', ?, 'user_message', 'review')""",
            (datetime.now(timezone.utc).isoformat(),),
        ).lastrowid
        connection.execute("DROP TABLE message_deliveries")
        connection.execute("""CREATE TABLE message_deliveries (
            accept_seq INTEGER PRIMARY KEY AUTOINCREMENT,
            delivery_id TEXT NOT NULL UNIQUE,
            schema_version INTEGER NOT NULL,
            source_session_id TEXT,
            source_principal TEXT NOT NULL,
            source_name TEXT NOT NULL,
            source_scope TEXT NOT NULL,
            source_task_id TEXT NOT NULL,
            target_session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            target_name TEXT NOT NULL,
            target_scope TEXT NOT NULL,
            target_task_id TEXT NOT NULL,
            target_generation TEXT NOT NULL,
            message TEXT NOT NULL,
            rendered_message TEXT NOT NULL,
            message_kind TEXT,
            wake INTEGER NOT NULL,
            payload_hash TEXT NOT NULL,
            state TEXT NOT NULL,
            user_log_id INTEGER UNIQUE REFERENCES logs(id),
            provider_ref TEXT,
            error_json TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""")
        connection.execute(
            "CREATE INDEX idx_message_deliveries_target_seq "
            "ON message_deliveries(target_session_id, accept_seq)"
        )
        connection.execute(
            "CREATE INDEX idx_message_deliveries_source_seq "
            "ON message_deliveries(source_session_id, accept_seq)"
        )
        now = datetime.now(timezone.utc).isoformat()
        connection.execute(
            """INSERT INTO message_deliveries VALUES (
                7, ?, 1, NULL, 'operator:review', '', '/scope-380-review', '',
                'target-review-380', 'target-review-380', '/scope-380-review', '380',
                'generation', 'review', 'review', NULL, 1, 'hash', 'SUBMITTED', ?,
                'native-review', NULL, ?, ?
            )""",
            (DELIVERY_ID, log_id, now, now),
        )
    return log_id


def test_t380_review_migration_copy_failure_rolls_back_then_cleanly_retries(
    tmp_path, monkeypatch,
):
    from app import db

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "migration-review.db")
    log_id = _install_previous_schema(db)
    connection = db._conn()

    class FailCopyOnce:
        def __init__(self, inner):
            self.inner = inner
            self.failed = False

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def execute(self, sql, *args):
            normalized = " ".join(str(sql).split()).upper()
            if (
                not self.failed
                and normalized.startswith("INSERT INTO MESSAGE_DELIVERIES (")
            ):
                self.failed = True
                raise sqlite3.OperationalError("synthetic receipt copy failure")
            return self.inner.execute(sql, *args)

    proxy = FailCopyOnce(connection)
    with pytest.raises(sqlite3.OperationalError, match="synthetic receipt copy failure"):
        db._migrate_message_deliveries(proxy)

    tables = {
        row["name"]: row["sql"]
        for row in connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table'"
        )
    }
    assert "message_deliveries" in tables
    assert "message_deliveries_pre_380_fix" not in tables
    assert "ON DELETE CASCADE" in tables["message_deliveries"]
    row = dict(connection.execute(
        "SELECT accept_seq, delivery_id, state, user_log_id FROM message_deliveries"
    ).fetchone())
    assert row == {
        "accept_seq": 7,
        "delivery_id": DELIVERY_ID,
        "state": "SUBMITTED",
        "user_log_id": log_id,
    }

    db._migrate_message_deliveries(connection)
    db._migrate_message_deliveries(connection)
    foreign_keys = {
        (row["from"], row["table"], row["on_delete"])
        for row in connection.execute(
            "PRAGMA foreign_key_list(message_deliveries)"
        ).fetchall()
    }
    assert not any(column == "target_session_id" for column, _table, _delete in foreign_keys)
    assert ("user_log_id", "logs", "SET NULL") in foreign_keys
    indexes = {
        row["name"] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='message_deliveries'"
        )
    }
    assert {
        "idx_message_deliveries_target_seq",
        "idx_message_deliveries_source_seq",
    } <= indexes
    assert dict(connection.execute(
        "SELECT accept_seq, delivery_id, state, user_log_id FROM message_deliveries"
    ).fetchone()) == row
    connection.close()


@pytest.mark.asyncio
async def test_t380_review_existing_key_rejects_wrong_route_but_survives_target_lifecycle(
    tmp_path, monkeypatch,
):
    from app import db, message_deliveries
    from app.mcp_proof import issue_mcp_proof
    from app.routes import sessions as routes

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "route-review.db")
    db.init_db()
    db.save_session(_session("source-review-380", "source-review-380", role="orchestrator"))
    db.save_session(_session("target-review-380", "target-review-380"))
    target = SimpleNamespace(
        id="target-review-380",
        name="target-review-380",
        scope="/scope-380-review",
        task_id="380",
        branch="task-380/target-review-380",
        needs_switch=False,
    )
    monkeypatch.setattr(
        routes.manager,
        "get_by_name",
        lambda name, _scope: target if name == "target-review-380" else None,
    )
    wakes = []
    monkeypatch.setattr(
        message_deliveries,
        "ensure_target_runner",
        lambda target_id: wakes.append(target_id),
    )
    proof = issue_mcp_proof("source-review-380")
    request = SimpleNamespace(
        headers={
            "x-orchestra-session-id": "source-review-380",
            "x-orchestra-mcp-proof": proof,
        },
        cookies={},
    )

    async def post(name: str):
        response = await routes.send_message(
            name,
            routes.SendRequest(
                delivery_id=DELIVERY_ID,
                message="same message",
                sender="source-review-380",
                scope="/scope-380-review",
            ),
            request=request,
        )
        return response, json.loads(response.body)

    accepted, accepted_payload = await post("target-review-380")
    assert accepted.status_code == 202
    assert accepted_payload["acceptance"] == "ACCEPTED"
    assert wakes == ["target-review-380"]
    before = dict(message_deliveries._row(DELIVERY_ID))

    wrong, wrong_payload = await post("different-route-target")
    assert wrong.status_code == 409
    assert wrong_payload["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert wrong_payload["error"]["outcome_unknown"] is False
    assert dict(message_deliveries._row(DELIVERY_ID)) == before
    assert wakes == ["target-review-380"]

    with db._conn() as connection:
        connection.execute(
            "UPDATE sessions SET name='renamed-target-review-380' "
            "WHERE id='target-review-380'"
        )
    monkeypatch.setattr(routes.manager, "get_by_name", lambda *_args: None)
    renamed, renamed_payload = await post("target-review-380")
    assert renamed.status_code == 202
    assert renamed_payload["acceptance"] == "ALREADY_ACCEPTED"

    with db._conn() as connection:
        connection.execute("DELETE FROM sessions WHERE id='target-review-380'")
    deleted, deleted_payload = await post("target-review-380")
    assert deleted.status_code == 202
    assert deleted_payload["acceptance"] == "ALREADY_ACCEPTED"
    assert deleted_payload["delivery_id"] == DELIVERY_ID
    assert dict(message_deliveries._row(DELIVERY_ID)) == before
    assert wakes == ["target-review-380"]
