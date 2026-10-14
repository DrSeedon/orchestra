import csv
import datetime as dt
import json
import re
import sqlite3
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

OUT=Path(__file__).resolve().parent
source=subprocess.run(['git','show','e303361d:.orchestra/tasks/V-840/evidence/tool_calls_7d.csv'],capture_output=True,text=True,check=True).stdout
prior_calls=list(csv.DictReader(source.splitlines()))
calls=[r for r in prior_calls if r['tool_name']=='Bash']
c=sqlite3.connect('file:/home/kesha/orchestra/data/orchestra.db?mode=ro',uri=True);c.row_factory=sqlite3.Row
c.execute('PRAGMA query_only=ON');c.execute('BEGIN')

def parsed_input(content):
    try:return json.loads(content[content.index('{'):])
    except (ValueError,json.JSONDecodeError):return {}

def safe(s):
    s=re.sub(r'(?i)([\w.-]*(?:token|secret|password|passwd|api[_-]?key|authorization|cookie)[\w.-]*\s*[=:]\s*)(["\']?)[^\s,;"\']+',r'\1[REDACTED]',s)
    s=re.sub(r'(?i)(Bearer\s+)[A-Za-z0-9._~-]+',r'\1[REDACTED]',s)
    s=re.sub(r'https?://[^\s/@:]+:[^\s/@]+@','https://[REDACTED]@',s)
    s=re.sub(r'/home/kesha/[^\s\"\']+','<workspace-path>',s)
    return s.replace('\n',' ')[:260].rstrip()

def labels(text):
    t=text.lower()
    out=[]
    for label,patterns in {
        'ci':['gh-clean run','gh run','github actions','workflow run','ci '],
        'restart':['systemctl restart','restart orchestra','after restart','api/health'],
        'quota_or_rate_limit':['rate limit','quota','429','resets at','rate_limit'],
        'other_worker':['worker_wip','get_worker_logs','list_agents','send_message','merge_worker','other agent','worker '],
        'network_service':['curl ','wget ','http://','https://','localhost:'],
        'process_or_output':['ps ','pgrep ','tail ','wc -l','output','.log','pid'],
    }.items():
        if any(p in t for p in patterns):out.append(label)
    return out

def classify(command,prior_flags,prev_tool,next_tool,subagent_wait):
    t=command.lower()
    shell_sleep=re.search(r'(^|[;&|]\s*)sleep\s+\d+(?:\.\d+)?',t)
    if shell_sleep and subagent_wait and re.search(r'/tmp/claude[^ ]*/.*tasks/.*output',t):return 'Claude subagent result polling'
    if shell_sleep and any(x in t for x in ('gh-clean run','gh run','github actions','workflow run')):return 'CI result polling'
    if shell_sleep and ('systemctl restart' in t or 'restart orchestra' in t):return 'service restart wait'
    if shell_sleep and ('api/health' in t or 'mainpid' in t or 'curl 127.0.0.1:8888' in t) and 'restart' in prior_flags:return 'service readiness after restart'
    if shell_sleep and re.search(r'\bquota\b|rate[_-]?limit|resetsat|429|five_hour|seven_day',t):return 'rate/quota polling'
    agent_tools=('mcp__orchestra__worker_wip','mcp__orchestra__get_worker_logs','mcp__orchestra__list_agents','mcp__orchestra__message_delivery_status')
    if next_tool in agent_tools or (any(w in prior_flags for w in ('wait','worker')) and next_tool in ('mcp__orchestra__merge_worker','mcp__orchestra__send_message')):return 'another worker/agent'
    if 'time.sleep(' in t or 'asyncio.sleep(' in t:
        if any(x in t for x in ('urllib','httpx','requests.','urlopen','curl ')):return 'remote API pacing/retry in script'
        if any(x in t for x in ('pytest','test_','assert ')):return 'test-embedded delay'
        return 'Python-embedded delay'
    if re.search(r'(?:kill|terminate).{0,100}sleep\s+1(?:\.0+)?\s*;\s*ps',t):return 'short process-exit check'
    if re.search(r'(^|[;&|]\s*)sleep\s+\d',t):
        if any(x in t for x in ('tail ','ps ','pgrep ','wc -l','grep ','cat ','output','pid','ls ','stat ','find ')):return 'own process/log polling'
        if any(x in t for x in ('curl ','wget ','http://','https://')):return 'remote service/network polling'
        return 'explicit shell delay, target unclear'
    return 'sleep text inside script/command; intent unclear'

out=[]
for row in calls:
    event=c.execute('SELECT content FROM logs WHERE id=?',(int(row['call_id']),)).fetchone()
    if not event:continue
    payload=parsed_input(event['content']);command=str(payload.get('command') or '')
    command_lower=command.lower()
    sleep_match=bool(re.search(r'(^|[;&| ])sleep\s+\d|time\.sleep\(|await asyncio\.sleep',command_lower))
    shell_sleep=bool(re.search(r'(^|[;&| ]*)sleep\s+\d',command_lower))
    embedded_sleep=bool(re.search(r'time\.sleep\(|await asyncio\.sleep',command_lower))
    if not sleep_match:continue
    sid=row['session_id'];cid=int(row['call_id']);rid=int(row['result_id'])
    previous=c.execute('SELECT id,ts,type,tool_name,content FROM logs WHERE session_id=? AND id<? ORDER BY id DESC LIMIT 8',(sid,cid)).fetchall()
    following=c.execute('SELECT id,ts,type,tool_name,content FROM logs WHERE session_id=? AND id>? ORDER BY id LIMIT 8',(sid,rid)).fetchall()
    adjacent=list(reversed(previous))+list(following)
    ctx=' '.join(str(x['content'] or '') for x in adjacent)
    prior_text=next((str(x['content'] or '') for x in previous if x['type'] in ('text','user_message')), '')
    prior_flags=labels(prior_text)
    prior_lower=prior_text.lower()
    for flag,pat in {'wait':r'\b(wait|waiting|жду|ожида|подожд)', 'worker':r'\b(worker|agent|воркер|агент)', 'restart':r'\b(restart|перезапуск|рестарт)', 'ci':r'\bci\b|github actions', 'quota':r'\bquota\b|лимит|rate.?limit'}.items():
        if re.search(pat,prior_lower) and flag not in prior_flags:prior_flags.append(flag)
    prev_tool=next((str(x['tool_name'] or '') for x in previous if x['type']=='tool'), '')
    next_tool=next((str(x['tool_name'] or '') for x in following if x['type']=='tool'), '')
    result_ts=c.execute('SELECT ts FROM logs WHERE id=?',(rid,)).fetchone()
    subagent_wait=False
    if result_ts:
        subagent_wait=bool(c.execute("SELECT 1 FROM logs WHERE session_id=? AND type='subagent_start' AND ts BETWEEN ? AND ? LIMIT 1",(sid,row['call_ts'],result_ts['ts'])).fetchone())
    reason=classify(command,prior_flags,prev_tool,next_tool,subagent_wait)
    sess=c.execute('SELECT name,scope,model,backend_type,role,pipeline,task_id,disabled_tools,system_prompt,prompt_overlay FROM sessions WHERE id=?',(sid,)).fetchone()
    if sess:
        allprompt=((sess['system_prompt'] or '')+' '+(sess['prompt_overlay'] or '')).lower()
        prompt_has={
            'prompt_has_bg_create':'bg_create' in allprompt,
            'prompt_has_sleep_rule':bool(re.search(r'never.{0,25}sleep|do not sleep|dont sleep|не спи',allprompt)),
            'prompt_has_poll_rule':bool(re.search(r'never.{0,25}poll|do not poll|не опрашива',allprompt)),
        }
        try:disabled=json.loads(sess['disabled_tools'] or '[]')
        except (TypeError,json.JSONDecodeError):disabled=[]
        tools_disabled_bg='bg_create' in disabled
        name=sess['name'];scope=sess['scope'];model=sess['model'];runtime=sess['backend_type'];role=sess['role'];pipeline=sess['pipeline'];task_id=sess['task_id']
    else:
        prompt_has={k:False for k in ('prompt_has_bg_create','prompt_has_sleep_rule','prompt_has_poll_rule')}
        tools_disabled_bg=False;name=scope=model=runtime=role=pipeline=task_id=''
    slept=re.findall(r'(?i)(?:^|[;&|]\s*)sleep\s+(\d+(?:\.\d+)?)',command)
    out.append({'call_id':cid,'result_id':rid,'session_id':sid,'session_name':name,'scope':scope,'project':Path(scope).name if scope else '',
      'model':model,'runtime':runtime,'role':role,'pipeline':pipeline,'task_id':task_id,'call_ts':row['call_ts'],
      'tool_duration_s':float(row['duration_s']),'sleep_seconds':sum(float(x) for x in slept),'sleep_count_in_command':len(slept),
      'sleep_kind':'shell' if shell_sleep else 'python_embedded','reason':reason,
      'context_flags':','.join(labels(ctx)),'followup_types':','.join(f"{x['type']}:{x['tool_name'] or ''}" for x in following),
      'previous_tool':prev_tool,'next_tool':next_tool,'prior_message_flags':','.join(prior_flags),
      'subagent_started_during_call':subagent_wait,
      'bg_create_disabled':tools_disabled_bg,**prompt_has,
      'command_sanitized':safe(command)})

fields=list(out[0]) if out else []
with (OUT/'sleep_calls_7d.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(out)
counts=defaultdict(list)
for r in out:counts[(r['reason'],r['runtime'],r['project'])].append(r)
with (OUT/'sleep_reason_summary_7d.csv').open('w',newline='') as f:
    w=csv.writer(f);w.writerow(['reason','runtime','project','calls','sleep_hours','median_tool_seconds','prompt_bg_create_calls','prompt_explicit_sleep_rule_calls','bg_create_disabled_calls'])
    for (reason,runtime,project),items in sorted(counts.items(),key=lambda x:-sum(r['sleep_seconds'] for r in x[1])):
        vals=sorted(r['tool_duration_s'] for r in items)
        w.writerow([reason,runtime,project,len(items),round(sum(r['sleep_seconds'] for r in items)/3600,3),vals[len(vals)//2],sum(r['prompt_has_bg_create'] for r in items),sum(r['prompt_has_sleep_rule'] for r in items),sum(r['bg_create_disabled'] for r in items)])
print('sleep_calls_classified',len(out),'by_reason')
for (reason,runtime,project),items in sorted(counts.items(),key=lambda x:-sum(r['sleep_seconds'] for r in x[1])):
    print(json.dumps({'reason':reason,'runtime':runtime,'project':project,'calls':len(items),'sleep_hours':round(sum(r['sleep_seconds'] for r in items)/3600,3),
      'prompt_bg_create':sum(r['prompt_has_bg_create'] for r in items),'prompt_sleep_rule':sum(r['prompt_has_sleep_rule'] for r in items),'bg_disabled':sum(r['bg_create_disabled'] for r in items),
      'examples':[{'session':r['session_name'],'ts':r['call_ts'],'duration':round(r['tool_duration_s'],1),'command':r['command_sanitized']} for r in sorted(items,key=lambda r:-r['tool_duration_s'])[:2]]},ensure_ascii=False))
c.rollback();c.close()
