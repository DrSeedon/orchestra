"""Run every available collected core node, keeping browser-sensitive modules serial."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[4]
TASK = ROOT / '.orchestra/tasks/V-1240/ci-followup'
plan = json.loads((TASK / 'core-partition.json').read_text())
runner = shutil.which('uv')
assert runner and '/orchestra/tools/uv/0.11.28/' in runner
cg = Path('/sys/fs/cgroup') / Path('/proc/self/cgroup').read_text().split('::',1)[1].strip().lstrip('/')
def headroom():
    maximum = (cg / 'memory.max').read_text().strip()
    return int(maximum) - int((cg / 'memory.current').read_text()) if maximum != 'max' else 2**60

env = dict(os.environ)
for key in json.loads((TASK/'child-test-env.json').read_text())['removed_keys']:
    env.pop(key, None)
placement = json.loads((TASK/'cache-placement.json').read_text())
cache = Path.home()/placement['relative_parent']/placement['cache_subdirectory']
env.update(GIT_AUTHOR_NAME='Orchestra CI',GIT_AUTHOR_EMAIL='orchestra-ci@example.invalid',
           GIT_COMMITTER_NAME='Orchestra CI',GIT_COMMITTER_EMAIL='orchestra-ci@example.invalid',
           PLAYWRIGHT_BROWSERS_PATH=str(cache/'browser-assets'),
           NPM_CONFIG_CACHE=str(cache/'npm-cache'),NPM_CONFIG_OFFLINE='true')
env['PATH'] = str(cache/'tool-bin') + os.pathsep + env['PATH']
results=[]
for phase,key,parallel,limit in [
    ('core-serial','serial_browser_sensitive_modules',False,1800),
    ('core-parallel','parallel_nonbrowser_modules',True,2400),
]:
    room=headroom()
    workers=2 if parallel and room>=10*1024**3 else 1
    if room < 7*1024**3:
        results.append(dict(phase=phase,state='capacity_blocked',headroom_bytes=room))
        break
    command=['timeout',str(limit)+'s',runner,'run','--frozen','python','-m','pytest',
             *plan[key],'-m','not browser and not live_probe','--timeout=60','--continue-on-collection-errors','-q','-rfs']
    if parallel: command += ['-n',str(workers),'--dist=loadscope']
    print(json.dumps(dict(phase=phase,modules=len(plan[key]),workers=workers,headroom_bytes=room)),flush=True)
    start=time.monotonic()
    with (TASK/f'raw/{phase}.log').open('w') as out:
        result=subprocess.run(command,cwd=ROOT,env=env,stdout=out,stderr=subprocess.STDOUT,check=False)
    item=dict(phase=phase,state='finished',exit_code=result.returncode,seconds=round(time.monotonic()-start,2),
              workers=workers,modules=len(plan[key]),command=command[3:])
    results.append(item)
    (TASK/'core-results.json').write_text(json.dumps(results,indent=2)+'\n')
    print(json.dumps({k:v for k,v in item.items() if k!='command'}),flush=True)
(TASK/'core-results.json').write_text(json.dumps(results,indent=2)+'\n')
