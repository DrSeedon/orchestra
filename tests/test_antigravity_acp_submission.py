"""Narrow R3 receipt boundary regressions over actual HTTP/SessionManager/stdio."""
import asyncio
from collections import Counter
from contextlib import asynccontextmanager
import json
from pathlib import Path
import uuid

import httpx
import pytest
import pytest_asyncio

from tests.test_antigravity_acp import stand, turn, end, USER, wait_prompt
from app.events import InjectedMessage
from tests.test_antigravity_acp_r2 import real_session

EVIDENCE = Path(__file__).resolve().parents[1] / ".orchestra/tasks/agy-acp-safe-20261116/submission"


@pytest_asyncio.fixture
async def http_stand(real_session, monkeypatch):
    from fastapi import FastAPI
    import uvicorn
    from app.manager import SessionManager
    from app.routes import sessions
    from app import deps
    manager = SessionManager(); s = real_session
    manager.sessions[s.id] = s
    monkeypatch.setattr(deps,"manager",manager)
    monkeypatch.setattr(sessions,"manager",manager)
    monkeypatch.setattr("app.auth.validate_session", lambda value:value=="submission-operator")
    @asynccontextmanager
    async def lifespan(app): yield
    app = FastAPI(lifespan=lifespan); app.include_router(sessions.router)
    server = uvicorn.Server(uvicorn.Config(app,host="127.0.0.1",port=18889,log_level="critical"))
    runner = asyncio.create_task(server.serve())
    try:
        async with asyncio.timeout(3):
            while not server.started: await asyncio.sleep(.01)
        async with httpx.AsyncClient(base_url="http://127.0.0.1:18889",trust_env=False,timeout=5,
            cookies={"session":"submission-operator"}) as client:
            yield s,client,manager
    finally:
        server.should_exit=True
        await asyncio.wait_for(runner,3)


async def settle(delivery_id,s):
    from app import message_deliveries
    async with asyncio.timeout(4):
        while True:
            row=message_deliveries._row(delivery_id)
            if row and row["state"] in {"SUBMITTED","FAILED_BEFORE_SUBMIT","DELIVERY_UNKNOWN"}: break
            await asyncio.sleep(.01)
        if s._backend and s._backend._task: await s._backend._task
        if s._listen_task: await s._listen_task
    return message_deliveries._row(delivery_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode",["missing-model","config-mismatch"])
async def test_http_pre_submit_refusal_is_not_a_submitted_receipt(stand,http_stand,monkeypatch,mode):
    s,client,_=http_stand
    if mode=="missing-model":
        # Keep registered route; the fake peer omits this model in its new-session metadata.
        monkeypatch.setenv("AGY_MOCK_MODE","only-argon")
    else: monkeypatch.setenv("AGY_MOCK_MODE",mode)
    delivery_id=str(uuid.uuid4())
    body={"scope":s.scope,"message":"must refuse before prompt","delivery_id":delivery_id}
    response=await client.post("/api/sessions/"+s.name+"/send",json=body)
    assert response.status_code in (200,202),response.text
    row=await settle(delivery_id,s)
    # On the old implementation this is SUBMITTED with zero session/prompt calls.
    assert Counter(r["method"] for r in stand.trace())["session/prompt"] == 0
    assert row["state"] == "FAILED_BEFORE_SUBMIT"
    status=await client.get("/api/message-deliveries/"+delivery_id)
    assert status.json()["error"]["outcome_unknown"] is False
    repeat=await client.post("/api/sessions/"+s.name+"/send",json=body)
    assert repeat.status_code in (200,202)
    again=await settle(delivery_id,s)
    assert again["state"] == "FAILED_BEFORE_SUBMIT"
    assert Counter(r["method"] for r in stand.trace())["session/prompt"] == 0
    sibling=stand.backend(model="gemini-4-argon-medium")
    assert end(await turn(sibling,"healthy sibling")).metadata["ok"]
    assert Counter(r["method"] for r in stand.trace())["spawn"] == 1


async def wait_receipt(delivery_id,states):
    from app import message_deliveries
    async with asyncio.timeout(4):
        while True:
            row=message_deliveries._row(delivery_id)
            if row and row["state"] in states:return row
            await asyncio.sleep(.01)


def payload(s,message):
    return {"scope":s.scope,"message":message,"delivery_id":str(uuid.uuid4())}


@pytest.mark.asyncio
async def test_successful_transport_submission_does_not_wait_for_turn_and_duplicates_once(stand,http_stand):
    s,client,_=http_stand
    body=payload(s,"HTTP_BLOCK"); url="/api/sessions/"+s.name+"/send"
    assert (await client.post(url,json=body)).status_code in (200,202)
    row=await wait_receipt(body["delivery_id"],{"SUBMITTED"})
    await wait_prompt(stand)
    assert not s._backend._task.done()  # still blocked inside inference, not send()
    assert (await client.post(url,json=body)).json()["delivery_state"]=="SUBMITTED"
    assert Counter(r["method"] for r in stand.trace())["session/prompt"]==1
    response=await client.post("/api/sessions/"+s.name+"/interrupt",json={"scope":s.scope})
    assert response.status_code==200
    await s._listen_task
    assert not s._last_turn_ok
    assert (await client.get("/api/message-deliveries/"+body["delivery_id"])).json()["delivery_state"]=="SUBMITTED"
    assert Counter(r["method"] for r in stand.trace())["session/prompt"]==1


@pytest.mark.asyncio
async def test_cancel_receipt_waiting_for_other_profile_turn_remains_known_not_submitted(stand,http_stand):
    s,client,_=http_stand
    other=stand.backend()
    await other.send(InjectedMessage("BLOCK",USER,"other"))
    await wait_prompt(stand)
    body=payload(s,"queued behind profile lock")
    assert (await client.post("/api/sessions/"+s.name+"/send",json=body)).status_code in (200,202)
    await wait_receipt(body["delivery_id"],{"PREPARING"})
    # HTTP interrupt must acquire the lifecycle lock while submit awaits the profile lock.
    response=await client.post("/api/sessions/"+s.name+"/interrupt",json={"scope":s.scope})
    assert response.status_code==200
    row=await settle(body["delivery_id"],s)
    assert row["state"]=="FAILED_BEFORE_SUBMIT"
    assert json.loads(row["error_json"])["outcome_unknown"] is False
    assert Counter(r["method"] for r in stand.trace())["session/prompt"]==1
    assert other.is_alive and not other._task.done()
    await other.interrupt(); [e async for e in other.events()]
    assert end(await turn(other,"after queued cancellation")).metadata["ok"]
    assert Counter(r["method"] for r in stand.trace())["spawn"]==1


@pytest.mark.asyncio
async def test_pre_send_egress_failure_is_a_known_failed_receipt(stand,http_stand):
    s,client,_=http_stand
    stand.egress.side_effect=RuntimeError("synthetic preflight denial")
    body=payload(s,"cannot start transport")
    assert (await client.post("/api/sessions/"+s.name+"/send",json=body)).status_code in (200,202)
    row=await settle(body["delivery_id"],s)
    assert row["state"]=="FAILED_BEFORE_SUBMIT"
    assert not stand.trace()


@pytest.mark.asyncio
async def test_post_write_rpc_refusal_is_sent_once_not_model_success(stand,http_stand):
    s,client,_=http_stand
    body=payload(s,"HTTP_RPC_MODEL")
    url="/api/sessions/"+s.name+"/send"
    assert (await client.post(url,json=body)).status_code in (200,202)
    row=await settle(body["delivery_id"],s)
    assert row["state"]=="SUBMITTED" and not s._last_turn_ok
    assert Counter(r["method"] for r in stand.trace())["session/prompt"]==1
    assert (await client.post(url,json=body)).json()["delivery_state"]=="SUBMITTED"
    assert Counter(r["method"] for r in stand.trace())["session/prompt"]==1
    assert s._backend.is_alive
    assert end(await turn(stand.backend(),"healthy sibling after RPC refusal")).metadata["ok"]
    assert Counter(r["method"] for r in stand.trace())["spawn"]==1


@pytest.mark.asyncio
async def test_lost_post_write_confirmation_is_unknown_and_duplicate_never_replays(stand,http_stand,monkeypatch):
    from app.antigravity_acp import AcpProfile
    original=AcpProfile._write
    async def lose_confirmation(owner,message,**kwargs):
        if message.get("method")!="session/prompt":return await original(owner,message,**kwargs)
        # Actual bytes go through real stdio; fault suppresses only local write proof.
        await original(owner,message,before_write=kwargs.get("before_write"),on_written=None)
        await wait_prompt(stand)
        raise ConnectionError("synthetic transport confirmation loss after write")
    monkeypatch.setattr(AcpProfile,"_write",lose_confirmation)
    s,client,_=http_stand; body=payload(s,"HTTP_BLOCK"); url="/api/sessions/"+s.name+"/send"
    assert (await client.post(url,json=body)).status_code in (200,202)
    row=await settle(body["delivery_id"],s)
    assert row["state"]=="DELIVERY_UNKNOWN"
    assert json.loads(row["error_json"])["outcome_unknown"] is True
    assert (await client.post(url,json=body)).json()["delivery_state"]=="DELIVERY_UNKNOWN"
    assert Counter(r["method"] for r in stand.trace())["session/prompt"]==1
    (EVIDENCE/"unknown-post-write.json").write_text(json.dumps({
        "receipt_state":row["state"],"error":json.loads(row["error_json"]),
        "methods":dict(Counter(r["method"] for r in stand.trace()))},indent=2))


@pytest.mark.asyncio
async def test_cancel_during_backpressured_write_is_unknown_and_bounded(stand,http_stand,monkeypatch):
    from app.antigravity_acp import AcpProfile
    original=AcpProfile._write
    blocked=asyncio.Event()
    async def backpressure(owner,message,**kwargs):
        if message.get("method")!="session/prompt":return await original(owner,message,**kwargs)
        drain=owner.process.stdin.drain
        async def hold_drain():
            blocked.set()
            await asyncio.Event().wait()
        owner.process.stdin.drain=hold_drain
        try:return await original(owner,message,**kwargs)
        finally:owner.process.stdin.drain=drain
    monkeypatch.setattr(AcpProfile,"_write",backpressure)
    s,client,_=http_stand;body=payload(s,"HTTP_BLOCK");url="/api/sessions/"+s.name+"/send"
    assert (await client.post(url,json=body)).status_code in (200,202)
    async with asyncio.timeout(3):await blocked.wait()
    await wait_receipt(body["delivery_id"],{"DISPATCHING"})
    # Cancel waits at most the ACP cancellation bound even though the write lock is held.
    response=await client.post("/api/sessions/"+s.name+"/interrupt",json={"scope":s.scope})
    assert response.status_code==200
    row=await settle(body["delivery_id"],s)
    assert row["state"]=="DELIVERY_UNKNOWN" and s._backend._owner.failure
    before=Counter(r["method"] for r in stand.trace())["session/prompt"]
    assert (await client.post(url,json=body)).json()["delivery_state"]=="DELIVERY_UNKNOWN"
    assert Counter(r["method"] for r in stand.trace())["session/prompt"]==before


@pytest.mark.asyncio
@pytest.mark.parametrize("refused",[False,True])
async def test_initial_receipt_uses_same_actual_transport_boundary(stand,http_stand,monkeypatch,refused):
    from app import initial_deliveries
    s,_,_=http_stand
    if refused:monkeypatch.setenv("AGY_MOCK_MODE","only-argon")
    delivery_id=str(uuid.uuid4())
    resource,status=await initial_deliveries.accept_initial_delivery(
        delivery_id=delivery_id,session_id=s.id,worker_name=s.name,scope=s.scope,
        sender="operator",message="initial synthetic user task",provenance=USER)
    assert status in (200,202)
    async with asyncio.timeout(4):
        await asyncio.gather(initial_deliveries._runner_tasks[delivery_id],return_exceptions=True)
        if s._listen_task:await s._listen_task
    receipt=initial_deliveries.get_initial_delivery(delivery_id,s.scope)
    assert receipt["delivery_state"]==("FAILED_BEFORE_SUBMIT" if refused else "SUBMITTED")
    assert Counter(r["method"] for r in stand.trace())["session/prompt"]==int(not refused)
