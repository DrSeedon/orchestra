"""Supported lifecycle races with a successful, still-awaited native compact."""
import asyncio
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.session import AgentSession
from tests.test_codex_compact_delivery_1150 import (
    begin_session, clock, compact_publications, usage,
)
from tests.test_codex_compact_state import compact, h, make_session, offline, terminal


@pytest.mark.asyncio
@pytest.mark.parametrize("transition", ["clear", "rollback", "restart"])
@pytest.mark.parametrize("stage", ["result", "handoff", "persist"])
async def test_awaited_compact_cannot_publish_after_supported_lifecycle_change(
    h, clock, monkeypatch, transition, stage,
):
    from app import message_deliveries
    from app.routes import sessions as routes

    s = make_session(h)
    ready, release = asyncio.Event(), asyncio.Event()
    native = h.backend.compact_context

    async def held_result():
        result = await native()  # real request, JSONL reader, ACK/S/C/T reducer
        ready.set()
        await release.wait()
        return result

    async def held_handoff():
        ready.set()
        await release.wait()
        return "summary-owned-by-the-old-compact"

    async def held_persist():
        ready.set()
        await release.wait()

    if stage == "result":
        monkeypatch.setattr(h.backend, "compact_context", held_result)
    elif stage == "handoff":
        s._build_runtime_handoff = held_handoff
    else:
        s._drain_persist = held_persist

    task = await begin_session(h, s)
    await h.deliver(usage(), compact(), terminal())
    await asyncio.wait_for(ready.wait(), 0.5)
    assert s._compacting
    assert h.backend.compact_diagnostics["outcome"] == "success"
    # Keep disconnect/finalize and the API lifecycle handler real. Only the OS
    # signal leaf is replaced: this backend owns an in-memory fake process.
    s._disconnect_backend = MethodType(AgentSession._disconnect_backend, s)
    h.backend._disconnect_direct = AsyncMock()
    monkeypatch.setattr(routes, "manager", SimpleNamespace(
        ensure_loaded=AsyncMock(return_value=s),
        get_session_lock=Mock(return_value=asyncio.Lock()),
    ))
    monkeypatch.setattr(message_deliveries, "_target_delivery_locks", {})
    recover = AsyncMock(return_value=[])
    monkeypatch.setattr(message_deliveries, "recover_message_deliveries", recover)
    request = routes.ScopeRequest(scope=s.scope)
    if transition == "clear":
        response = await routes.clear_session(s.name, request)
    elif transition == "rollback":
        s.session_id_history = [{
            "session_id": "replacement-thread", "runtime": "codex", "model": "gpt-6-luna",
        }]
        response = await routes.rollback_session(s.name, request)
    else:
        response = await routes.restart_cli(s.name, request)
        recover.assert_awaited_once_with(target_session_id=s.id)
    assert response["ok"]
    assert s._backend is None
    context = dict(await s.get_context())
    identity = (s.session_id, s.model, s.backend_type, s.last_summary)
    writes = s._persist.call_count
    release.set()
    result = await h.result(task)
    assert dict(await s.get_context()) == context
    assert (s.session_id, s.model, s.backend_type, s.last_summary) == identity
    assert s._persist.call_count == writes
    assert not compact_publications(s)
    assert not result["ok"]  # application of the obsolete snapshot was refused
    assert result["error"]
    assert result["compact_diagnostics"]["outcome"] == "success"  # native truth remains intact
    assert h.backend.compact_diagnostics["remote_outcome"] == "completed"


@pytest.mark.asyncio
async def test_supported_model_change_is_guarded_while_compact_is_awaited(h, clock, monkeypatch):
    s = make_session(h)
    retarget = Mock(wraps=h.backend.retarget_model)
    monkeypatch.setattr(h.backend, "retarget_model", retarget)
    task = await begin_session(h, s)
    old = (s.model, h.backend.model)
    result = await s.change_model("gpt-6-luna")
    assert not result["ok"]
    assert result["error"]
    assert (s.model, h.backend.model) == old
    retarget.assert_not_called()
    await h.deliver(usage(), compact(), terminal())
    assert (await h.result(task))["ok"]
    assert (await s.get_context())["total_tokens"] == 1200
    assert len(compact_publications(s)) == 1
