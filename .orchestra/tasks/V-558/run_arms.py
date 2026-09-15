"""Sequential one-shot code-writing trials, with an external sealed evaluator."""
import asyncio,dataclasses,hashlib,json,os,pathlib,shutil,signal,subprocess,sys,time
HERE=pathlib.Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT))
from scripts.wf_adapters import parse_codex_output,parse_claude_output
from scripts.wf_run import _readiness
from app.models import resolve_model
from transport import Relay
LAB=pathlib.Path('/home/kesha/.cache/orchestra-bench-V-558')
PYTHON='/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python'
ALLOWED={'app/quota_gate.py','app/routes/system.py'}

def dump(path,obj):path.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n')
def git(cwd,*args):return subprocess.check_output(['git',*args],cwd=cwd,stderr=subprocess.STDOUT).decode()

async def execute(name,remaining,output_name=None):
    arm=LAB/('arm-'+name);cwd=arm/'work';home=arm/'home'
    output=HERE/'evidence'/(output_name or name);output.mkdir()
    model=resolve_model(name);is_codex=name in ['luna','sol','astra']
    readiness=await _readiness(model);dump(output/'readiness.json',readiness)
    if readiness.get('state')=='blocked':raise RuntimeError(f'{name}: readiness blocked')
    effort='medium' if name=='astra' else 'high'
    relay=await Relay().start()
    env={'PATH':'/usr/bin:/bin','HOME':str(home),'LANG':'C.UTF-8','TMPDIR':str(arm/'tmp'),
         'CODEX_HOME':str(home/'.codex'),'CLAUDE_CONFIG_DIR':str(home/'.claude'),
         'HTTP_PROXY':f'http://127.0.0.1:{relay.port}','HTTPS_PROXY':f'http://127.0.0.1:{relay.port}',
         'http_proxy':f'http://127.0.0.1:{relay.port}','https_proxy':f'http://127.0.0.1:{relay.port}',
         'NO_PROXY':'','CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC':'1',
         'ORCHESTRA_DB_PATH':str(arm/'isolated.db'),'ORCHESTRA_TASK_REPOSITORY':str(arm/'isolated-tasks'),
         'GIT_CONFIG_GLOBAL':str(home/'.gitconfig')}
    if not is_codex:
        credentials=json.loads((home/'.claude/.credentials.json').read_text())
        env['CLAUDE_CODE_OAUTH_TOKEN']=credentials['claudeAiOauth']['accessToken']
    if is_codex:
        cli=['/usr/bin/codex','-m',model,'-s','danger-full-access','-a','never','exec','--ephemeral','--ignore-rules','--ignore-user-config','--skip-git-repo-check','-c','web_search="disabled"','-c',f'model_reasoning_effort="{effort}"','--json','-']
    else:
        cli=['/usr/bin/claude','-p','--model',model,'--no-session-persistence','--dangerously-skip-permissions','--effort',effort,'--output-format','stream-json','--verbose','--max-budget-usd',str(min(5.0,remaining)), '--setting-sources','','--strict-mcp-config','--mcp-config','{"mcpServers":{}}','--tools','Bash,Read,Write,Edit,Glob,Grep','--system-prompt','Ты выполняешь задачу программирования в изолированном репозитории. Реализуй требования пользователя, оставь результат на диске.']
    cmd=['/usr/bin/python3',str(HERE/'sandbox.py'),'--workspace',str(arm),'--cwd',str(cwd),'--port',str(relay.port),*cli]
    dump(output/'invocation.json',{'model':model,'effort':effort,'argv':cli,'cwd':str(cwd),'timeout_seconds':600,'prompt_sha256':hashlib.sha256((HERE/'prompt.txt').read_bytes()).hexdigest(),'started_at':time.time()})
    started=time.monotonic()
    try:
        with (output/'stdout.jsonl').open('wb') as stdout,(output/'stderr.log').open('wb') as stderr:
            proc=await asyncio.create_subprocess_exec(*cmd,cwd=cwd,env=env,stdin=asyncio.subprocess.PIPE,stdout=stdout,stderr=stderr,start_new_session=True)
            try:await asyncio.wait_for(proc.communicate((HERE/'prompt.txt').read_bytes()),600)
            except asyncio.TimeoutError:
                os.killpg(proc.pid,signal.SIGTERM)
                try:await asyncio.wait_for(proc.wait(),3)
                except asyncio.TimeoutError:os.killpg(proc.pid,signal.SIGKILL);await proc.wait()
                raise RuntimeError(f'{name}: timeout; no automatic retry')
    finally:
        await relay.close();dump(output/'relay.json',relay.events)
    wall=time.monotonic()-started
    raw=(output/'stdout.jsonl').read_text()
    if is_codex:result=parse_codex_output(raw,model)
    else:
        events=[json.loads(line) for line in raw.splitlines() if line.strip()]
        finals=[row for row in events if row.get('type')=='result']
        if len(finals)!=1:raise RuntimeError(f'{name}: {len(finals)} result records')
        result=parse_claude_output(json.dumps(finals[0]),model)
    row=dataclasses.asdict(result);row.update({'name':name,'wall_seconds':wall,'process_rc':proc.returncode})
    dump(output/'result.json',row)
    (output/'patch.diff').write_text(git(cwd,'diff','seed','--','app','tests'))
    changed=set(git(cwd,'diff','--name-only','seed').splitlines())
    untracked=git(cwd,'ls-files','--others','--exclude-standard').splitlines()
    extra=[p for p in changed|set(untracked) if p.startswith('app/') and p not in ALLOWED and '__pycache__' not in pathlib.PurePosixPath(p).parts and not p.endswith(('.pyc','.pyo'))]
    row['out_of_scope_production']=extra
    # Evaluate immutable reference tests against baseline + submitted production files.
    dest=LAB/('evaluation-'+name)
    shutil.copytree(LAB/'quota-reference',dest,ignore=shutil.ignore_patterns('__pycache__','.pytest_cache','tmp','isolated*','*.db'))
    for path in ALLOWED:shutil.copyfile(cwd/path,dest/path)
    eval_env={'PATH':'/usr/bin:/bin','HOME':str(dest),'LANG':'C.UTF-8','PYTHONPATH':str(dest),'ORCHESTRA_DB_PATH':str(dest/'isolated.db'),'ORCHESTRA_TASK_REPOSITORY':str(dest/'isolated-tasks')}
    command=[PYTHON,'-m','pytest','tests/test_quota_gate.py','tests/test_quota_map_api.py','-q','-p','no:randomly',f'--junitxml={output}/oracle.xml']
    with (output/'oracle.log').open('wb') as out:
        check=await asyncio.create_subprocess_exec(*command,cwd=dest,env=eval_env,stdout=out,stderr=asyncio.subprocess.STDOUT)
        await asyncio.wait_for(check.wait(),120)
    row['oracle_rc']=check.returncode;row['pass']=check.returncode==0 and not extra
    row['evaluated_app_path']=str(dest/'app/quota_gate.py')
    dump(output/'result.json',row)
    print(json.dumps({'name':name,'pass':row['pass'],'cost_usd':row['cost_usd'],'wall_seconds':wall}),flush=True)
    return row

async def main():
    manifest=json.loads((HERE/'evidence/arms-manifest.json').read_text())
    assert manifest['prompt_sha256']==hashlib.sha256((HERE/'prompt.txt').read_bytes()).hexdigest()
    assert len({r['tree'] for r in manifest['arms']})==1
    assert all(r['history_count']=='1' and not r['remotes'] for r in manifest['arms'])
    assert all(r['boundary_rc']==0 for r in json.loads((HERE/'evidence/preflight-results.json').read_text()))
    assert '93 passed' in (HERE/'evidence/quota-sandbox.log').read_text()
    rows=[];spent=0.0
    try:
        for name in ['luna','sol','astra','opus','fable']:
            if spent>=15:raise RuntimeError('budget exhausted, remaining arms not launched')
            row=await execute(name,15-spent);rows.append(row);spent+=row['cost_usd']
            dump(HERE/'evidence/arm-results.json',rows)
    except Exception as exc:
        dump(HERE/'evidence/runner-stop.json',{'error':str(exc),'completed':len(rows),'spent_usd':spent})
        raise
    print(f'All five finished; cost={spent:.6f}',flush=True)

if __name__=='__main__':
    asyncio.run(main())
