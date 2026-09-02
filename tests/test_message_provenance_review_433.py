import pytest
import sqlite3
import json


def test_review_storage_requires_senders_json_array():
    from app.events import MessageProvenance

    with pytest.raises(ValueError, match="array"):
        MessageProvenance.from_storage(
            "user", {"senders": {"alice": True}},
        )


def test_review_db_projection_rejects_missing_or_corrupt_provenance():
    from app.db import _decode_log_provenance

    with pytest.raises(ValueError):
        _decode_log_provenance({"id": 1, "origin": "user"})
    with pytest.raises(ValueError):
        _decode_log_provenance({
            "id": 2,
            "origin": "user",
            "origin_detail": {"senders": {"alice": True}},
        })


def test_review_rag_rejects_corrupt_user_provenance_atomically():
    from app.rag import _classify_log

    with pytest.raises(ValueError):
        _classify_log(
            "user_message", "body", origin="user",
            origin_detail={"senders": {"attacker": True}},
        )


def test_review_legacy_senderless_mailbox_is_unknown(tmp_path, monkeypatch):
    from app import db

    target = tmp_path / "legacy-mailbox-433.db"
    with sqlite3.connect(target) as connection:
        connection.execute(
            """CREATE TABLE mailbox (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   recipient TEXT NOT NULL, scope TEXT NOT NULL,
                   sender TEXT NOT NULL, body TEXT NOT NULL,
                   created_at REAL NOT NULL, delivered_at REAL, claimed_at REAL
               )"""
        )
        connection.execute(
            "INSERT INTO mailbox(recipient,scope,sender,body,created_at) "
            "VALUES('worker','/scope','','legacy senderless',1.0)"
        )
    monkeypatch.setattr(db, "DB_PATH", target)

    db.init_db()

    with db._conn() as connection:
        row = connection.execute(
            "SELECT origin,origin_detail FROM mailbox WHERE id=1"
        ).fetchone()
    assert row["origin"] == "unknown"
    assert '"unknown"' in row["origin_detail"]


def test_review_manifest_is_rechecked_under_write_lock(tmp_path, monkeypatch):
    from scripts import migrate_message_provenance_433 as migration
    from tests.test_message_provenance_migration_433 import _database

    target = tmp_path / "manifest-race-433.db"
    backup = tmp_path / "manifest-race-433.backup"
    _database(target)
    checks = []
    backups = []

    def check(_connection):
        checks.append(len(checks) + 1)
        if len(checks) == 2:
            raise ValueError("manifest drift under lock")
        return False

    monkeypatch.setattr(migration, "_check_manifest_receipt", check)
    monkeypatch.setattr(
        migration, "_backup_database",
        lambda *_args: backups.append(True),
    )

    with pytest.raises(ValueError, match="under lock"):
        migration.migrate_database(target, apply=True, backup_path=backup)
    assert checks == [1, 2]
    assert backups == []


def test_review_receipt_hash_is_validated_before_commit(tmp_path):
    from tests.test_message_provenance_migration_433 import _database, _run

    target = tmp_path / "receipt-hash-433.db"
    _database(target)
    delivery_id = "00000000-0000-4000-8000-000000004399"
    with sqlite3.connect(target) as connection:
        connection.execute(
            """INSERT INTO initial_deliveries(
                   delivery_id,schema_version,session_id,worker_name,scope,
                   sender,message,user_log_id,origin,origin_detail,payload_hash
               ) VALUES(?,1,'s','s','/scope','s','legacy',1,'unknown',
                        '{"senders":["unknown"]}','legacy-hash')""",
            (delivery_id,),
        )
        connection.execute(
            f"""CREATE TRIGGER corrupt_receipt_hash_433
               AFTER UPDATE OF schema_version ON initial_deliveries
               WHEN NEW.delivery_id='{delivery_id}'
               BEGIN
                 UPDATE initial_deliveries SET payload_hash='corrupt-after-update'
                  WHERE delivery_id=NEW.delivery_id;
               END"""
        )

    result = _run(target, "--apply")

    assert result.returncode != 0, (
        "#433 receipt upgrade validation missing at the receipt-update seam"
    )
    with sqlite3.connect(target) as connection:
        row = connection.execute(
            "SELECT schema_version,payload_hash FROM initial_deliveries WHERE delivery_id=?",
            (delivery_id,),
        ).fetchone()
        assert row == (1, "legacy-hash")


def test_review_receipt_hash_is_revalidated_after_log_triggers(tmp_path):
    from tests.test_message_provenance_migration_433 import _database, _run

    target = tmp_path / "receipt-hash-after-log-433.db"
    _database(target)
    delivery_id = "00000000-0000-4000-8000-000000004398"
    with sqlite3.connect(target) as connection:
        connection.execute(
            """INSERT INTO initial_deliveries(
                   delivery_id,schema_version,session_id,worker_name,scope,
                   sender,message,user_log_id,origin,origin_detail,payload_hash
               ) VALUES(?,1,'s','s','/scope','s','legacy',1,'unknown',
                        '{"senders":["unknown"]}','legacy-hash')""",
            (delivery_id,),
        )
        connection.execute(
            f"""CREATE TRIGGER corrupt_receipt_after_log_433
               AFTER UPDATE OF origin ON logs
               WHEN NEW.id=1
               BEGIN
                 UPDATE initial_deliveries SET payload_hash='corrupt-after-log'
                  WHERE delivery_id='{delivery_id}';
               END"""
        )

    result = _run(target, "--apply")

    assert result.returncode != 0, (
        "#433 final receipt validation missing after log-trigger writes"
    )
    with sqlite3.connect(target) as connection:
        row = connection.execute(
            "SELECT schema_version,payload_hash FROM initial_deliveries WHERE delivery_id=?",
            (delivery_id,),
        ).fetchone()
        assert row == (1, "legacy-hash")


@pytest.mark.asyncio
async def test_review_mailbox_preserves_durable_mixed_provenance(tmp_path, monkeypatch):
    from app import db, mailbox
    from app.events import MessageProvenance
    from app.session_turns import TurnManager

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "mailbox-review-433.db")
    db.init_db()
    mailbox.enqueue(
        recipient="target", scope="/scope", sender="agent-a", body="agent body",
        provenance=MessageProvenance(origin="agent", senders=("agent-a",)),
    )
    mailbox.enqueue(
        recipient="target", scope="/scope", sender="", body="user body",
        provenance=MessageProvenance(origin="user", senders=("user",)),
    )
    queued = mailbox.claim("target", "/scope")
    assert [row["provenance"].origin for row in queued] == ["agent", "user"]
    captured = []

    class Session:
        async def send(self, text, *, provenance):
            captured.append((text, provenance))

    await TurnManager(Session())._deliver_mailbox(queued)

    assert len(captured) == 1
    text, provenance = captured[0]
    assert "agent body" in text and "user body" in text
    assert provenance.origin == "unknown"
    assert provenance.senders == ("agent-a", "user")
    assert provenance.subtype == "mailbox_mixed"


@pytest.mark.asyncio
async def test_review_live_dashboard_cookie_delivers_user_origin(tmp_path, monkeypatch):
    from starlette.requests import Request
    from app import db
    from app.auth import create_session
    from app.routes import sessions as routes
    from tests.test_message_delivery_receipts_380 import _session_record

    monkeypatch.setenv("DASHBOARD_USER", "operator-433")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "secret-433")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "dashboard-live-433.db")
    db.init_db()
    token = create_session("operator-433")
    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/api/sessions/target/send",
        "headers": [(b"cookie", f"session={token}".encode())],
        "query_string": b"",
        "server": ("test", 80),
        "client": ("test", 1),
        "scheme": "http",
    })
    captured = []
    target = type("Target", (), {
        "id": "target-433", "name": "target", "scope": "/scope",
        "parent_name": "", "last_task_sender": "",
    })()
    db.save_session(_session_record(
        session_id=target.id, name=target.name, scope=target.scope,
    ))

    class Manager:
        sessions = {target.id: target}
        async def ensure_loaded(self, name, scope): return target
        async def ensure_loaded_any(self, name): return None
        async def send(self, session_id, message, *, provenance):
            captured.append((session_id, message, provenance))

    monkeypatch.setattr(routes, "manager", Manager())
    result = await routes.send_message(
        "target", routes.SendRequest(message="dashboard", scope="/scope"),
        request=request,
    )
    assert result["ok"] is True
    assert captured[0][2].origin == "user"
    assert captured[0][2].senders == ("user",)


@pytest.mark.asyncio
async def test_review_live_tg_bridge_bypasses_http_and_delivers_user_origin(monkeypatch):
    from app import tg_bridge

    captured = []

    class Manager:
        async def send(self, session_id, message, *, provenance):
            captured.append((session_id, message, provenance))

    monkeypatch.setattr(tg_bridge, "_manager", Manager())
    monkeypatch.setattr("app.main.mutating_admission_open", lambda: True)
    await tg_bridge._flush_batch("target-433", [(None, "telegram body", None)])
    assert captured[0][0] == "target-433"
    assert captured[0][2].origin == "user"
    assert captured[0][2].subtype == "telegram"


@pytest.mark.asyncio
async def test_review_live_mcp_receipt_persists_agent_principal(tmp_path, monkeypatch):
    from starlette.requests import Request
    from app import db, message_deliveries
    from app.mcp_proof import issue_mcp_proof
    from app.routes import sessions as routes
    from tests.test_message_delivery_receipts_380 import _session_record

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "mcp-live-433.db")
    db.init_db()
    source_id = "source-live-433"
    source_name = "source-live"
    target_id = "target-live-433"
    scope = "/scope-live-433"
    db.save_session(_session_record(
        session_id=source_id, name=source_name, scope=scope, role="orchestrator",
    ))
    db.save_session(_session_record(
        session_id=target_id, name="target-live", scope=scope,
        task_id="433", branch="task-433/target-live",
    ))
    target = type("Target", (), {
        "id": target_id, "name": "target-live", "scope": scope,
        "task_id": "433", "branch": "task-433/target-live", "needs_switch": False,
    })()

    class Manager:
        def get_by_name(self, name, requested_scope): return target
        async def preflight_message_delivery(self, session_id): return None

    monkeypatch.setattr(routes, "manager", Manager())
    monkeypatch.setattr(message_deliveries, "ensure_target_runner", lambda _id: None)
    proof = issue_mcp_proof(source_id)
    request = Request({
        "type": "http", "method": "POST", "path": "/send",
        "headers": [
            (b"x-orchestra-session-id", source_id.encode()),
            (b"x-orchestra-mcp-proof", proof.encode()),
        ],
        "query_string": b"", "server": ("test", 80),
        "client": ("test", 1), "scheme": "http",
    })
    delivery_id = "00000000-0000-4000-8000-000000004397"
    result = await routes.send_message(
        "target-live",
        routes.SendRequest(
            message="agent body", scope=scope, sender=source_name,
            delivery_id=delivery_id,
        ),
        request=request,
    )
    assert result.status_code == 202
    with db._conn() as connection:
        row = connection.execute(
            "SELECT source_principal,origin,origin_detail FROM message_deliveries "
            "WHERE delivery_id=?",
            (delivery_id,),
        ).fetchone()
    assert row["source_principal"] == f"mcp:{source_id}"
    assert row["origin"] == "agent"
    assert json.loads(row["origin_detail"])["senders"] == [source_name]
