import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/migrate_message_provenance_433.py"


def _database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE sessions (id TEXT PRIMARY KEY, name TEXT, scope TEXT);
            CREATE TABLE logs (
                id INTEGER PRIMARY KEY, type TEXT, content TEXT,
                origin TEXT, origin_detail TEXT
            );
            CREATE TABLE initial_deliveries (
                delivery_id TEXT, schema_version INTEGER, session_id TEXT,
                worker_name TEXT, scope TEXT, sender TEXT, message TEXT,
                user_log_id INTEGER, origin TEXT, origin_detail TEXT, payload_hash TEXT
            );
            CREATE TABLE message_deliveries (
                delivery_id TEXT, schema_version INTEGER, source_session_id TEXT,
                source_principal TEXT, source_name TEXT, source_scope TEXT,
                source_task_id TEXT, target_session_id TEXT, target_name TEXT,
                target_scope TEXT, target_task_id TEXT, target_generation TEXT,
                message TEXT, rendered_message TEXT, message_kind TEXT, wake INTEGER,
                user_log_id INTEGER, origin TEXT, origin_detail TEXT, payload_hash TEXT
            );
            INSERT INTO sessions VALUES ('s', 's', '/scope');
            INSERT INTO logs VALUES (
                1, 'user_message', '[12:34] historical user',
                'unknown', '{"senders":["unknown"]}'
            );
            """
        )


def _run(db_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--db", str(db_path), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_t5_manifest_drift_refuses_without_mutating(tmp_path):
    target = tmp_path / "target.db"
    manifest = tmp_path / "drift.json"
    _database(target)
    manifest.write_text(json.dumps({"migration_id": "changed"}), encoding="utf-8")

    result = _run(target, "--manifest", str(manifest))

    assert result.returncode != 0
    assert "manifest drift" in result.stderr
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT origin FROM logs").fetchone()[0] == "unknown"


def test_t5_existing_backup_is_never_overwritten(tmp_path):
    target = tmp_path / "target.db"
    backup = tmp_path / "protected.db"
    _database(target)
    backup.write_bytes(b"protected-backup")

    result = _run(target, "--apply", "--backup", str(backup))

    assert result.returncode != 0
    assert "backup path already exists" in result.stderr
    assert backup.read_bytes() == b"protected-backup"
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT origin FROM logs").fetchone()[0] == "unknown"


def test_t5_symlink_backup_alias_is_refused(tmp_path):
    target = tmp_path / "target.db"
    alias = tmp_path / "alias.db"
    _database(target)
    os.symlink(target, alias)

    result = _run(target, "--apply", "--backup", str(alias))

    assert result.returncode != 0
    assert "backup path aliases the database path" in result.stderr
    with sqlite3.connect(target) as connection:
        assert connection.execute("SELECT origin FROM logs").fetchone()[0] == "unknown"


def test_t5_timestamped_agent_prefix_is_not_migrated_as_user(tmp_path):
    target = tmp_path / "target.db"
    _database(target)
    with sqlite3.connect(target) as connection:
        connection.execute(
            "UPDATE logs SET content='[12:34] [from:agent-433] historical report'"
        )

    result = _run(target)

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout.splitlines()[-1])
    assert summary["counts"]["agent"] == 1
    assert summary["counts"]["user"] == 0


def test_t5_raise_ignore_rolls_back_every_update_and_receipt(tmp_path):
    target = tmp_path / "target.db"
    _database(target)
    with sqlite3.connect(target) as connection:
        connection.execute(
            "INSERT INTO logs VALUES (2,'user_message','[system] historical',"
            "'unknown','{\"senders\":[\"unknown\"]}')"
        )
        connection.execute(
            "CREATE TRIGGER ignore_one_433 BEFORE UPDATE OF origin ON logs "
            "WHEN OLD.id=2 BEGIN SELECT RAISE(IGNORE); END"
        )

    result = _run(target, "--apply")

    assert result.returncode != 0
    with sqlite3.connect(target) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM logs WHERE origin='unknown'"
        ).fetchone()[0] == 2
        assert connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
            "AND name='message_provenance_migrations'"
        ).fetchone()[0] == 0


def test_t5_matching_receipt_short_circuits_before_existing_backup(tmp_path):
    target = tmp_path / "target.db"
    backup = tmp_path / "before.db"
    _database(target)
    first = _run(target, "--apply", "--backup", str(backup))
    assert first.returncode == 0, first.stderr
    with sqlite3.connect(target) as connection:
        connection.execute(
            "INSERT INTO logs VALUES (2,'user_message','[12:34] [from:text-lies] new B1',"
            "'agent','{\"senders\":[\"real-agent\"]}')"
        )

    second = _run(target, "--apply", "--backup", str(backup))

    assert second.returncode == 0, second.stderr
    summary = json.loads(second.stdout.splitlines()[-1])
    assert summary["updated"] == 0 and summary["would_update"] == 0
    with sqlite3.connect(target) as connection:
        assert connection.execute(
            "SELECT origin FROM logs WHERE id=2"
        ).fetchone()[0] == "agent"
