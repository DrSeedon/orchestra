"""Offline preflight for ONE separately authorized live stand. No real provider traffic."""
import asyncio,json,os,sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app import db
from app.antigravity_acp import ensure_interactive_input
from app.events import MessageProvenance
from tests.test_antigravity_acp import stand,USER,turn,end
from tests.test_antigravity_acp_r2 import real_session,send_and_finish
from tests.test_antigravity_acp_submission import http_stand
from tests.test_message_delivery_receipts_380 import _session_record


def child(parent,name='stand-worker',**fields):
    row=_session_record(session_id=name,name=name,scope=parent.scope)
    row.update(parent_id=parent.id,parent_name=parent.name,**fields);db.save_session(row)
    return row


@pytest.mark.asyncio
async def test_durable_child_report_wakes_actual_parent_and_reuses_one_daemon(stand,real_session):
    s=real_session;child(s)
    await send_and_finish(s,'first owner turn')
    pid=s._backend._owner.process.pid
    await s.send('verified child complete',provenance=MessageProvenance('agent',('stand-worker',),'auto_report'))
    await asyncio.wait_for(s._listen_task,4);await s._await_log_futures()
    assert s._last_turn_ok and s._backend._owner.process.pid==pid
    assert sum(x['method']=='session/prompt' for x in stand.trace())==2
    assert sum(x['method']=='spawn' for x in stand.trace())==1
    assert db.get_logs(s.id)[-1]['type'] in {'status','text','tool_result'}


@pytest.mark.asyncio
@pytest.mark.parametrize('origin,subtype', [('system',''),('platform','cron'),('background_task','timer'),('platform','dreaming'),('platform','limit_wake'),('platform','rate_limit_retry'),('platform','server_error_retry'),('unknown',''),('agent','cron'),('agent','scheduler')])
async def test_automated_origins_stay_rejected_before_transport(stand,real_session,origin,subtype):
    s=real_session;child(s)
    with pytest.raises(ValueError,match='antigravity_interactive_only'):
        await s.send('forbidden',provenance=MessageProvenance(origin,('stand-worker',),subtype))
    assert not stand.trace()


def test_every_sender_requires_durable_direct_child_same_scope_and_orchestrator(stand,real_session):
    s=real_session;row=child(s)
    for senders in [('unrelated',),('stand-worker','unrelated')]:
        with pytest.raises(ValueError):ensure_interactive_input(s.model,MessageProvenance('agent',senders),target_session=s)
    with db._conn() as c:c.execute('UPDATE sessions SET scope=? WHERE id=?',(s.scope+'/other',row['id']))
    with pytest.raises(ValueError):ensure_interactive_input(s.model,MessageProvenance('agent',('stand-worker',)),target_session=s)
    with db._conn() as c:c.execute('UPDATE sessions SET scope=? WHERE id=?',(s.scope,row['id']))
    row['parent_id']='foreign';row['parent_name']='foreign';db.save_session(row)
    with pytest.raises(ValueError):ensure_interactive_input(s.model,MessageProvenance('agent',('stand-worker',)),target_session=s)
    row['parent_id']=s.id;db.save_session(row)
    ensure_interactive_input(s.model,MessageProvenance('agent',('stand-worker',)),target_session=s)
    with pytest.raises(ValueError):ensure_interactive_input(s.model,MessageProvenance('agent',('stand-worker',)),target_session=s,allow_child_agent=False)
    s.is_orchestrator=False
    with pytest.raises(ValueError):ensure_interactive_input(s.model,MessageProvenance('agent',('stand-worker',)),target_session=s)


@pytest.mark.asyncio
async def test_verified_http_child_report_reaches_real_transport(stand,http_stand):
    from app.mcp_proof import issue_mcp_proof
    s,client,_=http_stand;row=child(s)
    response=await client.post('/api/sessions/'+s.name+'/send',json={'scope':s.scope,'message':'child report','sender':row['name']},
        headers={'x-orchestra-session-id':row['id'],'x-orchestra-mcp-proof':issue_mcp_proof(row['id'])})
    assert response.status_code==200,response.text
    await asyncio.wait_for(s._listen_task,4)
    assert sum(x['method']=='session/prompt' for x in stand.trace())==1


def test_mcp_url_is_taken_from_stand_env(monkeypatch):
    from app import manager
    monkeypatch.setattr(manager,'get_role',lambda *a:SimpleNamespace(disabled_tools=[]))
    monkeypatch.setattr(manager,'get_active_pipeline',lambda *a:'default')
    monkeypatch.setenv('ORCHESTRA_URL','http://127.0.0.1:18889')
    cfg=manager._make_mcp_config('stand-ceo','/synthetic',role='orchestrator')
    assert cfg['orchestra']['env']['ORCHESTRA_URL']=='http://127.0.0.1:18889'


def test_cli_env_preserves_disabled_file_and_clean_exec_serializes_mcp(monkeypatch,tmp_path):
    from app import backend_antigravity as agy
    monkeypatch.setenv('ORCHESTRA_DISABLED_PROVIDERS_FILE',str(tmp_path/'disabled.json'))
    env=agy.cli_environment(tmp_path)
    assert env['ORCHESTRA_DISABLED_PROVIDERS_FILE']==str(tmp_path/'disabled.json') and env['HOME']==str(tmp_path)
    b=object.__new__(agy.AntigravityBackend);b.mcp_servers={'orchestra':{'command':'/synthetic/python','args':['/synthetic/mcp_stdio.py'],'env':{'ORCHESTRA_URL':'http://127.0.0.1:18889'}}}
    original=Path.is_file
    monkeypatch.setattr(Path,'is_file',lambda p:True if str(p)=='/home/kesha/.local/bin/agy-clean-exec' else original(p))
    monkeypatch.setattr(os,'access',lambda *a:True)
    server=b._acp_mcp_servers()[0]
    assert server['command']=='/home/kesha/.local/bin/agy-clean-exec'
    assert server['args']==['/synthetic/python','/synthetic/mcp_stdio.py']
    assert server['env']==[{'name':'ORCHESTRA_URL','value':'http://127.0.0.1:18889'}]


@pytest.mark.asyncio
async def test_auth_personal_method_accepts_oauth_type_without_fallback(stand,monkeypatch):
    monkeypatch.setenv('AGY_MOCK_MODE','auth-oauth-type')
    b=stand.backend();await turn(b,'one')
    assert sum(x['method']=='authenticate' for x in stand.trace())==1
    assert end(await turn(b,'two')).metadata.get('model_error') is None
    assert sum(x['method']=='spawn' for x in stand.trace())==1


def test_acp_conversation_metadata_precedes_legacy_without_writes(stand):
    from tests import test_antigravity_turn_health as legacy
    from app import backend_antigravity as agy
    b=stand.backend()
    connection,path=legacy.write_metadata(b,[]);connection.close()
    acp=b.home/'.gemini/antigravity-acp/conversations'/path.name;acp.parent.mkdir(parents=True,exist_ok=True)
    # A malformed ACP database stays unknown; no silent read of a different legacy conversation.
    acp.write_bytes(b'not sqlite')
    assert isinstance(agy._conversation_context(b.home,'conversation-a',1000000),agy.UnknownContext)
    assert acp.read_bytes()==b'not sqlite'


@pytest.mark.asyncio
async def test_hydrogen_orchestrator_exempt_and_codex_child_uses_cached_admission(monkeypatch):
    from app import quota_gate,models
    assert models.backend_for_model('antigravity/gemini-4-hydrogen-medium')=='antigravity'
    assert not quota_gate.session_requires_quota('antigravity',is_orchestrator=True)
    loader=AsyncMock(return_value={'providers':{},'observed_at_by_provider':{}})
    # conftest's default quota mock is not the contract under test.
    import importlib
    real=importlib.reload(quota_gate).get_worker_admission
    decision=await real('gpt-6-luna',observation_loader=loader)
    quota_gate.require_worker_admission(decision)  # Fresh unknown observation is normal admission, not invented capacity.
    loader.assert_awaited_once()


@pytest.mark.asyncio
async def test_real_auto_report_callback_delivers_durable_child_signal(stand,real_session,monkeypatch):
    from app.manager import SessionManager
    from app.session import AgentSession
    from app import deps
    s=real_session;manager=SessionManager();manager.sessions[s.id]=s
    w=AgentSession(id='auto-child',name='auto-child',scope=s.scope,cwd=s.cwd,model='gpt-6-luna',backend_type='codex',
        parent_id=s.id,parent_name=s.name)
    w._persist();await w._drain_persist();manager.sessions[w.id]=w
    monkeypatch.setattr(deps,'manager',manager)
    await manager._make_idle_callback(s.scope)(w.name,w.scope,['multiply unittest passed'],'end_turn',True)
    await asyncio.wait_for(s._listen_task,4);await s._await_log_futures()
    reports=[x for x in db.get_logs(s.id) if x['type']=='user_message' and x['origin']=='agent']
    assert reports and reports[0]['origin_detail']['subtype']=='auto_report'
    assert s._last_turn_ok and sum(x['method']=='session/prompt' for x in stand.trace())==1
    await w._drain_persist()


@pytest.mark.asyncio
async def test_queued_child_report_keeps_authorship_through_actual_flush(stand,real_session):
    from app.session import AgentStatus
    s=real_session;child(s)
    # Controlled pending boundary, then real backend+event listener; no pretend ACK.
    s.status=AgentStatus.RUNNING
    await s.send('queued child result',provenance=MessageProvenance('agent',('stand-worker',),'auto_report'))
    assert len(s._pending_messages)==1 and s._pending_acp_provenance[0].origin=='agent'
    s.status=AgentStatus.IDLE
    await s._flush_pending()
    await asyncio.wait_for(s._listen_task,4);await s._await_log_futures()
    assert not s._pending_messages and not s._pending_acp_provenance
    assert s._last_turn_ok and sum(x['method']=='session/prompt' for x in stand.trace())==1


@pytest.mark.parametrize("group",[977,"agy_oauth"])
def test_live_stand_counter_accepts_numeric_or_resolved_nft_group(monkeypatch,group):
    from scripts import verify_antigravity_live_stand as driver
    payload={"nftables":[{"rule":{"expr":[
        {"match":{"left":{"meta":{"key":"skgid"}},"right":group}},
        {"counter":{"packets":0,"bytes":0}}]}}]}
    monkeypatch.setattr(driver,"run",lambda args:json.dumps(payload))
    assert driver.nft_counter()=={"packets":0,"bytes":0}
