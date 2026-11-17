"""A1–A12/S2 regression boundaries. Run through run_antigravity_offline.sh."""
import array
import asyncio
from collections import Counter
import importlib.util
import json
import os
from pathlib import Path
import socket
import struct
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app import db, antigravity_acp as acp, backend_antigravity as agy
from app.events import MessageProvenance
from tests.test_antigravity_acp import stand, turn, end, USER
from tests.test_antigravity_acp_r2 import real_session, send_and_finish
from tests.test_antigravity_live_preflight import child
from tests.test_message_delivery_receipts_380 import _session_record

ROOT = Path(__file__).resolve().parents[1]


def own_job(s, *, kind="run", owner=None, status="triggering"):
    job_id = "bg-audit"
    db.bg_save_job(dict(id=job_id,type=kind,config=json.dumps({"_creator_session_id":owner or s.id}),
        message="done",target_session_id=s.id,target_name=s.name,target_scope=s.scope,
        created_by_name=s.name,status=status,expires_at="2099-01-01",trigger_at=None,
        created_at="2026-11-17",last_output="synthetic"))
    return MessageProvenance("background_task",(job_id,),"completed",job_id)


@pytest.mark.asyncio
async def test_owned_run_completion_reaches_actual_parent_transport(stand,real_session):
    s = real_session
    await send_and_finish(s,"first")
    pid = s._backend._owner.process.pid
    await s.send("own task complete",provenance=own_job(s))
    await asyncio.wait_for(s._listen_task,4)
    assert s._last_turn_ok and s._backend._owner.process.pid == pid
    assert Counter(r["method"] for r in stand.trace())["session/prompt"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,owner,status",[
    ("cron",None,"triggering"),("cron_command",None,"triggering"),("timer",None,"triggering"),
    ("command",None,"triggering"),("run","foreign","triggering"),("run",None,"active")])
async def test_bg_foreign_and_scheduled_remain_denied(stand,real_session,kind,owner,status):
    s = real_session
    with pytest.raises(ValueError,match="interactive_only"):
        acp.ensure_interactive_input(s.model,own_job(s,kind=kind,owner=owner,status=status),target_session=s)
    assert not stand.trace()


@pytest.mark.asyncio
async def test_live_peer_direct_only_and_manual_compact_not_extended(stand,real_session):
    s = real_session
    peer = _session_record(session_id="peer",name="peer",scope=s.scope)
    peer.update(role="orchestrator",is_orchestrator=True,parent_name="",parent_id="")
    db.save_session(peer)
    provenance = MessageProvenance("agent",("peer",),"direct_message")
    await s.send("direct peer message",provenance=provenance)
    await asyncio.wait_for(s._listen_task,4)
    assert s._last_turn_ok
    with pytest.raises(ValueError):
        acp.ensure_interactive_input(s.model,provenance,target_session=s,allow_child_agent=False)
    peer["status"]="archived";db.save_session(peer)
    with pytest.raises(ValueError):acp.ensure_interactive_input(s.model,provenance,target_session=s)


@pytest.mark.asyncio
@pytest.mark.parametrize("subtype",["cron","cron_command","timer","dreaming","scheduler",
    "limit_wake","rate_limit_retry","server_error_retry","system","platform","unknown"])
async def test_peer_or_child_cannot_launder_blocked_subtype(stand,real_session,subtype):
    s = real_session;child(s)
    for origin in ("agent","background_task","user"):
        with pytest.raises(ValueError):
            acp.ensure_interactive_input(s.model,MessageProvenance(origin,("stand-worker",),subtype),target_session=s)


@pytest.mark.asyncio
@pytest.mark.parametrize("message",["RPC_AUTH","RPC_QUOTA","RPC_MODEL","RPC_INTERNAL","ERROR"])
async def test_rpc_refusal_is_local_and_sibling_runs_same_daemon(stand,message):
    a,b=stand.backend(),stand.backend()
    assert not end(await turn(a,message)).metadata["ok"]
    pid=a._owner.process.pid
    assert not a._owner.failure
    assert end(await turn(b,"healthy sibling")).metadata["ok"]
    assert b._owner.process.pid==pid
    assert Counter(r["method"] for r in stand.trace())["spawn"]==1


@pytest.mark.asyncio
async def test_oversized_first_prompt_does_not_lose_instructions_or_kill_sibling(stand):
    a,b=stand.backend(role="IMPORTANT ROLE"),stand.backend()
    assert not end(await turn(a,"x"*(1024*1024))).metadata["ok"]
    assert not a._instructions_sent and not a._owner.failure
    assert sum(r["method"]=="session/prompt" for r in stand.trace())==0
    assert end(await turn(b,"healthy")).metadata["ok"]
    assert end(await turn(a,"small")).metadata["ok"] and a._instructions_sent
    payload=[r for r in stand.trace() if r["method"]=="prompt_start"][-1]
    assert "IMPORTANT ROLE" in json.dumps(payload)


@pytest.mark.asyncio
async def test_eof_only_recreates_on_next_explicit_turn_never_replays(stand):
    a=stand.backend()
    assert not end(await turn(a,"DIE")).metadata["ok"]
    pid=a._owner.process.pid
    trace_len=len(stand.trace())
    await asyncio.sleep(.05)
    assert len(stand.trace())==trace_len and a._owner.failure
    # Explicit caller creates a new front, with resume/new semantics of its session.
    b=stand.backend()
    assert end(await turn(b,"new explicit turn")).metadata["ok"]
    assert b._owner.process.pid!=pid
    counts=Counter(r["method"] for r in stand.trace())
    assert counts["spawn"]==2 and counts["session/prompt"]==2


@pytest.mark.asyncio
async def test_bounded_native_response_cache_replays_exact_retry(stand):
    b=stand.backend()
    assert end(await turn(b,"AUDIT_DUP_PERMISSION")).metadata["ok"]
    replies=[r for r in stand.trace() if r["method"]=="native_reply"]
    assert len(replies)==2 and replies[0]["result"]==replies[1]["result"]
    owner=b._owner
    for i in range(4100):
        key=json.dumps("finished-"+str(i))
        owner._client_request_ids[key]="digest"
        owner._client_responses[key]={"result":{}}
        owner._prune_client_requests()
    assert len(owner._client_request_ids)<=512 and len(owner._client_responses)<=512
    assert end(await turn(b,"next turn")).metadata["ok"]


@pytest.mark.asyncio
async def test_retarget_is_acknowledged_without_prompt_and_keeps_session(stand):
    b=stand.backend()
    await turn(b,"first")
    sid,pid=b.session_id,b._owner.process.pid
    await b.retarget_model("antigravity/gemini-4-argon-medium")
    assert b.session_id==sid and b.model=="gemini-4-argon-medium"
    assert b._owner.model_states[sid]["current"]=="gemini-4-argon-medium"
    assert end(await turn(b,"second")).metadata["ok"] and b._owner.process.pid==pid


@pytest.mark.asyncio
async def test_disconnect_releases_only_owned_session_then_last_front(stand,monkeypatch):
    monkeypatch.setenv("AGY_MOCK_MODE","close-support")
    a,b=stand.backend(),stand.backend()
    await turn(a,"a");await turn(b,"b");owner=a._owner;sid=a.session_id
    await a.release()
    assert sid not in owner.sessions and sid not in owner.model_states and sid not in owner.session_locks
    assert end(await turn(b,"still healthy")).metadata["ok"]
    await b.release()
    assert not owner.sessions and owner.process.returncode is not None
    assert Counter(r["method"] for r in stand.trace())["session/close"]==2


@pytest.mark.asyncio
async def test_tokens_reported_separately_from_context_and_unknown_never_free(stand):
    b=stand.backend()
    unknown=end(await turn(b,"ordinary"))
    assert unknown.usage.aggregate.accuracy=="unknown" and unknown.metadata["cost_unaccounted"]
    measured=end(await turn(b,"AUDIT_TOKENS"))
    assert measured.usage.aggregate.accuracy=="reported"
    assert measured.usage.aggregate.input_tokens==100 and measured.usage.aggregate.output_tokens==20
    assert measured.usage.aggregate.cache_read_tokens==50
    assert measured.usage.current.tokens==200
    assert measured.metadata["cost_usd"]>0 and measured.metadata["cost_kind"]=="api_equivalent"


def test_token_single_source_atomic_application_writes_and_private_legacy_backup(tmp_path):
    from app.antigravity_auth import prepare_acp_token_store,atomic_private_write,TOKEN_RELATIVE_PATH
    home=tmp_path/"synthetic";canonical=home/".gemini/antigravity-acp/antigravity-oauth-token"
    canonical.parent.mkdir(parents=True);canonical.write_bytes(b"synthetic-new")
    legacy=home/TOKEN_RELATIVE_PATH;legacy.parent.mkdir();legacy.write_bytes(b"synthetic-old")
    prepare_acp_token_store(home)
    assert legacy.is_symlink() and legacy.resolve()==canonical.resolve()
    assert legacy.with_name(legacy.name+".pre-acp-link").read_bytes()==b"synthetic-old"
    atomic_private_write(legacy,b"synthetic-refreshed")
    assert legacy.is_symlink() and canonical.read_bytes()==b"synthetic-refreshed"
    assert canonical.stat().st_mode & 0o777==0o600
    prepare_acp_token_store(home)


@pytest.mark.parametrize("short,weekly",[(100,10),(96,10),(10,100),(10,96)])
def test_both_fresh_quota_windows_gate_independently(short,weekly):
    from datetime import datetime,timezone
    from app import quota_gate
    from app.routes.system import _provider_usage_snapshot
    now=time.time();reset=datetime.fromtimestamp(now+1800,timezone.utc).isoformat()
    providers=_provider_usage_snapshot(None,None,None,{"gemini-weekly":{
        "remaining_fraction":1-weekly/100,"reset_time":reset}},{"gemini-5h":{
        "remaining_fraction":1-short/100,"reset_time":reset}})
    decision=quota_gate.evaluate_worker_admission("antigravity/gemini-4-hydrogen-high",providers,
        {"antigravity_gemini":now},now=now,_include_alternatives=False)
    assert decision.state=="blocked" and decision.utilization==max(short,weekly)
    stale=quota_gate.evaluate_worker_admission("antigravity/gemini-4-hydrogen-high",providers,
        {"antigravity_gemini":now-99999},now=now,_include_alternatives=False)
    assert stale.state=="unknown"


@pytest.mark.asyncio
async def test_automatic_compaction_is_policy_skip_not_fake_start(stand,real_session):
    s=real_session;logs=[]
    original=s._log
    s._log=lambda *a,**k:logs.append(a)
    s._turns.schedule_context_compaction(99)
    await s._auto_compact(delay_seconds=0)
    s._log=original
    assert logs and all("disabled by runtime policy" in row[1] for row in logs)
    assert not stand.trace()


def test_provider_overlay_is_canonical_and_other_runtimes_unchanged():
    from app.pipeline import provider_prompt_overlay
    assert provider_prompt_overlay("codex")==""
    text=provider_prompt_overlay("antigravity")
    assert "bg_create" in text and "cron" in text and "ручная" in text


def test_new_models_manual_only_aliases_and_prices():
    from app import models,backend_codex
    assert models.resolve_model("sol")=="gpt-6.1-sol"
    for alias,mid,window,price in [("sol62","gpt-6.2-sol",500000,2.0),("astra62","gpt-6.2-astra",272000,8.0)]:
        assert models.resolve_model(alias)==mid
        assert models.get_model_spec(mid).context_length==window
        assert mid in models.MANUAL_ONLY_MODEL_IDS
        assert backend_codex.CODEX_CONTEXT_LIMITS[mid]==window
        assert backend_codex.CODEX_TOKEN_PRICES[mid]["input"]==price
    assert models.resolve_model("agy-flash")=="antigravity/gemini-3.8-flash-medium"
    assert models.get_model_spec("antigravity/gemini-pro-orchestrator-g1-pro").context_length==1000000


def ipc_module():
    spec=importlib.util.spec_from_file_location("isolated_ipc",ROOT/"deploy/bin/orchestra_agy_ipc.py")
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


@pytest.mark.parametrize("body", [b"INVALID_JSON",b"[]",b"{}",b"{"])
def test_ipc_received_fd_error_has_zero_fd_delta(body):
    ipc=ipc_module();left,right=socket.socketpair()
    pipes=[os.pipe() for _ in range(3)];fds=[pair[0] for pair in pipes]
    before=len(os.listdir("/proc/self/fd"))
    try:
        rights=array.array("i",fds)
        left.sendmsg([struct.pack("!I",len(body))],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,rights)])
        left.sendall(body)
        if body==b"{}":
            req,received=ipc._recv_request_with_fds(right)
            for fd in received:os.close(fd)
        else:
            with pytest.raises((ValueError,UnicodeError)):ipc._recv_request_with_fds(right)
        assert len(os.listdir("/proc/self/fd"))==before
    finally:
        left.close();right.close()
        for pair in pipes:
            for fd in pair:os.close(fd)


def test_ipc_request_timeout_is_bounded_and_closes_partial_rights():
    ipc=ipc_module();ipc.IPC_REQUEST_TIMEOUT=.02
    left,right=socket.socketpair()
    try:
        with pytest.raises(TimeoutError):ipc._recv_request_with_fds(right)
        assert right.gettimeout() is None
    finally:left.close();right.close()


def test_systemd_memory_budgets_are_versioned():
    for name in ("spawner","tool-exec"):
        text=(ROOT/f"deploy/systemd/orchestra-agy-{name}.service").read_text()
        assert "MemoryHigh=6G" in text and "MemoryMax=8G" in text


def test_ipc_handler_exec_receives_safety_env_and_excludes_secrets(tmp_path,monkeypatch):
    ipc=ipc_module()
    marker=tmp_path/"marker";marker.write_text(json.dumps({"agy_gid":os.getgid()}))
    monkeypatch.setattr(ipc,"KILLSWITCH_READY_PATH",marker)
    gemini=tmp_path/".gemini";gemini.mkdir()
    left,right=socket.socketpair()
    pipes=[os.pipe() for _ in range(3)]
    captured={}
    class Process:
        pid=999999999
        def wait(self):return 0
    def popen(argv,**kwargs):
        captured.update(kwargs)
        return Process()
    monkeypatch.setattr(ipc.subprocess,"Popen",popen)
    monkeypatch.setattr(ipc.threading,"Thread",lambda **kwargs:SimpleNamespace(start=lambda:None))
    env={"HOME":str(tmp_path),"GEMINI_HOME":str(gemini),"BROWSER":"/usr/bin/true",
        "AGY_ACP_FORCE_FILE_STORAGE":"1","ALLOW_DATACENTER_OAUTH_EGRESS":"1",
        "ORCHESTRA_DISABLED_PROVIDERS_FILE":str(tmp_path/"disabled.json"),
        "UNRELATED_SECRET":"synthetic-never-forward"}
    raw=json.dumps({"argv":["synthetic-vendor","acp"],"cwd":str(tmp_path),"env":env}).encode()
    try:
        left.sendmsg([struct.pack("!I",len(raw))],[(socket.SOL_SOCKET,socket.SCM_RIGHTS,array.array("i",[v[0] for v in pipes]))])
        left.sendall(raw)
        ipc._handle_spawner_conn(right,os.getuid(),os.getgid())
        response=ipc._recv_response(left)
        assert response["ok"]
        assert all(captured["env"][k]==env[k] for k in ("BROWSER","AGY_ACP_FORCE_FILE_STORAGE","GEMINI_HOME"))
        assert "UNRELATED_SECRET" not in captured["env"]
        assert captured["close_fds"] and captured["start_new_session"]
    finally:
        left.close();right.close()
        for pair in pipes:
            for fd in pair:os.close(fd)


def test_ipc_capacity_never_starts_more_than_bound(monkeypatch):
    ipc=ipc_module()
    class Connection:
        closed=False
        def close(self):self.closed=True
    connections=[Connection() for _ in range(65)]
    queued=list(connections);threads=[]
    class Server:
        def setblocking(self,*a):pass
        def accept(self):
            if not queued:raise StopIteration
            return queued.pop(0),None
    monkeypatch.setenv("LISTEN_FDS","1")
    monkeypatch.setattr(ipc.socket,"socket",lambda **kwargs:Server())
    monkeypatch.setattr(ipc.threading,"Thread",lambda **kw:SimpleNamespace(start=lambda:threads.append(kw)))
    with pytest.raises(StopIteration):ipc._serve_unix_daemon("unused",lambda *a:None)
    assert len(threads)==64 and connections[-1].closed


@pytest.mark.asyncio
async def test_slow_cancel_quarantines_only_owned_session(stand,monkeypatch):
    from tests.test_antigravity_acp import owner_message,wait_prompt
    a,b=stand.backend(),stand.backend()
    await a.send(owner_message("BLOCK"));await wait_prompt(stand)
    pid=a._owner.process.pid
    async def slow_notify(*args):await asyncio.sleep(10)
    monkeypatch.setattr(a._owner,"notify",slow_notify)
    await a.interrupt()
    assert a.session_id in a._owner.uncertain_sessions and not a._owner.failure
    assert end(await turn(b,"healthy after other cancellation")).metadata["ok"]
    assert a._owner.process.pid==pid


@pytest.mark.asyncio
async def test_pending_merge_retains_dependency_barrier(tmp_path,monkeypatch):
    from app import hub_outbox as ob
    db.init_db()
    parent=_session_record(session_id="merge-parent",name="merge-parent",scope=str(tmp_path))
    parent.update(role="orchestrator",is_orchestrator=True);db.save_session(parent)
    worker=_session_record(session_id="merge-child",name="merge-child",scope=str(tmp_path))
    worker.update(parent_id=parent["id"],parent_name=parent["name"],role="worker");db.save_session(worker)
    who=ob.Identity(session_id=parent["id"],name=parent["name"],scope=str(tmp_path),parent_name="",role="orchestrator")
    calls=[]
    async def api(method,path,body):
        calls.append((method,path))
        return {"result":{"operation_state":"RUNNING","operation_id":"synthetic"}}
    monkeypatch.setattr(ob,"MERGE_POLL_BUDGET_S",0)
    entries=[{"tool":"merge_worker","_delivery_id":"11111111-1111-4111-8111-111111111111",
        "args":{"worker":worker["name"],"expected_head":"a"*40}},
        {"tool":"close_worker","args":{"worker":worker["name"]}}]
    report=await ob.execute(entries,who,api)
    assert report.done==[] and report.dropped and len(calls)==1


@pytest.mark.asyncio
async def test_cumulative_tokens_survive_backend_recreation_without_double_charge(stand):
    a=stand.backend()
    first=end(await turn(a,"AUDIT_TOKENS"))
    assert first.usage.aggregate.input_tokens==100
    b=stand.backend(resume=a.session_id)
    second=end(await turn(b,"AUDIT_TOKENS"))
    assert second.usage.aggregate.accuracy=="reported" and second.usage.aggregate.input_tokens==0
    unknown=stand.backend(resume="preexisting-unmeasured-native")
    value=end(await turn(unknown,"AUDIT_TOKENS"))
    assert value.usage.aggregate.accuracy=="unknown" and value.metadata["cost_unaccounted"]


@pytest.mark.asyncio
async def test_one_hundred_release_cycles_keep_owner_maps_bounded(stand,monkeypatch):
    monkeypatch.setenv("AGY_MOCK_MODE","close-support")
    keeper=stand.backend();await turn(keeper,"keep shared front")
    owner=keeper._owner
    for i in range(100):
        b=stand.backend();assert end(await turn(b,str(i))).metadata["ok"]
        await b.release()
        assert len(owner.sessions)==len(owner.session_locks)==len(owner.model_states)==1
        assert len(owner.cost_totals)==len(owner.usage_totals)==1
    await keeper.release()
    counts=Counter(r["method"] for r in stand.trace())
    assert counts["session/close"]==101 and counts["spawn"]==1
    assert owner.process.returncode is not None


@pytest.mark.asyncio
async def test_bg_http_cannot_forge_owner_without_mcp_proof(stand,real_session,monkeypatch):
    from app.routes import bg
    from app.mcp_proof import issue_mcp_proof
    from starlette.requests import Request
    s=real_session
    monkeypatch.setattr(bg,"manager",SimpleNamespace(get_by_name=lambda *a:s))
    capture=AsyncMock(return_value={"id":"synthetic","type":"run","status":"active"})
    from app import bg_jobs
    monkeypatch.setattr(bg_jobs,"bg_manager",SimpleNamespace(create=capture))
    req=bg.BgJobCreateRequest(type="run",config={"command":"synthetic"},
        target_name=s.name,target_scope=s.scope,created_by="forged")
    response=await bg.bg_job_create(req,Request({"type":"http","headers":[]}))
    assert response.status_code==403 and not capture.called
    headers=[(b"x-orchestra-session-id",s.id.encode()),(b"x-orchestra-mcp-proof",issue_mcp_proof(s.id).encode())]
    result=await bg.bg_job_create(req,Request({"type":"http","headers":headers}))
    assert result["id"]=="synthetic" and capture.call_args.kwargs["creator_session_id"]==s.id


def test_application_credential_promotion_preserves_canonical_link_and_refuses_active_writer(tmp_path):
    import fcntl
    from app.antigravity_auth import prepare_acp_token_store,promote_staged_token,TOKEN_RELATIVE_PATH
    home=tmp_path/"profile";canonical=home/".gemini/antigravity-acp/antigravity-oauth-token"
    canonical.parent.mkdir(parents=True);canonical.write_bytes(b"old-synthetic")
    prepare_acp_token_store(home)
    staged=tmp_path/"staged";staged.write_bytes(b"new-synthetic")
    fd=os.open(home/".gemini/.orchestra-vendor-writer.lock",os.O_RDWR)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(RuntimeError,match="stopping the active profile writer"):promote_staged_token(home,staged)
        assert canonical.read_bytes()==b"old-synthetic" and staged.exists()
    finally:os.close(fd)
    promote_staged_token(home,staged)
    assert (home/TOKEN_RELATIVE_PATH).is_symlink() and canonical.read_bytes()==b"new-synthetic"


@pytest.mark.asyncio
async def test_actual_archive_releases_front_and_keeps_durable_history(stand,real_session,monkeypatch):
    from app.manager import SessionManager
    from app import bg_jobs
    s=real_session;await send_and_finish(s,"archive after this")
    owner=s._backend._owner
    manager=SessionManager();manager.sessions[s.id]=s
    monkeypatch.setattr(bg_jobs,"bg_manager",SimpleNamespace(cancel_by_session=AsyncMock()))
    await manager.remove(s.id)
    assert db.get_session(s.id)["status"]=="archived" and s.id not in manager.sessions
    assert owner.process.returncode is not None and not owner.sessions


@pytest.mark.asyncio
async def test_bg_manager_persists_trusted_creator_and_denies_timer_even_with_forged_config(stand,real_session,monkeypatch):
    from app.bg_jobs import BgJobManager
    s=real_session;manager=BgJobManager()
    monkeypatch.setattr(manager,"_start_task",lambda *a,**k:None)
    denied=await manager.create("timer",{"delay_seconds":1,"_creator_session_id":s.id},"wake",
        s.id,s.name,s.scope,s.name,creator_session_id=s.id)
    assert "interactive_only" in denied["error"]
    result=await manager.create("run",{"command":"synthetic","_creator_session_id":"forged"},"done",
        s.id,s.name,s.scope,s.name,creator_session_id=s.id)
    row=db.bg_get_job(result["id"])
    assert json.loads(row["config"])["_creator_session_id"]==s.id


@pytest.mark.asyncio
async def test_optional_native_close_refusal_does_not_break_archive_or_sibling(stand,monkeypatch):
    monkeypatch.setenv("AGY_MOCK_MODE","close-support")
    a,b=stand.backend(),stand.backend()
    await turn(a,"a");await turn(b,"b")
    original=a._owner.request
    async def refused(method,*args,**kwargs):
        if method=="session/close":raise acp.AcpSessionError("optional close refused")
        return await original(method,*args,**kwargs)
    monkeypatch.setattr(a._owner,"request",refused)
    await a.release()
    assert a.session_id not in a._owner.sessions and not a._owner.failure
    assert end(await turn(b,"healthy")).metadata["ok"]
