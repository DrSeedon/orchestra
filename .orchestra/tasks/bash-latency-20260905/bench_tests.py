"""Sequential A/B runs in an enclosing MemoryMax=2G, nice=15 scope."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
root = Path.cwd()
sys.path.insert(0, str(root))
import app
output = root / '.orchestra/tasks/bash-latency-20260905'
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
tests = sys.argv[1:] or ['tests/test_merge_test_gate.py', 'tests/test_mcp_stdio.py', 'tests/test_harness_tools.py', 'tests/test_quota_gate.py']
env = {k:v for k,v in os.environ.items() if k != 'NOTIFY_SOCKET' and not k.startswith(('ORCHESTRA_', 'TG_', 'TELEGRAM_', 'ANTHROPIC_', 'OPENAI_', 'OPENROUTER_', 'DASHBOARD_'))}
env['PYTHONDONTWRITEBYTECODE'] = '1'

def tree_rss(pid):
    processes = {}
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit(): continue
        try:
            stat = (entry/'stat').read_text().rsplit(')',1)[1].split()
            processes[int(entry.name)] = (int(stat[1]), int(stat[21]) * os.sysconf('SC_PAGE_SIZE'))
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    owned = {pid}
    while True:
        found = {p for p,(parent,_) in processes.items() if parent in owned}
        if found <= owned: break
        owned |= found
    return sum(processes.get(p,(0,0))[1] for p in owned)

results = []
tag = os.environ.get('BENCH_LABEL', 'bench')
sequence = [int(n) for n in os.environ.get('BENCH_WORKERS', '0,2,4,4,2,0').split(',')]
for index, workers in enumerate(sequence):
    label = f'{tag}-{index}-n{workers}'
    junit = output / f'{label}.xml'
    argv = [sys.executable, '-m', 'pytest', *tests, '-q', '--timeout=30', f'--junitxml={junit}', '-n', str(workers)]
    if workers: argv += ['--dist=load', '--max-worker-restart=0']
    start = time.monotonic()
    peak = 0
    with (output/f'{label}.txt').open('w') as log:
        proc = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, env=env)
        while proc.poll() is None:
            peak = max(peak, tree_rss(proc.pid))
            time.sleep(.1)
    record = dict(workers=workers, seconds=round(time.monotonic()-start,3), peak_tree_rss_mb=round(peak/1024**2,1), returncode=proc.returncode, files=tests, head=head, python=sys.version.split()[0], app_module=app.__file__)
    if junit.exists():
        cases = []
        for case in ET.parse(junit).iter('testcase'):
            status = next((s for s in ['failure','error','skipped'] if case.find(s) is not None), 'passed')
            cases.append((case.get('classname'),case.get('name'),status))
        record['outcomes'] = {s:sum(c[2]==s for c in cases) for s in ['passed','failure','error','skipped']}
        record['outcome_hash'] = hashlib.sha256(json.dumps(sorted(cases)).encode()).hexdigest()
    results.append(record)
    filename = 'benchmark.json' if tag == 'bench' else f'{tag}.json'
    (output/filename).write_text(json.dumps(results,indent=2))
    print(json.dumps(record),flush=True)
    if proc.returncode: sys.exit(proc.returncode)
