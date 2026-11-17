"""Nonsecret catalog/permission/private-refresh live-driver contracts, offline only."""
import json,stat
from pathlib import Path
import httpx
import pytest
from fastapi import FastAPI
from scripts import verify_antigravity_live_stand as driver
from tests.test_antigravity_acp import stand,USER
from tests.test_antigravity_acp_r2 import real_session
from tests.test_antigravity_foreground import pending,finish


def test_catalog_summary_drops_auth_and_payload_fields():
    response={'configOptions':[{'id':'model','category':'model','currentValue':'gemini-4-hydrogen','options':[{'group':'Gemini','options':[{'value':'gemini-4-hydrogen','name':'display label'}]}]},
        {'id':'thought_level','category':'thought_level','currentValue':'medium','options':[{'value':'low'},{'value':'medium'}]},
        {'id':'secret','category':'auth','currentValue':'SYNTHETIC_PRIVATE','options':[]}],
        'models':{'currentModelId':'gemini-4-hydrogen-medium','availableModels':[{'modelId':'gemini-4-hydrogen-medium','name':'display label'}]},
        'modes':{'currentModeId':'default','availableModes':[{'id':'default','name':'display label'}]},'token':'SYNTHETIC_PRIVATE'}
    value=driver.catalog_summary(response)
    assert value['configOptions'][0]['values']==['gemini-4-hydrogen']
    assert value['configOptions'][1]['currentValue']=='medium'
    assert value['models']['availableModelIds']==['gemini-4-hydrogen-medium']
    assert value['modes']['availableModeIds']==['default']
    assert 'SYNTHETIC_PRIVATE' not in json.dumps(value) and 'display label' not in json.dumps(value)


def test_refresh_copy_is_atomic_private_and_keeps_source_immutable(tmp_path,monkeypatch):
    source=tmp_path/'source';source.mkdir();original=source/'untouched';original.write_bytes(b'synthetic original')
    cache=tmp_path/'persistent';cache.mkdir(mode=0o700)
    home=tmp_path/'temporary';token=home/'.gemini/antigravity-acp/antigravity-oauth-token';token.parent.mkdir(parents=True)
    token.write_bytes(b'synthetic refreshed state')
    monkeypatch.setattr(driver,'SOURCE',source);monkeypatch.setattr(driver,'PERSIST',cache)
    result=driver.persist_refresh_state(home)
    assert result['files_updated']==2 and result['atomic']
    for kind in ('antigravity-acp','antigravity-cli'):
        target=cache/'.gemini'/kind/'antigravity-oauth-token'
        assert target.read_bytes()==token.read_bytes() and stat.S_IMODE(target.stat().st_mode)==0o600
    assert all(stat.S_IMODE(p.stat().st_mode)==0o700 for p in cache.rglob('*') if p.is_dir())
    assert original.read_bytes()==b'synthetic original'
    assert driver.persist_refresh_state(home)['files_updated']==0
    assert not list(cache.rglob('.orchestra-*'))


def test_persistent_path_cannot_escape_to_source(tmp_path,monkeypatch):
    source=tmp_path/'source';source.mkdir();original=source/'untouched';original.write_bytes(b'synthetic original')
    cache=tmp_path/'cache';cache.mkdir(mode=0o700)
    monkeypatch.setattr(driver,'SOURCE',source);monkeypatch.setattr(driver,'PERSIST',cache)
    (cache/'escape').symlink_to(source,target_is_directory=True)
    with pytest.raises(RuntimeError):driver.persistent_write(cache/'escape/untouched',b'bad')
    assert original.read_bytes()==b'synthetic original'


@pytest.mark.asyncio
@pytest.mark.parametrize('wire_name',[None,'mcp_orchestra_spawn_worker'])
async def test_only_authorized_spawn_gets_one_real_owner_http_response(stand,real_session,monkeypatch,wire_name):
    from app.routes.native_requests import router
    from app.auth import create_session
    monkeypatch.setenv('DASHBOARD_USER','synthetic-owner');monkeypatch.setenv('DASHBOARD_PASSWORD','synthetic-private-test-only')
    app=FastAPI();app.include_router(router)
    if wire_name:monkeypatch.setenv('AGY_MOCK_MODE','spawn-flat-permission')
    s=real_session;await s.send('FG_SPAWN_PERMISSION',provenance=USER);row=(await pending(s))[0]
    if wire_name:assert row['details']['name']==wire_name  # Actual native RPC payload and binding, not a rewritten card.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1',trust_env=False,
        cookies={'session':create_session('synthetic-owner')}) as client:
        result=await driver.answer_spawn_permission(client,row,s.cwd)
    await finish(s)
    assert result['option_id']==row['options'][0]['optionId']
    assert result['tool_name']==(wire_name or 'mcp__orchestra__spawn_worker')
    assert sum(r['method']=='native_reply' for r in stand.trace())==1
    assert sum(r['method']=='session/prompt' for r in stand.trace())==1


@pytest.mark.parametrize('kind,name,model',[('question','mcp__orchestra__spawn_worker','gpt-6-luna'),('permission','run_command','gpt-6-luna'),('permission','edit','gpt-6-luna'),('permission','write_file','gpt-6-luna'),('permission','mcp__orchestra__spawn_worker','gpt-6.1-sol')])
def test_native_question_shell_edit_other_model_are_never_auto_approved(kind,name,model,tmp_path):
    request={'kind':kind,'details':{'name':name,'rawInput':{'name':'stand-calc-worker','role':'worker','model':model,'repo_path':str(tmp_path)}},'options':[{'kind':'allow_once','optionId':'allow'}]}
    with pytest.raises(RuntimeError):driver.allowed_spawn_permission(request,tmp_path)


def test_fresh_stand_scope_registered_for_normal_worker_task_allocation(tmp_path,monkeypatch):
    from app import db,tm,project_catalog
    repo=tmp_path/'demo';repo.mkdir();data=tmp_path/'data';data.mkdir()
    path=driver.seed_stand_catalog(repo,data)
    monkeypatch.setenv('ORCHESTRA_PROJECT_CATALOG',str(path));project_catalog.reset_cache()
    db.init_db()
    with db._conn() as connection:
        result=tm.sync_catalog(connection)
        row=tm.get_project_by_scope(connection,str(repo))
    assert str(repo) in result['scopes'] and row['canonical_id']=='stand-live'
    assert not (repo/'.orchestra').exists()  # Source-only project remains valid for memory admission.


def test_persistent_profile_initializes_once_without_reverting_refreshed_state(tmp_path,monkeypatch):
    source=tmp_path/'sandbox';source.mkdir();cache=tmp_path/'cache'
    for rel in driver.PROFILE_FILES:
        path=source/rel;path.parent.mkdir(parents=True,exist_ok=True)
        if rel.endswith('config.json'):path.write_text(json.dumps({'userSettings':{'useAiCredits':True}}))
        elif rel.endswith('settings.json'):path.write_text(json.dumps({'useG1Credits':True}))
        else:path.write_bytes(b'synthetic original profile')
    before={str(p.relative_to(source)):p.read_bytes() for p in source.rglob('*') if p.is_file()}
    monkeypatch.setattr(driver,'SOURCE',source);monkeypatch.setattr(driver,'PERSIST',cache)
    driver.initialize_persistent_profile()
    assert stat.S_IMODE(cache.stat().st_mode)==0o700 and (cache/'.gitignore').read_text()=='*\n'
    assert json.loads((cache/'.gemini/config/config.json').read_text())['userSettings']['useAiCredits'] is False
    assert json.loads((cache/'.gemini/antigravity-acp/settings.json').read_text())['useG1Credits'] is False
    assert all(stat.S_IMODE(p.stat().st_mode)==(0o700 if p.is_dir() else 0o600) for p in cache.rglob('*'))
    temporary=tmp_path/'temporary';token=temporary/'.gemini/antigravity-acp/antigravity-oauth-token';token.parent.mkdir(parents=True)
    token.write_bytes(b'synthetic refreshed cache');driver.persist_refresh_state(temporary)
    driver.initialize_persistent_profile()
    assert (cache/'.gemini/antigravity-acp/antigravity-oauth-token').read_bytes()==b'synthetic refreshed cache'
    assert before=={str(p.relative_to(source)):p.read_bytes() for p in source.rglob('*') if p.is_file()}


def test_source_snapshot_hashes_log_symlink_without_following_external_target(tmp_path,monkeypatch):
    import hashlib,os
    source=tmp_path/'source';source.mkdir();(source/'ordinary').write_bytes(b'immutable source')
    outside=tmp_path/'external-log';outside.write_bytes(b'outside log')
    link=source/'cli.log';link.symlink_to(outside)
    monkeypatch.setattr(driver,'SOURCE',source)
    snapshot=driver.source_snapshot()
    assert snapshot['cli.log']==hashlib.sha256(b'symlink\0'+os.fsencode(os.readlink(link))).digest()
    outside.write_bytes(b'changed outside source')
    assert driver.source_snapshot()==snapshot
    (source/'ordinary').write_bytes(b'changed source')
    assert driver.source_snapshot()!=snapshot and link.is_symlink()


@pytest.mark.parametrize('wire_name',['mcp_orchestra_run_command','mcp_other_spawn_worker','mcp_orchestra_spawn_worker_extra'])
def test_observed_spawn_alias_is_exact_not_a_generic_mcp_name_bypass(wire_name,tmp_path):
    request={'kind':'permission','details':{'name':wire_name,'rawInput':{'name':'stand-calc-worker','role':'worker',
        'model':'gpt-6-luna','repo_path':str(tmp_path)}},'options':[{'kind':'allow_once','optionId':'allow'}]}
    with pytest.raises(RuntimeError):driver.allowed_spawn_permission(request,tmp_path)


@pytest.mark.asyncio
async def test_stand_worker_routers_mount_without_background_loops_or_404(tmp_path,monkeypatch):
    from app import db,tm,project_catalog
    from app.auth import create_session
    from app.routes import sessions,system,tm as tm_routes,inbox,outbox,artifacts,attention,approvals,temp_rules
    from app.routes.native_requests import router as native_router
    repo=tmp_path/'demo';repo.mkdir();data=tmp_path/'data';data.mkdir()
    catalog_path=driver.seed_stand_catalog(repo,data)
    monkeypatch.setenv('ORCHESTRA_DB_PATH',str(data/'orchestra.db'))
    monkeypatch.setenv('ORCHESTRA_PROJECT_CATALOG',str(catalog_path))
    monkeypatch.setenv('DASHBOARD_USER','synthetic-owner')
    monkeypatch.setenv('DASHBOARD_PASSWORD','synthetic-private-test-only')
    project_catalog.reset_cache();db.init_db()
    with db._conn() as connection:tm.sync_catalog(connection)
    app=FastAPI()
    for router in (sessions.router,system.router,native_router,tm_routes.router,inbox.router,
            outbox.router,artifacts.router,attention.router,approvals.router,temp_rules.router):
        app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:18889',
            trust_env=False,cookies={'session':create_session('synthetic-owner')}) as client:
        routes={getattr(r,'path','') for r in app.routes}
        assert {'/api/tm/tasks','/api/inbox/events','/api/outbox','/api/artifacts/publish','/api/attention','/api/approvals','/api/temp-rules'}<=routes
        for url in ('/api/tm/projects?scope='+str(repo),'/api/outbox?recipient=stand-ceo&scope='+str(repo),
                    '/api/approvals?recipient=stand-ceo&scope='+str(repo)):
            resp=await client.get(url)
            assert resp.status_code==200, (url, resp.status_code, resp.text)


@pytest.mark.asyncio
async def test_acp_turns_record_turn_usage_and_completed_turns_handles_codex_zero_counter(stand,real_session):
    from types import SimpleNamespace
    from app import db
    s=real_session
    await s.send('turn one',provenance=USER);await finish(s)
    await s.send('turn two',provenance=USER);await finish(s)
    await s._await_log_futures()
    assert s.total_turns==2 and driver.completed_turns(db,s)==2
    with db._conn() as connection:
        rows=connection.execute('SELECT ok,stop_reason,cost_unaccounted,turn_duration_ms FROM turn_usage WHERE session_id=? ORDER BY id',(s.id,)).fetchall()
    assert len(rows)==2 and all(r['ok']==1 and r['stop_reason']=='end_turn' and r['cost_unaccounted']==1 and r['turn_duration_ms'] is not None for r in rows)
    # Simulate Codex worker where session.total_turns stays 0 while turn_usage/status logs record completion:
    codex_stub=SimpleNamespace(id=s.id,total_turns=0)
    assert driver.completed_turns(db,codex_stub)==2
