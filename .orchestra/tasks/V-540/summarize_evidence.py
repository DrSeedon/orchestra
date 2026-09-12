"""Reproducible metadata summary of historical Claude requests and byte differences."""
import collections
import hashlib
import json
import sqlite3
import subprocess
from datetime import datetime,timezone
from pathlib import Path
base=Path(__file__).parent
raw={k:json.loads(v) for k,v in (line.split(' ',1) for line in (base/'history.jsonl').read_text().splitlines()) if k!='native_session'}
meta=json.loads((base/'baseline.jsonl').read_text().splitlines()[0])
sid='75285d62-98bc-441c-9727-22c54bd8ab97'
c=sqlite3.connect(f"file:{meta['db']}?mode=ro",uri=True)
logs=c.execute("SELECT ts,type,content FROM logs WHERE session_id=? AND ts>=? AND ts<? AND type IN ('status','system','error') ORDER BY ts",(sid,meta['start_inclusive'],meta['end_exclusive'])).fetchall()
markers=('compact started','compact succeeded','listener reconnected','model change:','connect failed','zombie detected')
events=[{'ts':ts,'type':kind,'event':marker} for ts,kind,body in logs for marker in markers if marker in body]
print('db_lifecycle_events',json.dumps(events))
turns=raw['turns'];tab=collections.Counter()
for i,t in enumerate(turns):
 prev=turns[i-1]['ts'] if i else meta['start_inclusive']
 matching=[e for e in events if prev<e['ts']<=t['ts']]
 tab[f"large={t['cache_create_tokens']>100000},db_event={bool(matching)}"]+=1
print('db_cross_tab',json.dumps(dict(tab)))
path=Path('/home/kesha/.claude/projects/-home-kesha-orchestra/d32227c1-a7d1-422a-aaff-ca6ecfc79087.jsonl')
prompts=[]
for line in path.open():
 r=json.loads(line)
 if r.get('type')!='user':continue
 s=r.get('message',{}).get('content','')
 if isinstance(s,list):s='\n'.join(x.get('text','') for x in s if isinstance(x,dict))
 if s.startswith('[Orchestra platform note:'):
  body=s.split('\n',1)[1].split('\n\n---\n\n',1)[0].encode()
  prompts.append((r['timestamp'],body))
for (ta,a),(tb,b) in zip(prompts,prompts[1:]):
 if ta.startswith('2026-09-08T02:40') or ta.startswith('2026-09-08T15:43'):
  prefix=0
  while prefix<min(len(a),len(b)) and a[prefix]==b[prefix]:prefix+=1
  suffix=0
  while suffix<min(len(a),len(b))-prefix and a[len(a)-suffix-1]==b[len(b)-suffix-1]:suffix+=1
  delta_a=a[prefix:len(a)-suffix if suffix else len(a)]
  delta_b=b[prefix:len(b)-suffix if suffix else len(b)]
  print('USER_prompt_byte_difference',json.dumps({'from':ta,'to':tb,'sha256_a':hashlib.sha256(a).hexdigest(),'sha256_b':hashlib.sha256(b).hexdigest(),'common_prefix_bytes':prefix,'common_suffix_bytes':suffix,'old_changed_byte_count':len(delta_a),'new_changed_byte_count':len(delta_b),'old_bytes_hex':delta_a.hex() if len(delta_a)<30 else None,'new_bytes_hex':delta_b.hex() if len(delta_b)<30 else None}))
requests=raw['native_requests']
def dt(s):return datetime.fromisoformat(s.replace('Z','+00:00'))
large=[]
for prev,x in zip(requests,requests[1:]):
 if x['usage'].get('cache_creation_input_tokens',0)>100000:
  large.append({'ts':x['ts'],'previous_response_ts':prev['ts'],'response_gap_seconds':(dt(x['ts'])-dt(prev['ts'])).total_seconds(),**x['usage']})
print('native_large_requests',json.dumps(large))
print('native_counts',json.dumps({'requests':len(requests),'large_create_requests':len(large),'total_create':sum(x['usage'].get('cache_creation_input_tokens',0) for x in requests),'ephemeral_1h':sum(x['usage'].get('cache_creation',{}).get('ephemeral_1h_input_tokens',0) for x in requests),'ephemeral_5m':sum(x['usage'].get('cache_creation',{}).get('ephemeral_5m_input_tokens',0) for x in requests)}))
for p in Path('/proc').glob('[0-9]*/cmdline'):
 try:args=p.read_bytes().split(b'\0')
 except OSError:continue
 if b'd32227c1-a7d1-422a-aaff-ca6ecfc79087' not in args:continue
 system=args[args.index(b'--system-prompt')+1] if b'--system-prompt' in args else b''
 print('current_cli',json.dumps({'observed_at':datetime.now(timezone.utc).isoformat(),'pid':p.parent.name,'system_argument_bytes':len(system),'system_argument_sha256':hashlib.sha256(system).hexdigest(),'process_start':subprocess.check_output(['ps','-p',p.parent.name,'-o','lstart='],text=True).strip()}))
