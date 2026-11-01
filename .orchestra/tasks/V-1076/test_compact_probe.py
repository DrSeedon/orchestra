"""Offline characterization, not a proposed fix; asserts current behavior.

Uses production compact/request/reader/events methods with in-memory JSONL pipes.
All identifiers and payloads are synthetic. No CLI is created or connected.
"""
import asyncio
import hashlib
import inspect
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import pytest_asyncio

import app
import app.backend_codex as source
from app.backend_codex import CodexBackend, CodexProtocolError
from app.session import AgentSession
from app.session_hibernate import HibernateManager
from app.session_state import AgentStatus


HERE = Path(__file__).resolve().parent
THREAD = "synthetic-thread"
TURN = "synthetic-compact-turn"


def event(method, *, thread=THREAD, turn=None, **params):
    if thread is not None:
        params["threadId"] = thread
    if turn is not None:
        params["turn"] = {"id": turn}
    return {"method": method, "params": params}


def started(turn=TURN, thread=THREAD):
    return event("turn/started", turn=turn, thread=thread)


def completed(turn=TURN, status="completed", thread=THREAD):
    message = event("turn/completed", thread=thread)
    message["params"]["turn"] = {"id": turn, "status": status}
    return message


def compacted(method="item/completed", thread=THREAD, turn_id=TURN):
    if method == "item/completed":
        return event(method, thread=thread, turnId=turn_id,
                     item={"id": "synthetic-compact-item", "type": "contextCompaction"})
    return event(method, thread=thread)


@pytest.fixture(autouse=True)
def isolation(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("V-1076 forbids network, process spawn, and database access")

    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket.socket, "sendto", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", forbidden)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", forbidden)
    monkeypatch.setattr(sqlite3, "connect", forbidden)
    monkeypatch.setattr(source, "CODEX_COMPACT_TIMEOUT_SECONDS", 0.08)


class Harness:
    def __init__(self):
        self.backend = CodexBackend(model="gpt-5.6-sol", cwd=str(HERE))
        self.backend._thread_id = THREAD
        self.stream = asyncio.StreamReader()
        self.backend._proc = SimpleNamespace(
            returncode=None, stdout=self.stream, stdin=object(), wait=AsyncMock(return_value=0),
        )
        self.backend._runtime_context = Mock(return_value=None)
        self.backend._runtime_totals = Mock(return_value=None)
        self.backend._reload_stale_managed_config_before_turn = AsyncMock()
        self.outgoing = asyncio.Queue()
        self.backend._write = AsyncMock(side_effect=self.outgoing.put)
        self.trace = []
        self.barriers = {}
        original = self.backend._complete_compaction_from_notification

        def observed(message):
            result = original(message)
            if message.get("method") == "probe/barrier":
                marker = message["params"]["marker"]
                asyncio.get_running_loop().call_soon(self.barriers[marker].set)
            return result

        self.backend._complete_compaction_from_notification = observed
        self.reader = asyncio.create_task(self.backend._read_stdout())
        self.tasks = []
        self.process_exit = None

    async def begin(self):
        task = asyncio.create_task(self.backend.compact_context())
        self.tasks.append(task)
        request = await asyncio.wait_for(self.outgoing.get(), 1)
        assert request["method"] == "thread/compact/start"
        self.trace.append({"outgoing": request})
        return task, request["id"]

    async def deliver(self, *messages):
        for message in messages:
            self.trace.append({"incoming": message})
            self.stream.feed_data((json.dumps(message) + "\n").encode())
        marker = str(len(self.barriers))
        ready = asyncio.Event()
        self.barriers[marker] = ready
        barrier = event("probe/barrier", marker=marker)
        self.stream.feed_data((json.dumps(barrier) + "\n").encode())
        await asyncio.wait_for(ready.wait(), 1)

    async def ack(self, request_id):
        await self.deliver({"id": request_id, "result": {}})

    async def result(self, task):
        try:
            result = await asyncio.wait_for(asyncio.shield(task), 1)
            observed = {"return": result}
        except (Exception, asyncio.CancelledError) as exc:
            observed = {"exception": type(exc).__name__, "message": str(exc)}
        self.trace.append({"outcome": observed})
        return observed

    def report(self, name, observed, **extra):
        print(json.dumps({"scenario": name, "sequence": self.trace,
                          "observed": observed, "active_turn_id": self.backend.active_turn_id,
                          "compact_future_detached": self.backend._compact_future is None,
                          "compact_queue_detached": self.backend._compact_notifications is None,
                          "pending_request_ids": list(self.backend._pending_requests),
                          **extra}, ensure_ascii=False, sort_keys=True))

    async def close(self):
        if self.process_exit is not None:
            self.process_exit.set()
        for task in self.tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        self.backend._disconnecting = True
        self.stream.feed_eof()
        await asyncio.wait_for(self.reader, 1)


@pytest_asyncio.fixture
async def harness():
    h = Harness()
    try:
        yield h
    finally:
        await h.close()


def timeout_at(observed, stage):
    assert observed == {
        "exception": "TimeoutError",
        "message": f"Codex compact timed out after 0.08s while waiting for {stage}",
    }


def test_source_identity():
    functions = [CodexBackend.compact_context, CodexBackend._drain_compact_lifecycle,
                 CodexBackend._complete_compaction_from_notification,
                 CodexBackend._read_stdout, CodexBackend.events,
                 AgentSession._compact_codex_context, AgentSession._compaction_permit,
                 AgentSession.interrupt, HibernateManager.hibernate_now]
    print(json.dumps({"app_import_absolute": str(Path(app.__file__).resolve()),
                      "python": sys.executable,
                      "functions": [{"name": f.__qualname__, "file": inspect.getsourcefile(f),
                                     "line": inspect.getsourcelines(f)[1]} for f in functions],
                      "sha256": {name: hashlib.sha256((HERE.parents[2] / name).read_bytes()).hexdigest()
                                 for name in ("app/backend_codex.py", "app/backend_jsonrpc.py",
                                              "app/session.py", "app/session_hibernate.py")}}, sort_keys=True))


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["item/completed", "context/compacted", "thread/compacted"])
async def test_supported_success(harness, method):
    h = harness
    task, request_id = await h.begin()
    await h.ack(request_id)
    await h.deliver(started(), compacted(method), completed())
    observed = await h.result(task)
    assert observed["return"]["ok"] is True
    assert h.backend._compact_future is None
    h.report("success_" + method, observed)


@pytest.mark.asyncio
async def test_notifications_before_ack(harness):
    h = harness
    task, request_id = await h.begin()
    await h.deliver(started(), compacted(), completed())
    assert not task.done()
    await h.ack(request_id)
    observed = await h.result(task)
    assert observed["return"]["ok"]
    h.report("notifications_before_ack", observed)


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario,notifications,stage", [
    ("missing_compaction", [started(), completed()], "completion notification"),
    ("foreign_compaction", [started(), compacted(thread="synthetic-other-thread"), completed()], "completion notification"),
    ("missing_terminal", [started(), compacted()], "turn lifecycle"),
    ("foreign_terminal_turn", [started(), compacted(), completed(turn="synthetic-other-turn")], "turn lifecycle"),
    ("second_started_overwrites_turn", [started(), started("synthetic-other-turn"), compacted(), completed()], "turn lifecycle"),
])
async def test_missing_or_foreign(harness, scenario, notifications, stage):
    h = harness
    task, request_id = await h.begin()
    await h.ack(request_id)
    await h.deliver(*notifications)
    observed = await h.result(task)
    timeout_at(observed, stage)
    h.report(scenario, observed)


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario,notifications", [
    ("terminal_before_started", [completed(), started(), compacted()]),
    ("terminal_without_started", [compacted(), completed()]),
])
async def test_invalid_order(harness, scenario, notifications):
    h = harness
    task, request_id = await h.begin()
    await h.ack(request_id)
    await h.deliver(*notifications)
    observed = await h.result(task)
    assert observed["exception"] == "RuntimeError"
    assert "without a preceding turn/started" in observed["message"]
    h.report(scenario, observed)


@pytest.mark.asyncio
async def test_terminal_before_compaction(harness):
    h = harness
    task, request_id = await h.begin()
    await h.ack(request_id)
    await h.deliver(started(), completed(), compacted())
    observed = await h.result(task)
    assert observed["return"]["ok"]
    h.report("terminal_before_compaction", observed)


@pytest.mark.asyncio
@pytest.mark.parametrize("info,retry", [("internalServerError", False), ("usageLimitExceeded", False),
                                       ("sessionBudgetExceeded", True), ("responseStreamDisconnected", True)])
async def test_error_then_failed_without_compaction(harness, info, retry):
    h = harness
    task, request_id = await h.begin()
    await h.ack(request_id)
    error = event("error", turnId=TURN, willRetry=retry,
                  error={"message": "synthetic provider failure", "codexErrorInfo": info})
    await h.deliver(started(), error, completed(status="failed"))
    observed = await h.result(task)
    timeout_at(observed, "completion notification")
    assert h.backend._last_turn_error == {}
    assert all(m.get("method") != "error" for m in h.backend._notifications._queue)
    h.report("error_" + info + ("_retry" if retry else ""), observed,
             normal_event_error_seen=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["failed", "interrupted"])
async def test_terminal_failure_after_compaction(harness, status):
    h = harness
    task, request_id = await h.begin()
    await h.ack(request_id)
    await h.deliver(started(), compacted(), completed(status=status))
    observed = await h.result(task)
    assert observed["return"]["ok"] is True
    h.report("compaction_then_" + status, observed)


@pytest.mark.asyncio
@pytest.mark.parametrize("scenario,notifications", [
    ("foreign_lifecycle_same_turn_id", [started(thread="synthetic-other-thread"), compacted(), completed(thread="synthetic-other-thread")]),
    ("missing_thread_accepted", [started(thread=None), compacted(thread=None), completed(thread=None)]),
    ("wrong_compaction_turn_accepted", [started(), compacted(turn_id="synthetic-old-turn"), completed()]),
])
async def test_correlation_gaps(harness, scenario, notifications):
    h = harness
    task, request_id = await h.begin()
    await h.ack(request_id)
    await h.deliver(*notifications)
    observed = await h.result(task)
    assert observed["return"]["ok"] is True
    h.report(scenario, observed)


@pytest.mark.asyncio
async def test_request_error(harness):
    h = harness
    task, request_id = await h.begin()
    await h.deliver({"id": request_id, "error": {"code": -32000, "message": "synthetic request rejected"}})
    observed = await h.result(task)
    assert observed["exception"] == CodexProtocolError.__name__
    assert not h.backend._pending_requests
    h.report("rpc_error", observed)


@pytest.mark.asyncio
async def test_no_ack(harness):
    h = harness
    task, _ = await h.begin()
    await h.deliver(started(), compacted(), completed())
    observed = await h.result(task)
    timeout_at(observed, "request acknowledgement")
    assert not h.backend._pending_requests
    h.report("missing_ack_even_with_completion", observed)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["item/completed", "context/compacted", "thread/compacted"])
async def test_direct_late_completion(harness, method):
    h = harness
    task, request_id = await h.begin()
    await h.ack(request_id)
    await h.deliver(started())
    observed = await h.result(task)
    timeout_at(observed, "completion notification")
    await h.deliver(compacted(method), completed())
    assert task.exception() is not None
    queued = [m["method"] for m in h.backend._notifications._queue if m["method"] != "probe/barrier"]
    assert queued == [method, "turn/completed"]
    send = asyncio.create_task(h.backend.send("synthetic follow-up input"))
    h.tasks.append(send)
    request = await asyncio.wait_for(h.outgoing.get(), 1)
    assert request["method"] == "turn/start"
    h.trace.append({"outgoing": request})
    await h.deliver({"id": request["id"], "result": {"turn": {"id": "synthetic-next-user-turn"}}})
    await asyncio.wait_for(send, 1)
    stream = h.backend.events()
    late_event = await asyncio.wait_for(anext(stream), 1)
    await stream.aclose()
    assert late_event.content == "codex context compacted"
    h.report("direct_late_" + method + "_then_next_events", observed,
             queued_after_timeout=queued, next_events_status=late_event.content)


@pytest.mark.asyncio
async def test_late_terminal_does_not_resolve_lifecycle_wait(harness):
    h = harness
    task, request_id = await h.begin()
    await h.ack(request_id)
    await h.deliver(started(), compacted())
    observed = await h.result(task)
    timeout_at(observed, "turn lifecycle")
    await h.deliver(completed())
    assert task.exception() is not None
    h.report("late_terminal_after_lifecycle_timeout", observed,
             late_terminal_in_normal_queue=any(m["method"] == "turn/completed" for m in h.backend._notifications._queue))


@pytest.mark.asyncio
async def test_stale_old_operation_completes_retry(harness):
    h = harness
    first, request_id = await h.begin()
    await h.ack(request_id)
    timeout_at(await h.result(first), "completion notification")
    second, request_id = await h.begin()
    await h.ack(request_id)
    # These events are explicitly the previous operation's late notifications.
    await h.deliver(started(), compacted(), completed())
    observed = await h.result(second)
    assert observed["return"]["ok"] is True
    h.report("old_operation_notifications_complete_retry", observed,
             second_operation_emitted_no_own_lifecycle=True)


@pytest.mark.asyncio
async def test_single_deadline_spans_ack_and_completion(harness, monkeypatch):
    h = harness
    monkeypatch.setattr(source, "CODEX_COMPACT_TIMEOUT_SECONDS", 0.2)
    task, request_id = await h.begin()
    loop = asyncio.get_running_loop()
    ack_due = asyncio.Event()
    handle = loop.call_later(0.12, ack_due.set)
    try:
        await ack_due.wait()
        await h.ack(request_id)
        await h.deliver(started())
        # The intended completion is 0.12s after ACK: each phase is below 0.2s,
        # but their sum exceeds the single deadline. No polling or sleep loop.
        completion_due = asyncio.Event()
        completion_handle = loop.call_later(0.12, completion_due.set)
        try:
            observed = await h.result(task)
            assert observed["exception"] == "TimeoutError"
            assert "after 0.2s while waiting for completion notification" in observed["message"]
            assert not completion_due.is_set()
            h.report("one_deadline_for_ack_and_completion", observed,
                     configured_total_deadline_s=0.2, ack_scheduled_after_s=0.12,
                     completion_scheduled_after_ack_s=0.12)
        finally:
            completion_handle.cancel()
    finally:
        handle.cancel()


@pytest.mark.asyncio
async def test_old_events_in_normal_queue_do_not_satisfy_new_compact(harness):
    h = harness
    await h.deliver(started(), compacted(), completed())
    task, request_id = await h.begin()
    await h.ack(request_id)
    observed = await h.result(task)
    timeout_at(observed, "completion notification")
    h.report("old_notifications_already_in_normal_queue", observed)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["request acknowledgement", "completion notification", "turn lifecycle"])
async def test_task_cancellation(harness, stage):
    h = harness
    task, request_id = await h.begin()
    if stage != "request acknowledgement":
        await h.ack(request_id)
    if stage == "turn lifecycle":
        await h.deliver(started(), compacted())
    task.cancel()
    observed = await h.result(task)
    assert observed["exception"] == "CancelledError"
    assert h.backend._compact_future is None
    assert h.backend._compact_notifications is None
    assert not h.backend._pending_requests
    assert h.backend._write.await_count == 1  # No native turn/interrupt is sent.
    h.report("cancel_" + stage, observed, native_interrupt_sent=False)


@pytest.mark.asyncio
async def test_interrupt_cannot_identify_compact_turn(harness):
    h = harness
    task, request_id = await h.begin()
    await h.ack(request_id)
    await h.deliver(started())
    interrupted = await h.backend.interrupt()
    assert interrupted is False
    assert h.backend.active_turn_id is None
    observed = await h.result(task)
    timeout_at(observed, "completion notification")
    h.report("interrupt_during_compact", observed, interrupt_return=interrupted)


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["completion notification", "turn lifecycle"])
async def test_eof_in_compaction(harness, stage):
    h = harness
    task, request_id = await h.begin()
    await h.ack(request_id)
    await h.deliver(started(), *([compacted()] if stage == "turn lifecycle" else []))
    h.stream.feed_eof()
    await asyncio.wait_for(h.reader, 1)
    observed = await h.result(task)
    if stage == "completion notification":
        assert observed["exception"] == "RuntimeError"
        assert "exited with code" in observed["message"]
    else:
        timeout_at(observed, "turn lifecycle")
    h.report("eof_" + stage, observed)


@pytest.mark.asyncio
async def test_eof_waits_for_process_exit_before_failing_compact(harness):
    h = harness
    process_exit = asyncio.Event()
    h.process_exit = process_exit
    h.backend._proc.wait = AsyncMock(side_effect=process_exit.wait)
    task, request_id = await h.begin()
    await h.ack(request_id)
    h.stream.feed_eof()
    observed = await h.result(task)
    timeout_at(observed, "completion notification")
    h.report("stdout_eof_process_still_alive", observed)
    process_exit.set()


@pytest.mark.asyncio
async def test_rejects_concurrent_then_allows_retry(harness):
    h = harness
    task, request_id = await h.begin()
    await h.ack(request_id)
    with pytest.raises(RuntimeError, match="already in progress"):
        await h.backend.compact_context()
    timeout_at(await h.result(task), "completion notification")
    retry, request_id = await h.begin()
    await h.ack(request_id)
    await h.deliver(started("synthetic-retry-turn"), compacted(turn_id="synthetic-retry-turn"),
                    completed("synthetic-retry-turn"))
    observed = await h.result(retry)
    assert observed["return"]["ok"]
    h.report("concurrent_rejected_clean_retry_succeeds", observed)


@pytest.mark.asyncio
async def test_backend_concurrent_guard_ends_before_lifecycle(harness):
    h = harness
    first, request_id = await h.begin()
    await h.ack(request_id)
    await h.deliver(started(), compacted())
    assert h.backend._compact_future.done()
    assert not first.done()
    second, request_id = await h.begin()  # Accepted during first lifecycle drain.
    await h.ack(request_id)
    await h.deliver(completed())  # Routed to second operation's queue.
    first_result = await h.result(first)
    second_result = await h.result(second)
    timeout_at(first_result, "turn lifecycle")
    timeout_at(second_result, "completion notification")
    h.report("backend_concurrent_during_lifecycle", second_result,
             first_result=first_result, first_terminal_was_routed_to_second=True)


@pytest.mark.asyncio
async def test_invalid_json_completion_is_skipped(harness):
    h = harness
    task, request_id = await h.begin()
    await h.ack(request_id)
    await h.deliver(started())
    h.trace.append({"incoming_raw": "{synthetic invalid JSON}\n"})
    h.stream.feed_data(b"{synthetic invalid JSON}\n")
    await h.deliver(completed())
    observed = await h.result(task)
    timeout_at(observed, "completion notification")
    h.report("invalid_json_missing_completion", observed)


@pytest.mark.asyncio
async def test_foreign_usage_changes_returned_context(harness):
    h = harness
    task, request_id = await h.begin()
    await h.ack(request_id)
    await h.deliver(started(), event("thread/tokenUsage/updated", thread="synthetic-other-thread",
                                   tokenUsage={"last": {"totalTokens": 777},
                                               "modelContextWindow": 9999}), compacted(), completed())
    observed = await h.result(task)
    assert observed["return"]["context_tokens"] == 777
    assert observed["return"]["max_tokens"] == 9999
    h.report("foreign_usage_contaminates_result", observed)


@pytest.mark.asyncio
async def test_runtime_fallback_can_return_old_context(harness):
    h = harness
    h.backend._runtime_context.return_value = {"input_tokens": 70000, "model_context_window": 258400}
    task, request_id = await h.begin()
    await h.ack(request_id)
    await h.deliver(started(), compacted(), completed())
    observed = await h.result(task)
    assert observed["return"]["context_tokens"] == 70000
    h.report("synthetic_stale_runtime_fallback", observed,
             fallback_value_deliberately_from_before_compact=True)


def session_stub(backend):
    s = SimpleNamespace(
        name="synthetic-session", session_id=THREAD, _precompact_timer=None,
        _last_context={"percentage": 70, "total_tokens": 70000, "max_tokens": 100000},
        _compacting=True, _pending_messages=[], status=AgentStatus.IDLE,
        _hibernated=False, _backend=backend, backend_type="codex", is_orchestrator=False,
        _lifecycle_lock=asyncio.Lock(), _hibernate_task=None,
        _compaction_permit=AsyncMock(return_value=None),
        _ensure_backend=AsyncMock(return_value=backend),
        _log=Mock(), _persist=Mock(), _drain_persist=AsyncMock(),
        _build_runtime_handoff=AsyncMock(return_value=None),
        _wake_durable_message_deliveries=Mock(), _spawn_bg=Mock(),
        _disconnect_backend=AsyncMock(),
    )

    async def start(_permit, operation):
        return await operation()

    s._run_compaction_start = start
    s._hibernate = SimpleNamespace(schedule=Mock())
    return s


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_session_cleanup_and_hibernate_policy(harness, cancel):
    h = harness
    h.backend._hibernate_safe = True
    s = session_stub(h.backend)
    task = asyncio.create_task(AgentSession._compact_codex_context(s))
    h.tasks.append(task)
    request = await asyncio.wait_for(h.outgoing.get(), 1)
    h.trace.append({"outgoing": request})
    await h.ack(request["id"])
    await h.deliver(started())
    blocked = await HibernateManager(s).hibernate_now()
    assert blocked["reason"] == "compacting"
    if cancel:
        task.cancel()
    observed = await h.result(task)
    if cancel:
        assert observed["exception"] == "CancelledError"
    else:
        assert observed["return"]["ok"] is False
        assert observed["return"]["error"].startswith("TimeoutError:")
    assert s._compacting is False
    assert s._last_context["percentage"] == 70
    s._hibernate.schedule.assert_called_once()
    permitted = await HibernateManager(s).hibernate_now()
    assert permitted["ok"] is True
    s._disconnect_backend.assert_awaited_once()
    h.report("session_" + ("cancel" if cancel else "timeout") + "_cleanup", observed,
             session_logs=[list(call.args) for call in s._log.call_args_list],
             old_context_retained=True, hibernate_during=blocked, hibernate_after=permitted)
