"""V-614: shadow gate — DONE without a passing check after the last code edit.

Frozen acceptance branches (task V-614 §4):
  1. edit -> DONE with no check afterwards => flagged.
  2. edit -> passing strict check -> DONE => not flagged.
  3. a failing check does not clear the flag.
  4. an error inside the gate never raises out of send_message's call path.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest

from app import done_gate
from app.events import MessageProvenance

SESSION_ID = "worker-session-614"
ORCH_SESSION_ID = "orch-session-614"
SCOPE = "/scope-614"


def _session_record(*, session_id, name, role="worker", is_orchestrator=False):
    return {
        "id": session_id,
        "name": name,
        "scope": SCOPE,
        "cwd": f"/tmp/{name}",
        "model": "gpt-5.6-sol",
        "system_prompt": "",
        "status": "idle",
        "session_id": None,
        "cost_usd": 0.0,
        "worktree_path": f"/tmp/{name}",
        "branch": f"task-614/{name}",
        "base_branch": "main",
        "needs_switch": 0,
        "task_id": "614",
        "role": role,
        "is_orchestrator": is_orchestrator,
        "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "parent_name": "",
    }


@pytest.fixture
def gate_db(tmp_path, monkeypatch):
    from app import db

    db_path = tmp_path / "done-gate-614.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()
    db.save_session(_session_record(session_id=SESSION_ID, name="worker-614"))
    db.save_session(_session_record(
        session_id=ORCH_SESSION_ID, name="orch-614",
        role="orchestrator", is_orchestrator=True,
    ))
    return db


def _log_tool(db, session_id, *, tool_name, content, tool_use_id):
    db.add_log(
        session_id, datetime.now(timezone.utc), "tool", content,
        tool_use_id=tool_use_id, tool_name=tool_name,
    )


def _log_tool_result(db, session_id, *, tool_use_id, is_error=False):
    db.add_log(
        session_id, datetime.now(timezone.utc), "tool_result", "result",
        tool_use_id=tool_use_id, tool_is_error=is_error,
    )


def _edit(db, session_id, path, *, use_id="edit-1"):
    # Real content format from backends: "ToolName: {json input}" (app/backend_claude.py).
    _log_tool(
        db, session_id, tool_name="Edit",
        content=f"Edit: {json.dumps({'file_path': path})}", tool_use_id=use_id,
    )


def _bash(db, session_id, command, *, use_id, ok=True):
    _log_tool(
        db, session_id, tool_name="Bash",
        content=f"Bash: {json.dumps({'command': command})}", tool_use_id=use_id,
    )
    _log_tool_result(db, session_id, tool_use_id=use_id, is_error=not ok)


def test_edit_then_done_without_check_is_flagged(gate_db):
    _edit(gate_db, SESSION_ID, "/repo/app/foo.py")
    verdict = done_gate.evaluate(SESSION_ID, SCOPE)
    assert verdict["has_code_edit"] is True
    assert verdict["last_edit_file"] == "/repo/app/foo.py"
    assert verdict["checked"] is False
    assert verdict["flag"] is True


def test_edit_then_passing_strict_check_clears_flag(gate_db):
    _edit(gate_db, SESSION_ID, "/repo/app/foo.py")
    _bash(gate_db, SESSION_ID, "uv run --frozen python -m pytest tests/test_foo.py -q", use_id="chk-1", ok=True)
    verdict = done_gate.evaluate(SESSION_ID, SCOPE)
    assert verdict["checked"] is True
    assert verdict["flag"] is False
    assert "pytest" in verdict["check_command"]


def test_failing_check_does_not_clear_flag(gate_db):
    _edit(gate_db, SESSION_ID, "/repo/app/foo.py")
    _bash(gate_db, SESSION_ID, "python -m pytest tests/test_foo.py -q", use_id="chk-1", ok=False)
    verdict = done_gate.evaluate(SESSION_ID, SCOPE)
    assert verdict["checked"] is False
    assert verdict["flag"] is True


def test_non_strict_check_does_not_clear_flag(gate_db):
    """Canny-strictness: `| tail`, `|| true`, `; echo` do not count as a real check."""
    _edit(gate_db, SESSION_ID, "/repo/app/foo.py")
    _bash(gate_db, SESSION_ID, "python -m pytest tests/test_foo.py -q | tail -5", use_id="chk-1", ok=True)
    verdict = done_gate.evaluate(SESSION_ID, SCOPE)
    assert verdict["checked"] is False
    assert verdict["flag"] is True


def test_edit_only_in_orchestra_dir_is_not_code(gate_db):
    _edit(gate_db, SESSION_ID, "/repo/.orchestra/tasks/614/notes.py")
    verdict = done_gate.evaluate(SESSION_ID, SCOPE)
    assert verdict["has_code_edit"] is False
    assert verdict["flag"] is False


def test_edit_in_docs_dir_is_not_code(gate_db):
    _edit(gate_db, SESSION_ID, "/repo/docs/setup.sh")
    verdict = done_gate.evaluate(SESSION_ID, SCOPE)
    assert verdict["has_code_edit"] is False
    assert verdict["flag"] is False


def test_maybe_record_writes_verdict_for_worker_done(gate_db):
    _edit(gate_db, SESSION_ID, "/repo/app/foo.py")
    payload = done_gate.maybe_record(
        source_session_id=SESSION_ID, source_scope=SCOPE, source_task_id="614",
        source_name="worker-614", message="DONE #614: did the thing",
    )
    assert payload is not None
    assert payload["flag"] is True
    with gate_db._conn() as conn:
        rows = conn.execute(
            "SELECT content FROM logs WHERE session_id=? AND type='done_gate_verdict'",
            (SESSION_ID,),
        ).fetchall()
    assert len(rows) == 1
    stored = json.loads(rows[0]["content"])
    assert stored["session_id"] == SESSION_ID
    assert stored["task_id"] == "614"
    assert stored["flag"] is True


def test_maybe_record_skips_orchestrator(gate_db):
    _edit(gate_db, ORCH_SESSION_ID, "/repo/app/foo.py")
    payload = done_gate.maybe_record(
        source_session_id=ORCH_SESSION_ID, source_scope=SCOPE, source_task_id="614",
        source_name="orch-614", message="DONE #614: did the thing",
    )
    assert payload is None
    with gate_db._conn() as conn:
        rows = conn.execute(
            "SELECT content FROM logs WHERE session_id=? AND type='done_gate_verdict'",
            (ORCH_SESSION_ID,),
        ).fetchall()
    assert rows == []


def test_maybe_record_skips_non_done_message(gate_db):
    _edit(gate_db, SESSION_ID, "/repo/app/foo.py")
    payload = done_gate.maybe_record(
        source_session_id=SESSION_ID, source_scope=SCOPE, source_task_id="614",
        source_name="worker-614", message="WIP #614: not finished yet",
    )
    assert payload is None


def test_record_verdict_swallows_db_write_failure(gate_db, monkeypatch):
    _edit(gate_db, SESSION_ID, "/repo/app/foo.py")

    def _boom(*args, **kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(done_gate.db, "add_log", _boom)
    result = done_gate.record_verdict(
        session_id=SESSION_ID, scope=SCOPE, task_id="614",
        worker_name="worker-614", message="DONE #614: ok",
    )
    assert result is None


def test_record_verdict_swallows_evaluate_failure(gate_db, monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(done_gate, "evaluate", _boom)
    result = done_gate.record_verdict(
        session_id=SESSION_ID, scope=SCOPE, task_id="614",
        worker_name="worker-614", message="DONE #614: ok",
    )
    assert result is None


def test_config_override_via_kv(gate_db):
    done_gate.set_config_override(SCOPE, {"ignored_prefixes": [".orchestra/", "docs/", "vendor/"]})
    _edit(gate_db, SESSION_ID, "/repo/vendor/foo.py")
    verdict = done_gate.evaluate(SESSION_ID, SCOPE)
    assert verdict["has_code_edit"] is False
    done_gate.set_config_override(SCOPE, {})
    verdict_default = done_gate.evaluate(SESSION_ID, SCOPE)
    assert verdict_default["has_code_edit"] is True


# ── Integration through accept_message_delivery: gate must not delay/break send_message ──

DELIVERY_ID = "00000000-0000-4000-8000-000000000614"
TARGET_ID = "target-session-614"
TARGET_GENERATION = f"session={TARGET_ID}|task=614|branch=task-614/target|needs_switch=0"
PROVENANCE = MessageProvenance(
    origin="agent", senders=("worker-614",), subtype="direct_message", ref=DELIVERY_ID,
)


@pytest.fixture
def delivery_db(gate_db):
    gate_db.save_session(_session_record(session_id=TARGET_ID, name="target-614"))
    return gate_db


@pytest.mark.asyncio
async def test_accept_message_delivery_records_shadow_verdict(delivery_db, monkeypatch):
    from app import message_deliveries

    monkeypatch.setattr(message_deliveries, "ensure_target_runner", lambda *_: None)
    _edit(delivery_db, SESSION_ID, "/repo/app/foo.py")

    resource, status = await message_deliveries.accept_message_delivery(
        delivery_id=DELIVERY_ID,
        source_session_id=SESSION_ID,
        source_name="worker-614",
        source_scope=SCOPE,
        source_task_id="614",
        target_session_id=TARGET_ID,
        target_name="target-614",
        target_scope=SCOPE,
        target_task_id="614",
        target_generation=TARGET_GENERATION,
        message="DONE #614: shipped it",
        rendered_message="[from:worker-614] DONE #614: shipped it",
        message_kind=None,
        wake=True,
        provenance=PROVENANCE,
    )
    assert status == 202
    assert resource["acceptance"] == "ACCEPTED"
    with delivery_db._conn() as conn:
        rows = conn.execute(
            "SELECT content FROM logs WHERE session_id=? AND type='done_gate_verdict'",
            (SESSION_ID,),
        ).fetchall()
    assert len(rows) == 1
    assert json.loads(rows[0]["content"])["flag"] is True


@pytest.mark.asyncio
async def test_accept_message_delivery_survives_gate_exception(delivery_db, monkeypatch):
    from app import message_deliveries

    monkeypatch.setattr(message_deliveries, "ensure_target_runner", lambda *_: None)

    def _boom(**kwargs):
        raise RuntimeError("gate exploded")

    monkeypatch.setattr(done_gate, "maybe_record", _boom)

    resource, status = await message_deliveries.accept_message_delivery(
        delivery_id=DELIVERY_ID,
        source_session_id=SESSION_ID,
        source_name="worker-614",
        source_scope=SCOPE,
        source_task_id="614",
        target_session_id=TARGET_ID,
        target_name="target-614",
        target_scope=SCOPE,
        target_task_id="614",
        target_generation=TARGET_GENERATION,
        message="DONE #614: shipped it",
        rendered_message="[from:worker-614] DONE #614: shipped it",
        message_kind=None,
        wake=True,
        provenance=PROVENANCE,
    )
    assert status == 202
    assert resource["acceptance"] == "ACCEPTED"
