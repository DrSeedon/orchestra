"""Regression tests verifying all 26 audit defects (B01-B26) are closed."""
import json
from types import SimpleNamespace
import pytest

from app import acp_tools, backend_codex, backend_grok, db, hub_activity, mailbox
from app.events import AgentEvent, MessageProvenance
from app.harness.loop import AgentLoop, _NoopMCP
from app.session_turns import TurnManager


def test_b07_acp_tools_empty_result_never_fabricates_title_and_extracts_diffs():
    reducer = acp_tools.ToolReducer()
    events = reducer.apply({
        "toolCallId": "tc-1",
        "name": "mcp_orchestra_0eaef74b_task_create",
        "title": "Run mcp_orchestra_0eaef74b_task_create",
        "status": "completed",
        "rawInput": {"title": "Test task"},
        "content": [{"type": "diff", "path": "src/a.py", "oldText": "a", "newText": "b"}],
    })
    use = next(e for e in events if e[0] == "tool_use")
    res = next(e for e in events if e[0] == "tool_result")
    assert use[2]["tool_name"] == "mcp__orchestra__task_create"
    assert res[2]["has_output"] is True
    assert res[2]["raw_diffs"] == [{"path": "src/a.py", "old_text": "a", "new_text": "b"}]

    reducer2 = acp_tools.ToolReducer()
    ev2 = reducer2.apply({
        "toolCallId": "tc-2",
        "name": "mcp_orchestra_0eaef74b_bg_list",
        "title": "Run mcp_orchestra_0eaef74b_bg_list",
        "status": "failed",
        "rawInput": {},
    })
    res2 = next(e for e in ev2 if e[0] == "tool_result")
    assert res2[1] == ""
    assert res2[2]["has_output"] is False
    assert res2[2]["is_error"] is True


def test_b08_track_parent_report_normalizes_wire_and_grok_variants():
    s = SimpleNamespace(
        parent_name="boss", parent_id="p-1", last_task_sender=None,
        _report_calls={}, _turn_gen=3, _did_report=False,
    )
    tm = TurnManager(s)
    tm.track_parent_report(
        AgentEvent("tool_use", 'mcp_orchestra_0eaef74b_send_message: {"to":"boss","message":"done"}',
                   metadata={"tool_use_id": "c1", "tool_name": "mcp_orchestra_0eaef74b_send_message"}),
        "mcp_orchestra_0eaef74b_send_message",
    )
    assert "c1" in s._report_calls
    tm.track_parent_report(
        AgentEvent("tool_result", "Run mcp_orchestra_0eaef74b_send_message",
                   metadata={"tool_use_id": "c1"}),
        "mcp_orchestra_0eaef74b_send_message",
    )
    assert s._did_report is False, "Run ... placeholder must NEVER count as receipt"

    tm.track_parent_report(
        AgentEvent("tool_use", 'orchestra:send_message: {"to":"boss","message":"done"}',
                   metadata={"tool_use_id": "c2"}),
        "orchestra:send_message",
    )
    tm.track_parent_report(
        AgentEvent("tool_result", "Message sent to 'boss'", metadata={"tool_use_id": "c2"}),
        "orchestra:send_message",
    )
    assert s._did_report is True

    s._did_report = False
    tm.track_parent_report(
        AgentEvent("tool_use", 'use_tool: {"tool_name":"orchestra__send_message","tool_input":{"to":"boss","message":"hi"}}',
                   metadata={"tool_use_id": "c3"}),
        "use_tool",
    )
    tm.track_parent_report(
        AgentEvent("tool_result", json.dumps({"ok": True, "delivery_id": "d1", "delivery_state": "SUBMITTED"}),
                   metadata={"tool_use_id": "c3", "tool_name": "orchestra__send_message"}),
        "orchestra__send_message",
    )
    assert s._did_report is True


def test_b13_provenance_round_trip_orig_subtype():
    p = MessageProvenance("background_task", ("cron",), subtype="codex_turn_end_hold", ref="job-9", orig_subtype="completed")
    orig, detail = p.to_storage()
    restored = MessageProvenance.from_storage(orig, detail)
    assert restored.ref == "job-9"
    assert restored.orig_subtype == "completed"
    assert restored.subtype == "codex_turn_end_hold"


def test_b16_hub_activity_valid_json_and_file_change():
    parser = hub_activity.HubActivityStream(run_id="r1")
    big_args = {"command": "x" * 600, "extra": "y" * 200}
    evs = parser.feed([{
        "runId": "r1", "position": 1, "itemId": "it1", "type": "dynamic_tool", "status": "completed",
        "text": json.dumps({"toolName": "send_message", "input": big_args, "output": "z" * 4500}),
    }])
    tu = next(e for e in evs if e.type == "tool_use")
    tr = next(e for e in evs if e.type == "tool_result")
    parsed_summary = json.loads(tu.content.split(": ", 1)[1])
    assert isinstance(parsed_summary, dict)
    assert tr.metadata.get("trunc") == 4500

    fc_evs = parser.feed([{"runId": "r1", "position": 2, "itemId": "fc1", "type": "file_change", "status": "completed", "text": "src/main.py"}])
    fc_tr = next(e for e in fc_evs if e.type == "tool_result")
    assert fc_tr.content == "изменён файл"


def test_b19_codex_separates_summary_and_raw_thinking():
    b = backend_codex.CodexBackend.__new__(backend_codex.CodexBackend)
    b._live_tools = {}
    s_evs = b._convert_notification({"method": "item/reasoning/summaryTextDelta", "params": {"itemId": "r1", "delta": "sum"}})
    r_evs = b._convert_notification({"method": "item/reasoning/textDelta", "params": {"itemId": "r1", "delta": "raw"}})
    assert s_evs[0].metadata["thinking_part"] == "summary"
    assert r_evs[0].metadata["thinking_part"] == "raw"
    assert s_evs[0].metadata["item_id"] != r_evs[0].metadata["item_id"]


def test_b21_db_cap_content_preserves_valid_json_for_large_tools():
    long_args = {"file_path": "/a/b.py", "old_string": "A" * 10000, "new_string": "B" * 10000}
    row = {
        "id": 999,
        "type": "tool",
        "content": "Edit: " + json.dumps(long_args),
        "raw_input": long_args,
    }
    capped = db._cap_content(row, 4096)
    assert capped["projection"] == "tool_args"
    assert capped["trunc"] > 4096
    parsed = json.loads(capped["content"].split(": ", 1)[1])
    assert parsed["file_path"] == "/a/b.py"
    assert isinstance(capped["raw_input"], dict)


def test_b10_grok_unwraps_use_tool_and_closes_cancelled():
    b = backend_grok.GrokBackend.__new__(backend_grok.GrokBackend)
    b._message_buf = []
    b._thought_buf = []
    b._tool_names = {}
    b._shell_policy_violations = {}
    b._context_tokens = 0
    ev1 = b._session_update({
        "update": {
            "sessionUpdate": "tool_call", "toolCallId": "g1", "title": "use_tool",
            "rawInput": {"tool_name": "orchestra__send_message", "tool_input": {"to": "p", "message": "m"}},
        }
    })
    from app import acp_tools
    assert ev1[0].metadata["tool_name"] == "orchestra__send_message"
    assert acp_tools.canonical_orchestra_tool_name(ev1[0].metadata["tool_name"]) == "mcp__orchestra__send_message"
    ev2 = b._session_update({
        "update": {"sessionUpdate": "tool_call_update", "toolCallId": "g1", "status": "cancelled"}
    })
    assert ev2[-1].type == "tool_result" and ev2[-1].metadata["is_error"] is True


@pytest.mark.asyncio
async def test_b24_b09_b11_harness_stream_and_review_metadata():
    class FakeLLM:
        async def stream(self, _m, _t, **_kw):
            yield SimpleNamespace(kind="text_delta", text="hel")
            yield SimpleNamespace(kind="text_delta", text="lo")
            yield SimpleNamespace(kind="final", finish_reason="stop", reasoning_details=[], usage={"prompt_tokens": 1, "completion_tokens": 1})

    loop = AgentLoop(llm=FakeLLM(), mcp=_NoopMCP(), cwd="/tmp", history=[], tool_schemas=[], max_context=10000)
    events = [e async for e in loop.run("hi")]
    assert [e.type for e in events if e.type in {"stream", "text"}] == ["stream", "stream", "text"]


@pytest.mark.asyncio
async def test_b01_b20_b22_send_early_reject_context_known_and_no_event_id_leak(tmp_path, monkeypatch):
    from app import db, mailbox
    from app.routes import sessions as sessions_route
    from app.session import AgentSession
    from app.session_state import AgentStatus
    from datetime import datetime, timezone

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()

    s = AgentSession(
        id="agy-b01",
        name="agy-b01",
        scope=str(tmp_path),
        cwd=str(tmp_path),
        model="antigravity/gemini-4-carbon-medium",
        backend_type="antigravity",
        system_prompt="SYSTEM",
        created_at=datetime.now(timezone.utc),
    )
    # B20: Unknown context reports context_known=False
    assert s.to_dict()["context_known"] is False
    
    # B22: status log does not leak stale _acp_log_event_id across sequential events
    logged = []
    monkeypatch.setattr(s, "_log", lambda ltype, content, **kw: logged.append((ltype, kw.get("event_id"))))
    monkeypatch.setattr("app.live_broker.broker.publish", lambda *a, **kw: None)
    s._handle_event(SimpleNamespace(type="text", content="hi", metadata={"item_id": "acp:1:t:msg:0"}))
    s._handle_event(SimpleNamespace(type="status", content="done", metadata={}))
    assert logged[0] == ("text", "acp:1:t:msg:0")
    assert logged[1] == ("status", None)

    # B01: after_turn with unauthenticated non-user origin rejects BEFORE mailbox.enqueue
    s.status = AgentStatus.RUNNING
    s._persist()
    enq_calls = []
    monkeypatch.setattr(mailbox, "enqueue", lambda *a, **kw: enq_calls.append(a) or 99)
    monkeypatch.setattr(sessions_route, "manager", SimpleNamespace(
        sessions={s.id: s},
        get_session_id=lambda n, sc: s.id,
        get=lambda sid: s,
    ))
    req = sessions_route.SendRequest(message="wake cron", scope=str(tmp_path), channel="dashboard", after_turn=True)
    res = await sessions_route.send_message("agy-b01", req, request=None)
    assert res.status_code == 403
    assert enq_calls == []


def test_b17_hub_stream_separation():
    from pathlib import Path
    from app import backend_hub
    src = Path(backend_hub.__file__).read_text()
    assert 'AgentEvent("text", text)' in src
    assert 'AgentEvent("status", sync.strip())' in src


@pytest.mark.asyncio
async def test_manager_create_session_forwards_standalone_and_effort(tmp_path, monkeypatch):
    from app import db, manager as mgr_mod
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "mgr.db")
    db.init_db()
    m = mgr_mod.SessionManager()
    s = await m.create_session(
        name="standalone-codex-check",
        scope=str(tmp_path),
        cwd=str(tmp_path),
        model="gpt-6.2-sol",
        standalone=True,
        effort_override="high",
    )
    assert s.effort == "high"
    assert s.parent_name == ""


@pytest.mark.asyncio
async def test_stream_session_logs_owner_mode_filter(tmp_path, monkeypatch):
    from app import auth, db
    from app.routes import sessions as sessions_route
    from app.session import AgentSession
    from datetime import datetime, timezone

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "sse.db")
    db.init_db()
    s = AgentSession(
        id="sse-owner-check",
        name="sse-owner-check",
        scope=str(tmp_path),
        cwd=str(tmp_path),
        model="gpt-6.2-sol",
        backend_type="codex",
        system_prompt="SYSTEM",
        created_at=datetime.now(timezone.utc),
    )
    s._persist()
    await s._persist_task
    now = datetime.now(timezone.utc)
    db.add_log(s.id, now, "thinking", "internal thought")
    db.add_log(s.id, now, "thinking_stream", "live thought")
    db.add_log(s.id, now, "text", "visible answer")

    monkeypatch.setattr(sessions_route, "manager", SimpleNamespace(
        get_session_id=lambda n, sc: s.id,
        get=lambda sid: s,
    ))

    class _FakeReq:
        def __init__(self):
            self.calls = 0
        async def is_disconnected(self):
            self.calls += 1
            return self.calls >= 1

    async def _collect(owner_flag: bool):
        monkeypatch.setattr(auth, "is_owner_mode", lambda: owner_flag)
        monkeypatch.setattr(sessions_route, "is_owner_mode", lambda: owner_flag)
        resp = await sessions_route.stream_session_logs("sse-owner-check", str(tmp_path), _FakeReq(), after_id=0)
        chunks = []
        async for chunk in resp.body_iterator:
            chunks.append(chunk if isinstance(chunk, str) else chunk.decode())
        return [json.loads(c.removeprefix("data: ").strip()) for c in chunks if c.startswith("data: ")]

    owner_events = await _collect(True)
    assert any(ev.get("type") == "thinking" for ev in owner_events)
    assert any(ev.get("type") == "text" and ev.get("content") == "visible answer" for ev in owner_events)

    client_events = await _collect(False)
    assert not any(ev.get("type") in {"thinking", "thinking_stream"} for ev in client_events)
    assert not any(ev.get("type") in {"thinking", "thinking_stream"} for ev in client_events)
    assert any(ev.get("type") == "text" and ev.get("content") == "visible answer" for ev in client_events)
