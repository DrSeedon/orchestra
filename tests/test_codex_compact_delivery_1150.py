"""Offline regressions through the JSONL transport and real session lifecycle.

Deadlines below use virtual elapsed time; no provider requests or minute sleeps.
The existing harness isolates process/DB I/O, not the protocol or session reducer.
"""
import asyncio
import json
from unittest.mock import AsyncMock, Mock

import pytest

import app.backend_codex as source
from app import mcp_stdio
from app.session_state import AgentStatus
from tests.test_codex_compact_state import (  # reuse actual reader/request/session fixture
    THREAD, TURN, compact, error, event, h, make_session, offline, start, terminal,
)

PRODUCTION_BUDGET = source.CODEX_COMPACT_TIMEOUT_SECONDS


def compact_publications(session):
    # Existing wire contract: the frontend consumes this prefix to invalidate
    # context cache. The human-readable suffix is deliberately unconstrained.
    return [call for call in session._log.call_args_list
            if call.args[0] == "status"
            and call.args[1].startswith("compact done (native Codex):")]


class Clock:
    def __init__(self, real_timeout):
        self.now = 0
        self.real_timeout = real_timeout
        self.deadlines = []

    def timeout(self, seconds):
        if seconds != PRODUCTION_BUDGET:
            return self.real_timeout(seconds)
        context = self.real_timeout(None)
        self.deadlines.append((self.now + seconds, context))
        return context

    def advance(self, seconds):
        self.now += seconds
        for deadline, context in self.deadlines:
            if deadline <= self.now and context.when() is None:
                context.reschedule(asyncio.get_running_loop().time())


@pytest.fixture
def clock(monkeypatch, offline):
    clock = Clock(asyncio.timeout)
    monkeypatch.setattr(source, "CODEX_COMPACT_TIMEOUT_SECONDS", PRODUCTION_BUDGET)
    monkeypatch.setattr(asyncio, "timeout", clock.timeout)
    return clock


def usage(tokens=1200, *, turn=TURN, window=100000):
    return event("thread/tokenUsage/updated", turnId=turn, tokenUsage={
        "last": {"inputTokens": tokens, "totalTokens": tokens},
        "total": {"inputTokens": tokens * 2}, "modelContextWindow": window,
    })


async def begin_session(h, s):
    task = h.task(s.compact())
    request = await h.request("thread/compact/start")
    await h.ack(request)
    await h.deliver(start())
    return task


async def leave_caller(h, task, clock, exit):
    if exit == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await h.result(task)
        return None
    clock.advance(PRODUCTION_BUDGET + 1)
    result = await h.result(task)
    assert not result["ok"]
    assert result["compact_diagnostics"]["outcome"] == "timeout"
    return result


@pytest.mark.asyncio
async def test_observed_227_second_compact_publishes_before_bounded_deadline(h, clock):
    s = make_session(h)
    task = await begin_session(h, s)
    clock.advance(120.1)
    await h.deliver(error(retry=True))
    assert not task.done()  # old 120s policy fails before the real terminal
    clock.advance(106.583)
    await h.deliver(usage(), compact(), terminal())
    assert (await h.result(task))["ok"]
    assert (await s.get_context())["total_tokens"] == 1200
    assert (await s.get_context())["known"] is True
    s._persist.assert_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("exit", ["timeout", "cancel"])
@pytest.mark.parametrize("usage_order", ["before_terminal", "missing", "after_retirement"])
async def test_late_success_publishes_session_without_rewriting_caller(h, clock, exit, usage_order):
    s = make_session(h)
    task = await begin_session(h, s)
    response = await leave_caller(h, task, clock, exit)
    frozen = dict(response["compact_diagnostics"]) if response else None
    assert h.backend.compact_pending
    # A hibernate timer may already have refused this unresolved operation.
    h.backend._hibernate_safe = True
    assert (await s.hibernate_now())["reason"] == "compacting"
    s._persist.reset_mock()
    persisted = []
    s._persist.side_effect = lambda: persisted.append(dict(s._last_context))
    s._hibernate.schedule.reset_mock()
    messages = [compact(), terminal()]
    if usage_order == "before_terminal":
        messages.insert(0, usage())
    elif usage_order == "after_retirement":
        messages.append(usage())
    await h.deliver(*messages)
    assert not h.backend.compact_pending
    context = await s.get_context()
    assert context["known"] == (usage_order == "before_terminal")
    assert context["total_tokens"] == (1200 if context["known"] else 0)
    s._persist.assert_called_once()
    assert persisted == [dict(context)]
    s._hibernate.schedule.assert_called_once()
    assert len(compact_publications(s)) == 1
    diagnostics = h.backend.compact_diagnostics
    assert diagnostics["outcome"] == ("cancelled" if exit == "cancel" else "timeout")
    assert diagnostics["late"] and diagnostics["remote_outcome"] == "completed"
    if response:
        assert response["compact_diagnostics"] == frozen
        assert frozen["remote_outcome"] == "unknown"
        assert not response["ok"]
    await h.deliver(usage(9999), compact(), terminal())
    s._persist.assert_called_once()  # duplicates cannot republish or invent usage


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["failed", "interrupted", "error", "eof", "missing_evidence"])
async def test_failure_or_missing_evidence_never_publishes_success(h, clock, failure):
    s = make_session(h)
    task = await begin_session(h, s)
    s._persist.reset_mock()
    if failure == "eof":
        h.stream.feed_eof()
    elif failure == "error":
        await h.deliver(error())
    elif failure == "missing_evidence":
        await h.deliver(terminal())
        assert not task.done()
        clock.advance(PRODUCTION_BUDGET + 1)
    else:
        await h.deliver(terminal(failure))
    result = await h.result(task)  # failures must wake without advancing time
    assert not result["ok"]
    assert result["compact_diagnostics"]["outcome"] == (
        "timeout" if failure == "missing_evidence" else "failed"
    )
    assert result["error"]
    s._persist.assert_not_called()
    assert (await s.get_context())["total_tokens"] == 70000


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["failed", "interrupted", "missing_evidence", "eof"])
async def test_late_failure_releases_owner_without_success(h, clock, failure):
    s = make_session(h)
    task = await begin_session(h, s)
    await leave_caller(h, task, clock, "timeout")
    s._persist.reset_mock()
    if failure == "eof":
        h.stream.feed_eof()
        await h.result(h.reader)
    else:
        await h.deliver(usage(), terminal("completed" if failure == "missing_evidence" else failure))
    assert not h.backend.compact_pending
    s._persist.assert_not_called()
    assert not compact_publications(s)


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["turn", "backend", "model", "model_roundtrip", "transport", "thread"])
async def test_late_compact_cannot_revert_a_newer_snapshot(h, clock, change):
    s = make_session(h)
    task = await begin_session(h, s)
    await leave_caller(h, task, clock, "timeout")
    if change == "turn":
        # Even a newer turn which has already finished invalidates the snapshot.
        turn = await h.user()
        await h.deliver(usage(9000, turn=turn), terminal(turn=turn))
        assert any(item.type == "turn_end" for item in [item async for item in h.backend.events()])
    elif change == "backend":
        s._backend = object()
    elif change in ("model", "model_roundtrip"):
        h.backend.retarget_model("gpt-6-luna")
        if change == "model_roundtrip":
            h.backend.retarget_model(s.model)
        else:
            s.model = "gpt-6-luna"
    elif change == "transport":
        h.backend._transport_generation += 1
    else:
        s.session_id = "replacement-thread"
    s._last_context = {"known": True, "percentage": 9, "total_tokens": 9000, "max_tokens": 100000}
    s._persist.reset_mock()
    window = h.backend._model_context_window
    # Route at receive time for generation case: the old reader itself also has
    # its existing generation guard, covered by test_codex_compact_state.
    for message in (usage(window=88888), compact(), terminal()):
        h.backend._route_notification(message)
    assert (await s.get_context())["total_tokens"] == 9000
    s._persist.assert_not_called()
    if change in ("turn", "model", "model_roundtrip", "transport"):
        assert h.backend._model_context_window == window


@pytest.mark.asyncio
@pytest.mark.parametrize("user_usage", [True, False])
async def test_old_compact_usage_cannot_become_user_last_call(h, clock, monkeypatch, user_usage):
    task, request = await h.begin()
    await h.ack(request)
    await h.deliver(start())
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await h.result(task)
    turn = await h.user()
    consumed = asyncio.Event()
    record = h.backend._record_token_usage

    def observe(params):
        record(params)
        if h.backend._events_active:
            consumed.set()

    monkeypatch.setattr(h.backend, "_record_token_usage", observe)
    if user_usage:
        await h.deliver(usage(9000, turn=turn))
    events = h.backend.events()
    assert (await anext(events)).type == "status"
    next_event = h.task(anext(events))
    if user_usage:
        await asyncio.wait_for(consumed.wait(), 0.5)
    await h.deliver(usage(1000, window=88888), compact(), terminal(), terminal(turn=turn))
    tail = [await h.result(next_event), *[item async for item in events]]
    result = next(item for item in tail if item.type == "turn_end")
    assert result.metadata["ok"]
    assert result.metadata["context_known"] == user_usage
    if user_usage:
        assert result.metadata["context_tokens"] == 9000
    assert h.backend._model_context_window != 88888


@pytest.mark.asyncio
async def test_native_automatic_compact_supports_minutes_and_resumed_user_output(h, clock, monkeypatch):
    monkeypatch.setattr(source, "CODEX_SILENCE_HEARTBEAT_SECONDS", 0.001)
    turn = await h.user()
    await h.deliver(event("item/started", turnId=turn,
                          item={"id": "native-auto", "type": "contextCompaction"}))
    events = h.backend.events()
    assert (await anext(events)).type == "status"  # turn/started
    assert (await anext(events)).type == "status"
    clock.advance(480)
    waiting = await h.result(h.task(anext(events)))
    assert waiting.type == "thinking_stream" and waiting.metadata["activity"] == "waiting"
    await h.deliver(compact(turn=turn, item_id="native-auto"),
                    event("item/agentMessage/delta", turnId=turn, delta="resumed output"),
                    usage(1200, turn=turn), terminal(turn=turn))
    tail = [item async for item in events]
    assert any(item.content == "resumed output" for item in tail)
    assert sum(item.type == "turn_end" for item in tail) == 1
    assert not clock.deadlines  # explicit-call budget was never used


@pytest.mark.asyncio
@pytest.mark.parametrize("success", [True, False])
async def test_timer_reports_actual_compact_result(h, clock, monkeypatch, success):
    import app.session as session_source
    monkeypatch.setattr(session_source, "auto_compact_enabled", lambda: True)
    s = make_session(h)
    s._last_context["known"] = True
    s._precompact_timer = {"backend": "codex", "min_context_pct": 30}
    s._precompact_policy = Mock(return_value={"min_context_pct": 30})
    task = h.task(s._fire_precompact_timer())
    request = await h.request("thread/compact/start")
    await h.ack(request)
    await h.deliver(start(), compact(), terminal("completed" if success else "failed"))
    await h.result(task)
    result = s._precompact_timer["compact_result"]
    assert result["ok"] is success
    assert bool(result.get("error")) is not success
    # The final timer publication carries the actual result on the status
    # channel; native failures also retain their error-channel observation.
    publication = s._log.call_args_list[-1]
    assert publication.args[0] == "status"
    encoded = publication.args[1][publication.args[1].index("{"):]
    assert json.loads(encoded)["compact_result"] == result
    assert any(call.args[0] == "error" for call in s._log.call_args_list) is not success


@pytest.mark.asyncio
@pytest.mark.parametrize("delivery", ["direct", "queued"])
@pytest.mark.parametrize("exit", ["timeout", "cancel"])
async def test_delivery_survives_old_caller_exit_and_old_usage(h, clock, monkeypatch, delivery, exit):
    from app.events import MessageProvenance
    from app.live_broker import broker
    s = make_session(h)
    s._is_orchestrator = True
    s._spawn_bg = h.task
    s._activate_backend_tasks = Mock()
    s._refresh_runtime_context = AsyncMock()
    s._schedule_precompact_timer = Mock()
    s._cancel_precompact_timer = Mock()
    published = []
    monkeypatch.setattr(broker, "publish", lambda _sid, payload: published.append(payload))
    task = await begin_session(h, s)
    if delivery == "queued":
        await s.send("surviving message", provenance=MessageProvenance(origin="user", senders=("user",)))
        assert s._pending_messages
    await leave_caller(h, task, clock, exit)
    if delivery == "direct":
        sending = h.task(s.send("surviving message", provenance=MessageProvenance(origin="user", senders=("user",))))
    request = await h.request("turn/start")
    # Old compact usage overlaps new turn/start before its ACK. It must be
    # correlated after ACK rather than contaminating the user's caches.
    await h.deliver(usage(1000, window=88888), start("delivery-user"))
    await h.ack(request, {"turn": {"id": "delivery-user"}})
    if delivery == "direct":
        await h.result(sending)
    else:
        flush = next(item for item in h.tasks if "_flush_pending" in item.get_coro().__qualname__)
        await h.result(flush)
    assert s.status == AgentStatus.RUNNING
    await h.deliver(usage(9000, turn="delivery-user"), compact(), terminal())
    assert s.status == AgentStatus.RUNNING
    await h.deliver(event("item/agentMessage/delta", turnId="delivery-user", delta="delivered output"),
                    terminal(turn="delivery-user"))
    await h.result(s._listen_task)
    assert s.status == AgentStatus.IDLE
    assert s._pending_messages == []
    assert any(item.get("content") == "delivered output" for item in published)
    assert (await s.get_context())["total_tokens"] == 9000
    assert not compact_publications(s)


@pytest.mark.asyncio
async def test_no_ack_cannot_turn_late_lifecycle_into_success(h, clock):
    s = make_session(h)
    task = h.task(s.compact())
    await h.request("thread/compact/start")
    await leave_caller(h, task, clock, "timeout")
    await h.deliver(start(), usage(), compact(), terminal())
    s._persist.assert_not_called()
    assert not h.backend.compact_pending
    assert (await s.get_context())["total_tokens"] == 70000


@pytest.mark.asyncio
async def test_refused_retry_cannot_take_the_old_operations_publication_hook(h, clock):
    s = make_session(h)
    task = await begin_session(h, s)
    await leave_caller(h, task, clock, "timeout")
    assert not (await s.compact())["ok"]
    s._persist.reset_mock()
    await h.deliver(usage(), compact(), terminal())
    assert (await s.get_context())["total_tokens"] == 1200
    s._persist.assert_called_once()


@pytest.mark.asyncio
async def test_mcp_compact_call_budget_covers_backend_and_preserves_failure(monkeypatch, clock):
    error_value = "compact-error-sentinel-1150"

    class FailedResult(dict):
        def __str__(self):
            raise AssertionError("MCP must handle a failure, not dump the raw result")

    async def api(method, path, **options):
        assert method == "POST" and path == "/api/sessions/worker/compact"
        assert PRODUCTION_BUDGET < options["timeout"] <= PRODUCTION_BUDGET + 60
        return FailedResult(ok=False, error=error_value)

    monkeypatch.setattr(mcp_stdio, "_api", api)
    response = await mcp_stdio.compact_worker("worker")
    assert error_value in response


@pytest.mark.asyncio
@pytest.mark.parametrize("stopped", [False, True])
async def test_late_terminal_retries_refused_queue_but_respects_manual_stop(h, clock, monkeypatch, stopped):
    from app.live_broker import broker
    monkeypatch.setattr(broker, "publish", Mock())
    s = make_session(h)
    s._is_orchestrator = True
    s._spawn_bg = h.task
    s._activate_backend_tasks = Mock()
    s._refresh_runtime_context = AsyncMock()
    s._schedule_precompact_timer = Mock()
    s._cancel_precompact_timer = Mock()
    s._pending_messages = ["retained after a refused start"]
    task = await begin_session(h, s)
    await leave_caller(h, task, clock, "timeout")
    request = await h.request("turn/start")
    await h.deliver({"id": request, "error": {"code": -32000, "message": "synthetic compact still running"}})
    flush = next(item for item in h.tasks if "_flush_pending" in item.get_coro().__qualname__)
    await h.result(flush)
    assert s._pending_messages == ["retained after a refused start"]
    assert s.status == AgentStatus.IDLE
    if stopped:
        stop = h.task(s.interrupt())
        request = await h.request("turn/interrupt")
        await h.ack(request)
        await h.result(stop)
    count = len(h.tasks)
    await h.deliver(usage(), compact(), terminal())
    if stopped:
        assert len(h.tasks) == count
        assert s._pending_messages == ["retained after a refused start"]
        return
    request = await h.request("turn/start")
    await h.deliver(start("recovered-user"))
    await h.ack(request, {"turn": {"id": "recovered-user"}})
    retry = next(item for item in h.tasks[count:] if "_flush_pending" in item.get_coro().__qualname__)
    await h.result(retry)
    await h.deliver(usage(9000, turn="recovered-user"), terminal(turn="recovered-user"))
    await h.result(s._listen_task)
    assert not s._pending_messages
    assert (await s.get_context())["total_tokens"] == 9000


@pytest.mark.asyncio
async def test_critical_auto_compact_uses_the_same_late_publication(h, clock):
    s = make_session(h)
    task = h.task(s._auto_compact(delay_seconds=0))
    request = await h.request("thread/compact/start")
    await h.ack(request)
    await h.deliver(start())
    clock.advance(PRODUCTION_BUDGET + 1)
    await h.result(task)
    await h.deliver(usage(), compact(), terminal())
    assert (await s.get_context())["total_tokens"] == 1200
    assert len(compact_publications(s)) == 1


@pytest.mark.asyncio
async def test_late_fatal_error_is_not_relabelled_success(h, clock):
    s = make_session(h)
    task = await begin_session(h, s)
    await leave_caller(h, task, clock, "timeout")
    await h.deliver(error(), usage(), compact(), terminal())
    s._persist.assert_not_called()
    assert (await s.get_context())["total_tokens"] == 70000
