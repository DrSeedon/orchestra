import json, os, pathlib, subprocess, time
here=pathlib.Path(__file__).resolve().parent
runtime='/opt/orchestra/runtimes/20260817-b0b72d65-py312-rag-v2/bin/python'
lab=pathlib.Path('/home/kesha/.cache/orchestra-bench-V-558')
rows=[]
for label in ['baseline','reference']:
    cwd=lab/label
    env={'PATH':'/usr/bin:/bin','HOME':str(cwd),'LANG':'C.UTF-8','PYTHONPATH':str(cwd),'ORCHESTRA_DB_PATH':str(cwd/'isolated.db'),'ORCHESTRA_TASK_REPOSITORY':str(cwd/'isolated-tasks')}
    commands=[['-c','import app.bg_jobs; print(app.bg_jobs.__file__)'],['-m','pytest','tests/test_pidfd_leaks.py','tests/test_bg_jobs.py','tests/test_harness_tools.py','-q','-p','no:randomly']]
    for i,cmd in enumerate(commands):
        start=time.monotonic()
        with (here/'evidence'/f'{label}-{i}.log').open('w') as out:
            result=subprocess.run([runtime,*cmd],cwd=cwd,env=env,stdout=out,stderr=subprocess.STDOUT,timeout=240)
        rows.append({'label':label,'command':[runtime,*cmd],'cwd':str(cwd),'exit_code':result.returncode,'seconds':time.monotonic()-start})
(here/'evidence'/'controls-results.json').write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps(rows,indent=2))
