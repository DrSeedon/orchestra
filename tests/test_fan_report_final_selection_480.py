"""#480: fan reports keep the final substantive child message."""

import asyncio
from pathlib import Path

import pytest

from app.turn_markers import SILENT_TURN_MARKER


@pytest.fixture
def fan(tmp_path, monkeypatch):
    from app import db, fan_barrier

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "fan-report-480.db")
    db.init_db()
    fan_barrier.open_fan(
        fan_id="fan-480",
        parent_name="parent",
        scope="/repo",
        children=["child"],
        deadline_seconds=3600,
    )
    monkeypatch.setattr("app.deps.manager", _WakeRecorder())
    return fan_barrier


class _WakeRecorder:
    async def ensure_loaded(self, name, scope=None):
        return type("Parent", (), {"id": "sid-parent"})()

    async def send(self, session_id, message, *, provenance):
        assert session_id == "sid-parent"
        assert provenance.subtype == "fan_manifest"


class _FinishedChild:
    is_orchestrator = False
    _did_report = False
    _manually_interrupted = False
    _pending_messages = False
    _compacting = False
    _last_turn_ok = True
    _last_stop_reason = "end_turn"
    _auto_report_task = None
    scope = "/repo"
    parent_name = "parent"
    last_task_sender = "parent"

    def __init__(self, name, *texts):
        self.name = name
        self._turn_logs = list(texts)
        self._last_text_output = texts[-1] if texts else None

    async def on_idle(self, *args):
        raise AssertionError(f"fan child bypassed the barrier: {args!r}")


def _finish(name, *texts):
    from app.session_turns import TurnManager

    child = _FinishedChild(name, *texts)

    async def run():
        TurnManager(child).fire_auto_report()
        if child._auto_report_task is not None:
            await child._auto_report_task

    asyncio.run(run())


def _stored_report(fan):
    member = fan.manifest("fan-480")["members"][0]
    assert member["state"] == "done"
    assert member["report_path"]
    return Path(member["report_path"]).read_text(encoding="utf-8")


def _send(fan, message, kind=None, child="child"):
    return fan.intercept_delivery_report(
        child=child,
        target_name="parent",
        target_scope="/repo",
        message=message,
        message_kind=kind,
        require_drained_scope="/repo",
    )


def test_silent_turn_after_send_message_persists_done_not_prework(fan):
    _send(fan, "Prework: read project memory")
    _send(fan, "DONE #98: final report with commit 8b9945e")

    _finish("child", "Prework: read project memory", SILENT_TURN_MARKER)

    stored = _stored_report(fan)
    assert stored == "DONE #98: final report with commit 8b9945e"
    assert "Prework" not in stored
    assert SILENT_TURN_MARKER not in stored


def test_ordinary_final_text_remains_the_report(fan):
    _finish("child", "Prework: read project memory", "DONE #99: ordinary final text")

    stored = _stored_report(fan)
    assert stored == "DONE #99: ordinary final text"
    assert "Prework" not in stored


def test_missing_substantive_report_is_explicit(fan):
    _finish("child", SILENT_TURN_MARKER)

    stored = _stored_report(fan)
    assert stored.startswith("ОТЧЁТА НЕТ:")
    assert "служебным маркером тишины" in stored
    assert SILENT_TURN_MARKER not in stored


def test_late_explicit_terminal_delivery_cannot_replace_fixed_report(fan):
    fan.open_fan(
        fan_id="fan-480-explicit",
        parent_name="parent",
        scope="/repo",
        children=["explicit-child", "pending-sibling"],
        deadline_seconds=3600,
    )
    _send(fan, "DONE: accepted report", "done", "explicit-child")
    _send(fan, "FAILED: conflicting late report", "failed", "explicit-child")

    member = fan.manifest("fan-480-explicit")["members"][0]
    stored = Path(member["report_path"]).read_text(encoding="utf-8")
    assert member["state"] == "done"
    assert stored == "DONE: accepted report"


def test_late_legacy_delivery_cannot_replace_turn_end_report(fan):
    fan.open_fan(
        fan_id="fan-480-legacy-late",
        parent_name="parent",
        scope="/repo",
        children=["late-child", "pending-sibling"],
        deadline_seconds=3600,
    )
    _send(fan, "DONE: final legacy candidate", child="late-child")
    _finish("late-child", SILENT_TURN_MARKER)
    _send(fan, "late progress after turn-end", child="late-child")

    member = fan.manifest("fan-480-legacy-late")["members"][0]
    stored = Path(member["report_path"]).read_text(encoding="utf-8")
    assert member["state"] == "done"
    assert stored == "DONE: final legacy candidate"
