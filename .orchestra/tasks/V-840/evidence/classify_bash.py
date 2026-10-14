import csv
import json
import math
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

OUT=Path(__file__).resolve().parent
rows=[r for r in csv.DictReader((OUT/'tool_calls_7d.csv').open()) if r['tool_name']=='Bash']
c=sqlite3.connect('file:/home/kesha/orchestra/data/orchestra.db?mode=ro',uri=True);c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON')
groups=defaultdict(list)
for r in rows:
    rec=c.execute('SELECT content FROM logs WHERE id=?',(int(r['call_id']),)).fetchone()
    text=rec['content'] if rec else ''
    m=re.search(r'Bash:\s*(\{.*)',text,re.S)
    try: command=json.loads(m.group(1)).get('command','') if m else text
    except (ValueError,json.JSONDecodeError): command=text
    low=command.lower()
    if re.search(r'(^|[;&| ])sleep\s+\d|time\.sleep\(|await asyncio\.sleep',low): situation='sleep/wait'
    elif any(x in low for x in ('runserver','uvicorn','npm run dev','vite --host','http.server')): situation='foreground server/process'
    elif any(x in low for x in ('pytest ','npm test','pnpm test','node --test','playwright test')): situation='tests/checks'
    elif any(x in low for x in ('git worktree','sparse-checkout','sparse_convert.py')): situation='worktree/copy'
    elif any(x in low for x in ('curl ','wget ','http://','https://')): situation='network/http'
    elif any(x in low for x in ('fio ','dd if=','iostat','vmstat')): situation='disk/measurement'
    elif re.search(r'(^|[ /])(ffmpeg|manim|blender)(\s|$)',low) or any(x in low for x in ('npm run build','pnpm build','vite build','build_script.py','render_script.py','render.py')): situation='build/render'
    elif any(x in low for x in ('sqlite','orchestra.db','sql ')): situation='database'
    elif any(x in low for x in ('git status','git diff','git log','git show','git branch')): situation='git inspection'
    elif any(re.search(r'(^|[;&| ])'+re.escape(x)+r'(\s|$)',low) for x in ('rg','grep','find','sed','cat')): situation='file/search'
    elif re.search(r'(^|[;&| ])(python|python3|node)\b',low): situation='custom Python/Node scripts'
    else: situation='other shell'
    groups[(r['runtime'],situation)].append((float(r['duration_s']),r,command))

def scrub(value):
    value=re.sub(r'(?i)([\w.-]*(?:token|secret|password|passwd|api[_-]?key|authorization|cookie)[\w.-]*\s*[=:]\s*)(["\']?)[^\s,;"\']+',r'\1[REDACTED]',value)
    value=re.sub(r'(?i)(Bearer\s+)[A-Za-z0-9._~-]+',r'\1[REDACTED]',value)
    value=re.sub(r'https?://[^\s/@:]+:[^\s/@]+@','https://[REDACTED]@',value)
    value=re.sub(r'/home/kesha/[^\s\"\']+','<workspace-path>',value)
    return value.replace('\n',' ')[:240].rstrip()

turns=json.loads((OUT/'tool_summary_7d.json').read_text())['turn_wall_seconds_sum']
result=[]
for (runtime,situation),items in groups.items():
    vals=sorted(x[0] for x in items)
    example=max(items,key=lambda x:x[0])
    def pct(p): return vals[max(0,math.ceil(len(vals)*p)-1)]
    result.append({'tool':'Bash','situation':situation,'runtime':runtime,'count':len(vals),
      'p50_s':pct(.5),'p90_s':pct(.9),'p99_s':pct(.99),'sum_s':sum(vals),
      'share_of_all_turn_seconds_pct':100*sum(vals)/turns if turns else '',
      'example_session_id':example[1]['session_id'],'example_call_ts':example[1]['call_ts'],
      'example_duration_s':example[0],'example_command_sanitized':scrub(example[2])})
result.sort(key=lambda r:r['sum_s'],reverse=True)
with (OUT/'bash_situation_summary_7d.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(result[0]));w.writeheader();w.writerows(result)
for r in result[:14]:print(json.dumps(r,ensure_ascii=False))
c.rollback();c.close()
