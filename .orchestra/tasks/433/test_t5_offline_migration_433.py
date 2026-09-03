"""Frozen RED oracle for #433 T5: explicit-path CLI, rollback, WAL, precedence."""

import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/migrate_message_provenance_433.py"


def _session(session_id: str, name: str, scope: str = "/scope-433") -> dict:
    return {
        "id": session_id, "name": name, "scope": scope, "cwd": f"/tmp/{name}",
        "model": "gpt-5.6-sol", "system_prompt": "", "status": "idle",
        "session_id": None, "cost_usd": 0.0, "worktree_path": f"/tmp/{name}",
        "branch": f"task-433/{name}", "is_orchestrator": name == "orchestrator-433",
        "color": "", "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None, "parent_name": "orchestrator-433",
    }


def _summary(stdout: str) -> dict:
    lines = [line for line in stdout.splitlines() if line.strip()]
    assert lines, "#433 T5 CLI missing machine-readable summary"
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError as error:
        pytest.fail(f"#433 T5 CLI summary is not JSON: {error}: {lines[-1]!r}")


def _assert_complete_summary(summary, target: Path, *, mode: str, rows: int, sessions: int):
    required = {
        "mode", "target", "rows_before", "rows_after", "sessions_before",
        "sessions_after", "counts", "invalid", "would_update", "updated",
    }
    assert required <= set(summary), (
        "#433 T5 CLI counters incomplete: " + ", ".join(sorted(required - set(summary)))
    )
    assert summary["mode"] == mode
    assert summary["target"] == str(target.resolve())
    assert summary["rows_before"] == rows and summary["rows_after"] == rows
    assert summary["sessions_before"] == sessions and summary["sessions_after"] == sessions
    assert set(summary["counts"]) == {
        "user", "agent", "background_task", "platform", "system", "unknown"
    }
    assert sum(summary["counts"].values()) == rows
    assert summary["invalid"] == 0


def _run_cli(target: Path, decoy: Path, *args: str):
    env = os.environ.copy()
    env["ORCHESTRA_DB_PATH"] = str(decoy)
    env["PYTHONPATH"] = "."
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--db", str(target), *args],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=30,
    )


async def _build_target(db, initial_deliveries, message_deliveries):
    from app.events import MessageProvenance
    unknown = MessageProvenance(origin="unknown", senders=("unknown",))

    async def initial(delivery_id: str, sender: str, message: str):
        await initial_deliveries.accept_initial_delivery(
            delivery_id=delivery_id, session_id="target-433", worker_name="target-433",
            scope="/scope-433", sender=sender, message=message, provenance=unknown,
        )
        return initial_deliveries.prepare_initial_delivery(delivery_id)["user_log_id"]

    async def direct(delivery_id: str, principal: str, source_name: str, message: str):
        await message_deliveries.accept_message_delivery(
            delivery_id=delivery_id,
            source_session_id="sender-433" if principal.startswith("mcp:") else None,
            source_principal=principal, source_name=source_name, source_scope="/scope-433",
            target_session_id="target-433", target_name="target-433",
            target_scope="/scope-433",
            target_generation="session=target-433|task=|branch=task-433/target-433|needs_switch=0",
            message=message, rendered_message=message, provenance=unknown,
        )
        return message_deliveries.prepare_message_delivery(delivery_id)["user_log_id"]

    legacy_initial_match = "00000000-0000-4000-8000-000000004331"
    legacy_initial_mismatch = "00000000-0000-4000-8000-000000004332"
    legacy_direct_operator = "00000000-0000-4000-8000-000000004333"
    legacy_direct_mcp = "00000000-0000-4000-8000-000000004334"
    await initial(
        legacy_initial_match, "sender-433",
        "[12:34] RECEIPT-INITIAL-MATCH",
    )
    await initial(
        legacy_initial_mismatch, "ghost-433",
        "[from:fake-agent] RECEIPT-INITIAL-MISMATCH",
    )
    await direct(
        legacy_direct_operator, "operator:owner", "",
        "[from:fake-agent] RECEIPT-DIRECT-OPERATOR",
    )
    await direct(
        legacy_direct_mcp, "mcp:sender-433", "sender-433",
        "[12:34] RECEIPT-DIRECT-MCP",
    )
    await direct(
        "00000000-0000-4000-8000-000000004335",
        "mcp:sender-433", "sender-433",
        "[from:must-not-win] NEW-EXPLICIT-UNKNOWN",
    )

    # Only pre-B1 receipt schema is eligible for receipt-field reconstruction.
    # The fifth receipt stays on the new schema and proves explicit unknown is immutable.
    with db._conn() as connection:
        connection.execute(
            "UPDATE initial_deliveries SET schema_version=1 WHERE delivery_id IN (?,?)",
            (legacy_initial_match, legacy_initial_mismatch),
        )
        connection.execute(
            "UPDATE message_deliveries SET schema_version=1 WHERE delivery_id IN (?,?)",
            (legacy_direct_operator, legacy_direct_mcp),
        )

    legacy = {
        "[12:34] USER": "user",
        "[from TG:123] TG-USER": "user",
        "[from:sender-433] AGENT": "agent",
        "[Background job completed] BG": "background_task",
        "[Cron job fired] CRON": "background_task",
        "[Orchestra platform note: NOTE]": "platform",
        "[PREVIOUS CONTEXT SUMMARY — context was compacted]": "platform",
        "НЕДОСТАВКА: result": "platform",
        "BUG REPORT платформы: broken": "platform",
        "fan=platform-generated complete=true": "platform",
        "[system] Retrying after transient server error.": "system",
        "LIVE-USER-0": "unknown",
    }
    with db._conn() as connection:
        for content in legacy:
            connection.execute(
                "INSERT INTO logs(session_id,ts,type,content) VALUES(?,?,?,?)",
                ("target-433", datetime.now(timezone.utc).isoformat(), "user_message", content),
            )
        connection.execute(
            "UPDATE logs SET origin=?, origin_detail=?",
            ("unknown", json.dumps({"senders": ["unknown"]})),
        )
    return {
        **legacy,
        "[12:34] RECEIPT-INITIAL-MATCH": "agent",
        "[from:fake-agent] RECEIPT-INITIAL-MISMATCH": "unknown",
        "[from:fake-agent] RECEIPT-DIRECT-OPERATOR": "user",
        "[12:34] RECEIPT-DIRECT-MCP": "agent",
        "[from:must-not-win] NEW-EXPLICIT-UNKNOWN": "unknown",
    }


@pytest.mark.asyncio
async def test_t5_cli_is_explicit_dry_by_default_atomic_wal_safe_and_idempotent(
    tmp_path, monkeypatch,
):
    assert SCRIPT.exists(), (
        "#433 T5 missing behavior: offline provenance migration script is absent"
    )
    from app import db, initial_deliveries, message_deliveries

    target = tmp_path / "target-433.db"
    decoy = tmp_path / "decoy-global-433.db"
    backup = tmp_path / "before-apply-433.db"

    monkeypatch.setattr(db, "DB_PATH", target)
    db.init_db()
    for record in (
        _session("target-433", "target-433"),
        _session("sender-433", "sender-433"),
        _session("orchestrator-433", "orchestrator-433"),
    ):
        db.save_session(record)
    monkeypatch.setattr(initial_deliveries, "ensure_delivery_runner", lambda _id: None)
    monkeypatch.setattr(message_deliveries, "ensure_target_runner", lambda _id: None)
    expected = await _build_target(db, initial_deliveries, message_deliveries)

    monkeypatch.setattr(db, "DB_PATH", decoy)
    db.init_db()
    db.save_session(_session("decoy-433", "decoy-433", "/decoy"))
    with db._conn() as connection:
        decoy_sessions_before = connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]

    dry = _run_cli(target, decoy)
    assert dry.returncode == 0, dry.stderr
    dry_summary = _summary(dry.stdout)
    _assert_complete_summary(
        dry_summary, target, mode="dry-run", rows=len(expected), sessions=3
    )
    assert dry_summary["would_update"] > 0 and dry_summary["updated"] == 0
    with sqlite3.connect(target) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM logs WHERE type='user_message' AND origin='unknown'"
        ).fetchone()[0] == len(expected)
    with sqlite3.connect(decoy) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == decoy_sessions_before

    with sqlite3.connect(target) as connection:
        connection.execute(
            "CREATE TRIGGER fail_mid_433 BEFORE UPDATE OF origin ON logs "
            "WHEN OLD.content='[system] Retrying after transient server error.' "
            "BEGIN SELECT RAISE(ABORT, 'forced-mid-433'); END"
        )
    failed = _run_cli(target, decoy, "--apply")
    assert failed.returncode != 0, "#433 T5 rollback control did not fail"
    with sqlite3.connect(target) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM logs WHERE type='user_message' AND origin='unknown'"
        ).fetchone()[0] == len(expected), "#433 T5 partial updates survived rollback"
        connection.execute("DROP TRIGGER fail_mid_433")

    reader = sqlite3.connect(target)
    reader.execute("PRAGMA journal_mode=WAL")
    reader.execute("BEGIN")
    old_visible = reader.execute(
        "SELECT COUNT(*) FROM logs WHERE type='user_message' AND origin='unknown'"
    ).fetchone()[0]
    applied = _run_cli(target, decoy, "--apply", "--backup", str(backup))
    assert applied.returncode == 0, applied.stderr
    applied_summary = _summary(applied.stdout)
    _assert_complete_summary(
        applied_summary, target, mode="apply", rows=len(expected), sessions=3
    )
    assert applied_summary["updated"] == applied_summary["would_update"] > 0
    assert reader.execute(
        "SELECT COUNT(*) FROM logs WHERE type='user_message' AND origin='unknown'"
    ).fetchone()[0] == old_visible, "#433 T5 WAL reader lost its consistent snapshot"
    reader.rollback()
    reader.close()

    with sqlite3.connect(target) as connection:
        connection.row_factory = sqlite3.Row
        rows = {
            row["content"]: (row["origin"], json.loads(row["origin_detail"]))
            for row in connection.execute(
                "SELECT content,origin,origin_detail FROM logs WHERE type='user_message'"
            )
        }
        target_sessions = connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        initial_receipts = [dict(row) for row in connection.execute(
            "SELECT * FROM initial_deliveries ORDER BY delivery_id"
        )]
        message_receipts = [dict(row) for row in connection.execute(
            "SELECT * FROM message_deliveries ORDER BY delivery_id"
        )]
    assert {content: value[0] for content, value in rows.items()} == expected
    assert all(value[1]["senders"] for value in rows.values())
    assert rows["[12:34] RECEIPT-INITIAL-MATCH"][1]["senders"] == ["sender-433"]
    assert rows["[from:fake-agent] RECEIPT-INITIAL-MISMATCH"][1]["senders"] == ["unknown"]
    assert rows["[from:fake-agent] RECEIPT-DIRECT-OPERATOR"][1]["senders"] == ["user"]
    assert rows["[12:34] RECEIPT-DIRECT-MCP"][1]["senders"] == ["sender-433"]
    assert target_sessions == 3

    from app.events import MessageProvenance
    legacy_ids = {
        "00000000-0000-4000-8000-000000004331",
        "00000000-0000-4000-8000-000000004332",
        "00000000-0000-4000-8000-000000004333",
        "00000000-0000-4000-8000-000000004334",
    }
    for receipt in initial_receipts:
        provenance = MessageProvenance.from_storage(
            receipt["origin"], receipt["origin_detail"],
        )
        assert receipt["schema_version"] == initial_deliveries.SCHEMA_VERSION
        assert provenance.ref == receipt["delivery_id"]
        assert receipt["payload_hash"] == initial_deliveries._payload_hash(
            session_id=receipt["session_id"], worker_name=receipt["worker_name"],
            scope=receipt["scope"], sender=receipt["sender"],
            message=receipt["message"], provenance=provenance,
        )
    for receipt in message_receipts:
        provenance = MessageProvenance.from_storage(
            receipt["origin"], receipt["origin_detail"],
        )
        assert receipt["schema_version"] == message_deliveries.SCHEMA_VERSION
        if receipt["delivery_id"] in legacy_ids:
            assert provenance.ref == receipt["delivery_id"]
        origin, detail = provenance.to_storage()
        assert receipt["payload_hash"] == message_deliveries._payload_hash(
            source_session_id=receipt["source_session_id"],
            source_principal=receipt["source_principal"],
            source_scope=receipt["source_scope"],
            source_task_id=receipt["source_task_id"],
            target_session_id=receipt["target_session_id"],
            target_scope=receipt["target_scope"],
            target_task_id=receipt["target_task_id"],
            target_generation=receipt["target_generation"],
            message=receipt["message"], rendered_message=receipt["rendered_message"],
            message_kind=receipt["message_kind"], wake=bool(receipt["wake"]),
            origin=origin, origin_detail=json.loads(detail),
        )

    with sqlite3.connect(backup) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM logs WHERE type='user_message' AND origin='unknown'"
        ).fetchone()[0] == len(expected), (
            "#433 T5 backup is not the consistent pre-apply image"
        )
    with sqlite3.connect(decoy) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == decoy_sessions_before

    second = _run_cli(target, decoy, "--apply", "--backup", str(backup))
    assert second.returncode == 0, second.stderr
    second_summary = _summary(second.stdout)
    _assert_complete_summary(
        second_summary, target, mode="apply", rows=len(expected), sessions=3
    )
    assert second_summary["updated"] == 0 and second_summary["would_update"] == 0
