"""V-1028: a parent report through the hub outbox must suppress a duplicate auto-report."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app import hub_outbox
from app.backend_hub import HubBackend
from app.events import AgentEvent, MessageProvenance
from tests.test_turn_signals import _session, _settle, world  # noqa: F401


def _backend(world):
    session = _session(world)
    session.backend_type = "hub"
    session.model = "hub-gpt-6.1-sol"
    session._submit_db_write = Mock()
    session._spawn_bg = lambda coroutine: coroutine.close()
    session._turns.schedule_context_compaction = Mock()
    return session, HubBackend(session.model, ".", bridge=session._hub_bridge())


async def _outbox(backend, entries):
    return await backend._run_outbox(
        SimpleNamespace(delete_files=AsyncMock()), SimpleNamespace(remote_dir=".", ws_id="test-worker"),
        "\n".join(json.dumps(entry) for entry in entries).encode(),
    )


@pytest.mark.asyncio
async def test_hub_outbox_done_to_parent_prevents_second_auto_report(world, monkeypatch):
    session, backend = _backend(world)
    calls = []

    async def api(who, method, path, body):
        calls.append((method, path, body))
        await world["manager"].send(world["parent_id"], body["message"], provenance=MessageProvenance(
            "agent", (who.name,), subtype="direct_message", ref=body["delivery_id"],
        ))
        return {"ok": True, "delivery_state": "SUBMITTED"}

    monkeypatch.setattr(hub_outbox, "local_api_call", api)
    await _outbox(backend, [{"tool": "send_message", "args": {
        "to": "somebody-else", "message": "DONE: completed work",
    }}])
    assert calls[0][1] == "/api/sessions/boss/send", "outbox authority forces the own parent"
    session._handle_event(AgentEvent("text", "DONE: completed work"))
    session._handle_event(AgentEvent("turn_end", metadata={
        "ok": True, "stop_reason": "end_turn", "cost_usd": 0, "num_turns": 1,
    }))
    await _settle(session)
    assert len(world["manager"].sent) == 1
    assert session._did_report is True
    assert world["manager"].sent[0][2].subtype == "direct_message"


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["QUEUED", "WAITING_QUOTA", "WAITING_NEXT_TURN", "SUBMITTED"])
async def test_hub_outbox_durable_parent_receipt_counts_as_report_even_with_quota_metadata(
    world, monkeypatch, state,
):
    session, backend = _backend(world)
    receipt = {"ok": True, "delivery_state": state}
    if state == "WAITING_QUOTA":
        receipt["error"] = {"code": "WAITING_QUOTA", "message": "Claude quota gate closed"}
    monkeypatch.setattr(hub_outbox, "local_api_call", AsyncMock(return_value=receipt))
    summary = await _outbox(backend, [{"tool": "send_message", "args": {"message": "DONE"}}])
    assert "1 delivered" in summary and "dropped" not in summary
    assert session._did_report is True
    session._turns.fire_auto_report()
    await _settle(session)
    assert world["manager"].sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize("receipt", [
    {"ok": False},
    {"error": "connection refused"},
    {"ok": True, "delivery_state": "FAILED_BEFORE_SUBMIT", "error": {"message": "failed"}},
    {"ok": True, "delivery_state": "CANCELLED"},
    {"ok": True, "delivery_state": "DELIVERY_UNKNOWN"},
    {},
])
async def test_failed_hub_outbox_send_keeps_fallback_report(world, monkeypatch, receipt):
    session, backend = _backend(world)
    monkeypatch.setattr(hub_outbox, "local_api_call", AsyncMock(return_value=receipt))
    summary = await _outbox(backend, [{"tool": "send_message", "args": {"message": "DONE"}}])
    assert "dropped" in summary
    assert session._did_report is False
    session._turns.fire_auto_report()
    await _settle(session)
    assert len(world["manager"].sent) == 1
    assert world["manager"].sent[0][2].subtype == "auto_report"


@pytest.mark.asyncio
async def test_progress_and_checklist_outbox_entries_do_not_suppress_report(world, monkeypatch):
    session, backend = _backend(world)
    monkeypatch.setattr(hub_outbox, "local_api_call", AsyncMock(return_value={"ok": True}))
    await _outbox(backend, [
        {"tool": "update_progress", "args": {"percent": 100}},
        {"tool": "update_checklist", "args": {"items": ["work"], "completed": [0]}},
    ])
    assert session._did_report is False
    session._turns.fire_auto_report()
    await _settle(session)
    assert len(world["manager"].sent) == 1


@pytest.mark.asyncio
async def test_late_outbox_acceptance_cannot_mark_a_new_turn_reported(world, monkeypatch):
    session, backend = _backend(world)

    async def api(*_):
        session._turns.bump_turn_gen()
        return {"ok": True, "delivery_state": "SUBMITTED"}

    monkeypatch.setattr(hub_outbox, "local_api_call", api)
    await _outbox(backend, [{"tool": "send_message", "args": {"message": "old DONE"}}])
    assert session._did_report is False
    session._turns.fire_auto_report()
    await _settle(session)
    assert len(world["manager"].sent) == 1


@pytest.mark.asyncio
async def test_successful_parent_report_survives_later_outbox_failure(world, monkeypatch):
    session, backend = _backend(world)

    async def api(_who, _method, path, _body):
        if path.endswith("/progress"):
            raise OSError("progress unavailable")
        return {"ok": True}

    monkeypatch.setattr(hub_outbox, "local_api_call", api)
    summary = await _outbox(backend, [
        {"tool": "send_message", "args": {"message": "DONE"}},
        {"tool": "update_progress", "args": {"percent": 100}},
    ])
    assert "1 dropped" in summary
    session._turns.fire_auto_report()
    await _settle(session)
    assert session._did_report is True
    assert world["manager"].sent == []
