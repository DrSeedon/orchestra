"""Real native UI/TG bridge formatters with synthetic operator and fake Bot API."""
import asyncio
import json
from datetime import datetime,timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from app import db,native_requests,acp_tg_delivery
from app.events import MessageProvenance
from tests.test_antigravity_acp import stand,USER
from tests.test_antigravity_acp_r2 import real_session
from tests.test_antigravity_foreground import pending,finish


@pytest.fixture(autouse=True)
def fake_rate_admission(monkeypatch):
    from app import tg_bridge as tg
    monkeypatch.setattr(tg,"_tg_delivery_state_for",AsyncMock(return_value=None))
    monkeypatch.setattr(tg,"_tg_reserve_rate_slot",AsyncMock(return_value=True))


class FakeBot:
    def __init__(self,ambiguous=False):self.sent=[];self.ambiguous=ambiguous
    async def send_message(self,chat,text,**kwargs):
        self.sent.append((chat,text,kwargs))
        if self.ambiguous:raise TimeoutError("synthetic accepted-before-local-ACK")
        return SimpleNamespace(message_id=len(self.sent))
    async def get_chat_member(self,chat,user):return SimpleNamespace(status="creator" if user==123 else "member")


@pytest.mark.asyncio
async def test_real_tg_formatter_cursor_restart_and_first_attach_skips_old_history(monkeypatch,tmp_path):
    from app import tg_bridge as tg
    db.init_db()
    from tests.test_message_delivery_receipts_380 import _session_record
    db.save_session(_session_record(session_id="tg-fg",name="tg-fg",scope=str(tmp_path)))
    bot=FakeBot();monkeypatch.setattr(tg,"bot",bot)
    db.add_log("tg-fg",datetime.now(timezone.utc),"text","old history")
    dest,lease=acp_tg_delivery.start("tg-fg",77,9)
    assert await acp_tg_delivery.pump("tg-fg",77,9,dest,lease,tg)==0
    db.add_log("tg-fg",datetime.now(timezone.utc),"tool",'title: {"url":"https://synthetic.invalid/"}',tool_name="mcp__orchestra__task_get",tool_use_id="t1")
    db.add_log("tg-fg",datetime.now(timezone.utc),"tool_result","actual result",tool_name="mcp__orchestra__task_get",tool_use_id="t1")
    await acp_tg_delivery.pump("tg-fg",77,9,dest,lease,tg)
    assert len(bot.sent)==1 and "task_get" in bot.sent[0][1]
    assert "actual result" not in str(bot.sent)
    assert "old history" not in str(bot.sent)
    acp_tg_delivery.release(dest,lease)
    db.add_log("tg-fg",datetime.now(timezone.utc),"text","unsent tail after bridge restart")
    dest,lease=acp_tg_delivery.start("tg-fg",77,9)
    await acp_tg_delivery.pump("tg-fg",77,9,dest,lease,tg)
    assert len(bot.sent)==2 and "unsent tail" in bot.sent[-1][1]
    acp_tg_delivery.release(dest,lease)
    (tmp_path/"tg-delivered.json").write_text(json.dumps([x[1] for x in bot.sent]))


@pytest.mark.asyncio
async def test_ambiguous_tg_send_is_durable_unknown_and_not_replayed(monkeypatch,tmp_path):
    from app import tg_bridge as tg
    from tests.test_message_delivery_receipts_380 import _session_record
    db.init_db();db.save_session(_session_record(session_id="tg-unknown",name="tg-unknown",scope=str(tmp_path)))
    bot=FakeBot(ambiguous=True);monkeypatch.setattr(tg,"bot",bot)
    dest,lease=acp_tg_delivery.start("tg-unknown",77,9)
    db.add_log("tg-unknown",datetime.now(timezone.utc),"text","ambiguous output")
    with pytest.raises(TimeoutError):await acp_tg_delivery.pump("tg-unknown",77,9,dest,lease,tg)
    acp_tg_delivery.release(dest,lease)
    dest,lease=acp_tg_delivery.start("tg-unknown",77,9)
    with pytest.raises(acp_tg_delivery.UnknownSend):await acp_tg_delivery.pump("tg-unknown",77,9,dest,lease,tg)
    assert len(bot.sent)==1
    with db._conn() as c:assert c.execute("SELECT state FROM acp_tg_outbox WHERE destination=?",(dest,)).fetchone()[0]=="unknown"
    acp_tg_delivery.release(dest,lease)


@pytest.mark.asyncio
async def test_native_http_owner_csrf_option_and_idempotent_decision(stand,real_session,monkeypatch):
    monkeypatch.setenv("ANTIGRAVITY_AUTO_APPROVE","0")
    from app.routes import native_requests as route
    from app.auth import create_session,create_csrf_token
    monkeypatch.setenv("DASHBOARD_USER","synthetic-owner");monkeypatch.setenv("DASHBOARD_PASSWORD","synthetic-test-only-password")
    app=FastAPI();app.include_router(route.router)
    s=real_session;await s.send("FG_PERMISSION",provenance=USER);row=(await pending(s))[0]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://127.0.0.1",trust_env=False) as client:
        url="/api/native-requests/"+row["id"]+"/respond"
        body={"owner_id":s.id,"binding":row["binding"],"option_id":row["options"][0]["optionId"]}
        assert (await client.post(url,json=body)).status_code==403
        client.cookies.set("session",create_session("synthetic-owner"))
        caps=await client.get("/api/native-requests/capabilities")
        assert caps.status_code==200 and caps.json()["wire_version"]==1 and caps.json()["mid_turn_injection"] is True
        assert (await client.post(url,json=body)).status_code==403
        headers={"X-CSRF-Token":create_csrf_token("synthetic-owner")}
        assert (await client.post(url,json={**body,"owner_id":"foreign"},headers=headers)).status_code==403
        assert (await client.post(url,json={**body,"option_id":"unoffered"},headers=headers)).status_code==409
        assert (await client.post(url,json=body,headers=headers)).status_code==200
        await finish(s)
        assert (await client.post(url,json=body,headers=headers)).status_code==200
    assert sum(x["method"]=="native_reply" for x in stand.trace())==1


@pytest.mark.asyncio
async def test_real_tg_native_callback_rejects_foreign_user_and_topic(stand,real_session,monkeypatch):
    from app import tg_bridge as tg
    s=real_session;await s.send("FG_QUESTION",provenance=USER);row=(await pending(s))[0]
    bot=FakeBot();monkeypatch.setattr(tg,"bot",bot);monkeypatch.setattr(tg,"config",{"group_id":77,"topics":{s.name:9}})
    query=SimpleNamespace(data="acpn:"+row["id"]+":0",message=SimpleNamespace(chat=SimpleNamespace(id=77),message_thread_id=9),from_user=SimpleNamespace(id=999),answer=AsyncMock())
    assert "error" in await tg.native_request_callback(query)
    query.from_user.id=123;query.message.message_thread_id=10
    assert "error" in await tg.native_request_callback(query)
    query.message.message_thread_id=9
    assert (await tg.native_request_callback(query))["state"]=="responding"
    await finish(s)
    assert sum(x["method"]=="native_reply" for x in stand.trace())==1
    assert sum(x["method"]=="session/prompt" for x in stand.trace())==1


@pytest.mark.asyncio
async def test_chunked_tg_unknown_tail_does_not_resend_successful_prefix(monkeypatch,tmp_path):
    from app import tg_bridge as tg
    from tests.test_message_delivery_receipts_380 import _session_record
    db.init_db();db.save_session(_session_record(session_id="tg-chunks",name="tg-chunks",scope=str(tmp_path)))
    bot=FakeBot();original=bot.send_message
    async def ambiguous_second(*args,**kwargs):
        if len(bot.sent)==1:
            bot.ambiguous=True
        return await original(*args,**kwargs)
    monkeypatch.setattr(bot,"send_message",ambiguous_second);monkeypatch.setattr(tg,"bot",bot)
    dest,lease=acp_tg_delivery.start("tg-chunks",77,9)
    db.add_log("tg-chunks",datetime.now(timezone.utc),"text","long visible text "*900)
    with pytest.raises(TimeoutError):await acp_tg_delivery.pump("tg-chunks",77,9,dest,lease,tg)
    assert len(bot.sent)==2
    acp_tg_delivery.release(dest,lease);dest,lease=acp_tg_delivery.start("tg-chunks",77,9)
    with pytest.raises(acp_tg_delivery.UnknownSend):await acp_tg_delivery.pump("tg-chunks",77,9,dest,lease,tg)
    assert len(bot.sent)==2
    with db._conn() as c:assert [r[0] for r in c.execute("SELECT state FROM acp_tg_outbox WHERE destination=? ORDER BY chunk",(dest,))]==["sent","unknown"]
    acp_tg_delivery.release(dest,lease)
