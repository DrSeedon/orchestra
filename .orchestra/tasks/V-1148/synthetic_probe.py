"""Bounded AST-only probes of supplied source, NOT an app/integration test.

No app imports, source replacements, database schema, native histories, processes,
or network. Selected class definitions/method bodies are compiled unchanged.
Missing transport and constructor are replaced with explicit in-memory fixtures.
"""
import ast
import asyncio
import hashlib
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType, SimpleNamespace


ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "app/backend_codex.py"
METHODS = {
    "compact_pending", "compact_diagnostics", "compact_context",
    "_log_compact_state", "_release_compact", "_fail_compact_transport",
    "_notification_turn_id", "_is_compaction_notification",
    "_complete_compaction_from_notification", "_finish_compact_if_ready",
    "_fail_compact_operation", "_record_token_usage", "_usage_breakdown",
    "_route_notification",
}


def extract():
    tree = ast.parse(SOURCE.read_text(), filename=str(SOURCE))
    selected = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            if node.name in {"_CompactOperation", "CodexProtocolError"}:
                selected.append(node)
            elif node.name == "CodexBackend":
                node.body = [method for method in node.body
                             if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
                             and method.name in METHODS]
                assert {method.name for method in node.body} == METHODS
                node.bases = []
                node.decorator_list = []
                selected.append(node)
    module = ModuleType("v1148_extracted")
    sys.modules[module.__name__] = module
    clock = SimpleNamespace(now=0.0)
    module.__dict__.update(
        asyncio=asyncio, dataclass=dataclass, field=field,
        time=SimpleNamespace(monotonic=lambda: clock.now), json=json,
        logger=logging.getLogger("v1148.extracted"),
        CODEX_COMPACT_TIMEOUT_SECONDS=0.02,
    )
    # No sanitizer substitute: success/late-failure paths here do not call it.
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(SOURCE), "exec"),
         module.__dict__)
    return module, clock


def fixture(module):
    backend = module.CodexBackend()
    backend.is_alive = True
    backend._reader_failure = None
    backend._stdout_closed = False
    backend._thread_id = "synthetic-thread"
    backend._active_turn_id = None
    backend._events_active = False
    backend._starting_user_turn = None
    backend._compact_operation = None
    backend._last_compact = None
    backend._compact_future = None
    backend._compact_sequence = 0
    backend._transport_generation = 1
    backend._retired_compact_turns = set()
    backend._seen_compact_items = set()
    backend._model_context_window = 100000
    backend._notifications = asyncio.Queue()
    return backend


def event(method, turn_id="synthetic-compact", **params):
    return {"method": method, "params": {
        "threadId": "synthetic-thread", "turnId": turn_id, **params,
    }}


def started():
    return event("turn/started")


def compact():
    return event("item/completed", item={"id": "synthetic-item", "type": "contextCompaction"})


def terminal(status="completed"):
    return event("turn/completed", turn={"id": "synthetic-compact", "status": status})


def emit(label, value):
    print(label + "=" + json.dumps(value, sort_keys=True))


async def timeout_fixture(module, clock):
    backend = fixture(module)
    ack_seen = asyncio.Event()
    finish = backend._finish_compact_if_ready

    def observe_ack(operation):
        finish(operation)
        if operation.acknowledged:
            ack_seen.set()

    backend._finish_compact_if_ready = observe_ack

    async def request(method, params):
        assert method == "thread/compact/start"
        assert params == {"threadId": "synthetic-thread"}
        clock.now = 0.007
        return {}

    backend._request = request
    clock.now = 0
    caller = asyncio.create_task(backend.compact_context())
    await asyncio.wait_for(ack_seen.wait(), 0.5)
    assert backend._compact_operation.acknowledged
    clock.now = 0.045
    backend._route_notification(started())
    clock.now = 120.0
    try:
        await asyncio.wait_for(caller, 0.5)
    except TimeoutError as error:
        assert "0.02s" in str(error)
        snapshot = error.compact_diagnostics
    else:
        raise AssertionError("missing timeout")
    assert snapshot["outcome"] == "timeout"
    assert snapshot["remote_outcome"] == "unknown"
    assert backend.compact_pending
    assert backend._compact_future is None
    assert backend._compact_operation.future.cancelled()
    return backend, snapshot


async def main():
    module, clock = extract()
    emit("scope", {"kind": "AST-only; not normal import/integration",
                   "real_deadline_seconds": 0.02,
                   "diagnostic_timestamps": "injected synthetic clock, not elapsed measurements",
                   "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest()})
    before = time.monotonic()
    backend, snapshot = await timeout_fixture(module, clock)
    emit("caller_timeout", snapshot)
    clock.now = 120.159
    backend._route_notification(compact())
    assert backend.compact_pending
    clock.now = 120.169
    backend._route_notification(terminal())
    late = backend.compact_diagnostics
    assert late["outcome"] == "timeout" and late["remote_outcome"] == "completed"
    assert late["late"] and late["compacted"] and late["terminal_status"] == "completed"
    assert late["stage"] == "completion notification"
    assert not backend.compact_pending and backend._notifications.empty()
    assert snapshot["remote_outcome"] == "unknown" and snapshot["compacted"] is False
    emit("late_success", late)
    emit("original_exception_snapshot_unchanged", snapshot)

    backend, _ = await timeout_fixture(module, clock)
    backend._route_notification(event("thread/tokenUsage/updated", tokenUsage={
        "last": {"totalTokens": 1234, "inputTokens": 1000, "outputTokens": 234},
        "modelContextWindow": 100000,
    }))
    backend._route_notification(compact())
    backend._route_notification(terminal())
    assert backend._compact_context_tokens == 1234
    assert backend._last_call_usage["input_tokens"] == 1000
    backend._route_notification(event("thread/tokenUsage/updated", tokenUsage={
        "last": {"totalTokens": 42, "inputTokens": 40}, "modelContextWindow": 200000,
    }))
    assert backend._compact_context_tokens == 1234 and backend._model_context_window == 100000
    emit("late_usage", {"before_terminal_total": backend._compact_context_tokens,
                        "last_call_input": backend._last_call_usage["input_tokens"],
                        "tagged_usage_after_retirement_ignored": True})

    backend, _ = await timeout_fixture(module, clock)
    backend._route_notification(terminal("failed"))
    assert backend.compact_diagnostics["remote_outcome"] == "failed"
    assert backend.compact_diagnostics["outcome"] == "timeout"
    assert not backend.compact_pending
    emit("late_failed_terminal", backend.compact_diagnostics)

    backend, _ = await timeout_fixture(module, clock)
    backend._fail_compact_transport(RuntimeError("synthetic EOF"))
    assert not backend.compact_pending
    assert backend.compact_diagnostics["remote_outcome"] == "transport_closed"
    emit("late_transport_close", backend.compact_diagnostics)

    backend, _ = await timeout_fixture(module, clock)
    backend._route_notification(terminal())
    assert not backend.compact_pending
    assert backend.compact_diagnostics["remote_outcome"] == "completed"
    assert backend.compact_diagnostics["compacted"] is False
    emit("completed_without_compaction_evidence", backend.compact_diagnostics)

    backend, _ = await timeout_fixture(module, clock)
    backend._active_turn_id = "synthetic-user"
    backend._route_notification(event("thread/tokenUsage/updated", turn_id="synthetic-user", tokenUsage={
        "last": {"inputTokens": 9000, "totalTokens": 9100}, "modelContextWindow": 100000,
    }))
    assert backend._last_call_usage["input_tokens"] == 9000
    backend._route_notification(event("thread/tokenUsage/updated", tokenUsage={
        "last": {"inputTokens": 1000, "totalTokens": 1234}, "modelContextWindow": 100000,
    }))
    assert backend._last_call_usage["input_tokens"] == 1000
    assert backend._active_turn_id == "synthetic-user"
    backend._route_notification(compact())
    backend._route_notification(terminal())
    assert backend._active_turn_id == "synthetic-user" and not backend.compact_pending
    emit("overlapping_usage_cache", {
        "user_input_before_late_compact_usage": 9000,
        "shared_last_call_input_after": backend._last_call_usage["input_tokens"],
        "user_turn_ownership_preserved": True,
        "session_stats_or_turn_end_not_executed": True,
    })

    backend = fixture(module)
    backend._active_turn_id = "synthetic-user"
    backend._route_notification(event("item/started", turn_id="synthetic-user", item={
        "id": "native-compact", "type": "contextCompaction"}))
    backend._route_notification(event("item/completed", turn_id="synthetic-user", item={
        "id": "native-compact", "type": "contextCompaction"}))
    backend._route_notification(event("item/agentMessage/delta", turn_id="synthetic-user", delta="resumed"))
    assert not backend.compact_pending and backend._active_turn_id == "synthetic-user"
    assert backend._notifications.qsize() == 3
    emit("ordinary_native_compaction_routing", {
        "queued_records": 3, "active_turn_unchanged": True, "manual_compact_owner": False})
    emit("result", {"assertions": "PASS", "scenarios": 7,
                    "wall_seconds": round(time.monotonic() - before, 3)})


if __name__ == "__main__":
    asyncio.run(main())
