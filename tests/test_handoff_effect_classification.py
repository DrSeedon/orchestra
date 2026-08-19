"""#340: what blocks a runtime handoff and what travels with it.

Two directions, both required:
  * a call whose result row was written out of order is COMPLETED (the pair exists);
  * a call the transcript continued past travels as `unresolved` instead of locking
    the session out of every future switch, while a call with nothing logged after it
    still blocks — there its tool may be running right now.
"""

import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.runtime_history import build_runtime_state_packet, classify_handoff_effects


def _row(log_id, row_type, content, *, second, **metadata):
    return {
        "id": log_id,
        "ts": f"2026-08-11T10:00:{second:02d}+00:00",
        "type": row_type,
        "content": content,
        "event_id": "",
        "tool_use_id": metadata.get("tool_use_id"),
        "tool_name": metadata.get("tool_name"),
        "tool_is_error": metadata.get("tool_is_error"),
    }


def _packet(rows):
    return build_runtime_state_packet(
        rows,
        session_meta={"id": "s1"},
        snapshot_id=max(row["id"] for row in rows),
        current_system_prompt="system",
        project_docs=[],
    )


@pytest.fixture
def session(monkeypatch):
    from app.session import AgentSession

    monkeypatch.setattr("app.session.save_session", MagicMock())
    monkeypatch.setattr("app.session.add_log", MagicMock(return_value=1))
    monkeypatch.setattr("app.bg_jobs.bg_manager", None)
    return AgentSession(
        id="handoff-effects", name="effects-canary", scope="/test", cwd="/tmp",
        model="claude-sonnet-5[1m]", system_prompt="test",
        created_at=datetime.now(timezone.utc),
    )


def test_result_row_written_before_its_own_call_still_completes_the_effect():
    """The DB write pool assigns ids out of event order for 10% of live pairs (#340)."""
    packet = _packet([
        # id 1 < id 2, but the result happened AFTER the call — as `ts` records.
        _row(1, "tool_result", "read done", second=2, tool_use_id="call-1"),
        _row(2, "tool", "Read: a.py", second=1, tool_use_id="call-1", tool_name="Read"),
        _row(3, "text", "and so on", second=3),
    ])

    effect = packet["tool_effects"][0]
    assert effect["status"] == "completed"
    # The packet is counted against the target context window: diagnostic ballast is
    # dropped once the pair is closed.
    assert "call_ts" not in effect
    assert classify_handoff_effects(packet) == ((), 0)


def test_legacy_rows_without_ids_pair_in_event_order_not_insert_order():
    packet = _packet([
        _row(1, "tool_result", "legacy result", second=2, tool_name="Read"),
        _row(2, "tool", "legacy call", second=1, tool_name="Read"),
        _row(3, "text", "and so on", second=3),
    ])

    assert [effect["status"] for effect in packet["tool_effects"]] == ["completed"]
    assert classify_handoff_effects(packet) == ((), 0)


def test_call_the_transcript_continued_past_is_unresolved_and_does_not_block():
    packet = _packet([
        _row(1, "tool", "Bash: git status", second=1,
             tool_use_id="call-1", tool_name="Bash"),
        _row(2, "text", "the turn went on without that result row", second=2),
        _row(3, "status", "turn ended (end_turn)", second=3),
    ])

    effect = packet["tool_effects"][0]
    assert effect["status"] == "unresolved"
    blocking, unresolved = classify_handoff_effects(packet)
    assert blocking == ()
    assert unresolved == 1


def test_call_with_nothing_logged_after_it_still_blocks_and_names_itself():
    packet = _packet([
        _row(1, "text", "starting", second=1),
        _row(2, "tool", "Bash: sudo systemctl restart orchestra", second=2,
             tool_use_id="call-9", tool_name="Bash"),
    ])

    assert packet["tool_effects"][0]["status"] == "pending"
    blocking, unresolved = classify_handoff_effects(packet)
    assert unresolved == 0
    assert blocking == ({
        "call_id": "call-9",
        "tool_name": "Bash",
        "call_log_id": 2,
        "call_ts": "2026-08-11T10:00:02+00:00",
    },)


def test_block_decision_reads_the_last_EVENT_not_the_last_inserted_row():
    """The tail rule must use the same order the pairing uses, or it blocks blind."""
    packet = _packet([
        # The text row won the write race and got the higher id, but it happened first.
        _row(9, "text", "earlier event, later id", second=1),
        _row(5, "tool", "Bash: sudo systemctl restart orchestra", second=3,
             tool_use_id="call-9", tool_name="Bash"),
    ])

    assert packet["tool_effects"][0]["status"] == "pending"
    blocking, unresolved = classify_handoff_effects(packet)
    assert unresolved == 0
    assert [item["call_id"] for item in blocking] == ["call-9"]


def test_snapshot_refs_and_recent_messages_stay_in_insert_order():
    """Only the effect pairing moved to event order — the frozen refs did not."""
    packet = _packet([
        _row(1, "user_message", "first by id, later in time", second=3),
        _row(2, "text", "second by id, earlier in time", second=1),
    ])

    assert packet["raw_event_refs"]["event_ids"] == [1, 2]
    assert [message["log_id"] for message in packet["recent_messages"]] == [1, 2]


def _prepared_session(session, tmp_path, monkeypatch, rows):
    from app import db as dbmod

    db_path = tmp_path / "effects.db"
    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    dbmod.init_db()
    created_at = datetime.now(timezone.utc)
    session.scope = "/repo"
    session.cwd = "/repo"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO sessions (id, name, scope, cwd, model, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session.id, session.name, session.scope, session.cwd,
             session.model, created_at.isoformat()),
        )
        for offset, (row_type, content, tool_use_id, tool_name) in enumerate(rows):
            conn.execute(
                """INSERT INTO logs
                   (session_id, ts, type, content, event_id, tool_use_id, tool_name)
                   VALUES (?, ?, ?, ?, '', ?, ?)""",
                (
                    session.id,
                    (created_at + timedelta(seconds=offset)).isoformat(),
                    row_type, content, tool_use_id, tool_name,
                ),
            )
    session._drain_handoff_log_writes = AsyncMock()
    return session._prepare_runtime_handoff


@pytest.mark.asyncio
async def test_prepare_moves_a_session_whose_lost_result_can_never_arrive(
    session, tmp_path, monkeypatch,
):
    prepare = _prepared_session(session, tmp_path, monkeypatch, [
        ("tool", "Bash: git status", "call-1", "Bash"),
        ("text", "the turn went on", None, None),
        ("status", "turn ended (end_turn)", None, None),
    ])

    prepared = await prepare(
        "gpt-5.6-sol", idempotency_key="moves-on", project_docs=[],
    )

    assert prepared.ok is True
    assert prepared.pending_effects == 0
    assert prepared.unresolved_effects == 1
    assert prepared.packet["tool_effects"][0]["status"] == "unresolved"


@pytest.mark.asyncio
async def test_first_preparation_journals_what_it_lets_through(
    session, tmp_path, monkeypatch, caplog,
):
    """Not the idempotent replay — the FIRST switch is the one that carries them."""
    prepare = _prepared_session(session, tmp_path, monkeypatch, [
        ("tool", "Bash: git status", "call-1", "Bash"),
        ("text", "the turn went on", None, None),
    ])

    with caplog.at_level(logging.WARNING, logger="app.session"):
        prepared = await prepare(
            "gpt-5.6-sol", idempotency_key="journal-first", project_docs=[],
        )

    assert prepared.unresolved_effects == 1
    assert "1 unresolved tool effect(s)" in caplog.text
    assert prepared.handoff_id in caplog.text


@pytest.mark.asyncio
async def test_prepare_refuses_a_call_that_may_still_be_running_and_names_it(
    session, tmp_path, monkeypatch,
):
    prepare = _prepared_session(session, tmp_path, monkeypatch, [
        ("text", "starting", None, None),
        ("tool", "Bash: sudo systemctl restart orchestra", "call-9", "Bash"),
    ])

    prepared = await prepare(
        "gpt-5.6-sol", idempotency_key="still-running", project_docs=[],
    )

    assert prepared.ok is False
    assert prepared.error_code == "handoff_pending_effect"
    assert prepared.pending_effects == 1
    (detail,) = prepared.pending_effect_details
    assert detail["call_id"] == "call-9"
    assert detail["tool_name"] == "Bash"
    assert detail["call_log_id"] == 2
    assert detail["call_ts"]


@pytest.mark.asyncio
async def test_change_model_refusal_names_the_blocking_call_not_only_its_code(session):
    from app.runtime_history import PreparationResult
    from app.session import AgentStatus

    session.model = "gpt-5.6-sol"
    session.backend_type = "codex"
    session.session_id = "source-thread"
    session.status = AgentStatus.IDLE
    session._backend = AsyncMock()
    session._log = MagicMock()
    session._ensure_backend = AsyncMock()
    session._prepare_runtime_handoff = AsyncMock(return_value=PreparationResult(
        ok=False,
        error_code="handoff_pending_effect",
        pending_effects=1,
        pending_effect_details=({
            "call_id": "call-9",
            "tool_name": "Bash",
            "call_log_id": 2,
            "call_ts": "2026-08-11T10:00:02+00:00",
        },),
    ))

    result = await session.change_model("gpt-5.6-luna")

    assert result["ok"] is False
    assert result["error_code"] == "handoff_pending_effect"
    assert "Bash" in result["error"]
    assert "call-9" in result["error"]
    assert "2026-08-11T10:00:02+00:00" in result["error"]
    assert result["pending_effects"] == [{
        "call_id": "call-9",
        "tool_name": "Bash",
        "call_log_id": 2,
        "call_ts": "2026-08-11T10:00:02+00:00",
    }]
    session._ensure_backend.assert_not_awaited()
