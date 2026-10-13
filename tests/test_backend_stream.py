"""ClaudeBackend._convert StreamEvent scope filter + sub-agent tagging.

Main-agent text_delta → "stream". Sub-agent text_delta (parent_tool_use_id set)
→ "subagent_stream" tagged with subagent_id (surfaced, not dropped). Since V-831
thinking_delta → "thinking_stream" and a tool call's input_json_delta →
"tool_input_stream" (tool id/name taken from content_block_start), so a long call is
visible while the model writes it. Signature deltas stay dropped.
"""
from claude_agent_sdk import (
    StreamEvent,
    TaskNotificationMessage,
    TaskProgressMessage,
    TaskStartedMessage,
)

from app.backend_claude import ClaudeBackend
from app.events import AgentEvent


def _backend():
    return ClaudeBackend(model="claude-sonnet-5-5[1m]", cwd="/tmp")


def _stream(event, parent_tool_use_id=None):
    return StreamEvent(uuid="u", session_id="s", event=event,
                       parent_tool_use_id=parent_tool_use_id)


def test_text_delta_emits_stream_event():
    b = _backend()
    msg = _stream({
        "type": "content_block_delta", "index": 0,
        "delta": {"type": "text_delta", "text": "hello"},
    })
    events = b._convert(msg)
    assert len(events) == 1
    assert events[0].type == "stream"
    assert events[0].content == "hello"


def test_empty_text_delta_emits_nothing():
    b = _backend()
    msg = _stream({
        "type": "content_block_delta", "index": 0,
        "delta": {"type": "text_delta", "text": ""},
    })
    assert b._convert(msg) == []


def _tool_block_start(index=1, tool_id="toolu_A", name="Bash", parent=None):
    return _stream({"type": "content_block_start", "index": index,
                    "content_block": {"type": "tool_use", "id": tool_id, "name": name, "input": {}}},
                   parent_tool_use_id=parent)


def _json_delta(chunk, index=1, parent=None):
    return _stream({"type": "content_block_delta", "index": index,
                    "delta": {"type": "input_json_delta", "partial_json": chunk}},
                   parent_tool_use_id=parent)


def test_thinking_delta_streams_with_a_block_id():
    b = _backend()
    b._convert(_stream({"type": "content_block_start", "index": 0,
                        "content_block": {"type": "thinking", "thinking": ""}}))
    first = b._convert(_stream({"type": "content_block_delta", "index": 0,
                                "delta": {"type": "thinking_delta", "thinking": "hmm"}}))
    b._convert(_stream({"type": "content_block_stop", "index": 0}))
    b._convert(_stream({"type": "content_block_start", "index": 0,
                        "content_block": {"type": "thinking", "thinking": ""}}))
    second = b._convert(_stream({"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "thinking_delta", "thinking": "more"}}))

    assert [(e.type, e.content, e.metadata["activity"]) for e in first] == [
        ("thinking_stream", "hmm", "reasoning")]
    # Two thinking blocks must not merge into one live card.
    assert first[0].metadata["item_id"] != second[0].metadata["item_id"]


def test_tool_call_arguments_stream_with_tool_identity():
    b = _backend()
    started = b._convert(_tool_block_start())
    deltas = b._convert(_json_delta('{"command": "ec')) + b._convert(_json_delta('ho hi"}'))

    assert [(e.type, e.content) for e in started] == [("tool_input_stream", "")]
    assert started[0].metadata == {"tool_use_id": "toolu_A", "tool_name": "Bash", "short_name": "Bash"}
    assert "".join(e.content for e in deltas) == '{"command": "echo hi"}'
    assert all(e.type == "tool_input_stream" and e.metadata["tool_use_id"] == "toolu_A" for e in deltas)


def test_mcp_tool_name_is_shortened_and_unknown_block_deltas_dropped():
    b = _backend()
    out = b._convert(_tool_block_start(name="mcp__orchestra__send_message"))
    assert out[0].metadata["short_name"] == "send_message"
    # A delta whose block start was never seen has no tool identity → nothing to show.
    assert b._convert(_json_delta('{"a":', index=7)) == []


def test_block_indices_restart_per_message():
    b = _backend()
    b._convert(_tool_block_start(index=1, tool_id="toolu_A"))
    b._convert(_stream({"type": "message_start", "message": {}}))
    # Same index in the next message without its own start must not reuse toolu_A.
    assert b._convert(_json_delta('{"x":1}', index=1)) == []


def test_subagent_tool_arguments_are_tagged_and_isolated_from_main():
    b = _backend()
    b._convert(_tool_block_start(index=1, tool_id="toolu_main"))
    b._convert(_tool_block_start(index=1, tool_id="toolu_sub", name="Read", parent="toolu_task"))

    main = b._convert(_json_delta('{"m":1}', index=1))
    sub = b._convert(_json_delta('{"s":1}', index=1, parent="toolu_task"))

    assert main[0].metadata["tool_use_id"] == "toolu_main" and "subagent_id" not in main[0].metadata
    assert sub[0].metadata["tool_use_id"] == "toolu_sub"
    assert sub[0].metadata["subagent_id"] == "toolu_task"


def test_signature_delta_dropped():
    b = _backend()
    msg = _stream({
        "type": "content_block_delta", "index": 0,
        "delta": {"type": "signature_delta", "signature": "sig"},
    })
    assert b._convert(msg) == []


def test_subagent_text_delta_becomes_subagent_stream():
    # Sub-agent partials are no longer dropped — they surface as subagent_stream
    # tagged with subagent_id so the UI nests them under the sub-agent block.
    b = _backend()
    msg = _stream({
        "type": "content_block_delta", "index": 0,
        "delta": {"type": "text_delta", "text": "sub"},
    }, parent_tool_use_id="toolu_123")
    out = b._convert(msg)
    assert len(out) == 1
    assert out[0].type == "subagent_stream"
    assert out[0].content == "sub"
    assert out[0].metadata.get("subagent_id") == "toolu_123"


def test_subagent_stream_resolves_parent_tool_use_to_task_id():
    b = _backend()
    start = TaskStartedMessage(
        subtype="task_started",
        data={},
        task_id="agent-1",
        description="Review security",
        uuid="start-1",
        session_id="sdk-1",
        tool_use_id="toolu_123",
        task_type="local_agent",
    )
    b._convert(start)

    out = b._convert(_stream({
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "text_delta", "text": "finding"},
    }, parent_tool_use_id="toolu_123"))

    assert out[0].metadata["subagent_id"] == "agent-1"


def test_subagent_lifecycle_keeps_stable_id_type_and_description():
    b = _backend()
    start = TaskStartedMessage(
        subtype="task_started",
        data={},
        task_id="agent-1",
        description="Review security",
        uuid="start-1",
        session_id="sdk-1",
        tool_use_id="toolu_123",
        task_type="local_agent",
    )
    progress = TaskProgressMessage(
        subtype="task_progress",
        data={},
        task_id="agent-1",
        description="",
        usage={"total_tokens": 1234, "tool_uses": 2, "duration_ms": 500},
        uuid="progress-1",
        session_id="sdk-1",
        tool_use_id="toolu_123",
        last_tool_name="Read",
    )
    end = TaskNotificationMessage(
        subtype="task_notification",
        data={},
        task_id="agent-1",
        status="completed",
        output_file="",
        summary="No blockers",
        uuid="end-1",
        session_id="sdk-1",
        tool_use_id="toolu_123",
        usage={"total_tokens": 2000, "tool_uses": 3, "duration_ms": 800},
    )

    start_event = b._convert(start)[0]
    progress_event = b._convert(progress)[0]
    end_event = b._convert(end)[0]

    for event in (start_event, progress_event, end_event):
        assert event.metadata["subagent_id"] == "agent-1"
        assert event.metadata["task_type"] == "local_agent"
        assert "id=agent-1" in event.content
        assert "type=local_agent" in event.content
    assert progress_event.metadata["description"] == "Review security"
    assert end_event.metadata["description"] == "Review security"
    assert end_event.content.startswith("Review security |")


def test_non_delta_events_dropped():
    b = _backend()
    for etype in ("message_start", "content_block_start",
                  "content_block_stop", "message_delta", "message_stop"):
        # A bare content_block_start (no tool/thinking block) opens nothing to stream.
        assert b._convert(_stream({"type": etype})) == []


def test_tag_sub_marks_only_subagent_events():
    # main agent (sub_id None) → event unchanged; sub-agent → subagent_id stamped
    main = ClaudeBackend._tag_sub(AgentEvent("tool_use", "x", metadata={"tool_name": "Bash"}), None)
    assert "subagent_id" not in main.metadata
    assert main.metadata["tool_name"] == "Bash"

    sub = ClaudeBackend._tag_sub(AgentEvent("tool_use", "x", metadata={"tool_name": "Bash"}), "toolu_9")
    assert sub.metadata["subagent_id"] == "toolu_9"
    assert sub.metadata["tool_name"] == "Bash"  # existing metadata preserved
    assert sub.type == "tool_use"  # type unchanged — UI groups by id, not type


def test_omitted_thinking_still_streams_its_token_estimate():
    # Real CLI 2.1.293 capture (V-831): display omitted → empty text + estimated_tokens.
    b = _backend()
    b._convert(_stream({"type": "content_block_start", "index": 0,
                        "content_block": {"type": "thinking", "thinking": "", "signature": ""}}))
    out = b._convert(_stream({"type": "content_block_delta", "index": 0,
                              "delta": {"type": "thinking_delta", "thinking": "", "estimated_tokens": 250}}))
    assert [(e.type, e.content, e.metadata["estimated_tokens"]) for e in out] == [
        ("thinking_stream", "", 250)]
    assert b._convert(_stream({"type": "content_block_delta", "index": 0,
                               "delta": {"type": "thinking_delta", "thinking": ""}})) == []
