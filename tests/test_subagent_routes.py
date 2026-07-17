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
    monkeypatch.setattr(sr, "get_subagents", lambda sid: [])
    monkeypatch.setattr(sr, "get_session", lambda sid: {"session_id": "", "cwd": "/c"})
    r = await sr.subagent_transcript_ids("sess-1")
    assert r["agent_ids"] == []


@pytest.mark.asyncio
async def test_subagent_list_separates_jobs_and_matches_transcripts_by_task_id(monkeypatch):
    rows = [
        {
            "task_id": "agent-new", "task_type": "local_agent",
            "sdk_session_id": "sdk-old", "started_at": "2026-07-17T00:00:00+00:00",
            "ended_at": "2026-07-17T00:00:02+00:00", "duration_ms": 0,
        },
        {
            "task_id": "bash-1", "task_type": "local_bash",
            "sdk_session_id": "sdk-current", "started_at": "2026-07-17T00:00:00+00:00",
            "ended_at": "2026-07-17T00:00:03+00:00", "duration_ms": 0,
        },
    ]
    monkeypatch.setattr(sr, "get_subagents", lambda sid: rows)
    monkeypatch.setattr(sr, "get_session",
                        lambda sid: {"session_id": "sdk-current", "cwd": "/c"})
    import claude_agent_sdk
    calls = []

    def fake_list(sdk_id, cwd):
        calls.append((sdk_id, cwd))
        return ["agent-new"] if sdk_id == "sdk-old" else []

    monkeypatch.setattr(claude_agent_sdk, "list_subagents", fake_list)
    r = await sr.subagents_list("sess-1")
    by_id = {item["task_id"]: item for item in r["subagents"]}
    assert by_id["agent-new"]["kind"] == "agent"
    assert by_id["agent-new"]["transcript_id"] == "agent-new"
    assert by_id["agent-new"]["duration_ms"] == 2000
    assert by_id["bash-1"]["kind"] == "background"
    assert by_id["bash-1"]["transcript_id"] == ""
    assert by_id["bash-1"]["duration_ms"] == 3000
    assert calls == [("sdk-old", "/c")]


@pytest.mark.asyncio
async def test_transcript_uses_historical_sdk_session_from_telemetry(monkeypatch):
    monkeypatch.setattr(sr, "get_session",
                        lambda sid: {"session_id": "sdk-current", "cwd": "/c"})
    monkeypatch.setattr(sr, "get_subagent", lambda sid, task_id: {
        "task_id": task_id,
        "task_type": "local_agent",
        "sdk_session_id": "sdk-old",
    })

    class _Msg:
        type = "assistant"
        message = {"content": "historical transcript"}
        parent_tool_use_id = None

    import claude_agent_sdk
    called = {}

    def fake_messages(sdk_id, agent_id, cwd, **kwargs):
        called.update(sdk_id=sdk_id, agent_id=agent_id, cwd=cwd)
        return [_Msg()]

    monkeypatch.setattr(claude_agent_sdk, "get_subagent_messages", fake_messages)
    r = await sr.subagent_transcript("sess-1", "agent-old")
    assert r["count"] == 1
    assert called == {
        "sdk_id": "sdk-old", "agent_id": "agent-old", "cwd": "/c",
    }


@pytest.mark.asyncio
async def test_background_task_has_no_transcript(monkeypatch):
    monkeypatch.setattr(sr, "get_session",
                        lambda sid: {"session_id": "sdk-current", "cwd": "/c"})
    monkeypatch.setattr(sr, "get_subagent", lambda sid, task_id: {
        "task_id": task_id,
        "task_type": "local_bash",
        "sdk_session_id": "sdk-current",
    })
    r = await sr.subagent_transcript("sess-1", "bash-1")
    assert r["messages"] == []
    assert r["note"] == "background tasks do not have transcripts"


@pytest.mark.asyncio
async def test_transcript_reads_messages(monkeypatch):
    monkeypatch.setattr(sr, "get_subagent", lambda sid, task_id: None)
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
    monkeypatch.setattr(sr, "get_subagent", lambda sid, task_id: None)
    monkeypatch.setattr(sr, "get_session",
                        lambda sid: {"session_id": "550e8400-e29b-41d4-a716-446655440000", "cwd": "/c"})
    import claude_agent_sdk

    def boom(*a, **k):
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(claude_agent_sdk, "get_subagent_messages", boom)
    r = await sr.subagent_transcript("sess-1", "ae795e652a2bbf63a")
    assert r["messages"] == []
    assert "error" in r
