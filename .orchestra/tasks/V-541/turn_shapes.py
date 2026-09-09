"""Offline shapes of existing short turns, not keepalive experiments."""
import datetime as dt, gzip, json, pathlib, statistics as st
P=pathlib.Path(__file__).resolve().parent;D=json.load(gzip.open(P/'telemetry.json.gz'));T=D['turns'];S=D['snapshots']
def ts(s):return dt.datetime.fromisoformat(s).timestamp()
# Frozen IDs were resolved by a read-only join to the persistent orchestrator; replay is offline.
ids=set(json.loads((P/'orchestrator_turn_ids.json').read_text()))
prev={};rows=[]
for r in T:
 old=prev.get(r['session_id']);prev[r['session_id']]=r
 if old is None:continue
 gap=(ts(r['ts'])-ts(old['ts']))/60
 if r['id'] in ids and r['ts']>='2026-09-01' and 0<r['output_tokens']<=150 and r['input_tokens']<=100 and r['ok']:
  rows.append({**r,'gap_minutes':gap,'kind':'warm' if gap<=50 and r['cache_create_tokens']<10000 else 'cold' if gap>=65 and r['cache_create_tokens']>50000 else 'other'})
K=['input_tokens','cache_read_tokens','cache_create_tokens','output_tokens','cost_usd','gap_minutes']
out={'selection':'Orchestra-orchestrator, >=2026-09-01, ok, 0<output<=150, input<=100; warm gap<=50m and write<10K; cold gap>=65m and write>50K','rows':rows,'summary':{kind:{'n':len(rr),**{k:st.median(r[k] for r in rr) for k in K}} for kind in ['warm','cold','other'] if (rr:=[r for r in rows if r['kind']==kind])}}
(P/'turn_shapes.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out['summary'],indent=2))
print('cold rows',json.dumps([r for r in rows if r['kind']=='cold']))
print('warm last',json.dumps([r for r in rows if r['kind']=='warm'][-3:]))
# Show jumps, integer resolution, cached quota age, and cost defects in existing telemetry.
ss=[s for s in S if s['seven_day_pct'] is not None]
print('noninteger snapshots',sum(s['seven_day_pct']%1!=0 for s in ss),'of',len(ss))
ages=[ts(r['ts'])-ts(r['quota_sampled_at']) for r in T if r['quota_sampled_at']]
print('quota ages sec median/max',st.median(ages),max(ages))
print('cost zero despite positive tokens',sum((r['cost_usd'] or 0)==0 and sum(r[k] for k in K[:4])>0 for r in T))
print('token totals',[sum(r[k] for r in T) for k in K[:4]])
print('Sep1 changes',[(a['ts'],b['ts'],a['seven_day_pct'],b['seven_day_pct'],sum(a['ts']<r['ts']<=b['ts'] for r in T)) for a,b in zip(ss,ss[1:]) if b['ts'].startswith('2026-09-01') and b['seven_day_pct']!=a['seven_day_pct']][:12])
