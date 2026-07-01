"""ClaudeBackend._convert StreamEvent scope filter + sub-agent tagging.

Main-agent text_delta → "stream". Sub-agent text_delta (parent_tool_use_id set)
→ "subagent_stream" tagged with subagent_id (surfaced, not dropped). Non-text
deltas (thinking/tool-arg/sig) and non-delta events are still dropped.
"""
from claude_agent_sdk import StreamEvent

from app.backend_claude import ClaudeBackend
from app.events import AgentEvent


def _backend():
    return ClaudeBackend(model="claude-sonnet-5[1m]", cwd="/tmp")


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


def test_thinking_delta_dropped():
    b = _backend()
    msg = _stream({
        "type": "content_block_delta", "index": 0,
        "delta": {"type": "thinking_delta", "thinking": "hmm"},
    })
    assert b._convert(msg) == []


def test_input_json_delta_dropped():
    b = _backend()
    msg = _stream({
        "type": "content_block_delta", "index": 0,
        "delta": {"type": "input_json_delta", "partial_json": '{"a":'},
    })
    assert b._convert(msg) == []


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


def test_non_delta_events_dropped():
    b = _backend()
    for etype in ("message_start", "content_block_start",
                  "content_block_stop", "message_delta", "message_stop"):
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
