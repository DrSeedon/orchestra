"""R4 behavior regressions, real journal/HTTP/bridge and synthetic stdio only."""
import asyncio
import json
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import SendMessage
from app import db, acp_tg_delivery
from app.acp_tools import ToolReducer
from app.live_broker import LiveBroker, broker, coalesce
from tests.test_antigravity_acp import stand
from tests.test_antigravity_acp_r2 import real_session, send_and_finish
from tests.test_antigravity_acp_submission import http_stand
from tests.test_antigravity_foreground_delivery import FakeBot, fake_rate_admission
from tests.test_message_delivery_receipts_380 import _session_record


def session(tmp_path, sid):
    db.init_db()
    db.save_session(_session_record(session_id=sid, name=sid, scope=str(tmp_path)))
    return sid


def row(dest):
    with db._conn() as c:
        return dict(c.execute("SELECT * FROM acp_tg_outbox WHERE destination=? ORDER BY log_id,chunk", (dest,)).fetchone())


@pytest.mark.asyncio
async def test_failed_first_journal_write_does_not_poison_two_successors(stand, real_session, monkeypatch):
    from app import session as module
    s = real_session; original = module.add_log; calls = []
    def transient(*args, **kwargs):
        calls.append(args[3])
        if len(calls) == 1: raise RuntimeError("synthetic transient journal fault")
        return original(*args, **kwargs)
    monkeypatch.setattr(module, "add_log", transient)
    futures = []
    for text in ("first", "second", "third"):
        s._log("text", text); futures.append(s._acp_log_tail)
    results = await asyncio.gather(*futures, return_exceptions=True)
    assert isinstance(results[0], RuntimeError)
    assert all(isinstance(x, int) for x in results[1:])
    assert calls == ["first", "second", "third"]
    assert [x["content"] for x in db.get_logs(s.id)] == ["second", "third"]
    assert len(s._failed_log_writes) == 1


@pytest.mark.asyncio
async def test_confirmed_429_remains_pending_and_resumes_after_backoff(monkeypatch, tmp_path):
    from app import tg_bridge as tg
    sid = session(tmp_path, "r4-flood"); clock = [1000.0]
    # Patch only this module's wall clock; the shared barrier uses loop monotonic time.
    monkeypatch.setattr(acp_tg_delivery, "time", SimpleNamespace(time=lambda:clock[0]))
    bot = FakeBot(); calls = []
    async def send(chat, text, **kwargs):
        calls.append(text)
        if len(calls) == 1:
            raise TelegramRetryAfter(method=SendMessage(chat_id=chat,text=text), message="synthetic 429", retry_after=3)
        return await FakeBot.send_message(bot, chat, text, **kwargs)
    monkeypatch.setattr(bot, "send_message", send); monkeypatch.setattr(tg,"bot",bot)
    before = asyncio.get_running_loop().time()
    monkeypatch.setattr(tg, "_tg_flood_until", {})
    dest, lease = acp_tg_delivery.start(sid,77,9)
    db.add_log(sid,datetime.now(timezone.utc),"text","rate-limited body")
    assert await acp_tg_delivery.pump(sid,77,9,dest,lease,tg) == 0
    assert row(dest)["state"] == "pending" and row(dest)["next_attempt_at"] == 1003.0
    assert tg._tg_flood_until[77] >= before + 3
    assert await acp_tg_delivery.pump(sid,77,9,dest,lease,tg) == 0 and len(calls) == 1
    # Restart must retain a confirmed pre-delivery retry, not convert it to unknown.
    acp_tg_delivery.release(dest,lease); dest,lease = acp_tg_delivery.start(sid,77,9)
    clock[0] = 1004.0
    assert await acp_tg_delivery.pump(sid,77,9,dest,lease,tg) == 1
    assert row(dest)["state"] == "sent" and len(bot.sent) == 1 and len(calls) == 2
    assert await acp_tg_delivery.pump(sid,77,9,dest,lease,tg) == 0
    acp_tg_delivery.release(dest,lease)


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [TimeoutError, ConnectionResetError])
async def test_transport_ambiguity_is_unknown_never_replayed(monkeypatch,tmp_path,error):
    from app import tg_bridge as tg
    sid = session(tmp_path, "r4-ambiguous"); calls=[]
    async def send(*args,**kwargs):
        calls.append(args); raise error("synthetic mid-flight ambiguity")
    monkeypatch.setattr(tg,"bot",SimpleNamespace(send_message=send))
    dest,lease=acp_tg_delivery.start(sid,77,9)
    db.add_log(sid,datetime.now(timezone.utc),"text","uncertain")
    with pytest.raises(error): await acp_tg_delivery.pump(sid,77,9,dest,lease,tg)
    assert row(dest)["state"] == "unknown"
    with pytest.raises(acp_tg_delivery.UnknownSend): await acp_tg_delivery.pump(sid,77,9,dest,lease,tg)
    assert len(calls)==1
    acp_tg_delivery.release(dest,lease)


@pytest.mark.asyncio
async def test_empty_attach_forward_scan_delivers_all_120_in_exact_order(monkeypatch,tmp_path):
    from app import tg_bridge as tg
    sid=session(tmp_path,"r4-forward");bot=FakeBot();monkeypatch.setattr(tg,"bot",bot)
    dest,lease=acp_tg_delivery.start(sid,77,9)
    for i in range(1,121): db.add_log(sid,datetime.now(timezone.utc),"text",f"message {i}")
    # Legacy tail caller must still see only the last 100, unchanged.
    assert db.get_logs(sid,after_id=0,limit=100)[0]["content"]=="message 21"
    assert await acp_tg_delivery.pump(sid,77,9,dest,lease,tg)==100
    assert await acp_tg_delivery.pump(sid,77,9,dest,lease,tg)==20
    assert [x[1] for x in bot.sent]==[f"message {i}" for i in range(1,121)]
    assert await acp_tg_delivery.pump(sid,77,9,dest,lease,tg)==0
    acp_tg_delivery.release(dest,lease)


@pytest.mark.asyncio
async def test_late_input_real_stdio_session_journal_and_tg(stand,real_session,monkeypatch):
    from app import tg_bridge as tg
    s=real_session;bot=FakeBot();monkeypatch.setattr(tg,"bot",bot)
    dest,lease=acp_tg_delivery.start(s.id,77,9)
    q=broker.subscribe(s.id)
    try:
        await send_and_finish(s,"FG_LATE_INPUT")
        logs=db.get_logs(s.id);tools=[x for x in logs if x["type"] in {"tool","tool_update","tool_result"}]
        assert [x["type"] for x in tools]==["tool","tool_update","tool_result"]
        assert len({x["tool_use_id"] for x in tools})==1
        assert tools[1]["raw_input"]==tools[2]["raw_input"]=={"CommandLine":"echo late synthetic"}
        assert tools[2]["tool_name"]=="run_command" and tools[2]["content"]=="AB"
        live=[]
        while not q.empty(): live.append(q.get_nowait())
        outputs=[x for x in live if isinstance(x,dict) and x.get("type")=="tool_stream"]
        assert [x["content"] for x in outputs][-2:]==["A","AB"]
        assert all(x["replace"] for x in outputs)
        evidence=Path(__file__).resolve().parents[1]/".orchestra/tasks/agy-acp-safe-20261117/r2/late-input-transcript.json"
        evidence.parent.mkdir(parents=True,exist_ok=True)
        evidence.write_text(json.dumps({"logs":tools,"live":outputs},ensure_ascii=False,indent=2))
        await acp_tg_delivery.pump(s.id,77,9,dest,lease,tg)
        texts=[x[1] for x in bot.sent]
        assert sum("Аргументы:" in x for x in texts)==1
        assert sum("echo late synthetic" in x for x in texts)==1
        assert sum("Результат:" in x for x in texts)==1
        assert sum(x["method"]=="session/prompt" for x in stand.trace())==1
    finally:
        broker.unsubscribe(s.id,q);acp_tg_delivery.release(dest,lease)


def test_tool_reducer_late_mcp_arguments_and_terminal_metadata():
    reducer=ToolReducer()
    start=reducer.apply({"toolCallId":"t","name":"call_mcp_tool","rawInput":{}})
    patch={"toolCallId":"t","rawInput":{"ServerName":"orchestra","ToolName":"task_get","Arguments":{"id":"synthetic"}}}
    update=reducer.apply(patch)
    assert [x[0] for x in update].count("tool_update")==1
    assert update[0][2]["tool_name"]=="mcp__orchestra__task_get"
    assert update[0][2]["raw_input"]=={"id":"synthetic"}
    assert reducer.apply(patch)==[]
    final=reducer.apply({"toolCallId":"t","status":"completed"})[-1]
    assert final[0]=="tool_result" and final[2]["raw_input"]=={"id":"synthetic"}
    assert start[0][0]=="tool_use"


def test_cumulative_tool_snapshots_live_and_reconnect_are_not_deltas():
    reducer=ToolReducer();b=LiveBroker();q=b.subscribe("s")
    for output in ("A","AB","replacement"):
        for kind,content,meta in reducer.apply({"toolCallId":"t","name":"run_command","status":"in_progress","rawOutput":output}):
            if kind=="tool_stream": b.publish("s",{"type":kind,"content":content,**meta})
    frames=coalesce([q.get_nowait() for _ in range(q.qsize())])
    assert [x["content"] for x in frames]==["A","AB","replacement"]
    replay=b.subscribe("s").get_nowait()
    assert replay["content"]=="replacement" and replay["replace"] is True
    # Legacy deltas retain their old append contract.
    old=LiveBroker()
    for value in ("A","B"):old.publish("old",{"type":"tool_stream","tool_use_id":"x","content":value})
    assert old.subscribe("old").get_nowait()["content"]=="AB"


@pytest.mark.asyncio
async def test_real_sse_late_final_a_preserves_identity_of_live_b(stand,http_stand):
    s,client,_=http_stand
    async with client.stream("GET","/api/sessions/"+s.name+"/stream",params={"scope":s.scope}) as response:
        iterator=response.aiter_lines()
        async with asyncio.timeout(3):
            while True:
                line=await anext(iterator)
                if line.startswith("data: ") and json.loads(line[6:]).get("type")=="__session":break
        broker.publish(s.id,{"type":"stream","content":"B is streaming","item_id":"acp:B"})
        db.add_log(s.id,datetime.now(timezone.utc),"text","A final",event_id="acp:A")
        frames=[]
        async with asyncio.timeout(3):
            while True:
                line=await anext(iterator)
                if not line.startswith("data: "):continue
                frame=json.loads(line[6:]);frames.append(frame)
                if frame.get("type")=="text":break
    assert frames[0]["type"]=="stream" and frames[0]["item_id"]=="acp:B"
    assert frames[-1]["item_id"]==frames[-1]["event_id"]=="acp:A"
    replay=broker.subscribe(s.id)
    try:
        current=replay.get_nowait()
        assert current["item_id"]=="acp:B" and current["replace"] is True
        assert current["content"]=="B is streaming"
    finally:broker.unsubscribe(s.id,replay);broker.clear_accum(s.id)


def test_additive_tool_metadata_upgrade_preserves_old_journal_and_sync(tmp_path):
    sid=session(tmp_path,"r4-metadata")
    db.add_log(sid,datetime.now(timezone.utc),"text","legacy row")
    with db._conn() as c: c.execute("ALTER TABLE logs DROP COLUMN tool_raw_input_json")
    db.init_db()  # Upgrade the prior schema without changing immutable rows.
    db.add_log(sid,datetime.now(timezone.utc),"tool_result","result",tool_use_id="t",
               tool_name="run_command",tool_raw_input={"CommandLine":"echo synthetic"})
    rows=db.get_logs_forward(sid)
    assert rows[0]["content"]=="legacy row" and "raw_input" not in rows[0]
    assert rows[1]["raw_input"]=={"CommandLine":"echo synthetic"}
    assert db.get_logs_sync()["logs"][-1]["raw_input"]==rows[1]["raw_input"]
