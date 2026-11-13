"""Offline V-1290 regressions using synthetic stream events and SQLite protobufs."""

import asyncio
import json
import sqlite3
from types import SimpleNamespace

import pytest

from app import backend_antigravity as agy
from app.antigravity_auth import AuthSnapshot
from app.usage_contract import KnownContext, UnknownContext


RETRY_ERROR = "API error (attempt 1): request failed: stream idle timeout (5m0s): context deadline exceeded"


@pytest.fixture
def backend_factory(tmp_path, monkeypatch):
    monkeypatch.setattr(agy, "ANTIGRAVITY_HOME_ROOT", tmp_path / "homes")
    monkeypatch.setattr(agy, "read_auth_snapshot", lambda _: AuthSnapshot(b"synthetic", "generation-a"))

    def build(*, resume=None, model="gemini-4-carbon-high", session="worker"):
        return agy.AntigravityBackend(SimpleNamespace(
            model="antigravity/" + model, cwd=str(tmp_path), system_prompt="synthetic",
            mcp_servers={"orchestra": {"env": {"ORCHESTRA_SESSION_ID": session}}},
            context_limit=1_000_000, resume_session_id=resume,
        ))

    return build


def response_step(text="answer", state="DONE"):
    return {"event": "step_update", "step_update": {
        "step_type": "agent_response", "state": state, "text_delta": text,
    }}


def result(*, conversation="conversation-a", status="SUCCESS", response="answer",
           error=None, tokens=(100, 50, 20, 10), turns=1, seconds=2.5):
    return {
        "conversation_id": conversation, "status": status, "response": response,
        "error": error, "num_turns": turns, "duration_seconds": seconds,
        "usage": dict(zip(("input_tokens", "cache_read_tokens", "output_tokens",
                           "thinking_tokens"), tokens)),
    }


async def turn(backend, monkeypatch, terminal, *, rows=(), code=0, after_wait=None):
    stdout, stderr = asyncio.StreamReader(), asyncio.StreamReader()
    for row in rows:
        stdout.feed_data((json.dumps(row) + "\n").encode())
    if terminal is not None:
        stdout.feed_data((json.dumps({"event": "result", "result": terminal}) + "\n").encode())
    stdout.feed_eof()
    stderr.feed_eof()
    process = SimpleNamespace(stdout=stdout, stderr=stderr, returncode=None)
    captured = {}

    async def wait():
        process.returncode = code
        if after_wait:
            after_wait()
        return code

    async def spawn(*args, **kwargs):
        captured.update(args=args, kwargs=kwargs)
        return process

    process.wait = wait
    monkeypatch.setattr(agy.asyncio, "create_subprocess_exec", spawn)
    await backend.send("synthetic prompt")
    events = [event async for event in backend.events()]
    await backend._task
    return events, captured


def ending(events):
    ends = [event for event in events if event.type == "turn_end"]
    assert len(ends) == 1
    return ends[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["terminal", "stream", "active-stream", "both"])
@pytest.mark.parametrize("code", [0, 1])
async def test_recovered_retry_error_never_emits_a_turn_error(backend_factory, monkeypatch, source, code):
    backend = backend_factory()
    rows = [] if source == "terminal" else [response_step(state="ACTIVE" if source == "active-stream" else "DONE")]
    terminal = result(status="ERROR", response="answer" if source in {"terminal", "both"} else "",
                      error=RETRY_ERROR)
    events, _ = await turn(backend, monkeypatch, terminal, rows=rows, code=code)
    end = ending(events)
    assert end.metadata["ok"] is True
    assert end.metadata["stop_reason"] == "end_turn"
    assert "model_error" not in end.metadata
    assert not any(event.type == "error" for event in events)


@pytest.mark.asyncio
async def test_replayed_sticky_error_does_not_poison_next_turn(backend_factory, monkeypatch):
    backend = backend_factory()
    for count in (1, 2):
        events, captured = await turn(backend, monkeypatch, result(
            status="ERROR", error=RETRY_ERROR, tokens=(100 * count, 50 * count, 20 * count, 10 * count),
            turns=count, seconds=2.5 * count,
        ))
        assert ending(events).metadata["ok"] is True
        assert not any(event.type == "error" for event in events)
        assert ("--conversation" in captured["args"]) == (count == 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("error,reason", [
    (RETRY_ERROR, "model"), ("OAuth credential expired", "credentials"),
    ("location eligibility refused", "credentials"), ("quota exhausted", "quota"),
    ("rate limit exceeded", "quota"),
])
async def test_unrecovered_failure_after_prior_success_still_fails(backend_factory, monkeypatch, error, reason):
    backend = backend_factory()
    await turn(backend, monkeypatch, result())
    events, _ = await turn(backend, monkeypatch, result(status="ERROR", response="", error=error))
    end = ending(events)
    assert end.metadata["ok"] is False
    assert end.metadata["stop_reason"] == reason
    assert end.metadata["model_error"] == reason
    assert [event.content for event in events if event.type == "error"] == [error]
    # A failed terminal with unchanged totals must not charge the prior turn twice.
    assert end.metadata["input_tokens"] == 0
    assert end.metadata["cost_usd"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("error,reason", [("OAuth refused", "credentials"), ("quota exhausted", "quota")])
@pytest.mark.parametrize("completed", [False, True])
async def test_partial_auth_quota_failure_requires_completion(backend_factory, monkeypatch, error, reason, completed):
    events, _ = await turn(backend_factory(), monkeypatch, result(status="ERROR", response="", error=error),
                           rows=[response_step(state="DONE" if completed else "ACTIVE")])
    end = ending(events)
    assert end.metadata["ok"] is completed
    assert end.metadata["stop_reason"] == ("end_turn" if completed else reason)
    assert sum(event.type == "error" for event in events) == int(not completed)


@pytest.mark.asyncio
async def test_terminal_response_can_recover_sticky_auth_error(backend_factory, monkeypatch):
    events, _ = await turn(backend_factory(), monkeypatch, result(status="ERROR", error="OAuth refused"))
    assert ending(events).metadata["ok"] is True
    assert not any(event.type == "error" for event in events)


@pytest.mark.asyncio
@pytest.mark.parametrize("rows", [[], [response_step("  ")], [{"event": "step_update", "step_update": {
    "step_type": "thinking", "text_delta": "thoughts", "state": "DONE",
}}]])
async def test_non_assistant_output_does_not_recover_model_failure(backend_factory, monkeypatch, rows):
    events, _ = await turn(backend_factory(), monkeypatch, result(status="ERROR", response="", error=RETRY_ERROR), rows=rows)
    assert ending(events).metadata["stop_reason"] == "model"
    assert ending(events).metadata["ok"] is False


@pytest.mark.asyncio
async def test_output_without_terminal_is_still_protocol_failure(backend_factory, monkeypatch):
    events, _ = await turn(backend_factory(), monkeypatch, None, rows=[response_step()])
    assert ending(events).metadata["ok"] is False
    assert ending(events).metadata["model_error"] == "protocol"
    assert sum(event.type == "error" for event in events) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("state,info", [
    ("ERROR", {"error": {"message": "synthetic tool failure"}}),
    ("DONE", {"error": "synthetic tool failure"}),
    ("ERROR", {"output": "synthetic tool failure"}),
])
async def test_tool_error_is_a_single_result_and_completed_turn_stays_ok(backend_factory, monkeypatch, state, info):
    tool = {"event": "step_update", "step_update": {
        "step_type": "tool", "tool_name": "run_command", "state": state,
        "conversation_id": "conversation-a", "step_index": 1,
        "tool_info": {"parameters": {"CommandLine": "false"}, **info},
    }}
    events, _ = await turn(backend_factory(), monkeypatch, result(), rows=[tool, tool])
    results = [event for event in events if event.type == "tool_result"]
    assert len(results) == 1
    assert results[0].metadata["is_error"] is True
    assert "synthetic tool failure" in results[0].content
    assert not any(event.type == "error" for event in events)
    assert ending(events).metadata["ok"] is True
    assert ending(events).metadata["stop_reason"] == "end_turn"


def varint(value):
    encoded = bytearray()
    while value >= 128:
        encoded.append((value & 127) | 128)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def field(number, value):
    if isinstance(value, bytes):
        return varint(number * 8 + 2) + varint(len(value)) + value
    return varint(number * 8) + varint(value)


def metadata(used=183159, maximum=256000):
    window = (field(1, used) if used is not None else b"") + (field(4, maximum) if maximum is not None else b"")
    # Generation usage is different from occupied context; never sum these fields.
    usage = b"".join(field(key, value) for key, value in ((2, 999999), (3, 123), (5, 800000), (9, 100), (10, 23)))
    unknown = field(88, b"ignored") + varint(89 * 8 + 1) + b"12345678" + varint(90 * 8 + 5) + b"1234"
    return unknown + field(1, field(4, usage) + field(9, field(10, window)))


def write_metadata(backend, rows, *, conversation="conversation-a", wal=False):
    database = backend.home / ".gemini/antigravity-cli/conversations" / f"{conversation}.db"
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    if wal:
        connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE gen_metadata (idx INTEGER, data BLOB, size INTEGER)")
    connection.executemany("INSERT INTO gen_metadata VALUES (?, ?, ?)", [(idx, data, len(data)) for idx, data in rows])
    connection.commit()
    return connection, database


@pytest.mark.asyncio
async def test_latest_generation_context_is_read_after_process_wait(backend_factory, monkeypatch):
    backend = backend_factory()

    def finish():
        # Deliberately insert in non-idx order; latest generation beats aggregate usage.
        connection, _ = write_metadata(backend, [(9, metadata()), (1, metadata(42, 256000))])
        connection.close()

    events, _ = await turn(backend, monkeypatch, result(), after_wait=finish)
    end = ending(events)
    assert end.usage.current == KnownContext(183159, 256000, 71)
    assert end.usage.aggregate.input_tokens == 100
    assert end.usage.metadata()["max_tokens"] == 256000
    assert end.usage.metadata()["context_known"] is True


def test_metadata_reader_uses_read_only_uri_and_observes_wal(backend_factory, monkeypatch):
    backend = backend_factory()
    writer, database = write_metadata(backend, [(1, metadata())], wal=True)
    connect = sqlite3.connect
    opened = []

    def read_only(database_uri, **kwargs):
        opened.append((database_uri, kwargs))
        return connect(database_uri, **kwargs)

    monkeypatch.setattr(agy.sqlite3, "connect", read_only)
    try:
        before = database.read_bytes()
        assert agy._conversation_context(backend.home, "conversation-a", 1_000_000) == KnownContext(183159, 256000, 71)
        assert database.read_bytes() == before
        assert opened == [(database.resolve().as_uri() + "?mode=ro", {"uri": True, "timeout": 0.1})]
    finally:
        writer.close()


@pytest.mark.parametrize("used,maximum", [(0, 256000), (256000, 256000), (150000, 200000)])
def test_context_boundaries_use_cli_maximum(backend_factory, used, maximum):
    backend = backend_factory()
    connection, _ = write_metadata(backend, [(1, metadata(used, maximum))])
    connection.close()
    assert agy._conversation_context(backend.home, "conversation-a", 1_000_000) == KnownContext(used, maximum, int(used * 100 / maximum))


@pytest.mark.parametrize("payload", [
    b"", b"\x80", b"\x0a\x05x", b"\x00", b"\x0b", b"\x09xx", b"\x0dxx",
    b"\xff" * 11, field(1, 7), field(1, field(9, field(10, 3))),
    metadata(None, 256000), metadata(183159, None), metadata(1, 0), metadata(256001, 256000),
    b"x" * 1048577,
])
def test_corrupt_or_invalid_latest_metadata_is_unknown(backend_factory, payload):
    backend = backend_factory()
    connection, _ = write_metadata(backend, [(1, metadata()), (2, payload)])
    connection.close()
    context = agy._conversation_context(backend.home, "conversation-a", 1_000_000)
    # Never silently use the older valid row when the latest row is corrupt.
    assert isinstance(context, UnknownContext)


@pytest.mark.parametrize("case", ["missing", "empty", "missing-table", "corrupt-db", "text-blob"])
@pytest.mark.asyncio
async def test_missing_or_unreadable_metadata_never_breaks_turn(backend_factory, monkeypatch, case):
    backend = backend_factory()
    if case != "missing":
        connection, database = write_metadata(backend, [])
        if case == "missing-table":
            connection.execute("DROP TABLE gen_metadata")
        elif case == "text-blob":
            connection.execute("INSERT INTO gen_metadata VALUES (1, 'not bytes', 9)")
        connection.commit()
        connection.close()
        if case == "corrupt-db":
            database.write_bytes(b"invalid sqlite")
    events, _ = await turn(backend, monkeypatch, result())
    assert ending(events).metadata["ok"] is True
    assert isinstance(ending(events).usage.current, UnknownContext)
    assert not any(event.type == "error" for event in events)
    if case == "missing":
        assert not (backend.home / ".gemini/antigravity-cli/conversations").exists()


@pytest.mark.parametrize("conversation", [None, "../outside", "/absolute", "bad?mode=rw"])
def test_invalid_conversation_never_opens_a_database(backend_factory, monkeypatch, conversation):
    def forbidden(*args, **kwargs):
        pytest.fail("invalid conversation attempted a database read")

    monkeypatch.setattr(agy.sqlite3, "connect", forbidden)
    assert isinstance(agy._conversation_context(backend_factory().home, conversation, 1000000), UnknownContext)


@pytest.mark.asyncio
async def test_multiturn_usage_is_delta_and_survives_backend_recreation(backend_factory, monkeypatch):
    backend = backend_factory()
    first, captured = await turn(backend, monkeypatch, result(tokens=(1000, 500, 100, 25), turns=3, seconds=5.25))
    assert "--conversation" not in captured["args"]
    assert ending(first).metadata["cost_usd"] == pytest.approx(.00305)
    backend = backend_factory(resume="conversation-a")
    second, captured = await turn(backend, monkeypatch, result(tokens=(1400, 800, 150, 40), turns=5, seconds=8))
    assert captured["args"][captured["args"].index("--conversation") + 1] == "conversation-a"
    end = ending(second)
    assert end.usage.aggregate.input_tokens == end.metadata["input_tokens"] == 400
    assert end.metadata["cached_input_tokens"] == end.metadata["cache_read"] == 300
    assert end.metadata["output_tokens"] == 50
    assert end.metadata["reasoning_tokens"] == 15
    assert end.metadata["num_turns"] == 2
    assert end.metadata["turn_duration_ms"] == 2750
    assert end.metadata["cost_usd"] == end.metadata["cost_usd_cached"] == pytest.approx(.00133)
    assert end.metadata["cost_is_delta"] is True
    assert end.metadata["cost_unaccounted"] is False
    state = json.loads((backend.home / "orchestra-conversation.json").read_text())
    assert state["cumulative"] == {
        "input_tokens": 1400, "cache_read_tokens": 800, "output_tokens": 150,
        "thinking_tokens": 40, "num_turns": 5, "duration_seconds": 8,
    }
    third, _ = await turn(backend, monkeypatch, result(tokens=(1400, 800, 150, 40), turns=5, seconds=8))
    assert ending(third).metadata["cost_usd"] == 0
    assert ending(third).metadata["num_turns"] == 1
    assert ending(third).metadata["turn_duration_ms"] == 0
    assert ending(third).metadata["event_id"] != end.metadata["event_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("reset", ["conversation", "generation", "model", "counters", "single-counter"])
async def test_usage_baseline_resets_with_its_identity_or_cli_epoch(backend_factory, monkeypatch, reset):
    backend = backend_factory()
    await turn(backend, monkeypatch, result(tokens=(1000, 500, 100, 25), turns=3, seconds=5))
    next_result = result(tokens=(400, 300, 50, 15), turns=2, seconds=3)
    if reset == "conversation":
        next_result["conversation_id"] = "conversation-b"
    elif reset == "generation":
        monkeypatch.setattr(agy, "read_auth_snapshot", lambda _: AuthSnapshot(b"synthetic-b", "generation-b"))
    elif reset == "model":
        backend = backend_factory(resume="conversation-a", model="gemini-4-argon-high")
    elif reset == "single-counter":
        next_result = result(tokens=(1400, 300, 150, 40), turns=5, seconds=8)
    events, captured = await turn(backend, monkeypatch, next_result)
    end = ending(events)
    assert end.metadata["input_tokens"] == next_result["usage"]["input_tokens"]
    assert end.metadata["output_tokens"] == next_result["usage"]["output_tokens"]
    assert end.metadata["cache_read"] == next_result["usage"]["cache_read_tokens"]
    assert end.metadata["num_turns"] == next_result["num_turns"]
    assert end.metadata["turn_duration_ms"] == next_result["duration_seconds"] * 1000
    if reset in {"generation", "model"}:
        assert "--conversation" not in captured["args"]


@pytest.mark.asyncio
@pytest.mark.parametrize("state", [None, "invalid json", [], {"model": "gemini-4-carbon-high",
    "generation": "generation-a", "conversation_id": "conversation-a"}])
async def test_old_missing_or_malformed_state_migrates_without_crashing(backend_factory, monkeypatch, state):
    backend = backend_factory(resume="conversation-a")
    backend.home.mkdir(parents=True)
    if state is not None:
        (backend.home / "orchestra-conversation.json").write_text(state if isinstance(state, str) else json.dumps(state))
    events, _ = await turn(backend, monkeypatch, result())
    assert ending(events).metadata["ok"] is True
    assert ending(events).metadata["input_tokens"] == 100
    assert "cumulative" in json.loads((backend.home / "orchestra-conversation.json").read_text())


@pytest.mark.asyncio
async def test_absent_telemetry_preserves_baseline_for_next_report(backend_factory, monkeypatch):
    backend = backend_factory()
    await turn(backend, monkeypatch, result())
    partial = result()
    partial.pop("usage")
    partial.pop("duration_seconds")
    partial.pop("num_turns")
    events, _ = await turn(backend, monkeypatch, partial)
    assert ending(events).metadata["input_tokens"] == 0
    assert ending(events).metadata["num_turns"] == 1
    assert ending(events).metadata["turn_duration_ms"] is None
    events, _ = await turn(backend, monkeypatch, result(tokens=(150, 75, 30, 15), turns=2, seconds=4))
    assert ending(events).metadata["input_tokens"] == 50
    assert ending(events).metadata["reasoning_tokens"] == 5
    assert ending(events).metadata["turn_duration_ms"] == 1500


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [-1, True, "garbled", float("inf"), float("nan"), 1.5])
async def test_invalid_cumulative_counters_fail_soft(backend_factory, monkeypatch, bad):
    backend = backend_factory()
    terminal = result(tokens=(bad, bad, bad, bad), turns=bad, seconds=-1)
    events, _ = await turn(backend, monkeypatch, terminal)
    end = ending(events)
    assert end.metadata["ok"] is True
    assert end.metadata["input_tokens"] == end.metadata["output_tokens"] == end.metadata["cache_read"] == 0
    assert end.metadata["reasoning_tokens"] is None
    assert end.metadata["num_turns"] == 1
    assert end.metadata["turn_duration_ms"] is None


@pytest.mark.asyncio
async def test_failed_turn_spend_advances_baseline_without_becoming_success(backend_factory, monkeypatch):
    backend = backend_factory()
    events, _ = await turn(backend, monkeypatch, result(status="ERROR", response="", error=RETRY_ERROR))
    assert ending(events).metadata["ok"] is False
    assert ending(events).metadata["cost_usd"] > 0
    events, _ = await turn(backend, monkeypatch, result(tokens=(150, 75, 30, 15), turns=2, seconds=4))
    assert ending(events).metadata["input_tokens"] == 50
    assert ending(events).metadata["cost_usd"] == pytest.approx(.000202)


@pytest.mark.asyncio
@pytest.mark.parametrize("error", ["OAuth refused", "quota exhausted"])
@pytest.mark.parametrize("last_step", ["tool", "partial-response"])
async def test_intermediate_reply_does_not_hide_later_terminal_refusal(backend_factory, monkeypatch, error, last_step):
    rows = [response_step("I will inspect the file")]
    if last_step == "tool":
        rows.append({"event": "step_update", "step_update": {
            "step_type": "tool", "tool_name": "read_file", "state": "DONE", "step_index": 1,
            "tool_info": {"output": "file contents"},
        }})
    else:
        rows.append(response_step("partial", "ACTIVE"))
    events, _ = await turn(backend_factory(), monkeypatch, result(status="ERROR", response="", error=error), rows=rows)
    assert ending(events).metadata["ok"] is False
    assert sum(event.type == "error" for event in events) == 1


@pytest.mark.asyncio
async def test_interrupted_terminal_accounts_spend_and_stays_interrupted(backend_factory, monkeypatch):
    backend = backend_factory()
    events, _ = await turn(backend, monkeypatch, result(), after_wait=lambda: setattr(backend, "_interrupted", True))
    end = ending(events)
    assert end.metadata["ok"] is False
    assert end.metadata["stop_reason"] == "interrupt"
    assert end.metadata["input_tokens"] == 100
    assert end.metadata["cost_usd"] > 0
    events, _ = await turn(backend, monkeypatch, result(tokens=(150, 75, 30, 15), turns=2, seconds=4))
    assert ending(events).metadata["input_tokens"] == 50


@pytest.mark.asyncio
async def test_terminal_context_uses_conversation_without_init_event(backend_factory, monkeypatch):
    backend = backend_factory(resume="conversation-old")
    connection, _ = write_metadata(backend, [(1, metadata(12, 256000))], conversation="conversation-old")
    connection.close()
    connection, _ = write_metadata(backend, [(1, metadata())], conversation="conversation-new")
    connection.close()
    events, _ = await turn(backend, monkeypatch, result(conversation="conversation-new"))
    assert ending(events).usage.current == KnownContext(183159, 256000, 71)
