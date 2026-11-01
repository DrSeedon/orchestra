"""V-1028: parent-specific report tracking, harness errors and interrupted turns."""

import json
from unittest.mock import Mock

import pytest

from app.events import AgentEvent
from app.harness.loop import AgentLoop
from app.session import AgentStatus
from tests.test_turn_signals import _session, _settle, world  # noqa: F401


def _tool(session, *, name="mcp__orchestra__send_message", target="boss", result="Message sent", error=False):
    session._handle_event(AgentEvent(
        "tool_use", f'{name}: {json.dumps({"to": target, "message": "DONE"})}',
        {"tool_name": name, "tool_use_id": "call"},
    ))
    session._handle_event(AgentEvent(
        "tool_result", result, {"tool_use_id": "call", "is_error": error},
    ))


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime", ["claude", "codex", "harness"])
@pytest.mark.parametrize("target,reported", [("boss", True), ("sibling", False), ("w1", False)])
async def test_only_successful_parent_send_suppresses_auto_report(world, runtime, target, reported):
    session = _session(world)
    session.backend_type = runtime
    if runtime == "codex":
        session.model = "gpt-6-luna"
    _tool(session, name="send_message" if runtime == "harness" else "mcp__orchestra__send_message",
          target=target)
    assert session._did_report is reported
    session._turns.fire_auto_report()
    await _settle(session)
    assert len(world["manager"].sent) == (0 if reported else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("result,error", [
    ("[mcp error] parent unavailable", False),
    ("[error] denied", False),
    ("Send failed: quota blocked", False),
    ('{"ok":false,"error":"denied"}', False),
    ("Message was NOT delivered; state=FAILED_BEFORE_SUBMIT", False),
    ("Message cancelled; it was not sent", False),
    ("Message delivery outcome is unknown", False),
    ("Message NOT delivered; target queue blocked", False),
    ("unexpected opaque response", False),
    ("denied", True),
])
async def test_failed_parent_send_still_creates_durable_signal(world, result, error):
    session = _session(world)
    session._submit_db_write = Mock()
    _tool(session, result=result, error=error)
    assert not session._did_report
    session._turns.fire_auto_report()
    await _settle(session)
    assert len(world["manager"].sent) == 1


@pytest.mark.asyncio
async def test_harness_mcp_error_is_error_and_does_not_suppress_fallback(world):
    class MCP:
        def display_name(self, name):
            return f"mcp__orchestra__{name}"

        def has_tool(self, name):
            return name == "send_message"

        async def call(self, name, args):
            return "[mcp error] parent unavailable"

    session = _session(world)
    session.backend_type = "harness"
    session._submit_db_write = Mock()
    loop = AgentLoop(None, MCP(), ".", [], "system", [])
    events = [event async for event in loop._dispatch_tool({
        "id": "harness-send", "function": {
            "name": "send_message", "arguments": '{"to":"boss","message":"DONE"}',
        },
    })]
    assert events[-1].metadata["is_error"] is True
    for event in events:
        session._handle_event(event)
    session._turns.fire_auto_report()
    await _settle(session)
    assert len(world["manager"].sent) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime", ["claude", "harness", "codex"])
@pytest.mark.parametrize("interrupted", [False, True])
async def test_real_turn_end_path_records_signal_for_final_text_or_provider_interrupt(
    world, runtime, interrupted,
):
    session = _session(world)
    session.backend_type = runtime
    if runtime == "codex":
        session.model = "gpt-6-luna"
    session._submit_db_write = Mock()
    session._spawn_bg = lambda coroutine: coroutine.close()
    session._turns.schedule_context_compaction = Mock()
    session._handle_event(AgentEvent("text", "final output"))
    session._handle_event(AgentEvent("turn_end", metadata={
        "ok": not interrupted, "stop_reason": "interrupted" if interrupted else "end_turn",
        "num_turns": 1, "cost_usd": 0,
    }))
    await _settle(session)
    assert session.status == AgentStatus.IDLE
    assert len(world["manager"].sent) == 1
    message = world["manager"].sent[0][1]
    assert "final output" in message
    assert ("Turn failed" in message) is interrupted


@pytest.mark.asyncio
@pytest.mark.parametrize("condition,reason", [
    ("manual", "manual interrupt"),
    ("owner", "owner initiated turn"),
    ("pending", "pending messages"),
    ("silent", "silent turn marker"),
    ("compacting", "compacting"),
])
async def test_intentional_skip_has_a_visible_reason(world, condition, reason):
    session = _session(world)
    session._log = Mock()
    if condition == "manual":
        session._manually_interrupted = True
    elif condition == "owner":
        session._owner_initiated_turn = True
    elif condition == "pending":
        session._pending_messages.append("next task")
    elif condition == "silent":
        session._last_text_output = "[[ORCHESTRA:SILENT_TURN]]"
    elif condition == "compacting":
        session._compacting = True
    session._turns.fire_auto_report()
    await _settle(session)
    assert world["manager"].sent == []
    session._log.assert_any_call("status", f"auto-report skipped: {reason}")


@pytest.mark.asyncio
async def test_parent_id_alone_is_sufficient_to_report(world):
    session = _session(world)
    session.parent_name = ""
    session.last_task_sender = ""
    session._turns.fire_auto_report()
    await _settle(session)
    assert len(world["manager"].sent) == 1


@pytest.mark.asyncio
async def test_stale_tool_result_from_prior_turn_cannot_suppress_new_turn(world):
    session = _session(world)
    session._handle_event(AgentEvent(
        "tool_use", 'send_message: {"to":"boss","message":"DONE"}',
        {"tool_name": "send_message", "tool_use_id": "old"},
    ))
    session._turns.bump_turn_gen()
    session._handle_event(AgentEvent("tool_result", "Message sent", {"tool_use_id": "old"}))
    assert session._did_report is False


@pytest.mark.asyncio
@pytest.mark.parametrize("result", [
    'Message accepted; state=QUEUED',
    'Message delivery is deferred by a quota gate; state=WAITING_QUOTA',
    '{"ok":true,"delivery_state":"WAITING_QUOTA"}',
])
async def test_durable_parent_receipt_suppresses_duplicate_auto_report(world, result):
    session = _session(world)
    _tool(session, result=result)
    assert session._did_report
    session._turns.fire_auto_report()
    await _settle(session)
    assert world["manager"].sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize("waiting", [False, True])
async def test_post_turn_deferral_is_visible(world, waiting):
    session = _session(world)
    session._log = Mock()
    session.status = AgentStatus.WAITING if waiting else AgentStatus.IDLE
    session._turns._idle_tail(0, allow_auto_report=waiting)
    await _settle(session)
    assert world["manager"].sent == []
    reason = "background jobs pending" if waiting else "server error retry pending"
    session._log.assert_any_call("status", f"auto-report skipped: {reason}")
