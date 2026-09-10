"""Read-only numerical extraction and reproducible weekly summaries; no provider requests."""
import collections, datetime as dt, gzip, hashlib, json, pathlib, sqlite3, subprocess
p=pathlib.Path(__file__).resolve().parent
pid=int(subprocess.check_output(['systemctl','show','orchestra','-p','MainPID','--value']))
env=pathlib.Path(f'/proc/{pid}/environ').read_bytes().split(b'\0')
path=next(v.split(b'=',1)[1].decode() for v in env if v.startswith(b'ORCHESTRA_DB_PATH='))
c=sqlite3.connect('file:'+path+'?mode=ro',uri=True);c.row_factory=sqlite3.Row;c.execute('BEGIN')
turns=[dict(r) for r in c.execute('select id,ts,runtime,model,ok,stop_reason,cost_usd,cost_unaccounted,input_tokens,cache_read_tokens,cache_create_tokens,output_tokens from turn_usage order by ts,id')]
snaps=[dict(r) for r in c.execute('select * from usage_snapshots order by ts,id')]
c.rollback();c.close()
obj=dict(source=path,pid=pid,captured_at=dt.datetime.now(dt.timezone.utc).isoformat(),turns=turns,snapshots=snaps)
raw=json.dumps(obj,separators=(',',':')).encode()
with gzip.GzipFile(filename=str(p/'telemetry.json.gz'),mode='wb',mtime=0) as f:f.write(raw)
D=lambda s:dt.datetime.fromisoformat(s.replace('Z','+00:00'))
keys=['input_tokens','cache_read_tokens','cache_create_tokens','output_tokens']
def total(ts):
 vals=[sum(t[k] or 0 for t in ts) for k in keys]
 return dict(turns=len(ts),tokens=dict(zip(keys,vals)),cost_usd=sum(t['cost_usd'] or 0 for t in ts),unaccounted=sum(bool(t['cost_unaccounted']) for t in ts),zero_token_turns=sum(not any(t[k] for k in keys) for t in ts),models=dict(collections.Counter(t['model'] for t in ts)),api_1h=sum(a*b for a,b in zip(vals,[5,.5,10,25]))/1e6,api_5m=sum(a*b for a,b in zip(vals,[5,.5,6.25,25]))/1e6)
weeks=[]
for day in [4,11,18,25]:
 start=dt.datetime(2026,8,day,7,tzinfo=dt.timezone.utc);end=start+dt.timedelta(days=7)
 weeks.append((start,end))
start=dt.datetime(2026,9,1,7,tzinfo=dt.timezone.utc);weeks.append((start,start+dt.timedelta(days=7)))
result=dict(source=path,captured_at=obj['captured_at'],sha256=hashlib.sha256(raw).hexdigest(),claude=[],codex=[],provider_shapes={})
for start,end in weeks:
 ss=[s for s in snaps if start<=D(s['ts'])<end and str(s['seven_day_resets_at']).startswith(end.date().isoformat()) and s['seven_day_pct'] is not None]
 tt=[t for t in turns if t['runtime']=='claude' and start<=D(t['ts'])<end]
 a=total(tt);a.update(start=start.isoformat(),end=end.isoformat(),snapshots=len(ss),first={k:ss[0][k] for k in ['ts','seven_day_pct']},last={k:ss[-1][k] for k in ['ts','seven_day_pct']},max_gap_minutes=max((D(b['ts'])-D(a['ts'])).total_seconds()/60 for a,b in zip(ss,ss[1:])),saturated_snapshots=sum(s['seven_day_pct']>=100 for s in ss))
 a['api_per_full_delta']=a['api_1h']*100/(ss[-1]['seven_day_pct']-ss[0]['seven_day_pct'])
 a['api_per_full_from_zero']=a['api_1h']*100/ss[-1]['seven_day_pct']
 result['claude'].append(a)
cw=collections.defaultdict(list);shapes=collections.Counter()
for s in snaps:
 j=json.loads(s['provider_usage'] or '{}')
 for provider,v in j.items():
  for w in v.get('windows',[]):shapes[(provider,w.get('id'),w.get('window_minutes'))]+=1
 for w in j.get('codex',{}).get('windows',[]):
  if w.get('window_minutes')==10080 and w.get('resets_at'):cw[w['resets_at']].append(dict(ts=s['ts'],pct=w['utilization'],plan=j['codex'].get('plan_type')))
result['provider_shapes']=[dict(provider=k[0],id=k[1],minutes=k[2],count=v) for k,v in shapes.items()]
# Group reset timestamps to date; retain raw reset variants to expose drift.
cd=collections.defaultdict(list)
for reset,ss in cw.items():cd[reset[:10]].append((reset,ss))
for day,groups in sorted(cd.items()):
 ss=sorted([s for _,g in groups for s in g],key=lambda s:s['ts']);resets=sorted(r for r,_ in groups);end=D(resets[-1]);start=end-dt.timedelta(days=7)
 tt=[t for t in turns if t['runtime']=='codex' and start<=D(t['ts'])<end];a=total(tt)
 a.pop('api_1h');a.pop('api_5m');a.update(reset_variants=resets,start=start.isoformat(),end=end.isoformat(),first=ss[0],last=ss[-1],snapshots=len(ss),plans=dict(collections.Counter(s['plan'] for s in ss)))
 result['codex'].append(a)
(p/'measurements.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(result,ensure_ascii=False,indent=2))
