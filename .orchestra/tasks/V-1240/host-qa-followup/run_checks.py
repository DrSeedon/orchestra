"""Child-only isolated, offline regression invocations for the host QA follow-up."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[4]
TASK=Path(__file__).parent
prior=ROOT/'.orchestra/tasks/V-1240/ci-followup'
env=dict(os.environ)
for key in json.loads((prior/'child-test-env.json').read_text())['removed_keys']:
    env.pop(key,None)
env.update(GIT_AUTHOR_NAME='Orchestra CI',GIT_AUTHOR_EMAIL='orchestra-ci@example.invalid',
           GIT_COMMITTER_NAME='Orchestra CI',GIT_COMMITTER_EMAIL='orchestra-ci@example.invalid')
placement=json.loads((prior/'cache-placement.json').read_text())
cache=Path.home()/placement['relative_parent']/placement['cache_subdirectory']
env.update(PLAYWRIGHT_BROWSERS_PATH=str(cache/'browser-assets'),
           NPM_CONFIG_CACHE=str(cache/'npm-cache'),NPM_CONFIG_OFFLINE='true')
env['PATH']=str(cache/'tool-bin')+os.pathsep+env['PATH']
env['PYTHONPATH']=str(TASK)+os.pathsep+env.get('PYTHONPATH','')
runner=shutil.which('uv')
assert runner and '/orchestra/tools/uv/0.11.28/' in runner
command=[runner,'run','--frozen','python','-m','pytest',*sys.argv[1:],'-q','--timeout=60','-rfs']
result=subprocess.run(command,cwd=ROOT,env=env,check=False,timeout=300)
print('CHILD_EXIT_CODE='+str(result.returncode),flush=True)
raise SystemExit(result.returncode)
