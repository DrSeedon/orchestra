"""Recover deadline snapshots and score source files with the frozen oracle."""
import json,pathlib,shutil,subprocess,hashlib,collections,xml.etree.ElementTree as ET
HERE=pathlib.Path(__file__).resolve().parent
LAB=pathlib.Path('/home/kesha/.cache/orchestra-bench-V-558')
PYTHON='/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python'
ALLOWED={'app/quota_gate.py','app/routes/system.py'}
rows=[]
for name in ['luna','sol','astra','opus','fable']:
    folder=name if name in ['luna','sol','astra'] else name+'-authenticated'
    out=HERE/'evidence'/folder;cwd=LAB/('arm-'+name)/'work'
    def git(*args):return subprocess.check_output(['git',*args],cwd=cwd).decode()
    changed=set(git('diff','--name-only','seed').splitlines())
    untracked=set(git('ls-files','--others','--exclude-standard').splitlines())
    unexpected=sorted(p for p in changed|untracked if p.startswith('app/') and p not in ALLOWED and '__pycache__' not in pathlib.PurePosixPath(p).parts and not p.endswith(('.pyc','.pyo')))
    (out/'patch.diff').write_text(git('diff','seed','--','app','tests'))
    files={}
    for path in sorted(changed|untracked):
        if not path.startswith(('app/','tests/')) or '__pycache__' in pathlib.PurePosixPath(path).parts or path.endswith(('.pyc','.pyo')):continue
        source=cwd/path
        if not source.is_file():continue
        target=out/'submitted'/path;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        files[path]=hashlib.sha256(source.read_bytes()).hexdigest()
    (out/'submitted-sha256.json').write_text(json.dumps(files,indent=2)+'\n')
    if (out/'result.json').exists():
        row=json.loads((out/'result.json').read_text());row['completion']='end_turn'
    else:
        events=[json.loads(l) for l in (out/'stdout.jsonl').read_text().splitlines() if l.strip()]
        messages={}
        for event in events:
            if event.get('type')!='assistant':continue
            message=event.get('message',{});mid=message.get('id')
            if not mid:continue
            merged=messages.setdefault(mid,{})
            for key,value in message.get('usage',{}).items():
                if isinstance(value,(int,float)):merged[key]=max(merged.get(key,0),value)
        keys=['input_tokens','cache_creation_input_tokens','cache_read_input_tokens','output_tokens']
        observed={key:sum(m.get(key,0) for m in messages.values()) for key in keys}
        (out/'observed-message-usage.json').write_text(json.dumps({'deduplication':'maximum numeric usage per message.id, then sum unique ids','messages':messages,'sum':observed},indent=2)+'\n')
        row={'name':name,'completion':'timeout','wall_seconds':600,'cost_usd':None,'usage_complete':False,'observed_usage':observed,'observed_messages':len(messages),'cost_note':'No final result event; exact billed output and total_cost_usd unavailable. Partial message usage is not final billing.'}
        dest=LAB/('evaluation-'+name)
        shutil.copytree(LAB/'quota-reference',dest,ignore=shutil.ignore_patterns('__pycache__','.pytest_cache','tmp','isolated*','*.db'))
        for path in ALLOWED:shutil.copyfile(cwd/path,dest/path)
        env={'PATH':'/usr/bin:/bin','HOME':str(dest),'LANG':'C.UTF-8','PYTHONPATH':str(dest),'ORCHESTRA_DB_PATH':str(dest/'isolated.db'),'ORCHESTRA_TASK_REPOSITORY':str(dest/'isolated-tasks')}
        with (out/'oracle.log').open('wb') as stream:
            check=subprocess.run([PYTHON,'-m','pytest','tests/test_quota_gate.py','tests/test_quota_map_api.py','-q','-p','no:randomly',f'--junitxml={out}/oracle.xml'],cwd=dest,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=120)
        row['oracle_rc']=check.returncode;row['evaluated_app_path']=str(dest/'app/quota_gate.py')
    xml=ET.parse(out/'oracle.xml').getroot();cases=xml.findall('.//testcase')
    row['tests']=len(cases);row['failures']=sum(c.find('failure') is not None or c.find('error') is not None for c in cases)
    row['skipped']=sum(c.find('skipped') is not None for c in cases)
    row['out_of_scope_production']=unexpected
    row['source_pass']=row['oracle_rc']==0 and not unexpected
    row['artifact_folder']=folder
    row['submitted_sha256']=files
    row.pop('text',None)
    rows.append(row)
    print(name,row['tests'],row['failures'],row['completion'],row['source_pass'],flush=True)
(HERE/'evidence/final-results.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
