"""Native compact regression oracles: real JSONL reader/request/send/events, no CLI."""
import asyncio
import json
import socket
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio

import app
import app.backend_codex as source
from app.backend_codex import CodexBackend, CodexProtocolError
from app.session import AgentSession
from app.session_state import AgentStatus

THREAD = "compact-test-thread"
TURN = "compact-test-turn"


def event(method, *, thread=THREAD, turn=None, **params):
    if thread is not None:
        params["threadId"] = thread
    if turn is not None:
        params["turn"] = {"id": turn}
    return {"method": method, "params": params}


def start(turn=TURN, thread=THREAD):
    return event("turn/started", thread=thread, turn=turn)


def terminal(status="completed", turn=TURN, thread=THREAD):
    message = event("turn/completed", thread=thread)
    message["params"]["turn"] = {"id": turn, "status": status}
    return message


def compact(method="item/completed", turn=TURN, thread=THREAD, item_id="compact-item"):
    params = {"turnId": turn} if turn is not None else {}
    if method == "item/completed":
        params["item"] = {"id": item_id, "type": "contextCompaction"}
    return event(method, thread=thread, **params)


def error(retry=False, turn=TURN, thread=THREAD):
    return event("error", thread=thread, turnId=turn, willRetry=retry,
                 error={"message": "synthetic compact failure", "codexErrorInfo": "internalServerError"})


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("compact regression tests must remain offline")
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    for name in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(source, "CODEX_COMPACT_TIMEOUT_SECONDS", 0.06)


class Pipe:
    def __init__(self, outgoing):
        self.outgoing = outgoing

    def write(self, raw):
        self.outgoing.put_nowait(json.loads(raw))

    async def drain(self):
        pass


class Harness:
    def __init__(self):
        self.backend = CodexBackend(model="gpt-5.6-sol", cwd=str(Path(__file__).parent))
        self.backend._thread_id = THREAD
        self.outgoing = asyncio.Queue()
        self.stream = asyncio.StreamReader()
        self.exit = asyncio.Event()
        self.exit.set()
        self.backend._proc = SimpleNamespace(returncode=None, stdin=Pipe(self.outgoing),
                                             stdout=self.stream, wait=self.exit.wait)
        self.backend._runtime_context = Mock(return_value=None)
        self.backend._runtime_totals = Mock(return_value=None)
        self.backend._reload_stale_managed_config_before_turn = AsyncMock()
        self.tasks = []
        self.barriers = {}
        original = self.stream.readline

        async def observe():
            raw = await original()
            try:
                message = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                message = {}
            if message.get("method") == "test/barrier":
                asyncio.get_running_loop().call_soon(self.barriers[message["params"]["n"]].set)
            return raw
        self.stream.readline = observe
        self.reader = asyncio.create_task(self.backend._read_stdout())

    def task(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.append(task)
        return task

    async def request(self, method):
        request = await asyncio.wait_for(self.outgoing.get(), 0.5)
        assert request["method"] == method
        return request["id"]

    async def begin(self):
        task = self.task(self.backend.compact_context())
        return task, await self.request("thread/compact/start")

    async def deliver(self, *messages):
        marker = len(self.barriers)
        ready = self.barriers[marker] = asyncio.Event()
        for message in (*messages, {"method": "test/barrier", "params": {"n": marker}}):
            self.stream.feed_data((json.dumps(message) + "\n").encode())
        await asyncio.wait_for(ready.wait(), 0.5)

    async def ack(self, request, result=None):
        await self.deliver({"id": request, "result": result or {}})

    async def result(self, task):
        return await asyncio.wait_for(asyncio.shield(task), 0.5)

    async def user(self, turn="user-turn"):
        task = self.task(self.backend.send("synthetic user input"))
        request = await self.request("turn/start")
        await self.deliver(start(turn), {"id": request, "result": {"turn": {"id": turn}}})
        await self.result(task)
        return turn

    async def close(self):
        for task in self.tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.backend._disconnecting = True
        self.exit.set()
        if not self.stream.at_eof():
            self.stream.feed_eof()
        await asyncio.wait_for(self.reader, 0.5)


@pytest_asyncio.fixture
async def h():
    harness = Harness()
    try:
        yield harness
    finally:
        await harness.close()


def test_import_identity():
    imported = Path(app.__file__).resolve().relative_to(Path(__file__).resolve().parents[1])
    assert imported == Path("app/__init__.py")
    print("APP_IMPORT=" + imported.as_posix())


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["item/completed", "context/compacted", "thread/compacted"])
@pytest.mark.parametrize("before_ack,reverse", [(False, False), (True, False), (False, True), (True, True)])
async def test_success_forms_and_order(h, method, before_ack, reverse):
    task, request = await h.begin()
    if not before_ack:
        await h.ack(request)
    c, t = compact(method), terminal()
    await h.deliver(start(), *([t, c] if reverse else [c, t]))
    if before_ack:
        assert not task.done()
        await h.ack(request)
    assert (await h.result(task))["ok"] is True
    assert h.backend.active_turn_id is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["failed", "interrupted", "unsupported"])
@pytest.mark.parametrize("with_compact", [False, True])
async def test_terminal_failure_never_ok_or_timeout(h, status, with_compact):
    task, request = await h.begin()
    await h.ack(request)
    await h.deliver(start(), *([compact()] if with_compact else []), terminal(status))
    with pytest.raises(RuntimeError, match=status) as observed:
        await h.result(task)
    assert not isinstance(observed.value, TimeoutError)


@pytest.mark.asyncio
@pytest.mark.parametrize("retry", [False, True])
async def test_failed_beats_retry_hint_and_retains_cause(h, retry):
    task, request = await h.begin()
    await h.ack(request)
    await h.deliver(start(), error(retry), terminal("failed"))
    with pytest.raises(RuntimeError, match="synthetic compact failure") as observed:
        await h.result(task)
    assert not isinstance(observed.value, TimeoutError)


@pytest.mark.asyncio
async def test_retryable_error_can_recover(h):
    task, request = await h.begin()
    await h.ack(request)
    await h.deliver(start(), error(True), compact(), terminal())
    assert (await h.result(task))["ok"]


@pytest.mark.asyncio
@pytest.mark.parametrize("before_ack", [False, True])
async def test_fatal_error_wakes_without_terminal(h, before_ack):
    task, request = await h.begin()
    if not before_ack:
        await h.ack(request)
    await h.deliver(start(), error())
    with pytest.raises(RuntimeError, match="synthetic compact failure") as observed:
        await h.result(task)
    assert not isinstance(observed.value, TimeoutError)
    with pytest.raises(RuntimeError, match="already in progress|unresolved"):
        await h.backend.compact_context()


@pytest.mark.asyncio
async def test_whole_operation_is_busy_after_item(h):
    task, request = await h.begin()
    await h.ack(request)
    await h.deliver(start(), compact())
    with pytest.raises(RuntimeError, match="already in progress"):
        await h.backend.compact_context()
    with pytest.raises(RuntimeError, match="compact"):
        await h.backend.send("do not steer compact")
    await h.deliver(terminal())
    assert (await h.result(task))["ok"]


@pytest.mark.asyncio
async def test_second_started_does_not_replace_owner(h):
    task, request = await h.begin()
    await h.ack(request)
    await h.deliver(start(), start("foreign-turn"), compact(), terminal())
    assert (await h.result(task))["ok"]


@pytest.mark.asyncio
@pytest.mark.parametrize("foreign", ["thread", "turn"])
async def test_foreign_events_cannot_complete_or_contaminate(h, foreign):
    task, request = await h.begin()
    await h.ack(request)
    await h.deliver(start())
    turn = "foreign-turn" if foreign == "turn" else TURN
    thread = "foreign-thread" if foreign == "thread" else THREAD
    await h.deliver(error(turn=turn, thread=thread),
                    event("thread/tokenUsage/updated", thread=thread, turnId=turn,
                          tokenUsage={"last": {"totalTokens": 777}, "modelContextWindow": 9999}),
                    compact(turn=turn, thread=thread), terminal(turn=turn, thread=thread))
    assert not task.done()
    await h.deliver(compact(), terminal())
    result = await h.result(task)
    assert result["context_tokens"] is None
    assert result["max_tokens"] != 9999


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["ack", "completion", "terminal"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_timeout_cancel_retains_owner_and_reconciles(h, stage, cancel):
    task, request = await h.begin()
    if stage != "ack":
        await h.ack(request)
    await h.deliver(start(), *([compact()] if stage == "terminal" else []))
    if cancel:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
        await h.result(task)
    with pytest.raises(RuntimeError, match="already in progress|unresolved"):
        await h.backend.compact_context()
    assert not h.backend._pending_requests
    assert h.backend.compact_pending is True
    diagnostics = h.backend.compact_diagnostics
    assert diagnostics["outcome"] == ("cancelled" if cancel else "timeout")
    assert diagnostics["remote_outcome"] == "unknown"
    assert "stage" in diagnostics and "operation" in diagnostics
    await h.deliver(compact(), terminal())
    assert not h.backend.compact_pending
    assert h.backend.compact_diagnostics["late"] is True
    assert all(m["method"] not in ("item/completed", "turn/completed")
               for m in h.backend._notifications._queue)
    retry, request = await h.begin()
    await h.ack(request)
    # Duplicates of the old completed turn must not claim the retry.
    await h.deliver(start(), compact(), terminal())
    assert not retry.done()
    await h.deliver(start("retry-turn"), compact(turn="retry-turn", item_id="retry-item"),
                    terminal(turn="retry-turn"))
    assert (await h.result(retry))["ok"]


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["ack", "completion", "terminal"])
@pytest.mark.parametrize("transport", ["eof", "read_error", "disconnect"])
@pytest.mark.parametrize("scheduling_delay", [0, 0.09])
async def test_transport_failure_wakes_every_stage_without_waiting_process(
    h, monkeypatch, stage, transport, scheduling_delay,
):
    # This oracle must be woken by transport failure, never the compact deadline.
    # The independent asyncio.wait below bounds a broken wakeup; timeout/cancel
    # behavior keeps its real short deadline in the dedicated tests above.
    monkeypatch.setattr(source, "CODEX_COMPACT_TIMEOUT_SECONDS", None)
    task, request = await h.begin()
    if stage != "ack":
        await h.ack(request)
    await h.deliver(start(), *([compact()] if stage == "terminal" else []))
    expected_stage = {
        "ack": "request acknowledgement",
        "completion": "completion notification",
        "terminal": "turn lifecycle",
    }[stage]
    assert h.backend.compact_diagnostics["stage"] == expected_stage
    h.exit.clear()
    process_wait = AsyncMock(side_effect=h.exit.wait)
    h.backend._proc.wait = process_wait
    # Simulate a descheduled event loop crossing the old global 60 ms budget.
    # Advance only this loop's clock: no sleeps, live I/O or wall-clock race.
    loop = asyncio.get_running_loop()
    clock = loop.time
    monkeypatch.setattr(loop, "time", lambda: clock() + scheduling_delay)
    if transport == "eof":
        h.stream.feed_eof()
    elif transport == "read_error":
        h.stream.set_exception(OSError("synthetic pipe failure"))
    else:
        h.backend.teardown_owned_pipes = AsyncMock()
        await h.backend._finalize_disconnect()
    done, _ = await asyncio.wait({task}, timeout=0.5)
    assert task in done, "transport closure left the compact waiter pending"
    with pytest.raises(RuntimeError, match="transport closed|disconnected") as observed:
        await task
    assert not isinstance(observed.value, TimeoutError)
    assert not h.backend.compact_pending
    assert not h.backend._pending_requests
    assert not h.exit.is_set()
    assert not h.reader.done()
    if transport != "disconnect":
        process_wait.assert_awaited_once()
    else:
        process_wait.assert_not_awaited()
    assert h.backend.compact_diagnostics["outcome"] == "failed"
    assert h.backend.compact_diagnostics["remote_outcome"] == "transport_closed"
    assert h.backend.compact_diagnostics["stage"] == expected_stage


@pytest.mark.asyncio
async def test_rpc_rejection_is_not_unresolved(h):
    task, request = await h.begin()
    await h.deliver({"id": request, "error": {"code": -32000, "message": "synthetic rejected"}})
    with pytest.raises(CodexProtocolError):
        await h.result(task)
    assert not h.backend.compact_pending
    retry, request = await h.begin()
    await h.ack(request)
    await h.deliver(start(), compact(), terminal())
    assert (await h.result(retry))["ok"]


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["item/completed", "context/compacted", "thread/compacted"])
async def test_legacy_missing_ids_has_exclusive_lifecycle_boundary(h, method):
    task, request = await h.begin()
    await h.ack(request)
    await h.deliver(start(thread=None), compact(method, thread=None, turn=None), terminal(thread=None))
    assert (await h.result(task))["ok"]


@pytest.mark.asyncio
async def test_missing_start_does_not_report_success(h):
    task, request = await h.begin()
    await h.ack(request)
    await h.deliver(compact(), terminal())
    with pytest.raises((RuntimeError, TimeoutError)):
        await h.result(task)


@pytest.mark.asyncio
async def test_old_main_queue_and_stale_runtime_snapshot_are_not_evidence(h):
    await h.deliver(start("old-turn"), compact(turn="old-turn"), terminal(turn="old-turn"))
    h.backend._runtime_context.return_value = {"input_tokens": 70000, "model_context_window": 9999}
    task, request = await h.begin()
    await h.ack(request)
    await h.deliver(start(), compact(item_id="new-item"), terminal())
    result = await h.result(task)
    assert result["context_tokens"] is None
    assert result["max_tokens"] != 9999


@pytest.mark.asyncio
async def test_ordinary_user_turn_and_auto_compaction_are_supported(h):
    turn = await h.user()
    await h.deliver(compact(turn=turn), terminal(turn=turn))
    events = [item async for item in h.backend.events()]
    assert any(item.content == "codex context compacted" for item in events)
    assert any(item.type == "turn_end" and item.metadata["ok"] for item in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("late_before_ack", [False, True])
async def test_ordinary_send_recovers_while_unresolved_with_early_events(h, late_before_ack):
    first, request = await h.begin()
    await h.ack(request)
    with pytest.raises(TimeoutError):
        await h.result(first)
    send = h.task(h.backend.send("ordinary recovery message"))
    request = await h.request("turn/start")
    # User lifecycle arrives before its ACK, while old compact has no known turn.
    await h.deliver(start("user-turn"), compact(turn="user-turn", item_id="auto-item"))
    if late_before_ack:
        await h.deliver(start(), compact(), terminal())
    await h.ack(request, {"turn": {"id": "user-turn"}})
    await h.result(send)
    if not late_before_ack:
        await h.deliver(start(), compact(), terminal())
    await h.deliver(event("item/agentMessage/delta", turnId="user-turn", delta="user output"),
                    terminal(turn="user-turn"))
    events = [item async for item in h.backend.events()]
    assert sum(item.content == "codex context compacted" for item in events) == 1
    assert any(item.content == "user output" for item in events)
    assert sum(item.type == "turn_end" for item in events) == 1
    assert not h.backend.compact_pending


@pytest.mark.asyncio
async def test_native_interrupt_uses_compact_turn(h):
    task, request = await h.begin()
    await h.ack(request)
    await h.deliver(start())
    interrupt = h.task(h.backend.interrupt())
    request = await h.request("turn/interrupt")
    await h.ack(request)
    assert await h.result(interrupt)
    await h.deliver(terminal("interrupted"))
    with pytest.raises(RuntimeError, match="interrupted"):
        await h.result(task)


def make_session(h):
    # Real AgentSession and compact permit/start/finally; persistence/timers are isolated.
    s = AgentSession(id="compact-state", name="compact-state", scope=str(Path(__file__).parent),
                     cwd=str(Path(__file__).parent), role="worker", model="gpt-5.6-sol",
                     created_at=datetime.now(timezone.utc), session_id=THREAD, backend_type="codex")
    s._backend = h.backend
    s._ensure_backend = AsyncMock(return_value=h.backend)
    s._last_context = {"percentage": 70, "total_tokens": 70000, "max_tokens": 100000}
    s._log = Mock()
    s._persist = Mock()
    s._drain_persist = AsyncMock()
    s._build_runtime_handoff = AsyncMock(return_value=None)
    s._wake_durable_message_deliveries = Mock()
    s._hibernate.schedule = Mock()
    s._disconnect_backend = AsyncMock()
    return s


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "failed", "timeout", "cancel"])
async def test_session_compact_path_and_hibernate(h, outcome):
    s = make_session(h)
    h.backend._hibernate_safe = True
    task = h.task(s.compact())
    request = await h.request("thread/compact/start")
    await h.ack(request)
    await h.deliver(start())
    assert (await s.hibernate_now())["reason"] == "compacting"
    if outcome in ("success", "failed"):
        await h.deliver(event("thread/tokenUsage/updated", turnId=TURN,
                              tokenUsage={"last": {"totalTokens": 1234}, "modelContextWindow": 100000}),
                        compact(), terminal("completed" if outcome == "success" else "failed"))
    if outcome == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await h.result(task)
    else:
        result = await h.result(task)
        assert result["ok"] == (outcome == "success")
    assert not s._compacting
    assert s._last_context["total_tokens"] == (1234 if outcome == "success" else 70000)
    s._wake_durable_message_deliveries.assert_called_once()
    if outcome in ("timeout", "cancel"):
        assert (await s.hibernate_now())["reason"] == "compacting"
        s._disconnect_backend.assert_not_awaited()
        await h.deliver(compact(), terminal())
    assert (await s.hibernate_now())["ok"]
    s._disconnect_backend.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["error", "failed", "interrupted"])
async def test_tagged_failure_without_started_is_actionable(h, failure):
    task, request = await h.begin()
    await h.ack(request)
    await h.deliver(error() if failure == "error" else terminal(failure))
    with pytest.raises(RuntimeError) as observed:
        await h.result(task)
    assert not isinstance(observed.value, TimeoutError)


@pytest.mark.asyncio
async def test_failed_terminal_keeps_its_embedded_error(h):
    task, request = await h.begin()
    await h.ack(request)
    failed = terminal("failed")
    failed["params"]["turn"]["error"] = {"message": "synthetic terminal failure"}
    await h.deliver(start(), failed)
    with pytest.raises(RuntimeError, match="synthetic terminal failure"):
        await h.result(task)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["item/completed", "context/compacted", "thread/compacted"])
async def test_fully_id_free_legacy_is_bounded_by_started_and_terminal(h, method):
    task, request = await h.begin()
    await h.ack(request)
    await h.deliver(start(turn=None, thread=None), compact(method, turn=None, thread=None),
                    terminal(turn=None, thread=None))
    assert (await h.result(task))["ok"]
    assert h.backend.compact_diagnostics["ignored"]["legacy_unscoped"] > 0


@pytest.mark.asyncio
async def test_foreign_started_cannot_supply_own_lifecycle(h):
    task, request = await h.begin()
    await h.ack(request)
    await h.deliver(start(thread="foreign-thread"), compact(), terminal(thread="foreign-thread"))
    assert not task.done()
    await h.deliver(start(), compact(item_id="own-item"), terminal())
    assert (await h.result(task))["ok"]


@pytest.mark.asyncio
async def test_no_ack_despite_completed_protocol_still_times_out(h):
    task, _ = await h.begin()
    await h.deliver(start(), compact(), terminal())
    with pytest.raises(TimeoutError, match="request acknowledgement") as observed:
        await h.result(task)
    assert observed.value.compact_diagnostics["remote_outcome"] == "completed"
    assert not h.backend.compact_pending


@pytest.mark.asyncio
async def test_completed_terminal_without_compaction_allows_safe_retry(h):
    task, request = await h.begin()
    await h.ack(request)
    await h.deliver(start(), terminal())
    with pytest.raises(TimeoutError, match="completion notification"):
        await h.result(task)
    assert not h.backend.compact_pending
    retry, request = await h.begin()
    await h.ack(request)
    await h.deliver(compact())  # late tagged C from the old turn
    await h.deliver(start("retry-turn"), terminal(turn="retry-turn"))
    assert not retry.done()
    await h.deliver(compact(turn="retry-turn", item_id="retry-item"))
    assert (await h.result(retry))["ok"]


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["item/completed", "context/compacted", "thread/compacted"])
async def test_early_idle_compaction_cannot_be_shown_as_next_user_compact(h, method):
    await h.deliver(start("old-turn"), compact(method, turn=None), terminal(turn="old-turn"))
    turn = await h.user()
    await h.deliver(terminal(turn=turn))
    events = [item async for item in h.backend.events()]
    assert not any(item.content == "codex context compacted" for item in events)
    assert sum(item.type == "turn_end" for item in events) == 1


@pytest.mark.asyncio
async def test_duplicate_item_id_cannot_supply_new_compaction_evidence(h):
    task, request = await h.begin()
    await h.ack(request)
    await h.deliver(start(), compact(), terminal())
    await h.result(task)
    retry, request = await h.begin()
    await h.ack(request)
    await h.deliver(start("retry-turn"), compact(turn="retry-turn"), terminal(turn="retry-turn"))
    assert not retry.done()
    await h.deliver(compact(turn="retry-turn", item_id="new-item"))
    assert (await h.result(retry))["ok"]


@pytest.mark.asyncio
async def test_invalid_json_is_diagnosed_without_false_success(h):
    task, request = await h.begin()
    await h.ack(request)
    await h.deliver(start())
    h.stream.feed_data(b"{invalid compact record}\n")
    await h.deliver(terminal())
    with pytest.raises(TimeoutError):
        await h.result(task)
    assert h.backend.compact_diagnostics["ignored"]["invalid_json"] == 1


@pytest.mark.asyncio
async def test_diagnostic_metadata_does_not_contain_bodies_or_native_ids(h):
    task, request = await h.begin()
    await h.ack(request)
    await h.deliver(start(), error(True))
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await h.result(task)
    metadata = json.dumps(h.backend.compact_diagnostics)
    assert "synthetic compact failure" not in metadata
    assert THREAD not in metadata and TURN not in metadata
    assert h.backend.compact_diagnostics["error_info"] == ["internalServerError"]
    assert h.backend.compact_diagnostics["will_retry"] is True
    assert h.backend.compact_diagnostics["stage"] == "completion notification"


@pytest.mark.asyncio
async def test_session_unknown_usage_does_not_reuse_precompact_percentage(h):
    s = make_session(h)
    task = h.task(s.compact())
    request = await h.request("thread/compact/start")
    await h.ack(request)
    await h.deliver(start(), compact(), terminal())
    assert (await h.result(task))["ok"]
    assert s._last_context["known"] is False
    assert s._last_context["percentage"] == 0
    assert s._last_context["total_tokens"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("started", [False, True])
async def test_session_interrupt_does_not_disconnect_unknown_compact(h, started):
    s = make_session(h)
    task = h.task(s.compact())
    request = await h.request("thread/compact/start")
    await h.ack(request)
    if started:
        await h.deliver(start())
    interrupt = h.task(s.interrupt())
    if started:
        request = await h.request("turn/interrupt")
        await h.ack(request)
        await h.deliver(terminal("interrupted"))
    await h.result(interrupt)
    s._disconnect_backend.assert_not_awaited()
    if not started:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await h.result(task)
        # The same path remains manually interruptible after the caller leaves.
        await h.deliver(start())
        interrupt = h.task(s.interrupt())
        request = await h.request("turn/interrupt")
        await h.ack(request)
        await h.result(interrupt)
        await h.deliver(terminal("interrupted"))
    else:
        assert not (await h.result(task))["ok"]
    assert not h.backend.compact_pending
    s._disconnect_backend.assert_not_awaited()


@pytest.mark.asyncio
async def test_session_actual_send_and_listener_proceed_after_compact_timeout(h, monkeypatch):
    s = make_session(h)
    task = h.task(s.compact())
    request = await h.request("thread/compact/start")
    await h.ack(request)
    assert not (await h.result(task))["ok"]
    s._activate_backend_tasks = Mock()
    s._refresh_runtime_context = AsyncMock()
    s._schedule_precompact_timer = Mock()
    s._cancel_precompact_timer = Mock()
    # Keep event handling real while isolating DB/UI publication side effects.
    from app.live_broker import broker
    published = []
    monkeypatch.setattr(broker, "publish", lambda _sid, payload: published.append(payload))
    from app.events import MessageProvenance
    send = h.task(s.send("ordinary follow-up", provenance=MessageProvenance(origin="user", senders=("user",))))
    request = await h.request("turn/start")
    await h.deliver(start("session-user"))
    await h.ack(request, {"turn": {"id": "session-user"}})
    await h.result(send)
    assert s.status == AgentStatus.RUNNING
    await h.deliver(start(), compact(), terminal())
    assert s.status == AgentStatus.RUNNING
    await h.deliver(event("item/agentMessage/delta", turnId="session-user", delta="user output"),
                    terminal(turn="session-user"))
    await asyncio.wait_for(s._listen_task, 0.5)
    assert s.status == AgentStatus.IDLE
    assert any(item.get("content") == "user output" for item in published)
    assert not any(item.get("content") == "codex context compacted" for item in published)
    assert not h.backend.compact_pending


@pytest.mark.asyncio
async def test_one_deadline_includes_ack_and_completion(h, monkeypatch):
    monkeypatch.setattr(source, "CODEX_COMPACT_TIMEOUT_SECONDS", 0.2)
    task, request = await h.begin()
    ready = asyncio.Event()
    handle = asyncio.get_running_loop().call_later(0.12, ready.set)
    try:
        await ready.wait()
        await h.ack(request)
        await h.deliver(start())
        too_late = asyncio.Event()
        completion = asyncio.get_running_loop().call_later(0.12, too_late.set)
        try:
            with pytest.raises(TimeoutError, match="completion notification"):
                await h.result(task)
            assert not too_late.is_set()
        finally:
            completion.cancel()
    finally:
        handle.cancel()


@pytest.mark.asyncio
async def test_retired_identity_is_not_evicted_by_many_ordinary_turns(h):
    task, request = await h.begin()
    await h.ack(request)
    await h.deliver(start(), compact(), terminal())
    await h.result(task)
    await h.deliver(*(terminal(turn=f"idle-old-{n}") for n in range(70)))
    retry, request = await h.begin()
    await h.ack(request)
    await h.deliver(start(), compact(), terminal())
    assert not retry.done()
    await h.deliver(start("retry-turn"), compact(turn="retry-turn", item_id="new-item"),
                    terminal(turn="retry-turn"))
    assert (await h.result(retry))["ok"]


@pytest.mark.asyncio
@pytest.mark.parametrize("old_stage", ["read", "process_wait"])
async def test_old_reader_cannot_fail_or_route_into_new_generation(h, old_stage):
    old_reader = h.reader
    old_stream = h.stream
    waiting = asyncio.Event()
    release_exit = asyncio.Event()

    async def wait_old_process():
        waiting.set()
        await release_exit.wait()
        return 0

    h.backend._proc.wait = wait_old_process
    if old_stage == "process_wait":
        old_stream.feed_eof()
        await asyncio.wait_for(waiting.wait(), 0.5)
    h.backend._transport_generation += 1
    h.backend._stdout_closed = False
    new_stream = asyncio.StreamReader()
    h.backend._proc = SimpleNamespace(returncode=None, stdout=new_stream,
                                     stdin=Pipe(h.outgoing), wait=AsyncMock(return_value=0))
    h.reader = asyncio.create_task(h.backend._read_stdout())
    task, request = await h.begin()
    if old_stage == "read":
        old_stream.feed_data((json.dumps(terminal("failed")) + "\n").encode())
    release_exit.set()
    await asyncio.wait_for(old_reader, 0.5)
    assert not task.done()
    assert h.backend._stdout_closed is False
    for message in ({"id": request, "result": {}}, start(), compact(), terminal()):
        new_stream.feed_data((json.dumps(message) + "\n").encode())
    assert (await h.result(task))["ok"]
    new_stream.feed_eof()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["error", "failed", "interrupted"])
async def test_legacy_failure_without_started_is_not_hidden_by_timeout(h, method):
    task, request = await h.begin()
    await h.ack(request)
    await h.deliver(error(turn=None, thread=None) if method == "error"
                    else terminal(method, turn=None, thread=None))
    with pytest.raises(RuntimeError) as observed:
        await h.result(task)
    assert not isinstance(observed.value, TimeoutError)


@pytest.mark.asyncio
async def test_session_queued_delivery_reaches_actual_listener_after_timeout(h, monkeypatch):
    s = make_session(h)
    # Admission is covered by the existing session suite; this isolates queue release.
    s._is_orchestrator = True
    s._pending_messages = ["queued user input"]
    s._spawn_bg = h.task
    from app.live_broker import broker
    monkeypatch.setattr(broker, "publish", Mock())
    task = h.task(s.compact())
    request = await h.request("thread/compact/start")
    await h.ack(request)
    assert not (await h.result(task))["ok"]
    request = await h.request("turn/start")
    await h.deliver(start("queued-user"))
    await h.ack(request, {"turn": {"id": "queued-user"}})
    await h.deliver(event("item/agentMessage/delta", turnId="queued-user", delta="queued user output"),
                    terminal(turn="queued-user"))
    # _flush_pending holds the session lock through ACK, then owns the listener.
    flush = next(task for task in h.tasks if "_flush_pending" in task.get_coro().__qualname__)
    await h.result(flush)
    await asyncio.wait_for(s._listen_task, 0.5)
    assert s.status == AgentStatus.IDLE
    assert s._pending_messages == []
    assert h.backend.compact_pending  # Ordinary work did not invent compact success.
    await h.deliver(start(), compact(), terminal())
    assert not h.backend.compact_pending


@pytest.mark.asyncio
async def test_unresolved_compact_preserves_manual_interrupt_of_ordinary_running_turn(h):
    s = make_session(h)
    task = h.task(s.compact())
    request = await h.request("thread/compact/start")
    await h.ack(request)
    assert not (await h.result(task))["ok"]
    s.status = AgentStatus.RUNNING
    h.backend._active_turn_id = "ordinary-turn"
    h.backend.interrupt = AsyncMock(return_value=False)
    # Teardown is the existing ordinary-turn manual-stop fallback, not compact
    # recovery. This test does not operate on a real process.
    await asyncio.wait_for(s.interrupt(), 0.5)
    s._disconnect_backend.assert_awaited_once()
    assert s.status == AgentStatus.IDLE


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["eof", "read_error", "disconnect"])
@pytest.mark.parametrize("reverse", [False, True])
async def test_preack_completed_lifecycle_transport_failure_wakes_ack_waiter(h, monkeypatch, transport, reverse):
    # C/T before ACK must not turn EOF into either success or an ACK timeout.
    # A long compact deadline makes the short independent observation window
    # distinguish transport wakeup from expiration of the operation's budget.
    monkeypatch.setattr(source, "CODEX_COMPACT_TIMEOUT_SECONDS", 5)
    task, _request = await h.begin()
    c, t = compact(), terminal()
    await h.deliver(start(), *([t, c] if reverse else [c, t]))
    assert not task.done()
    process_wait_started = asyncio.Event()
    h.exit.clear()

    async def pending_process_exit():
        process_wait_started.set()
        return await h.exit.wait()

    h.backend._proc.wait = pending_process_exit
    if transport == "eof":
        h.stream.feed_eof()
    elif transport == "read_error":
        h.stream.set_exception(OSError("synthetic pre-ACK pipe failure"))
    else:
        h.backend.teardown_owned_pipes = AsyncMock()
        await h.backend._finalize_disconnect()
    if transport != "disconnect":
        await asyncio.wait_for(process_wait_started.wait(), 0.5)
    done, _ = await asyncio.wait({task}, timeout=0.15)
    assert task in done, "transport closure left the compact ACK waiter pending"
    with pytest.raises(RuntimeError) as observed:
        await task
    assert not isinstance(observed.value, TimeoutError)
    assert not h.backend.compact_pending
    assert not h.backend._pending_requests
    assert h.backend.compact_diagnostics["outcome"] == "failed"
    assert h.backend.compact_diagnostics["remote_outcome"] == "completed"
    assert h.backend.compact_diagnostics["stage"] == "request acknowledgement"


@pytest.mark.asyncio
@pytest.mark.parametrize("reverse", [False, True])
async def test_preack_completed_lifecycle_rpc_rejection_cannot_return_success(h, reverse):
    task, request = await h.begin()
    c, t = compact(), terminal()
    await h.deliver(start(), *([t, c] if reverse else [c, t]))
    assert not task.done()
    await h.deliver({"id": request, "error": {"code": -32000, "message": "synthetic pre-ACK rejection"}})
    with pytest.raises(CodexProtocolError, match="synthetic pre-ACK rejection"):
        await h.result(task)
    assert not h.backend.compact_pending
    assert not h.backend._pending_requests
