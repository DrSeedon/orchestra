"""Task #83 — ClaudeBackend._convert StreamEvent scope filter.

v1 streaming: ONLY main-agent text_delta becomes a "stream" AgentEvent.
Everything else (thinking/tool-arg deltas, subagent partials, non-delta events)
is dropped — the final AssistantMessage still carries them and is persisted.
"""
from claude_agent_sdk import StreamEvent

from app.backend_claude import ClaudeBackend


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


def test_subagent_text_delta_dropped():
    b = _backend()
    msg = _stream({
        "type": "content_block_delta", "index": 0,
        "delta": {"type": "text_delta", "text": "sub"},
    }, parent_tool_use_id="toolu_123")
    assert b._convert(msg) == []


def test_non_delta_events_dropped():
    b = _backend()
    for etype in ("message_start", "content_block_start",
                  "content_block_stop", "message_delta", "message_stop"):
        assert b._convert(_stream({"type": etype})) == []
