"""Audit resets before interpreting API-equivalent per subscription pool."""
import collections,datetime as dt,gzip,json,pathlib,statistics
p=pathlib.Path(__file__).resolve().parent
j=json.load(gzip.open(p/'telemetry.json.gz'));ss=j['snapshots'];tt=j['turns']
D=lambda s:dt.datetime.fromisoformat(s.replace('Z','+00:00'))
def totals(turns):
 keys=['input_tokens','cache_read_tokens','cache_create_tokens','output_tokens'];v=[sum(t[k] or 0 for t in turns) for k in keys]
 # Reprice two historical Haiku rows at Haiku 4.5 rates instead of Opus.
 api=sum(a*b for a,b in zip(v,[5,.5,10,25]))/1e6
 five=sum(a*b for a,b in zip(v,[5,.5,6.25,25]))/1e6
 for t in turns:
  if 'haiku' in t['model']:
   api-=sum((t[k] or 0)*a for k,a in zip(keys,[4,.4,8,20]))/1e6
   five-=sum((t[k] or 0)*a for k,a in zip(keys,[4,.4,5,20]))/1e6
 return dict(n=len(turns),tokens=dict(zip(keys,v)),api_1h=api,api_5m=five,read_api=v[1]*.5/1e6,cost_usd=sum(t['cost_usd'] or 0 for t in turns),unaccounted=sum(bool(t['cost_unaccounted']) for t in turns),zero_tokens=sum(not any(t[k] for k in keys) for t in turns),zero_cost_with_tokens=sum(t['cost_usd']==0 and any(t[k] for k in keys) for t in turns),models=dict(collections.Counter(t['model'] for t in turns)))
result={'claude_weeks':[],'codex_calendar':[]}
for date in ['2026-08-04','2026-08-11','2026-08-18','2026-08-25','2026-09-01']:
 start=D(date+'T07:00:00+00:00');end=start+dt.timedelta(days=7)
 snaps=[s for s in ss if start<=D(s['ts'])<end and s['seven_day_resets_at'].startswith(end.date().isoformat()) and s['seven_day_pct'] is not None]
 turns=[t for t in tt if t['runtime']=='claude' and start<=D(t['ts'])<end]
 drops=[dict(before=a['ts'],after=b['ts'],from_pct=a['seven_day_pct'],to_pct=b['seven_day_pct']) for a,b in zip(snaps,snaps[1:]) if b['seven_day_pct']<a['seven_day_pct']]
 positive=sum(max(0,b['seven_day_pct']-a['seven_day_pct']) for a,b in zip(snaps,snaps[1:]))
 z=totals(turns);z.update(start=start.isoformat(),end=end.isoformat(),drops=drops,positive_pp=positive,from_zero_pp=positive+snaps[0]['seven_day_pct'],first=snaps[0]['ts'],first_pct=snaps[0]['seven_day_pct'],last=snaps[-1]['ts'],last_pct=snaps[-1]['seven_day_pct'],first_saturation=next((s['ts'] for s in snaps if s['seven_day_pct']==100),None),max_gap_min=max((D(b['ts'])-D(a['ts'])).total_seconds()/60 for a,b in zip(snaps,snaps[1:])))
 z['conditional_api_per_100pp']=z['api_1h']*100/z['from_zero_pp'];result['claude_weeks'].append(z)
 ts=[t for t in tt if t['runtime']=='codex' and 'spark' not in t['model'] and start<=D(t['ts'])<end]
 z=totals(ts)
 for k in ['api_1h','api_5m','read_api']:z.pop(k)
 z.update(start=start.isoformat(),end=end.isoformat());result['codex_calendar'].append(z)
start='2026-08-16T07:20:43.838690+00:00';end='2026-08-23T07:26:17.051280+00:00'
z=totals([t for t in tt if t['runtime']=='codex' and 'spark' not in t['model'] and start<t['ts']<=end]);z.update(start=start,end=end)
for k in ['api_1h','api_5m','read_api']:z.pop(k)
result['codex_stable_observed_cycle']=z
result['anomaly_sensitivity']={'previous_week_excluding_16pp':result['claude_weeks'][3]['api_1h']/0.84,'sep_week_179pp':result['claude_weeks'][4]['api_1h']/1.79}
result['clean_monotonic_3week_summary']={'min':min(z['api_1h'] for z in result['claude_weeks'][:3]),'max':max(z['api_1h'] for z in result['claude_weeks'][:3]),'mean':statistics.mean(z['api_1h'] for z in result['claude_weeks'][:3]),'median':statistics.median(z['api_1h'] for z in result['claude_weeks'][:3])}
(p/'analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False,indent=2))
