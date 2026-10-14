import csv
import datetime as dt
import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

OUT=Path(__file__).resolve().parent
rows=list(csv.DictReader((OUT/'sleep_calls_7d.csv').open()))
embedded={r['call_id']:r['kind'] for r in csv.DictReader((OUT/'embedded_sleep_analysis.csv').open())}
c=sqlite3.connect('file:/home/kesha/orchestra/data/orchestra.db?mode=ro',uri=True);c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON')

def decode(s):
    try:return json.loads(s[s.index('{'):])
    except (ValueError,json.JSONDecodeError):return {}

def reason(command,row):
    t=command.lower()
    shell=re.search(r'(^|[;&|]\s*)sleep\s+(\d+(?:\.\d+)?)',t)
    if not shell:
        return ('Python embedded sleep syntax; execution unconfirmed'
                if embedded.get(row['call_id']) == 'executed_python_sleep_call'
                else 'embedded sleep reference; execution unconfirmed')
    before=t[:shell.start()]
    after=t[shell.end():]
    direct=' '.join(re.split(r'\s*(?:;|&&|\|\|)\s*',after)[:3])
    if any(x in direct for x in ('gh-clean run','gh run','github actions','workflow run')):return 'CI result polling'
    if any(x in before[-200:]+' '+direct for x in ('systemctl restart','restart orchestra','systemctl is-active','journalctl -u')):return 'service restart/readiness check'
    if re.search(r'\b(?:quota|429|resetsat|five_hour|seven_day)\b|rate[_-]limit',direct):return 'rate/quota polling'
    if re.search(r'/tmp/claude[^ ]*/.*tasks/.*output',t):
        call_ts=row['call_ts'];result=c.execute('SELECT ts FROM logs WHERE id=?',(int(row['result_id']),)).fetchone()
        if result:
            event=c.execute("SELECT 1 FROM logs WHERE session_id=? AND type='subagent_start' AND ts BETWEEN ? AND ? LIMIT 1",(row['session_id'],call_ts,result['ts'])).fetchone()
            if event:return 'Claude subagent output polling'
    if row.get('next_tool') in ('mcp__orchestra__worker_wip','mcp__orchestra__get_worker_logs','mcp__orchestra__list_agents'):
        return 'another worker/agent status'
    if re.search(r'select.{0,100}status.{0,100}from\s+sessions|sessions.{0,100}status',direct):return 'another session state polling'
    if re.search(r'(?:kill|terminate).{0,100}sleep\s+1(?:\.0+)?\s*;\s*ps',t):return 'short process-exit check'
    if any(x in after for x in ('tail ','ps ','pgrep ','wc -l','grep ','cat ','output','pid','ls ','stat ','test -e','test -s','find ')):return 'own process/output polling'
    if any(x in after for x in ('curl ','wget ','http://','https://')):return 'remote service/network polling'
    if any(x in t for x in ('pytest','ffmpeg','manim','render','uvicorn','runserver','nohup',' &')):return 'own long-running process/build'
    return 'explicit wait; target not visible in command'

for row in rows:
    rec=c.execute('SELECT content FROM logs WHERE id=?',(int(row['call_id']),)).fetchone()
    obj=decode(rec['content']) if rec else {}
    row['reason']=reason(str(obj.get('command') or ''),row)

with (OUT/'sleep_calls_7d.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
groups=defaultdict(list)
for row in rows:groups[(row['reason'],row['runtime'],row['project'])].append(row)
with (OUT/'sleep_reason_summary_7d.csv').open('w',newline='') as f:
    w=csv.writer(f);w.writerow(['reason','runtime','project','calls','tool_hours','literal_sleep_hours','p50_tool_s','p90_tool_s','p99_tool_s','prompt_bg_create_calls','prompt_sleep_rule_calls','bg_create_disabled_calls','example_session','example_ts','example_tool_seconds','example_command'])
    for (kind,runtime,project),items in sorted(groups.items(),key=lambda x:-sum(float(r['tool_duration_s']) for r in x[1])):
        values=sorted(float(r['tool_duration_s']) for r in items)
        def pct(p):return values[max(0,int(len(values)*p + .999999)-1)]
        ex=max(items,key=lambda r:float(r['tool_duration_s']))
        cmd=decode(c.execute('SELECT content FROM logs WHERE id=?',(int(ex['call_id']),)).fetchone()['content']).get('command','')
        cmd=re.sub(r'(?i)([\w.-]*(?:token|secret|password|authorization)[\w.-]*\s*[=:]\s*)[^\s,;]+',r'\1[REDACTED]',str(cmd))
        cmd=re.sub(r'/home/kesha/[^\s\"\']+','<workspace-path>',cmd).replace('\n',' ')[:220].rstrip()
        w.writerow([kind,runtime,project,len(items),round(sum(float(r['tool_duration_s']) for r in items)/3600,4),round(sum(float(r['sleep_seconds']) for r in items)/3600,4),pct(.5),pct(.9),pct(.99),sum(r['prompt_has_bg_create']=='True' for r in items),sum(r['prompt_has_sleep_rule']=='True' for r in items),sum(r['bg_create_disabled']=='True' for r in items),ex['session_name'],ex['call_ts'],ex['tool_duration_s'],cmd])
print('rows',len(rows),'reason_counts',len(groups))
for (kind,runtime,project),items in sorted(groups.items(),key=lambda x:-sum(float(r['tool_duration_s']) for r in x[1])):
 print(runtime,project,kind,len(items),round(sum(float(r['tool_duration_s']) for r in items)/3600,3),round(sum(float(r['sleep_seconds']) for r in items)/3600,3))
c.close()
