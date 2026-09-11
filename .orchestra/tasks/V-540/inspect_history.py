"""Extract metadata only; never copy raw prompts or journal content into Git."""
import collections
import hashlib
import json
import re
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

baseline = json.loads(Path(__file__).with_name('baseline.jsonl').read_text().splitlines()[0])
c = sqlite3.connect(f"file:{baseline['db']}?mode=ro", uri=True)
c.row_factory = sqlite3.Row
sid='75285d62-98bc-441c-9727-22c54bd8ab97'
start,end=baseline['start_inclusive'],baseline['end_exclusive']
usage=list(c.execute("SELECT id,ts,cache_create_tokens,cache_read_tokens,cost_usd FROM turn_usage WHERE runtime='claude' AND session_id=? AND ts>=? AND ts<? ORDER BY ts",(sid,start,end)))
def dt(s):return datetime.fromisoformat(s.replace('Z','+00:00'))
events=[]
journal_count=0
journal_first=None
journal_last=None
p=subprocess.Popen(['journalctl','-u','orchestra','--since',start,'--until',end,'-o','json','--no-pager'],stdout=subprocess.PIPE,text=True)
for line in p.stdout:
 try:r=json.loads(line)
 except ValueError:continue
 journal_count+=1
 stamp=datetime.fromtimestamp(int(r['__REALTIME_TIMESTAMP'])/1e6,timezone.utc).isoformat()
 journal_first=journal_first or stamp
 journal_last=stamp
 msg=r.get('MESSAGE','')
 if '[Orchestra-orchestrator]' not in msg:continue
 for marker in ('hibernating','waking from hibernate','listener reconnected','compact started','compact succeeded','model change:','ClaudeBackend connect failed'):
  if marker in msg:
   events.append({'ts':datetime.fromtimestamp(int(r['__REALTIME_TIMESTAMP'])/1e6,timezone.utc).isoformat(),'event':marker});break
print('journal_rc',p.wait())
print('journal_coverage',json.dumps({'rows':journal_count,'first':journal_first,'last':journal_last}))
print('journal_events',json.dumps(events))
rows=[]
for i,u in enumerate(usage):
 prev=dt(usage[i-1]['ts']) if i else dt(start)
 current=dt(u['ts'])
 es=[e for e in events if prev<dt(e['ts'])<=current]
 rows.append({**dict(u),'gap_since_previous_turn_end_seconds':(current-prev).total_seconds() if i else None,'events_since_previous_turn_end':es})
print('turns',json.dumps(rows))
print('cross_tab',json.dumps(dict(collections.Counter(f"large={r['cache_create_tokens']>100000},lifecycle={bool(r['events_since_previous_turn_end'])}" for r in rows))))
meta=c.execute('SELECT session_id FROM sessions WHERE id=?',(sid,)).fetchone()
path=Path('/home/kesha/.claude/projects/-home-kesha-orchestra') / (meta[0]+'.jsonl')
requests={}; prompts=[]
for line in path.open():
 try:r=json.loads(line)
 except ValueError:continue
 message=r.get('message',{})
 if r.get('type')=='assistant':
  k=message.get('id')
  if k and k not in requests:
   u=message.get('usage',{})
   requests[k]={'ts':r.get('timestamp'),'request_id':r.get('requestId'),'model':message.get('model'),'usage':u}
 if r.get('type')=='user':
  content=message.get('content','')
  if isinstance(content,list):content='\n'.join(x.get('text','') for x in content if isinstance(x,dict))
  if content.startswith('[Orchestra platform note:'):
   body=content.split('\n',1)[1].split('\n\n---\n\n',1)[0]
   prompts.append({'ts':r.get('timestamp'),'sha256':hashlib.sha256(body.encode()).hexdigest(),'bytes':len(body.encode()),'worker_context_fields':re.findall(r'ctx:\d+%',body)})
print('native_session',meta[0])
print('reinjected_USER_prompts',json.dumps(prompts))
print('native_requests',json.dumps(list(requests.values())))
