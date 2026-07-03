"""Sub-agent transcript endpoints: telemetry list, transcript ids, transcript,
path-traversal guard."""

import pytest

from app.routes import subagent as sr


@pytest.mark.asyncio
async def test_transcript_rejects_path_traversal():
    for bad in ("../../etc/passwd", "a/b", "a.b", "..", "x/../y"):
        r = await sr.subagent_transcript("sess-1", bad)
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_transcript_ids_missing_session(monkeypatch):
    monkeypatch.setattr(sr, "get_session", lambda sid: None)
    r = await sr.subagent_transcript_ids("nope")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_transcript_ids_no_sdk_session(monkeypatch):
    monkeypatch.setattr(sr, "get_session", lambda sid: {"session_id": "", "cwd": "/c"})
    r = await sr.subagent_transcript_ids("sess-1")
    assert r["agent_ids"] == []


@pytest.mark.asyncio
async def test_transcript_reads_messages(monkeypatch):
    monkeypatch.setattr(sr, "get_session",
                        lambda sid: {"session_id": "550e8400-e29b-41d4-a716-446655440000", "cwd": "/c"})

    class _Msg:
        type = "user"
        message = {"content": "hello from subagent"}
        parent_tool_use_id = None

    import claude_agent_sdk
    monkeypatch.setattr(claude_agent_sdk, "get_subagent_messages",
                        lambda *a, **k: [_Msg()])
    r = await sr.subagent_transcript("sess-1", "ae795e652a2bbf63a")
    assert r["count"] == 1
    assert r["messages"][0]["content"] == "hello from subagent"


@pytest.mark.asyncio
async def test_transcript_sdk_error_graceful(monkeypatch):
    monkeypatch.setattr(sr, "get_session",
                        lambda sid: {"session_id": "550e8400-e29b-41d4-a716-446655440000", "cwd": "/c"})
    import claude_agent_sdk

    def boom(*a, **k):
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(claude_agent_sdk, "get_subagent_messages", boom)
    r = await sr.subagent_transcript("sess-1", "ae795e652a2bbf63a")
    assert r["messages"] == []
    assert "error" in r
