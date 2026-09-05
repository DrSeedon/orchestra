import os,sys,subprocess
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
import app
out=Path('.orchestra/tasks/bash-latency-20260905')
files=['tests/test_bash_completion.py','tests/test_merge_completion_watch.py','tests/test_mcp_stdio.py','tests/test_merge_operations.py','tests/test_merge_progress_424.py','tests/test_bg_jobs.py','tests/test_harness_tools.py','tests/test_harness_production.py','tests/test_harness_inject.py','tests/test_audit0901_harness.py','tests/test_backend_harness_turn_usage_422.py','tests/test_routes_surface.py','tests/test_default_pipeline.py']
print('Imported app:',app.__file__,flush=True)
with (out/'vps-regression-final.txt').open('w') as log:
 r=subprocess.run([sys.executable,'-m','pytest',*files,'-q','--timeout=40'],stdout=log,stderr=subprocess.STDOUT,timeout=300)
print('Regression exit:',r.returncode,flush=True)
print((out/'vps-regression-final.txt').read_text()[-2000:],flush=True)
if r.returncode:sys.exit(r.returncode)
os.environ['BENCH_LABEL']='final-vps'
os.environ['BENCH_WORKERS']='0,2,0,2'
r=subprocess.run([sys.executable,str(out/'bench_tests.py')],timeout=300)
sys.exit(r.returncode)
