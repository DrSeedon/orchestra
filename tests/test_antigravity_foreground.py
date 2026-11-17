"""Foreground contract: real SessionManager/backend/journal, synthetic native peer."""
import asyncio
from collections import Counter
from datetime import datetime,timezone
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from tests.test_antigravity_acp import stand,turn,end,USER
from tests.test_antigravity_acp_r2 import real_session,send_and_finish
from app import db,native_requests
from app.events import InjectedMessage
from app.session import AgentSession,AgentStatus

EVIDENCE=Path(__file__).resolve().parents[1]/".orchestra/tasks/agy-acp-safe-20261117"


async def pending(s,count=1):
    async with asyncio.timeout(3):
        while True:
            rows=native_requests.pending_for(s.id)
            if len(rows)==count:return rows
            await asyncio.sleep(.01)


async def finish(s):
    async with asyncio.timeout(4):await s._listen_task
    await s._drain_persist();await s._await_log_futures()


@pytest.mark.asyncio
async def test_ordered_transcript_two_sessions_two_turns_and_passive_poll(stand,real_session,monkeypatch):
    from app.routes import system
    from app.backend_antigravity import antigravity_readiness
    from app.runtime_registry import RuntimeReadinessContext
    from app import tg_bridge as tg,acp_tg_delivery
    from tests.test_antigravity_foreground_delivery import FakeBot
    from unittest.mock import AsyncMock
    bot=FakeBot();monkeypatch.setattr(tg,"bot",bot)
    monkeypatch.setattr(tg,"_tg_delivery_state_for",AsyncMock(return_value=None))
    monkeypatch.setattr(tg,"_tg_reserve_rate_slot",AsyncMock(return_value=True))
    a=real_session
    b=AgentSession(id="second-foreground",name="second",scope=a.scope,cwd=a.cwd,
        model=a.model,backend_type="antigravity",is_orchestrator=True,mcp_servers={})
    b._persist()
    try:
        for s in (a,b):
            await s._drain_persist()
            dest,lease=acp_tg_delivery.start(s.id,77,9 if s is a else 10)
            for _ in range(2):
                await send_and_finish(s,"FG_TRANSCRIPT")
                await s._await_log_futures()
                await acp_tg_delivery.pump(s.id,77,9 if s is a else 10,dest,lease,tg)
            acp_tg_delivery.release(dest,lease)
            await s._await_log_futures()
            rows=db.get_logs(s.id)
            native=[x for x in rows if x["type"] in {"text","thinking","tool","tool_result"}]
            assert [x["type"] for x in native]==["text","thinking","tool","tool_result","tool_result","tool","tool_result","text"]*2
            assert [x["content"] for x in native if x["type"]=="text"]==["before tool ","after tool"]*2
            results=[x for x in native if x["type"]=="tool_result"]
            assert "early output" in results[0]["content"] and "late output" in results[1]["content"]
            assert results[2]["tool_name"]=="mcp__orchestra__task_get" and results[2]["tool_is_error"]==1
            assert "resource preview" in results[2]["content"] and "+++" in results[2]["content"]
            assert s._last_text_output=="before tool after tool"
            assert len({x["event_id"] for x in native})==len(native)
        assert "early output" in str(bot.sent) and "late output" in str(bot.sent) and "task_get" in str(bot.sent)
        (EVIDENCE/"fake-tg-transcript.json").write_text(json.dumps([x[1] for x in bot.sent],ensure_ascii=False,indent=2))
        before=len(stand.trace());stand.egress.reset_mock()
        for _ in range(10):
            await antigravity_readiness(RuntimeReadinessContext(a.model))
            await system._refresh_antigravity_usage(force_refresh=True)
        assert len(stand.trace())==before;stand.egress.assert_not_awaited()
        methods=Counter(x["method"] for x in stand.trace())
        assert methods["spawn"]==methods["initialize"]==methods["authenticate"]==1
        assert methods["session/new"]==2 and methods["session/prompt"]==4
        (EVIDENCE/"ordered-transcript.json").write_text(json.dumps({"methods":dict(methods),"logs":db.get_logs(a.id)},ensure_ascii=False,indent=2))
    finally:await b.abort_unpublished()


@pytest.mark.asyncio
@pytest.mark.parametrize("decision",["allow","deny","cancel","timeout","two","question"])
async def test_native_decision_returns_rpc_not_prompt(stand,real_session,monkeypatch,decision):
    s=real_session
    if decision=="timeout":monkeypatch.setattr(native_requests,"TTL",.12)
    text="FG_QUESTION" if decision=="question" else "FG_PERMISSION_TWO" if decision=="two" else "FG_PERMISSION"
    await s.send(text,provenance=USER)
    rows=await pending(s,2 if decision=="two" else 1)
    assert rows[0]["kind"]==("question" if decision=="question" else "permission")
    if decision!="timeout":
        for row in rows:
            option=row["options"][1 if decision=="deny" else 0]["optionId"]
            native_requests.resolve(row["id"],owner_id=s.id,binding=row["binding"],option_id=option,cancel=decision=="cancel")
    await finish(s)
    replies=[x for x in stand.trace() if x["method"]=="native_reply"]
    assert len(replies)==len(rows)
    assert len({x["request_id"] for x in replies})==len(replies)
    assert sum(x["method"]=="session/prompt" for x in stand.trace())==1
    assert s._last_turn_ok and "continued after native response" in s._last_text_output


@pytest.mark.asyncio
async def test_foreign_option_binding_and_stale_profile_rejected(stand,real_session):
    s=real_session;await s.send("FG_PERMISSION",provenance=USER);row=(await pending(s))[0]
    with pytest.raises(PermissionError):native_requests.resolve(row["id"],owner_id="foreign",binding=row["binding"],option_id=row["options"][0]["optionId"])
    with pytest.raises(PermissionError):native_requests.resolve(row["id"],owner_id=s.id,binding="changed",option_id=row["options"][0]["optionId"])
    with pytest.raises(ValueError):native_requests.resolve(row["id"],owner_id=s.id,binding=row["binding"],option_id="not-offered")
    with db._conn() as c:c.execute("UPDATE acp_profile_epochs SET epoch='changed'")
    with pytest.raises(ValueError,match="Stale"):native_requests.resolve(row["id"],owner_id=s.id,binding=row["binding"],option_id=row["options"][0]["optionId"])
    await s.interrupt();await finish(s)
    assert sum(x["method"]=="session/prompt" for x in stand.trace())==1


@pytest.mark.asyncio
async def test_cancel_and_eof_retire_pending_native_requests(stand,real_session):
    s=real_session;await s.send("FG_PERMISSION",provenance=USER);row=(await pending(s))[0]
    await s.interrupt();await finish(s)
    assert sum(x["method"]=="native_reply" for x in stand.trace())==1
    assert not native_requests.pending_for(s.id)
    with pytest.raises(ValueError):native_requests.resolve(row["id"],owner_id=s.id,binding=row["binding"],option_id=row["options"][0]["optionId"])


@pytest.mark.asyncio
async def test_native_eof_invalidates_callback_without_replay(stand,real_session):
    s=real_session;await s.send("FG_NATIVE_EOF",provenance=USER);row=(await pending(s))[0]
    await finish(s)
    assert not s._last_turn_ok and not native_requests.pending_for(s.id)
    with pytest.raises(ValueError):native_requests.resolve(row["id"],owner_id=s.id,binding=row["binding"],cancel=True)
    assert sum(x["method"]=="spawn" for x in stand.trace())==1


@pytest.mark.asyncio
@pytest.mark.parametrize("tag",["BAD","UNKNOWN"])
async def test_malformed_and_unknown_native_requests_fail_closed(stand,real_session,tag):
    s=real_session;await send_and_finish(s,"FG_PERMISSION_"+tag)
    await s._await_log_futures()
    assert sum(x["method"]=="native_reply" for x in stand.trace())==1
    assert not native_requests.pending_for(s.id)
    assert sum(x["method"]=="session/prompt" for x in stand.trace())==1


@pytest.mark.asyncio
async def test_duplicate_rpc_id_has_one_pending_card_and_one_reply(stand,real_session):
    s=real_session;await s.send("FG_PERMISSION_DUPLICATE",provenance=USER);row=(await pending(s))[0]
    await asyncio.sleep(.03)
    assert len(native_requests.pending_for(s.id))==1
    native_requests.resolve(row["id"],owner_id=s.id,binding=row["binding"],cancel=True)
    await finish(s)
    assert sum(x["method"]=="native_reply" for x in stand.trace())==1


@pytest.mark.asyncio
async def test_resume_binding_survives_backend_recreation_but_not_epoch_reset(stand,real_session):
    s=real_session;await send_and_finish(s,"first")
    sid=s.session_id;await s._disconnect_backend()
    await send_and_finish(s,"second")
    assert s.session_id==sid
    assert sum(x["method"]=="session/resume" for x in stand.trace())==0 # same owner already holds native session
    count=len(stand.trace())
    with db._conn() as c:c.execute("UPDATE acp_profile_epochs SET epoch='new-operator-epoch'")
    await s._disconnect_backend();await send_and_finish(s,"stale epoch must refuse")
    assert not s._last_turn_ok and len(stand.trace())==count


@pytest.mark.asyncio
async def test_foreign_orchestra_session_cannot_resume_same_native_id(stand,real_session):
    s=real_session;await send_and_finish(s,"first")
    b=stand.backend(resume=s.session_id);b.app_session_id="another-owner"
    assert not end(await turn(b,"foreign resume")).metadata["ok"]
    assert sum(x["method"]=="session/prompt" for x in stand.trace())==1


@pytest.mark.asyncio
@pytest.mark.parametrize("effort,ok",[("high",True),("xhigh",False)])
async def test_effort_is_exact_offered_variant_with_no_nearest_fallback(stand,monkeypatch,effort,ok):
    monkeypatch.setenv("AGY_MOCK_MODE","effort-variants")
    b=stand.backend();b.effort=effort
    event=end(await turn(b,"exact effort"))
    assert event.metadata["ok"] is ok
    if ok:assert event.metadata["selected_model"]=="gemini-4-carbon-high"
    assert sum(x["method"]=="session/prompt" for x in stand.trace())==int(ok)


@pytest.mark.asyncio
async def test_v2_peer_is_not_silently_treated_as_v1(stand,monkeypatch):
    monkeypatch.setenv("AGY_MOCK_MODE","wire-v2")
    event=end(await turn(stand.backend(),"wrong wire"))
    assert not event.metadata["ok"]
    assert not any(x["method"] in {"authenticate","session/prompt"} for x in stand.trace())


@pytest.mark.asyncio
async def test_explicit_restart_resumes_bound_fixed_profile_without_history_replay(stand,real_session):
    from app.antigravity_acp import shutdown_profiles
    s=real_session;await send_and_finish(s,"first explicit turn")
    sid=s.session_id
    await s._disconnect_backend();await shutdown_profiles()
    await send_and_finish(s,"explicit user after app restart")
    assert s.session_id==sid and s._last_turn_ok
    assert sum(x["method"]=="session/resume" for x in stand.trace())==1
    assert sum(x["method"]=="session/new" for x in stand.trace())==1
    assert sum(x["method"]=="session/prompt" for x in stand.trace())==2


def test_tool_reducer_missing_or_null_fields_preserve_last_output_and_mark_nontext():
    from app.acp_tools import ToolReducer
    r=ToolReducer()
    unnamed=ToolReducer().apply({"toolCallId":"unnamed","kind":"execute","title":"Not a canonical name"})
    assert unnamed[0][2]["tool_name"]=="tool"
    for status in ("completed","failed"):
        first=ToolReducer().apply({"toolCallId":"terminal","name":"read_file","status":status,"rawOutput":"initial result"})
        assert [x[0] for x in first]==["tool_use","tool_result"]
        assert first[-1][2]["is_error"] is (status=="failed")
    initial=r.apply({"toolCallId":"x","name":"run_command","title":"Caption is not name","kind":"execute","status":"in_progress","rawInput":{"CommandLine":"echo x"},"rawOutput":{"value":"original"}})
    final=r.apply({"toolCallId":"x","status":"completed","rawOutput":None})
    assert final[0][0]=="tool_result" and "original" in final[0][1]
    assert final[0][2]["tool_name"]=="run_command"
    assert r.apply({"toolCallId":"x","status":"completed"})==[]
    late=r.apply({"toolCallId":"x","status":"completed","rawOutput":{"value":"changed"}})
    assert len(late)==1 and "changed" in late[0][1]
    unsupported=r.apply({"toolCallId":"y","status":"failed","content":[{"type":"content","content":{"type":"image","mimeType":"image/png","data":"not-retained"}}]})
    assert [x[0] for x in unsupported]==["tool_use","tool_result"]
    assert "unsupported" in unsupported[-1][1] and "not-retained" not in str(r.states)


def test_pending_request_from_a_dead_app_is_stale_without_rpc():
    db.init_db();native_requests.schema()
    from tests.test_message_delivery_receipts_380 import _session_record
    db.save_session(_session_record(session_id="synthetic-owner",name="synthetic-owner",scope="/synthetic"))
    with db._conn() as c:c.execute("INSERT INTO acp_native_requests VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",("orphan","synthetic-owner","native","profile","epoch","dead-transport","turn","1","binding","permission",json.dumps({"options":[],"title":"stale","kind":"permission"}),"pending",9999999999,None,1))
    assert native_requests.pending_for("synthetic-owner")==[]
    assert native_requests.get("orphan")["state"]=="stale"
    with pytest.raises(ValueError,match="Stale"):native_requests.resolve("orphan",owner_id="synthetic-owner",binding="binding",cancel=True)



def test_explicit_google_telegram_and_real_provider_negative_controls():
    import socket,subprocess
    for host in ("accounts.google.com","generativelanguage.googleapis.com","api.telegram.org"):
        with pytest.raises(PermissionError,match="external DNS denied"):socket.getaddrinfo(host,443)
    # Audit rejects before exec; neither a real binary nor its version/help is invoked.
    for executable in ("/blocked-real-provider/agy","/blocked-real-provider/antigravity"):
        with pytest.raises(PermissionError,match="only fake_agy"):
            subprocess.run([executable,"acp"],check=True)


@pytest.mark.asyncio
async def test_live_thought_segment_reconnect_keeps_stable_item_identity(stand,real_session):
    from app.live_broker import broker
    s=real_session;await s.send("FG_LIVE_THOUGHT",provenance=USER)
    projection=[]
    async with asyncio.timeout(3):
        while not projection:
            q=broker.subscribe(s.id)
            try:
                rows=[]
                while not q.empty():rows.append(q.get_nowait())
                projection=[x for x in rows if x.get("type")=="thinking_stream"]
            finally:broker.unsubscribe(s.id,q)
            if not projection:await asyncio.sleep(.01)
    item=projection[0]["item_id"]
    assert projection[0].get("replace") is True
    await s.interrupt();await finish(s)
    assert any(x["type"]=="thinking" and x["event_id"]==item for x in db.get_logs(s.id))
    again=broker.subscribe(s.id)
    try:assert not any(x.get("item_id")==item for x in list(again._queue))
    finally:broker.unsubscribe(s.id,again)


@pytest.mark.asyncio
async def test_reused_native_rpc_id_with_changed_payload_is_not_approved(stand,real_session):
    s=real_session;await s.send("FG_PERMISSION_MUTATED",provenance=USER);await finish(s)
    assert not s._last_turn_ok and not native_requests.pending_for(s.id)
    assert sum(x["method"]=="native_reply" for x in stand.trace())==0
    assert sum(x["method"]=="session/prompt" for x in stand.trace())==1
    assert sum(x["method"]=="spawn" for x in stand.trace())==1
