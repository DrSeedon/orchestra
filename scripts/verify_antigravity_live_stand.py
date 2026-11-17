"""One explicitly authorized isolated live cycle; no production lifespan or retry.

Run directly with candidate .venv. Credentials never enter tracked evidence. This
is a bounded verification driver, not a supported service entry point.
"""
import asyncio
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
STAND = Path('/tmp/orchestra-live-stand-20261117')
SOURCE = Path('/home/kesha/orchestra/.orchestra/tasks/katya-nl-pro-probe-20261116/sandbox_home')
PERSIST = SOURCE.parent/'acp_stand_profile'
PROFILE_FILES = ('.config/antigravity/credential-user-scope','.gemini/config/config.json',
    '.gemini/antigravity-cli/antigravity-oauth-token','.gemini/antigravity-cli/installation_id',
    '.gemini/antigravity-cli/cache/onboarding.json','.gemini/antigravity-cli/cache/default_project_id.txt',
    '.gemini/antigravity-cli/settings.json')
PRODUCTION = Path('/home/kesha/orchestra')
OUT = ROOT/'.orchestra/tasks/agy-acp-safe-20261117/split-config/live'
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
REPORT = {'authorization':'one isolated live stand cycle, explicit owner Step1',
          'started_at':datetime.now(timezone.utc).isoformat(), 'events':[], 'outcome':'PREPARING', 'native_permission_requests':0, 'native_owner_responses':[]}
SOURCE_HASHES = {}
RPC = []
SPAWNS = []
BASELINE_PIDS = set()
STAND_CREATED = False


def safe(value):
    text = str(value)
    for key in ('INTERNAL_TOKEN','DASHBOARD_PASSWORD'):
        secret = os.environ.get(key, '')
        if secret: text = text.replace(secret, '[redacted]')
    text = re.sub(r'ya29\.[A-Za-z0-9_-]+', '[redacted]', text)
    text = re.sub(r'(Bearer\s+)[^\s"\']+', r'\1[redacted]', text, flags=re.I)
    return text


def save():
    (OUT/'telemetry.json').write_text(json.dumps(REPORT,ensure_ascii=False,indent=2)+'\n')


def event(kind, **fields):
    item={'at':datetime.now(timezone.utc).isoformat(),'kind':kind,**fields}
    REPORT['events'].append(item);save()
    print(json.dumps(item,ensure_ascii=False),flush=True)


def run(args, **kwargs):
    return subprocess.run(args,check=True,capture_output=True,text=True,timeout=15,**kwargs).stdout


def vendor_pids():
    result={}
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit():continue
        try:
            if (entry/'comm').read_text().strip() != 'agy-vendor.elf':continue
            result[int(entry.name)]=(entry/'stat').read_text().split()[21]
        except OSError:pass
    return result


def nft_counter():
    raw=run(['sudo','-n','nft','-j','list','table','inet','orchestra_oauth_killswitch'])
    data=json.loads(raw);values=[]
    for item in data['nftables']:
        rule=item.get('rule',{});expr=rule.get('expr',[])
        if any(e.get('match',{}).get('left')=={'meta':{'key':'skgid'}} and e['match'].get('right') in (977, 'agy_oauth') for e in expr):
            for e in expr:
                if 'counter' in e:values.append(e['counter'])
    if not values:raise RuntimeError('killswitch skgid977 counter not found')
    return {'packets':sum(x['packets'] for x in values),'bytes':sum(x['bytes'] for x in values)}


def source_snapshot():
    result={}
    for file in SOURCE.rglob('*'):
        if file.is_symlink():
            # A log alias is part of the immutable source metadata, not a
            # directory or credential target to traverse/copy implicitly.
            result[str(file.relative_to(SOURCE))]=hashlib.sha256(b'symlink\0'+os.fsencode(os.readlink(file))).digest()
            continue
        if file.is_file():
            digest=hashlib.sha256()
            with file.open('rb') as stream:
                for chunk in iter(lambda:stream.read(1048576),b''):digest.update(chunk)
            result[str(file.relative_to(SOURCE))]=digest.digest()
    return result


def persistent_write(path, raw):
    from app.antigravity_auth import atomic_private_write
    relative=path.relative_to(PERSIST)
    current=PERSIST
    if current.is_symlink() or not path.resolve().is_relative_to(PERSIST.resolve()):
        raise RuntimeError('persistent profile path escape/symlink refused')
    if PERSIST.resolve()==SOURCE.resolve() or PERSIST.resolve().is_relative_to(SOURCE.resolve()):
        raise RuntimeError('persistent profile must be separate from immutable source')
    for part in relative.parts[:-1]:
        current=current/part
        if current.is_symlink():raise RuntimeError('persistent profile parent symlink refused')
        current.mkdir(exist_ok=True,mode=0o700);current.chmod(0o700)
    if path.is_symlink():raise RuntimeError('persistent credential symlink refused')
    atomic_private_write(path,raw)


def initialize_persistent_profile():
    if PERSIST.is_symlink():raise RuntimeError('persistent profile symlink refused')
    if PERSIST.exists():
        if PERSIST.stat().st_uid!=os.getuid() or PERSIST.stat().st_mode&0o777!=0o700:
            raise RuntimeError('persistent profile must be privately owned0700')
        if not all((PERSIST/rel).is_file() for rel in PROFILE_FILES):
            raise RuntimeError('persistent profile is incomplete; refusing implicit reinitialization')
        return
    PERSIST.mkdir(mode=0o700)
    persistent_write(PERSIST/'.gitignore',b'*\n')
    for rel in PROFILE_FILES:persistent_write(PERSIST/rel,(SOURCE/rel).read_bytes())
    shutil.copytree(PERSIST/'.gemini/antigravity-cli',PERSIST/'.gemini/antigravity-acp')
    settings={'useG1Credits':False,'telemetryEnabled':False,'auth':{'type':'oauth-personal'}}
    for kind in ('antigravity-cli','antigravity-acp'):
        persistent_write(PERSIST/'.gemini'/kind/'settings.json',json.dumps(settings).encode())
    config=PERSIST/'.gemini/config/config.json';value=json.loads(config.read_text())
    value.setdefault('userSettings',{})['useAiCredits']=False;persistent_write(config,json.dumps(value).encode())
    for path in PERSIST.rglob('*'):path.chmod(0o700 if path.is_dir() else 0o600)


def persist_refresh_state(home):
    raw=(home/'.gemini/antigravity-acp/antigravity-oauth-token').read_bytes()
    if not raw:raise RuntimeError('authenticated profile token is empty; refusing save')
    writes=0
    for kind in ('antigravity-acp','antigravity-cli'):
        target=PERSIST/'.gemini'/kind/'antigravity-oauth-token'
        if target.is_symlink():raise RuntimeError('persistent token symlink refused')
        if not target.is_file() or target.read_bytes()!=raw:
            persistent_write(target,raw);writes+=1
        target.chmod(0o600)
    return {'directory':str(PERSIST),'atomic':True,'mode':'0600','files_updated':writes}


def catalog_summary(result):
    def ids(option):
        values=[]
        for row in option.get('options',[]) or []:
            if not isinstance(row,dict):continue
            for item in ([row] if 'value' in row else row.get('options',[]) or []):
                if isinstance(item,dict) and isinstance(item.get('value'),str):values.append(item['value'][:256])
        return values[:256]
    options=[]
    for option in result.get('configOptions',[]) or []:
        if not isinstance(option,dict):continue
        # Only model/thought/mode selectors have a known nonsecret value contract.
        if option.get('category') not in {'model','thought_level','mode'} and option.get('id') not in {'model','thought_level','mode'}:continue
        options.append({'id':option.get('id'),'category':option.get('category'),
            'currentValue':option.get('currentValue'),'values':ids(option)})
    models=result.get('models') or {};modes=result.get('modes') or {}
    return {'configOptions':options,'models':{'currentModelId':models.get('currentModelId'),
        'availableModelIds':[x['modelId'] for x in models.get('availableModels',[]) or [] if isinstance(x,dict) and isinstance(x.get('modelId'),str)]},
        'modes':{'currentModeId':modes.get('currentModeId'),
        'availableModeIds':[x['id'] for x in modes.get('availableModes',[]) or [] if isinstance(x,dict) and isinstance(x.get('id'),str)]}}


def allowed_spawn_permission(request,repo):
    from app.acp_tools import canonical_name
    if request.get('kind')!='permission':raise RuntimeError('question/unknown native request is outside live authorization')
    details=request.get('details') or {}
    if canonical_name(details)!='mcp__orchestra__spawn_worker':raise RuntimeError('native request is not the authorized spawn_worker')
    raw=details.get('rawInput') or {};arguments=raw.get('Arguments',raw) if isinstance(raw,dict) else None
    if not isinstance(arguments,dict) or arguments.get('model') not in {'gpt-6-luna','luna'} or arguments.get('role','worker')!='worker':
        raise RuntimeError('native spawn request model/role is not authorized')
    if (not isinstance(arguments.get('name'),str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,49}',arguments['name'])
            or arguments['name']=='stand-ceo' or Path(arguments.get('repo_path','')).resolve()!=Path(repo).resolve()):
        raise RuntimeError('native spawn request target is not authorized')
    option=next((x for x in request.get('options',[]) if x.get('kind')=='allow_once'),None)
    if option is None:raise RuntimeError('native spawn permission has no allow-once option')
    return option['optionId']


async def answer_spawn_permission(client,request,repo):
    option=allowed_spawn_permission(request,repo)
    csrf=await client.get('/api/native-requests/csrf');csrf.raise_for_status()
    response=await client.post('/api/native-requests/'+request['id']+'/respond',
        headers={'X-CSRF-Token':csrf.json()['token']},json={'owner_id':request['owner_id'],
            'binding':request['binding'],'option_id':option,'cancel':False})
    response.raise_for_status()
    return {'request_id':request['id'],'tool_name':'mcp__orchestra__spawn_worker','option_id':option,
            'state':response.json().get('state')}


def seed_stand_catalog(repo,data_dir):
    # Normal task allocation requires a registered scope. Keep the source-only
    # demo repo at its initial README commit; the catalog belongs to stand data.
    project={'tag':'stand','name':'Isolated Stand','scope':str(repo),
             'write_namespace':'stand-live','namespaces':{'stand-live':''}}
    path=data_dir/'projects.yaml'
    path.write_text(json.dumps({'version':1,'projects':[project]},indent=2))
    path.chmod(0o600)
    return path


def prepare():
    global STAND_CREATED
    if STAND.exists():raise RuntimeError('Stand path already exists; refuse to reuse state')
    STAND.mkdir(mode=0o700)
    STAND_CREATED = True
    for folder in ('data','profile_home','demo_repo','worktrees','tasks','runtime'):(STAND/folder).mkdir(mode=0o700)
    home=STAND/'profile_home'
    SOURCE_HASHES.update(source_snapshot())
    initialize_persistent_profile()
    # This is the only authorized durable private-state exception beneath the
    # production task folder; no profile file may enter its Git index.
    run(['git','-C',str(PRODUCTION),'check-ignore','-q','--',str(PERSIST/'.gemini/antigravity-acp/antigravity-oauth-token')])
    REPORT['persistent_profile_gitignored']=True
    for rel in PROFILE_FILES:
        raw=(PERSIST/rel).read_bytes()
        dest=home/rel;dest.parent.mkdir(parents=True,exist_ok=True,mode=0o700);dest.write_bytes(raw);dest.chmod(0o600)
    cli=home/'.gemini/antigravity-cli';acp=home/'.gemini/antigravity-acp'
    shutil.copytree(cli,acp)
    # ACP's persisted token is authoritative even if a prior CLI mirror write failed.
    cached=(PERSIST/'.gemini/antigravity-acp/antigravity-oauth-token').read_bytes()
    for kind in (cli,acp):(kind/'antigravity-oauth-token').write_bytes(cached)
    settings={'useG1Credits':False,'telemetryEnabled':False,'auth':{'type':'oauth-personal'}}
    for target in (cli/'settings.json',acp/'settings.json'):
        target.write_text(json.dumps(settings));target.chmod(0o600)
    cfg=home/'.gemini/config/config.json';data=json.loads(cfg.read_text())
    data.setdefault('userSettings',{})['useAiCredits']=False;cfg.write_text(json.dumps(data));cfg.chmod(0o600)
    for path in home.rglob('*'):path.chmod(0o700 if path.is_dir() else 0o600)
    disabled=STAND/'data/disabled_providers.json';disabled.write_text('["claude","grok"]\n');disabled.chmod(0o600)
    repo=STAND/'demo_repo'
    seed_stand_catalog(repo,STAND/'data')
    run(['git','init','--initial-branch=main',str(repo)])
    (repo/'README.md').write_text('# Isolated multiplication verification\n')
    run(['git','-C',str(repo),'add','README.md'])
    run(['git','-C',str(repo),'-c','user.name=Stand Verification','-c','user.email=stand@localhost','-c','core.hooksPath=/dev/null','-c','commit.gpgsign=false','commit','-m','Initialize isolated stand'])
    # Copy only redacted quota telemetry, never the production DB or provider auth.
    with sqlite3.connect((PRODUCTION/'data/orchestra.db').as_uri()+'?mode=ro',uri=True) as connection:
        row=connection.execute('SELECT ts,provider_usage FROM usage_snapshots ORDER BY id DESC LIMIT 1').fetchone()
    providers=json.loads(row[1]) if row else {}
    codex=(providers.get('codex') or {}).get('raw_payload')
    quota={'observed_at':row[0] if row else None,'codex':codex}
    (STAND/'data/quota-cache.json').write_text(json.dumps(quota));(STAND/'data/quota-cache.json').chmod(0o600)
    env={'ORCHESTRA_DB_PATH':str(STAND/'data/orchestra.db'),
         'ORCHESTRA_TASK_REPOSITORY':str(STAND/'tasks'),
         'ORCHESTRA_PROJECT_CATALOG':str(STAND/'data/projects.yaml'),
         'ORCHESTRA_DISABLED_PROVIDERS_FILE':str(disabled),
         'ORCHESTRA_URL':'http://127.0.0.1:18889',
         'ANTIGRAVITY_AUTH_HOME':str(home), 'ANTIGRAVITY_BIN':'/home/kesha/.local/bin/agy',
         'ANTIGRAVITY_PROXY_URL':'http://127.0.0.1:18080', 'CODEX_PROXY_URL':'http://127.0.0.1:18080',
         'ORCHESTRA_RESIDENTIAL_PROXY_URL':'http://127.0.0.1:18080',
         'ORCHESTRA_ENFORCE_PROVIDER_EGRESS':'1','ORCHESTRA_EGRESS_VERIFY_TTL_SECONDS':'600',
         'NO_PROXY':'localhost,127.0.0.1,::1','NO_GRPC_PROXY':'localhost,127.0.0.1,::1',
         'INTERNAL_TOKEN':secrets.token_hex(32),'DASHBOARD_USER':'stand-owner',
         'DASHBOARD_PASSWORD':secrets.token_hex(32),'OWNER_MODE':'1',
         'ALLOWED_ROOTS':str(STAND),'TMPDIR':str(STAND/'runtime')}
    for key in list(os.environ):
        if any(x in key for x in ('PROXY','API_KEY','TOKEN','DASHBOARD','MULTICODE','NOTIFY_SOCKET')):os.environ.pop(key,None)
    os.environ.update(env)
    REPORT['profile_copy']={'file_count':len(PROFILE_FILES),'source_file_hash_count':len(SOURCE_HASHES),'source_unchanged':None,'no_credit_settings':True,'persistent_profile':str(PERSIST)}
    REPORT['quota_cache']={'observed_at':quota['observed_at'],'codex_available':isinstance(codex,dict),'probe_policy':'cache-only; no quota refresh'}
    REPORT['profile_initial_token_digest']=hashlib.sha256((acp/'antigravity-oauth-token').read_bytes()).hexdigest()
    # digest is comparison-only, never written in telemetry.
    return quota


def audit(kind,args):
    if kind in {'socket.connect','socket.bind'}:
        address=args[1]
        if isinstance(address,tuple) and (address[0] not in {'127.0.0.1','::1'} or address[1]==8888):
            raise PermissionError('stand isolation: external/direct or production callback blocked')
    if kind=='socket.getaddrinfo' and args[0] not in {'127.0.0.1','::1',None}:
        raise PermissionError('stand isolation: direct DNS blocked; use approved loopback proxy')
    if kind=='sqlite3.connect':
        raw=os.fsdecode(args[0])
        if raw!=':memory:':
            from urllib.parse import urlsplit,unquote
            path=Path(unquote(urlsplit(raw).path) if raw.startswith('file:') else raw).resolve()
            if not path.is_relative_to(STAND):raise PermissionError('stand isolation: SQLite outside stand blocked')
    if kind=='subprocess.Popen':
        argv=args[1]
        if isinstance(argv,(tuple,list)) and argv:
            binary=Path(argv[0]).name
            if binary in {'agy','agy.real','agy-vendor.elf'}:
                if binary!='agy' or list(argv)[1:2]!=['acp'] or any(x['binary']=='agy' for x in SPAWNS):
                    raise PermissionError('stand guard: only one agy acp launch, no probes/retries')
                SPAWNS.append({'binary':'agy','at':time.monotonic()})
            elif binary in {'codex','codex.real'}:
                if any(x['binary']=='codex' for x in SPAWNS):raise PermissionError('stand guard: only one Codex child process')
                SPAWNS.append({'binary':'codex','at':time.monotonic()})


async def exercise(quota):
    from fastapi import FastAPI,Request
    from fastapi.responses import JSONResponse
    import httpx,uvicorn
    from app import db,workspace,manager as manager_module,deps,models,native_requests
    from app.routes import sessions,system
    from app.routes.native_requests import router as native_router
    from app import antigravity_acp as acp
    from app.auth import create_session,validate_session,check_internal_token
    from app.task_runtime import task_runtime_mode,production_runtime
    from app.live_broker import broker
    db.init_db()
    assert db.DB_PATH==STAND/'data/orchestra.db'
    assert models.list_disabled_providers()==['claude','grok']
    from app import tm
    with db._conn() as connection:
        REPORT['stand_project_catalog']=tm.sync_catalog(connection)
        assert tm.get_project_by_scope(connection,str(STAND/'demo_repo')) is not None
    workspace.WORKTREE_ROOT=STAND/'worktrees';manager_module.WORKTREE_ROOT=workspace.WORKTREE_ROOT
    system._USAGE_CACHE_FILE=STAND/'data/usage_cache.json'
    observed=datetime.fromisoformat(quota['observed_at']).timestamp() if quota.get('observed_at') else 0
    system._codex_usage_cache.update(data=quota.get('codex'),ts=observed,failed_at=time.time())
    async def no_refresh(**kwargs):return system._quota_observation_from_cache()
    system.current_quota_observation=no_refresh
    async def cached_usage(**kwargs):
        return {'disabled_providers':models.list_disabled_providers(),'antigravity':{},'codex':system._codex_usage_cache['data'],
                'anthropic':None,'grok':None,'observation_policy':'isolated stand cache-only'}
    system._get_usage_data=cached_usage
    manager=deps.manager
    original_request=acp.AcpProfile.request
    async def observed_request(owner,method,params,**kwargs):
        record={'method':method,'at':time.monotonic()};RPC.append(record)
        if method=='session/prompt' and sum(x['method']==method for x in RPC)>2:raise RuntimeError('stand guard: third ACP prompt blocked')
        try:result=await original_request(owner,method,params,**kwargs)
        except BaseException as error:
            record['error']=safe(error)[:600];raise
        record['ok']=True
        if method in {'session/new','session/resume','session/set_config_option'}:
            REPORT.setdefault('session_catalog',[]).append({'method':method,'summary':catalog_summary(result)})
            save()
        if method=='authenticate':
            REPORT['authenticate_success']=True
            REPORT.setdefault('auth_state_updates',[]).append(persist_refresh_state(STAND/'profile_home'))
            save()
        if method=='initialize':
            REPORT['initialize']={'protocolVersion':result.get('protocolVersion'),
                'authMethods':[{k:m.get(k) for k in ('id','type')} for m in result.get('authMethods',[])],
                'agentCapabilities':result.get('agentCapabilities')}
            event('initialized',protocolVersion=result.get('protocolVersion'))
        record['ok']=True;return result
    acp.AcpProfile.request=observed_request
    @asynccontextmanager
    async def lifespan(app):
        with task_runtime_mode(production_runtime()):
            try:yield
            finally:
                await manager.shutdown_all()
                await acp.shutdown_profiles()
    app=FastAPI(lifespan=lifespan);app.include_router(sessions.router);app.include_router(system.router);app.include_router(native_router)
    worker_creations=0
    @app.middleware('http')
    async def isolate_http(request:Request,call_next):
        nonlocal worker_creations
        if request.url.port!=18889:return JSONResponse({'error':'stand port required'},status_code=403)
        if not (validate_session(request.cookies.get('session','')) or check_internal_token(request.headers.get('authorization',''))):
            return JSONResponse({'error':'stand authentication required'},status_code=403)
        if request.method=='POST' and request.url.path=='/api/sessions':
            body=await request.json()
            if body.get('name')!='stand-ceo':
                worker_creations+=1
                if (worker_creations>1 or body.get('model') not in {'gpt-6-luna','luna'} or body.get('parent_name')!='stand-ceo'
                        or not isinstance(body.get('name'),str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,49}',body['name']) or body.get('role')!='worker'
                        or any(body.get(key)!=str(STAND/'demo_repo') for key in ('cwd','scope','repo_path'))):
                    return JSONResponse({'error':'one authorized Luna child in isolated demo scope only'},status_code=403)
        response=await call_next(request)
        if response.status_code>=400:REPORT.setdefault('http_errors',[]).append({'path':request.url.path,'status':response.status_code})
        return response
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=18889,log_level='warning',access_log=False))
    task=asyncio.create_task(server.serve())
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if task.done():await task
                await asyncio.sleep(.1)
        event('stand_started',port=18889,background_loops=False)
        async with httpx.AsyncClient(base_url='http://127.0.0.1:18889',trust_env=False,timeout=35,
                                     cookies={'session':create_session('stand-owner')}) as client:
            for url in ('/api/stats','/api/usage'):
                response=await client.get(url);response.raise_for_status()
            role=('Single explicitly authorized local integration check. Spawn exactly ONE gpt-6-luna worker in this demo repo. '
                'Pass model_reason="Explicit local-only isolated stand verification authorized by owner; use this VPS worktree". '
                'Use role worker, base_branch main, name stand-calc-worker. No other workers/models, no retries, no background jobs. '
                'Do not call Bash/run_command/edit/read_file yourself. Only the Orchestra spawn tool and optional worker_wip. '
                'On any error, report it once and stop. After the worker report, acknowledge in one short sentence and finish; no further tools.')
            response=await client.post('/api/sessions',json={'name':'stand-ceo','cwd':str(STAND/'demo_repo'),'scope':str(STAND/'demo_repo'),
                'model':'antigravity/gemini-4-hydrogen-medium','is_orchestrator':True,'role':'orchestrator','system_prompt':role})
            if response.status_code>=400:raise RuntimeError('session create refused: '+safe(response.text)[:1000])
            ceo=manager.get_by_name('stand-ceo',str(STAND/'demo_repo'));assert ceo is not None
            await asyncio.sleep(10)
            assert not vendor_pids() and not SPAWNS and not RPC,'idle precheck unexpectedly launched provider'
            event('idle_precheck_pass',seconds=10,real_vendor_processes=0,rpc=0)
            message='Через инструмент mcp__orchestra__spawn_worker запусти одного воркера (model=\'gpt-6-luna\', role=\'worker\') с задачей: создать файл calc_stand.py с функцией multiply(a, b) и тестом test_calc_stand.py, запустить python3 -m unittest и завершить работу кратким отчётом. Сам файлы не редактируй и Bash не вызывай — только запусти воркера и скажи 1 фразой, что ждёшь его отчёт.'
            send=asyncio.create_task(client.post('/api/sessions/stand-ceo/send',json={'scope':ceo.scope,'message':message,'channel':'dashboard'}))
            deadline=time.monotonic()+420;pid_seen=None;last_progress=None;turn1=None
            while time.monotonic()<deadline:
                pids=vendor_pids()
                if pids:
                    if len(pids)!=1:raise RuntimeError('multiple vendor processes detected')
                    pid=next(iter(pids))
                    if pid_seen is None:
                        pid_seen=pid;REPORT['PID_ACP']=pid;event('vendor_started',pid=pid)
                    elif pid!=pid_seen:raise RuntimeError('vendor PID changed; no restart allowed')
                if send.done():
                    response=await send
                    if response.status_code>=400:raise RuntimeError('user send refused: '+safe(response.text)[:1200])
                logs=db.get_logs_forward(ceo.id,limit=2000)
                if REPORT.get('http_errors'):raise RuntimeError('stand HTTP refusal: '+json.dumps(REPORT['http_errors']))
                errors=[x for x in logs if x['type']=='error']
                if errors:raise RuntimeError('live turn error: '+safe(errors[-1]['content'])[:1500])
                if ceo._backend and ceo._backend._owner.failure:raise RuntimeError(ceo._backend._owner.failure)
                for log in logs:
                    if log['type']=='tool' and log.get('tool_name') not in {'mcp__orchestra__spawn_worker','mcp__orchestra__worker_wip','call_mcp_tool','tool_search','mcp__orchestra__get_worker_wip'}:
                        # Name may be opaque until structured MCP input arrives; do not allow shell/edit.
                        if any(k in (log.get('tool_name') or '').lower() for k in ('command','bash','edit','write_file')):
                            raise RuntimeError('orchestrator attempted prohibited shell/edit tool')
                pending=native_requests.pending_for(ceo.id)
                if pending:
                    if REPORT['native_permission_requests'] or len(pending)!=1:
                        raise RuntimeError('more than one native request; stop without another response')
                    REPORT['native_permission_requests']=1
                    result=await answer_spawn_permission(client,pending[0],STAND/'demo_repo')
                    REPORT['native_owner_responses'].append(result);save()
                children=[x for x in manager.sessions.values() if x.id!=ceo.id]
                if len(children)>1:raise RuntimeError('more than one child created')
                for child in children:
                    child_errors=[x for x in db.get_logs_forward(child.id,limit=2000) if x['type']=='error']
                    if child_errors:raise RuntimeError('child error: '+safe(child_errors[-1]['content'])[:1200])
                progress=(ceo.total_turns,len(children),sum(x.total_turns for x in children),ceo.status.value)
                if progress!=last_progress:event('progress',parent_turns=progress[0],children=progress[1],child_turns=progress[2],parent_status=progress[3]);last_progress=progress
                if ceo.total_turns>=1 and turn1 is None:
                    turn1={'pid':pid_seen,'status':ceo.status.value,'stop_reason':ceo._last_stop_reason,'ok':ceo._last_turn_ok};REPORT['turn1']=turn1
                if ceo.total_turns>=2 and ceo.status.value=='idle' and children and children[0].total_turns>=1:
                    worker=children[0]
                    if not ceo._last_turn_ok or not worker._last_turn_ok:raise RuntimeError('parent/child terminal turn not successful')
                    REPORT['turn2']={'pid':pid_seen,'status':ceo.status.value,'stop_reason':ceo._last_stop_reason,'ok':ceo._last_turn_ok}
                    REPORT['worker']={'id':worker.id,'model':worker.model,'worktree':worker.worktree_path,'turns':worker.total_turns,'ok':worker._last_turn_ok}
                    break
                await asyncio.sleep(.25)
            else:raise TimeoutError('one-cycle stand deadline reached; no retries')
            assert ceo.total_turns==2 and len(children)==1 and vendor_pids()=={pid_seen:vendor_pids()[pid_seen]}
            assert (Path(worker.worktree_path)/'calc_stand.py').is_file() and (Path(worker.worktree_path)/'test_calc_stand.py').is_file()
            # Retain only redacted event content and quantitative telemetry, never raw native protocol/auth.
            for session in (ceo,worker):
                await session._await_log_futures()
                records=db.get_logs_forward(session.id,limit=3000)
                (OUT/(session.name+'-logs.json')).write_text(json.dumps([{k:(safe(v) if isinstance(v,str) else v) for k,v in row.items()} for row in records],ensure_ascii=False,indent=2))
            with db._conn() as connection:
                REPORT['turn_usage']=[{k:r[k] for k in ('session_id','model','ok','stop_reason','input_tokens','output_tokens','cache_read_tokens','turn_duration_ms')} for r in connection.execute('SELECT * FROM turn_usage ORDER BY id')]
            before={'logs':len(db.get_logs_forward(ceo.id,limit=5000))+len(db.get_logs_forward(worker.id,limit=5000)),
                    'parent_turns':ceo.total_turns,'worker_turns':worker.total_turns,'rpc':len(RPC),'pids':vendor_pids()}
            event('silence_audit_start',seconds=45)
            await asyncio.sleep(45)
            after={'logs':len(db.get_logs_forward(ceo.id,limit=5000))+len(db.get_logs_forward(worker.id,limit=5000)),
                   'parent_turns':ceo.total_turns,'worker_turns':worker.total_turns,'rpc':len(RPC),'pids':vendor_pids()}
            REPORT['silence']={'seconds':45,'before':before,'after':after,'unchanged':before==after}
            if before!=after:raise RuntimeError('post-turn silence audit changed')
            REPORT['outcome']='LIVE_CYCLE_PASS'
    finally:
        # Persist partial evidence even when init/auth/model selection refuses.
        for session in list(manager.sessions.values()):
            try:
                await session._await_log_futures()
                records=db.get_logs_forward(session.id,limit=3000)
                (OUT/(session.name+'-logs.json')).write_text(json.dumps([{k:(safe(v) if isinstance(v,str) else v) for k,v in row.items()} for row in records],ensure_ascii=False,indent=2))
            except Exception as error:REPORT.setdefault('evidence_errors',[]).append(safe(error))
        with db._conn() as connection:
            REPORT['turn_usage']=[{k:r[k] for k in ('session_id','model','ok','stop_reason','input_tokens','output_tokens','cache_read_tokens','turn_duration_ms')} for r in connection.execute('SELECT * FROM turn_usage ORDER BY id')]
        server.should_exit=True
        try:await asyncio.wait_for(task,30)
        except BaseException:
            task.cancel();await asyncio.gather(task,return_exceptions=True)
            await manager.shutdown_all();await acp.shutdown_profiles()
        REPORT['rpc_counts']=dict(Counter(x['method'] for x in RPC))
        REPORT['rpc_outcomes']=RPC
        REPORT['spawn_counts']=dict(Counter(x['binary'] for x in SPAWNS))
        REPORT['server_stopped']=task.done()
        REPORT['stand_child_creation_attempts']=worker_creations
        event('stand_shutdown',server_stopped=task.done(),vendor_pids=list(vendor_pids()))


def main():
    if '--authorized-step1' not in sys.argv:raise SystemExit('Explicit --authorized-step1 required')
    os.umask(0o077)
    production_before=run(['git','-C',str(PRODUCTION),'status','--porcelain','--untracked-files=no'])
    disabled_before=(PRODUCTION/'data/disabled_providers.json').read_bytes()
    assert json.loads(disabled_before).get('disabled_providers')==['antigravity','claude','grok']
    token_initial=None
    try:
        BASELINE_PIDS.update(vendor_pids())
        REPORT['preexisting_vendor_pids']=sorted(BASELINE_PIDS)
        if BASELINE_PIDS:raise RuntimeError('existing vendor process; refuse live stand without touching it')
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1',18889))==0:raise RuntimeError('18889 occupied; refuse')
        quota=prepare();token_initial=REPORT.pop('profile_initial_token_digest')
        # Explicit authorized preflight: proxy identity only, no model/auth request.
        ip=json.loads(run(['curl','-sS','--max-time','5','-x','http://127.0.0.1:18080','https://ipinfo.io/json']))
        REPORT['proxy']={k:ip.get(k) for k in ('ip','country','org','city')}
        assert ip['ip']=='178.93.29.64' and ip['country']=='NL' and 'AS215294' in ip['org']
        REPORT['nft_before']=nft_counter();event('safety_preflight_pass',proxy=REPORT['proxy'],nft_before=REPORT['nft_before'])
        sys.addaudithook(audit)
        asyncio.run(exercise(quota))
    except BaseException as error:
        REPORT['outcome']='STOPPED_NO_RETRY';REPORT['error']=safe(error)[:2000]
        event('fail_stop',error=REPORT['error'],error_type=type(error).__name__)
    finally:
        try:
            REPORT['nft_after']=nft_counter()
            if 'nft_before' in REPORT:
                REPORT['nft_delta']={k:REPORT['nft_after'][k]-REPORT['nft_before'][k] for k in ('packets','bytes')}
                if REPORT['nft_delta']['packets']!=0:REPORT['outcome']='KILLSWITCH_COUNTER_CHANGED'
        except BaseException as error:REPORT['nft_final_error']=safe(error)
        if STAND_CREATED and STAND.exists():
            try:
                token=STAND/'profile_home/.gemini/antigravity-acp/antigravity-oauth-token'
                REPORT['oauth_refresh_state_changed']=token.is_file() and hashlib.sha256(token.read_bytes()).hexdigest()!=token_initial
                REPORT.setdefault('profile_copy',{})['source_unchanged']=(source_snapshot()==SOURCE_HASHES)
                if not REPORT['profile_copy']['source_unchanged']:REPORT['outcome']='SOURCE_PROFILE_CHANGED'
                if REPORT.get('authenticate_success'):
                    REPORT.setdefault('auth_state_updates',[]).append(persist_refresh_state(STAND/'profile_home'))
                REPORT['refresh_state_policy']='authenticated refresh state atomically saved to private acp_stand_profile; temporary copy removed; source immutable'
            except Exception as error:
                REPORT['auth_state_cleanup_error']=safe(error);REPORT['outcome']='PRIVATE_STATE_CLEANUP_ERROR'
            finally:
                shutil.rmtree(STAND)
        REPORT['stand_created']=STAND_CREATED
        REPORT['stand_removed']=STAND_CREATED and not STAND.exists()
        REPORT['leftover_owned_vendor_pids']=sorted(set(vendor_pids())-BASELINE_PIDS)
        REPORT['foreign_vendor_pids_preserved']=sorted(set(vendor_pids())&BASELINE_PIDS)
        REPORT['production_tracked_unchanged']=run(['git','-C',str(PRODUCTION),'status','--porcelain','--untracked-files=no'])==production_before
        REPORT['production_disabled_unchanged']=(PRODUCTION/'data/disabled_providers.json').read_bytes()==disabled_before
        REPORT['ended_at']=datetime.now(timezone.utc).isoformat();save()
    return 0 if REPORT['outcome']=='LIVE_CYCLE_PASS' else 1


if __name__=='__main__':raise SystemExit(main())
