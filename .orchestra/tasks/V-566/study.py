"""V-566 only: fixed read-only skill comparison, not a local_bench provider fallback."""
import asyncio,hashlib,json,os,pathlib,shutil,subprocess,sys,time
HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT))
from scripts.local_bench.process import run_process,write_json
from scripts.local_bench.isolation import Relay
from app.models import resolve_model
from scripts.wf_run import _readiness

PACKAGE=HERE/'package'
LAB=pathlib.Path('/home/kesha/.cache/orchestra-study-V-566')
WORK=LAB/'workspace'
TEMPLATE='<active_skill name="grill-me">\n{skill}\n</active_skill>\n\n<user_request>\n{task}\n</user_request>\n'
CLAUDE_SYSTEM='Use the supplied active skill for the user request. The specific user request takes precedence over the generic skill workflow.'


def visible(variant):
    return TEMPLATE.format(skill=(PACKAGE/f'prompt-{variant}.md').read_text(),task=(PACKAGE/'task.txt').read_text())


def env_for(home):
    return {'PATH':'/usr/bin:/bin','HOME':str(home),'LANG':'C.UTF-8','TMPDIR':str(home/'tmp'),
            'CODEX_HOME':str(home/'.codex'),'CLAUDE_CONFIG_DIR':str(home/'.claude'),
            'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC':'1','PYTHONDONTWRITEBYTECODE':'1','NO_PROXY':''}


def wrapped(home,port,command):
    return ['/usr/bin/python3',str(HERE/'readonly_boundary.py'),'--workspace',str(WORK),'--home',str(home),'--port',str(port),*command]


def inventory():
    return {str(p.relative_to(WORK)):hashlib.sha256(p.read_bytes()).hexdigest() for p in WORK.rglob('*') if p.is_file()}


async def prepare(arms):
    LAB.mkdir(parents=True,exist_ok=True)
    if not WORK.exists():shutil.copytree(PACKAGE/'fixture',WORK)
    baseline=inventory()
    assert baseline=={'docs/'+pathlib.Path(name).name:sha for name,sha in json.loads((PACKAGE/'manifest.json').read_text())['files'].items() if name.startswith('fixture/')}
    old=visible('before');new=visible('after')
    assert old.replace('Read ALL available docs.','Read documents relevant to the plan being challenged.')==new
    write_json(HERE/'scaffold.json',{'template':TEMPLATE,'claude_system':CLAUDE_SYSTEM,'cwd':str(WORK),'before_sha256':hashlib.sha256(old.encode()).hexdigest(),'after_sha256':hashlib.sha256(new.encode()).hexdigest(),'single_input_replacement_verified':True,'docs':baseline,'package_commit':'e858399f2ade6827c5f25f6497b85cbd9f74b2e7'})
    for variant in ['before','after']:(HERE/f'visible-{variant}.txt').write_text(visible(variant))
    ready=[]
    for index,(alias,variant,repeat) in enumerate(arms):
        name=f'{alias}-{variant}-r{repeat}'
        out=HERE/'arms'/name
        if (out/'dispatched.json').exists():raise RuntimeError(f'No duplicate dispatch: {out}')
        out.mkdir(parents=True,exist_ok=True)
        # Opaque equal-length home names; variant is never encoded in the visible path.
        home=LAB/('h'+hashlib.sha256(name.encode()).hexdigest()[:12]);home.mkdir(mode=0o700,exist_ok=True)
        for directory in ['tmp','.codex','.claude']:(home/directory).mkdir(exist_ok=True)
        runtime='claude' if alias in ['opus','fable'] else 'codex'
        env=env_for(home)
        if runtime=='codex':
            source=pathlib.Path(os.environ.get('CODEX_HOME',str(pathlib.Path.home()/'.codex')))/'auth.json'
            shutil.copyfile(source,home/'.codex/auth.json');os.chmod(home/'.codex/auth.json',0o600)
        else:
            source=pathlib.Path(os.environ.get('CLAUDE_CONFIG_DIR',str(pathlib.Path.home()/'.claude')))/'.credentials.json'
            env['CLAUDE_CODE_OAUTH_TOKEN']=json.loads(source.read_text())['claudeAiOauth']['accessToken']
            (home/'.claude.json').write_text('{"hasCompletedOnboarding":true}')
        model=resolve_model(alias)
        readiness=await _readiness(model)
        write_json(out/'readiness.json',readiness)
        if readiness.get('state')=='blocked':raise RuntimeError(f'{alias}: quota readiness blocked')
        effort='medium' if alias=='astra' else 'high'
        if runtime=='codex':
            command=['/usr/bin/codex','-m',model,'-s','danger-full-access','-a','never','exec','--ephemeral','--ignore-user-config','--ignore-rules','--disable','multi_agent','--skip-git-repo-check','-c','web_search="disabled"','-c',f'model_reasoning_effort="{effort}"','--json','-']
        else:
            command=['/usr/bin/claude','-p','--model',model,'--effort',effort,'--no-session-persistence','--dangerously-skip-permissions','--setting-sources','','--strict-mcp-config','--mcp-config','{"mcpServers":{}}','--tools','Bash,Read,Glob,Grep','--output-format','stream-json','--include-partial-messages','--verbose','--max-budget-usd','1','--system-prompt',CLAUDE_SYSTEM]
        version=subprocess.run(wrapped(home,0,[command[0],'--version']),cwd=WORK,env=env,capture_output=True,text=True,timeout=15)
        if version.returncode:raise RuntimeError(version.stderr)
        # Actual file-boundary probes, executed without any provider call.
        forbidden=[str(PACKAGE/'evaluation.md'),str(PACKAGE/f'prompt-{variant}.md'),str(PACKAGE/f'prompt-{"after" if variant=="before" else "before"}.md'),str(ROOT/'app/quota_gate.py'),os.environ.get('ORCHESTRA_DB_PATH','/home/kesha/orchestra/data/orchestra.db'),str(pathlib.Path.home()/'.agents/skills'),str(ROOT/'.orchestra/pipelines/default/prompts/skills/grill-me.md')]
        code="import pathlib,json,socket; rows=[]\n"
        code+="for p in "+repr(forbidden)+":\n try:\n  path=pathlib.Path(p); list(path.iterdir()) if path.is_dir() else path.read_bytes(); rows.append([p,'ALLOWED'])\n except PermissionError: rows.append([p,'DENIED'])\n"
        code+="assert all(r[1]=='DENIED' for r in rows),rows\n"
        code+="p=pathlib.Path('docs/beta-launch.md'); p.read_text()\ntry:\n p.open('a'); raise AssertionError('write allowed')\nexcept PermissionError: pass\n"
        code+="s=socket.socket(); assert s.connect_ex(('127.0.0.1',8888)) in (1,13)\nprint(json.dumps(rows))\n"
        check=subprocess.run(wrapped(home,0,['/usr/bin/python3','-S','-c',code]),cwd=WORK,env=env,capture_output=True,text=True,timeout=15)
        (out/'boundary.stdout').write_text(check.stdout);(out/'boundary.stderr').write_text(check.stderr)
        if check.returncode:raise RuntimeError(f'{name} boundary failed: {check.stderr}')
        metadata={'name':name,'alias':alias,'model':model,'variant':variant,'repeat':repeat,'runtime':runtime,'effort':effort,'runtime_version':version.stdout.strip(),'argv':command,'cwd':str(WORK),'explicit_input_sha256':hashlib.sha256(visible(variant).encode()).hexdigest(),'home':str(home),'timeout_seconds':180,'grace_seconds':20,'boundary_verified':True}
        write_json(out/'invocation.json',metadata)
        ready.append((metadata,home,env,out))
    return ready,baseline


async def one(item,start):
    meta,home,env,out=item
    relay=await Relay().start()
    env.update({key:f'http://127.0.0.1:{relay.port}' for key in ['HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy']})
    prices=None
    if meta['runtime']=='codex':
        p=json.loads((HERE/'codex-prices.json').read_text())[meta['model']]
        prices={'input':p['input'],'cached_input':p['cached'],'cache_write':p['write'],'output':p['output']}
    try:
        await start.wait()
        # Replace unique preparation HOME with an identical visible path within the pair.
        active_home=LAB/('home-'+meta['alias'])
        if active_home.exists():active_home.rename(LAB/('retired-'+meta['name']))
        home.rename(active_home);home=active_home
        env.update(env_for(home))
        env.update({key:f'http://127.0.0.1:{relay.port}' for key in ['HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy']})
        meta['prepared_home']=meta['home'];meta['home']=str(home)
        write_json(out/'invocation.json',meta)
        with (out/'dispatched.json').open('x') as marker: json.dump({'at':time.time()},marker)
        result=await run_process(wrapped(home,relay.port,meta['argv']),WORK,env,out/'execution',runtime=meta['runtime'],prompt=visible(meta['variant']),timeout=180,grace=20,budget=1,prices=prices)
        write_json(out/'result.json',result)
        print(json.dumps({'name':meta['name'],'completion':result['completion'],'accounting':result['accounting'],'seconds':result['wall_seconds']},ensure_ascii=False),flush=True)
        return result
    finally:
        await relay.close();write_json(out/'relay.json',relay.events)
        auth=home/'.codex/auth.json'
        if auth.exists():auth.unlink()


async def main(mode):
    if mode=='initial':arms=[(m,v,1) for m in ['astra','luna','opus'] for v in ['before','after']]
    elif mode=='repeat':arms=[('astra',v,2) for v in ['before','after']]
    elif mode=='extend':arms=[(m,v,1) for m in ['sol','fable'] for v in ['before','after']]
    else:raise ValueError(mode)
    ready,baseline=await prepare(arms)
    write_json(HERE/f'prepared-{mode}.json',{'names':[m['name'] for m,_,_,_ in ready],'doc_hashes':baseline,'created_at':time.time(),'paid_calls_dispatched':False})
    if os.environ.get('V566_PREFLIGHT_ONLY')=='1':return
    start=asyncio.Event()
    grouped={}
    for item in ready:grouped.setdefault(item[0]['alias'],[]).append(item)
    async def pair(alias,items):
        after_first=(alias=='luna') if mode!='repeat' else True
        items.sort(key=lambda item: (item[0]['variant']!='after') if after_first else (item[0]['variant']!='before'))
        rows=[]
        for item in items:rows.append(await one(item,start))
        return rows
    calls=[asyncio.create_task(pair(alias,items)) for alias,items in grouped.items()]
    start.set()
    grouped_results=await asyncio.gather(*calls,return_exceptions=True)
    results=[row for group in grouped_results for row in (group if isinstance(group,list) else [group])]
    assert inventory()==baseline,'Subject documents changed'
    write_json(HERE/f'run-{mode}.json',{'complete':all(isinstance(r,dict) for r in results),'names':[m['name'] for m,_,_,_ in ready],'errors':[str(r) for r in results if isinstance(r,BaseException)],'docs_unchanged':True})

if __name__=='__main__':asyncio.run(main(sys.argv[1]))
