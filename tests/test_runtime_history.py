import base64
import importlib.metadata
import json
import shutil
import sqlite3
import subprocess
import uuid
from datetime import datetime, timezone

import pytest

from app import db as dbmod
from app.events import MessageProvenance
from app.runtime_history import (
    CLAUDE_CLI_HISTORY_VERSION,
    CLAUDE_SDK_HISTORY_VERSION,
    ClaudeLogSessionStore,
    build_runtime_state_packet,
    runtime_packet_sha256,
    render_codex_history,
    render_claude_history,
)


def _row(log_id, row_type, content, **metadata):
    return {
        "id": log_id,
        "ts": f"2026-08-11T10:00:{log_id:02d}+00:00",
        "type": row_type,
        "content": content,
        "event_id": "",
        "tool_use_id": metadata.get("tool_use_id"),
        "tool_name": metadata.get("tool_name"),
        "tool_is_error": metadata.get("tool_is_error"),
        "origin": metadata.get("origin", "unknown"),
        "origin_detail": metadata.get("origin_detail", {"senders": ["unknown"]}),
    }


def _render(rows, *, exclude=()):
    return render_claude_history(
        rows,
        snapshot_id=max((row["id"] for row in rows), default=0),
        session_id="11111111-2222-4333-8444-555555555555",
        cwd="/tmp/project",
        model="claude-sonnet-5[1m]",
        branch="task-174/test",
        exclude_user_messages=exclude,
    )


def test_render_claude_history_preserves_dialogue_and_completes_tools():
    rows = [
        _row(
            1, "user_message", "[Orchestra platform note: quoted by user]",
            origin="user", origin_detail={"senders": ["user"]},
        ),
        _row(2, "tool", "Read: {\"path\":\"a\"}", tool_use_id="a", tool_name="Read"),
        _row(3, "tool", "Read: {\"path\":\"b\"}", tool_use_id="b", tool_name="Read"),
        _row(4, "tool_result", "B result", tool_use_id="b", tool_name="Read"),
        _row(5, "tool_result", "A result", tool_use_id="a", tool_name="Read"),
        _row(6, "text", "Answer"),
        _row(7, "thinking", "private reasoning"),
        _row(8, "status", "turn ended"),
        _row(
            9, "user_message", "plain platform payload",
            origin="platform", origin_detail={"senders": ["Orchestra"]},
        ),
    ]

    history = _render(rows)

    assert history.report.users == 1
    assert history.report.assistants == 1
    assert history.report.tool_calls == 2
    assert history.report.tool_results == 2
    assert history.report.reasoning_omitted == 1
    serialized = repr(history.entries)
    assert "quoted by user" in serialized
    assert "Answer" in serialized
    assert "private reasoning" not in serialized
    assert "plain platform payload" not in serialized

    calls = {}
    results = []
    for entry in history.entries:
        for block in entry["message"]["content"] if isinstance(entry["message"]["content"], list) else []:
            if block["type"] == "tool_use":
                calls[block["input"]["source_log_id"]] = block["id"]
            elif block["type"] == "tool_result":
                results.append(block["tool_use_id"])
    assert results == [calls[3], calls[2]]
    assert all(result in calls.values() for result in results)


def test_render_closes_orphan_calls_and_results_without_pending_tail():
    history = _render([
        _row(1, "tool_result", "orphan output"),
        _row(2, "tool", "unanswered call"),
    ])

    blocks = [
        block
        for entry in history.entries
        if isinstance(entry["message"]["content"], list)
        for block in entry["message"]["content"]
    ]
    call_ids = {block["id"] for block in blocks if block["type"] == "tool_use"}
    result_ids = {block["tool_use_id"] for block in blocks if block["type"] == "tool_result"}
    assert call_ids == result_ids
    assert blocks[-1]["type"] == "tool_result"
    assert "historical call is not pending" in repr(blocks)


def test_unmatched_identified_result_does_not_consume_another_call():
    history = _render([
        _row(1, "tool", "CALL-A", tool_use_id="call-a", tool_name="Read"),
        _row(2, "tool", "CALL-LEGACY", tool_name="Read"),
        _row(3, "tool_result", "RESULT-B", tool_use_id="call-b"),
        _row(4, "tool_result", "RESULT-LEGACY"),
    ])

    calls = {}
    results = {}
    for entry in history.entries:
        content = entry["message"]["content"]
        for block in content if isinstance(content, list) else []:
            if block["type"] == "tool_use":
                calls[block["input"]["source_log_id"]] = block
            elif block["type"] == "tool_result":
                results[block["content"]] = block["tool_use_id"]

    assert calls[3]["input"]["synthetic"] is True
    assert results["RESULT-B"] == calls[3]["id"]
    assert results["RESULT-B"] != calls[1]["id"]
    assert results["RESULT-LEGACY"] == calls[2]["id"]


def test_pending_tool_is_closed_before_following_assistant_text():
    history = _render([
        _row(1, "tool", "CALL-A", tool_use_id="call-a", tool_name="Read"),
        _row(2, "text", "answer after missing result"),
    ])

    sequence = []
    for entry in history.entries:
        content = entry["message"]["content"]
        if isinstance(content, str):
            sequence.append((entry["type"], "text"))
        else:
            sequence.extend((entry["type"], block["type"]) for block in content)
    assert sequence == [
        ("assistant", "tool_use"),
        ("user", "tool_result"),
        ("assistant", "text"),
    ]


def test_urlsafe_base64_and_tool_metadata_are_sanitized_and_bounded():
    binary = base64.urlsafe_b64encode(bytes(range(256)) * 3).decode()
    tool_name = "name segment! " * 200 + "Authorization: Bearer metadata-secret"
    history = _render([
        _row(1, "tool", f"blob={binary}", tool_use_id="call-a", tool_name=tool_name),
        _row(2, "tool_result", "done", tool_use_id="call-a"),
    ])

    serialized = repr(history.entries)
    call = next(
        block
        for entry in history.entries
        if isinstance(entry["message"]["content"], list)
        for block in entry["message"]["content"]
        if block["type"] == "tool_use"
    )
    assert binary not in serialized
    assert "metadata-secret" not in serialized
    assert "binary/base64 omitted" in serialized
    assert len(call["input"]["source_tool_name"]) <= 512
    assert history.report.secrets_redacted >= 2
    assert history.report.truncated >= 1


def test_wrapped_base64_is_redacted_before_history_budget():
    raw = bytes(range(256)) * 4
    encoded = base64.b64encode(raw).decode()
    wrapped = "  \n".join(
        encoded[index:index + 76]
        for index in range(0, len(encoded), 76)
    )
    assert base64.b64decode("".join(wrapped.split()), validate=True) == raw

    history = _render([
        _row(1, "tool", f"blob={wrapped}", tool_use_id="call-a", tool_name="Read"),
        _row(2, "tool_result", "done", tool_use_id="call-a"),
    ])

    serialized = repr(history.entries)
    assert wrapped not in serialized
    assert "binary/base64 omitted" in serialized
    assert history.report.secrets_redacted >= 1


def test_full_serialized_tool_history_obeys_hard_cap():
    import app.runtime_history as history_module

    history = _render([
        _row(
            index,
            "tool",
            f"call-{index}",
            tool_use_id=f"tool-{index}",
            tool_name="Read",
        )
        for index in range(1, 3_001)
    ])
    tool_entries = [
        entry for entry in history.entries
        if history_module._claude_tool_identity(entry)
    ]
    visible_chars = sum(len(json.dumps(
        entry["message"], ensure_ascii=False, separators=(",", ":")
    )) for entry in tool_entries)
    calls = {
        history_module._claude_tool_identity(entry)
        for entry in tool_entries
        if entry["type"] == "assistant"
    }
    results = {
        history_module._claude_tool_identity(entry)
        for entry in tool_entries
        if entry["type"] == "user"
    }

    assert visible_chars <= history_module.TOOL_VISIBLE_BUDGET
    assert calls == results
    assert len(calls) < 3_000
    assert history.report.truncated > 0


def test_render_codex_history_uses_response_items_and_completed_custom_tools():
    rows = [
        _row(1, "user_message", "Question"),
        _row(
            2,
            "tool",
            'Read: {"token":"secret-value"}',
            tool_use_id="tool-1",
            tool_name="Read",
        ),
        _row(
            3,
            "tool_result",
            "marker from tool",
            tool_use_id="tool-1",
            tool_name="Read",
        ),
        _row(4, "text", "Answer"),
        _row(5, "tool", "orphan call"),
    ]

    rendered = render_codex_history(
        rows,
        snapshot_id=5,
        thread_id="11111111-2222-4333-8444-555555555555",
    )

    assert [item["type"] for item in rendered.history] == [
        "message",
        "custom_tool_call",
        "custom_tool_call_output",
        "message",
        "custom_tool_call",
        "custom_tool_call_output",
    ]
    assert rendered.history[0] == {
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": "Question"}],
    }
    assert rendered.history[3] == {
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": "Answer"}],
    }
    first_call = rendered.history[1]
    first_output = rendered.history[2]
    assert first_output["call_id"] == first_call["call_id"]
    assert json.loads(first_call["input"]) == {
        "recorded_call": 'Read: {"token":[redacted]}',
        "source_tool_name": "Read",
        "source_log_id": 2,
        "already_executed": True,
        "synthetic": False,
    }
    assert "marker from tool" in first_output["output"]
    assert "secret-value" not in repr(rendered.history)
    assert rendered.history[-1]["type"] == "custom_tool_call_output"
    assert rendered.report.tool_calls == 2
    assert rendered.report.tool_results == 1


def test_codex_uses_shared_tool_cap_and_wrapped_base64_sanitizer():
    import app.runtime_history as history_module

    encoded = base64.urlsafe_b64encode(bytes(range(256)) * 4).decode()
    wrapped = " \n".join(
        encoded[index:index + 76]
        for index in range(0, len(encoded), 76)
    )
    rows = [
        _row(
            index,
            "tool",
            wrapped if index == 3_000 else f"call-{index}",
            tool_use_id=f"tool-{index}",
            tool_name="Read",
        )
        for index in range(1, 3_001)
    ]

    rendered = render_codex_history(
        rows,
        snapshot_id=3_000,
        thread_id="11111111-2222-4333-8444-555555555555",
    )
    tool_items = [
        item for item in rendered.history
        if item["type"] in {"custom_tool_call", "custom_tool_call_output"}
    ]
    visible_chars = sum(len(json.dumps(
        item, ensure_ascii=False, separators=(",", ":")
    )) for item in tool_items)
    calls = {
        item["call_id"]
        for item in tool_items
        if item["type"] == "custom_tool_call"
    }
    outputs = {
        item["call_id"]
        for item in tool_items
        if item["type"] == "custom_tool_call_output"
    }
    serialized = repr(tool_items)

    assert visible_chars <= history_module.TOOL_VISIBLE_BUDGET
    assert calls == outputs
    assert len(calls) < 3_000
    assert wrapped not in serialized
    assert "binary/base64 omitted" in serialized
    assert rendered.report.secrets_redacted >= 1
    assert rendered.report.truncated > 0


def test_render_is_idempotent_and_excludes_only_latest_matching_user():
    rows = [
        _row(1, "user_message", "same"),
        _row(2, "text", "old answer"),
        _row(3, "user_message", "same"),
    ]

    first = _render(rows, exclude=("same",))
    second = _render(rows, exclude=("same",))

    assert first.entries == second.entries
    user_contents = [
        entry["message"]["content"]
        for entry in first.entries
        if entry["type"] == "user" and isinstance(entry["message"]["content"], str)
    ]
    assert user_contents == ["same"]


def test_render_redacts_secrets_and_bounds_tool_payload(monkeypatch):
    import app.runtime_history as history_module

    monkeypatch.setattr(history_module, "TOOL_CALL_LIMIT", 80)
    monkeypatch.setattr(history_module, "TOOL_RESULT_LIMIT", 100)
    monkeypatch.setattr(history_module, "TOOL_DETAIL_BUDGET", 120)
    private_key = "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----"
    rows = [
        _row(1, "user_message", "authorization: Bearer abc123"),
        _row(2, "tool", '{"token":"tool-secret","data":"' + "x" * 200 + '"}'),
        _row(3, "tool_result", private_key + " " + "A" * 600),
    ]

    rendered = history_module.render_claude_history(
        rows,
        snapshot_id=3,
        session_id=str(uuid.uuid4()),
        cwd="/tmp/project",
        model="claude-sonnet-5[1m]",
    )
    payload = repr(rendered.entries)
    assert "abc123" not in payload
    assert "tool-secret" not in payload
    assert "BEGIN PRIVATE KEY" not in payload
    assert "A" * 512 not in payload
    assert "original_chars=233" in payload
    assert rendered.report.secrets_redacted >= 4
    assert rendered.report.truncated >= 1
    assert rendered.report.tool_detailed_chars <= 120


@pytest.mark.asyncio
async def test_claude_log_store_returns_independent_copy_and_ignores_append():
    history = _render([_row(1, "user_message", "remember")])
    store = ClaudeLogSessionStore(history)
    key = {"project_key": "p", "session_id": history.session_id}

    first = await store.load(key)
    first[0]["message"]["content"] = "changed"
    second = await store.load(key)
    await store.append(key, [{"type": "user"}])

    assert second[0]["message"]["content"] == "remember"
    assert await store.load({**key, "subpath": "subagents/a"}) is None


@pytest.mark.live_probe
def test_installed_claude_history_versions_match_pins():
    assert importlib.metadata.version("claude-agent-sdk") == CLAUDE_SDK_HISTORY_VERSION
    cli = shutil.which("claude")
    if cli is None:
        pytest.skip("Claude CLI is not installed")
    result = subprocess.run(
        [cli, "--version"], capture_output=True, text=True, check=True, timeout=10
    )
    assert result.stdout.strip().split(maxsplit=1)[0] == CLAUDE_CLI_HISTORY_VERSION


def test_history_log_snapshot_excludes_row_inserted_after_boundary(tmp_path, monkeypatch):
    db_path = tmp_path / "history.db"
    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    dbmod.init_db()
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO sessions (id, name, scope, cwd, model, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            ("s1", "w", "/s", "/s", "claude-sonnet-5[1m]", datetime.now(timezone.utc).isoformat()),
        )
    dbmod.add_log(
        "s1", datetime.now(timezone.utc), "user_message", "before",
        provenance=MessageProvenance(origin="user", senders=("user",)),
    )

    base = sqlite3.connect(db_path)
    base.row_factory = sqlite3.Row

    class InterleavingConnection:
        inserted = False

        def execute(self, sql, params=()):
            cursor = base.execute(sql, params)
            if "COALESCE(MAX(id)" in sql and not self.inserted:
                self.inserted = True
                dbmod.add_log("s1", datetime.now(timezone.utc), "text", "after")
            return cursor

    snapshot_id, rows = dbmod.get_history_logs("s1", conn=InterleavingConnection())
    base.close()

    assert snapshot_id == rows[-1]["id"]
    assert [row["content"] for row in rows] == ["before"]


def test_history_columns_are_nullable_additive_and_marker_round_trips(tmp_path, monkeypatch):
    db_path = tmp_path / "migration.db"
    monkeypatch.setattr(dbmod, "DB_PATH", db_path)
    dbmod.init_db()
    dbmod.init_db()

    with sqlite3.connect(db_path) as conn:
        session_cols = {
            row[1]: row for row in conn.execute("PRAGMA table_info(sessions)")
        }
        log_cols = {row[1]: row for row in conn.execute("PRAGMA table_info(logs)")}
    assert session_cols["history_import_source"][3] == 0
    for name in ("tool_use_id", "tool_name", "tool_is_error"):
        assert log_cols[name][3] == 0

    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """INSERT INTO sessions (id, name, scope, cwd, model, created_at,
                                      history_import_source)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                "s1", "w", "/s", "/s", "claude-sonnet-5[1m]",
                datetime.now(timezone.utc).isoformat(), "logs:claude",
            ),
        )
    row = dbmod.get_session("s1")
    assert row["history_import_source"] == "logs:claude"


def test_state_packet_projects_only_bounded_uuid_from_tool_result_body():
    marker = "29020000-0000-4000-8000-000000000002"
    instruction = "WRITE_MARKER_FROM_RAW=/tmp/forbidden-marker"
    packet = build_runtime_state_packet(
        [
            _row(1, "tool", "read", tool_use_id="call-1", tool_name="Read"),
            _row(
                2, "tool_result", f"{instruction}\nreference={marker}",
                tool_use_id="call-1", tool_name="Read", tool_is_error=False,
            ),
        ],
        session_meta={"id": "s1", "source_runtime": "codex", "target_runtime": "claude"},
        snapshot_id=2,
        current_system_prompt="system",
        project_docs=[],
    )

    rendered = json.dumps(packet, ensure_ascii=False)
    assert marker in rendered
    assert instruction not in rendered
    assert packet["tool_effects"][0]["portable_identifiers"] == [{
        "kind": "uuid", "value": marker, "authority": "transcript_untrusted",
    }]


def test_state_packet_redacts_secret_from_tool_metadata():
    packet = build_runtime_state_packet(
        [
            _row(
                1, "tool", "opaque call", tool_use_id="call-1",
                tool_name="Read Authorization: Bearer metadata-secret",
            ),
            _row(
                2, "tool_result", "done", tool_use_id="call-1",
                tool_name="Read", tool_is_error=False,
            ),
        ],
        session_meta={"id": "s1"}, snapshot_id=2,
        current_system_prompt="system", project_docs=[],
    )

    serialized = json.dumps(packet, ensure_ascii=False)
    assert "metadata-secret" not in serialized
    assert "Authorization: [redacted]" in serialized


def test_state_packet_redacts_and_bounds_tool_call_id():
    secret_id = "Bearer call-secret " + "x" * 700
    packet = build_runtime_state_packet(
        [
            _row(1, "tool", "call", tool_use_id=secret_id, tool_name="Read"),
            _row(
                2, "tool_result", "done", tool_use_id=secret_id,
                tool_name="Read", tool_is_error=False,
            ),
        ],
        session_meta={"id": "s1"}, snapshot_id=2,
        current_system_prompt="system", project_docs=[],
    )

    effect = packet["tool_effects"][0]
    assert effect["status"] == "completed"
    assert effect["call_id"].startswith("tool-id-sha256:")
    assert "call-secret" not in json.dumps(packet, ensure_ascii=False)


def test_state_packet_pairs_legacy_tools_fifo_but_never_guesses_unknown_ids():
    packet = build_runtime_state_packet(
        [
            _row(1, "tool", "legacy call", tool_name="Read"),
            _row(2, "tool_result", "legacy result", tool_name="Read"),
            _row(
                3, "tool_result", "unknown id",
                tool_use_id="unknown", tool_name="Read",
            ),
        ],
        session_meta={"id": "s1"}, snapshot_id=3,
        current_system_prompt="system", project_docs=[],
    )

    assert packet["tool_effects"][0]["status"] == "completed"
    assert packet["tool_effects"][0]["call_id"] == "legacy-1"
    assert packet["tool_effects"][1]["status"] == "ambiguous"
    assert packet["tool_effects"][1]["call_id"] == "unknown"


def test_state_packet_integrity_is_recomputed_from_content():
    packet = build_runtime_state_packet(
        [_row(1, "user_message", "before")],
        session_meta={"id": "s1"}, snapshot_id=1,
        current_system_prompt="system", project_docs=[],
    )
    expected = packet["integrity"]["canonical_sha256"]
    assert runtime_packet_sha256(packet) == expected

    packet["recent_messages"][0]["content"] = "tampered"
    assert runtime_packet_sha256(packet) != expected
