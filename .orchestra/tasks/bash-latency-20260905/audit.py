"""Read-only, bounded log sample; emits aggregates, never command text or secrets."""
import collections
import datetime
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys

root = Path(sys.argv[1])
os.chdir(root)
c = sqlite3.connect(f"file:{root}/data/orchestra.db?mode=ro", uri=True)
c.execute("PRAGMA query_only=ON")
hi = c.execute("SELECT max(id) FROM logs").fetchone()[0]
lo = max(0, hi - 100000)
pending = {}
stats = collections.defaultdict(list)
counts = collections.Counter()
tools = collections.Counter()
categories = collections.defaultdict(list)
orchestra_categories = collections.defaultdict(list)
recent_orchestra = collections.defaultdict(list)
slow = []
scopes = dict(c.execute("SELECT id,scope FROM sessions"))
span = []
for ident, sid, ts, typ, tid, name, content in c.execute(
    "SELECT id,session_id,ts,type,tool_use_id,tool_name,"
    "CASE WHEN type='tool' THEN substr(content,1,12000) ELSE '' END "
    "FROM logs WHERE id>? AND id<=? ORDER BY id", (lo, hi)
):
    counts[typ] += 1
    if not span: span.append(ts)
    last_ts = ts
    if typ == 'tool':
        name = name or content.split(':', 1)[0]
        tools[name] += 1
        if tid:
            pending[sid, tid] = (ts, name, content)
    elif typ == 'tool_result' and tid:
        start = pending.pop((sid, tid), None)
        if start:
            a, name, command = start
            delta = (datetime.datetime.fromisoformat(ts.replace('Z','+00:00')) - datetime.datetime.fromisoformat(a.replace('Z','+00:00'))).total_seconds()
            if delta < 0:
                counts['negative_pairs'] += 1
                continue
            stats[name].append(delta)
            if name in ('Bash', 'exec_command', 'functions.exec_command'):
                category = 'other'
                for candidate, pattern in [('pytest', r'\bpytest\b'), ('search', r'\b(?:rg|grep|find)\b'), ('sleep', r'\bsleep\s+\d'), ('install', r'\b(?:pip|uv)\s+(?:add|sync|install)'), ('curl', r'\b(?:curl|wget)\b')]:
                    if re.search(pattern, command):
                        category = candidate
                        break
                categories[category].append(delta)
                if Path(scopes.get(sid, '')).name == 'orchestra':
                    orchestra_categories[category].append(delta)
                    if a >= '2026-08-29':
                        recent_orchestra[category].append(delta)
                if delta > 60:
                    slow.append(dict(log_id=ident, seconds=round(delta,2), category=category, orchestra=Path(scopes.get(sid, '')).name == 'orchestra', features=[x for x in ['pytest','sleep','curl','grep','find','rg ','git ','timeout','python','node','ssh','test_lock'] if x in command]))
                if category == 'pytest':
                    counts['pytest_mentions_tests_path'] += bool(re.search(r'pytest[^\n]*\btests/?(?:[\s"\\]|$)',command))
                if name == 'Bash':
                    counts['bash_has_shell_separator'] += any(x in command for x in ['&&', ';', '\\n'])

def summary(values):
    values = sorted(values)
    return dict(n=len(values), hours=round(sum(values)/3600,3), median_sec=round(values[len(values)//2],3), p95_sec=round(values[min(len(values)-1,int(len(values)*.95))],3), over30=sum(x>30 for x in values))

env_keys = []
if (root / '.env').exists():
    for line in (root / '.env').read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            env_keys.append(line.split('=',1)[0].strip())
proc = subprocess.run(['systemctl','show','orchestra','-p','MainPID','--value'], capture_output=True,text=True)
runtime_rg = 'unavailable'
if proc.stdout.strip().isdigit() and int(proc.stdout.strip()):
    try:
        raw = Path('/proc') / proc.stdout.strip() / 'environ'
        env = dict(x.split(b'=',1) for x in raw.read_bytes().split(b'\0') if b'=' in x)
        runtime_rg = shutil.which('rg', path=os.fsdecode(env.get(b'PATH',b'')))
    except PermissionError:
        runtime_rg = 'permission denied'
print(json.dumps(dict(root=str(root), head=subprocess.check_output(['git','-c',f'safe.directory={root}','rev-parse','HEAD'],text=True).strip(), cpu=os.cpu_count(), test_files=len(list((root/'tests').glob('test_*.py'))), xdist=bool(importlib.util.find_spec('xdist')), shell_rg=shutil.which('rg'), service_path_rg=runtime_rg, env_keys_read=len(env_keys), sample=dict(id_gt=lo,id_lte=hi, first_ts=span[0],last_ts=last_ts, counts=counts, tool_counts=tools, paired={k:summary(v) for k,v in stats.items() if k in ('Bash','exec_command','functions.exec_command')}, shell_categories={k:summary(v) for k,v in categories.items()}, orchestra_categories={k:summary(v) for k,v in orchestra_categories.items()}, recent_orchestra_since_20260829={k:summary(v) for k,v in recent_orchestra.items()}, slowest=sorted(slow,key=lambda x:x['seconds'],reverse=True)[:20], unmatched_starts=len(pending)), method='Last 100000 log ID positions, all projects; same-session tool_use_id pairs. Arrival timestamp intervals, not CPU time. Categories are command-text heuristics; composite commands overlap semantically.'), ensure_ascii=False,indent=2))
