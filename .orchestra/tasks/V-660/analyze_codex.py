"""Summarize Codex quota snapshots against turn usage; no live DB writes."""
import argparse, bisect, datetime as dt, json, math, pathlib, sqlite3, statistics
ROOT=pathlib.Path(__file__).resolve().parent
START='2026-08-03T00:00:00+00:00'
MODELS=['gpt-6-luna','gpt-6-sol','gpt-6-astra','gpt-5.6-luna','gpt-5.6-sol','gpt-5.6-astra','gpt-5.3-codex-spark']
# Current OpenAI standard-speed credit rates per MTok (input / cached input / output).
RATES={
 'gpt-6-luna':(2.5,.25,12.5), 'gpt-6-sol':(50,5,250), 'gpt-6-astra':(250,25,1250),
 'gpt-5.6-luna':(5,.5,30), 'gpt-5.6-sol':(100,10,500),
}
def stamp(s): return dt.datetime.fromisoformat(s.replace('Z','+00:00')).timestamp()
def key(m):
 m=m.lower()
 for x in MODELS:
  if x in m:return x
 return 'other'
def get_windows(db):
 c=sqlite3.connect(f'file:{db}?mode=ro',uri=True); c.row_factory=sqlite3.Row
 turns=[dict(r) for r in c.execute("SELECT ts,model,input_tokens,cache_read_tokens,output_tokens,cost_usd FROM turn_usage WHERE runtime='codex' AND ts>=? ORDER BY ts",(START,))]
 for t in turns:t['time']=stamp(t['ts']);t['model_key']=key(t['model'])
 times=[t['time'] for t in turns]
 samples=[]
 for r in c.execute("SELECT ts,provider_usage FROM usage_snapshots WHERE ts>=? AND provider_usage IS NOT NULL ORDER BY ts",(START,)):
  try:p=json.loads(r['provider_usage']).get('codex',{})
  except (ValueError,TypeError):continue
  plan=p.get('plan_type','unknown')
  for w in p.get('windows',[]):
   if w.get('id') not in ('primary','secondary') or w.get('utilization') is None:continue
   samples.append({'ts':r['ts'],'time':stamp(r['ts']),'window':w['id'],'q':float(w['utilization']),'reset':w.get('resets_at') or '', 'plan':plan})
 c.close()
 out=[]
 by={w:[] for w in ('primary','secondary')}
 for s in samples:by[s['window']].append(s)
 for win,ss in by.items():
  start=None;prev=None
  for r in ss:
   good=0<=r['q']<100 and r['reset']
   # `resets_at` is a sliding display timestamp on Codex, so it changes between
   # snapshots and cannot define a new window. Segment on plan changes, gaps,
   # and observed utilization decreases instead.
   broken=prev is not None and (r['time']-prev['time']>900 or r['plan']!=prev['plan'] or r['q']<prev['q'])
   if not good:start=None;prev=r;continue
   if start is None or broken:start=r
   if r['time']-start['time']>=10800:
    a=bisect.bisect_right(times,start['time']);b=bisect.bisect_right(times,r['time']);tt=turns[a:b]
    agg={m:{'input':0,'cached':0,'output':0,'cost_usd':0,'rows':0} for m in MODELS}
    for t in tt:
     m=t['model_key']
     if m=='other':continue
     inp=t['input_tokens'] or 0;cached=t['cache_read_tokens'] or 0;outtok=t['output_tokens'] or 0
     agg[m]['input']+=max(0,inp-cached);agg[m]['cached']+=cached;agg[m]['output']+=outtok;agg[m]['cost_usd']+=t['cost_usd'] or 0;agg[m]['rows']+=1
    credits={m:sum(agg[m][k]/1e6*r for k,r in zip(('input','cached','output'),RATES[m])) for m in MODELS if m in RATES}
    credit_total=sum(credits.values())
    total=sum(a['input']+a['cached']+a['output'] for a in agg.values())
    cost=sum(a['cost_usd'] for a in agg.values())
    pp=r['q']-start['q']
    row={'window':win,'plan':r['plan'],'start':start['ts'],'end':r['ts'],'day':start['ts'][:10],'hours':(r['time']-start['time'])/3600,'delta_pp':pp,'model_usage':agg,'tokens':total,'credit_rate_units':credit_total,'cost_usd':cost,'n':sum(a['rows'] for a in agg.values())}
    out.append(row);start=r
   prev=r
 return turns,samples,out

def one_x(rows,feature):
 x=[r[feature] for r in rows];y=[r['delta_pp'] for r in rows]
 den=sum(a*a for a in x);b=sum(a*v for a,v in zip(x,y))/den if den else None
 if b is None:return {'n':len(rows),'error':'zero predictor'}
 err=[v-b*a for a,v in zip(x,y)]
 return {'n':len(rows),'scale':b,'rmse':math.sqrt(statistics.mean(e*e for e in err)),'actual_pp':sum(y),'predicted_pp':sum(b*a for a in x)}

def main(db):
 turns,samples,allwins=get_windows(db)
 # Keep intervals with observed Codex activity; negative/zero deltas remain visible as counters.
 use=[r for r in allwins if r['n'] and r['tokens']>0]
 bymodel={}
 for m in MODELS:
  rows=[r for r in use if r['model_usage'][m]['rows']>0]
  sole=[r for r in rows if sum(v['rows'] for v in r['model_usage'].values())==r['model_usage'][m]['rows']]
  bymodel[m]={'turn_rows':sum(r['model_usage'][m]['rows'] for r in use),'input_uncached':sum(r['model_usage'][m]['input'] for r in use),'cached_input':sum(r['model_usage'][m]['cached'] for r in use),'output':sum(r['model_usage'][m]['output'] for r in use),'windows_with_model':len(rows),'sole_model_windows':len(sole),'sole_window_days':sorted({r['day'] for r in sole}),'plans_in_windows':sorted({r['plan'] for r in rows})}
 # All-plan observational aggregate; not a tariff estimate. Hold out the last three UTC dates.
 train=[r for r in use if r['day']<='2026-09-26'];test=[r for r in use if r['day']>='2026-09-27']
 metrics={}
 for feature in ('tokens','credit_rate_units','cost_usd'):
  metrics[feature]={'train':one_x(train,feature),'holdout':one_x(test,feature),'holdout_days':sorted({r['day'] for r in test})}
 split_metrics={}
 for win in ('primary','secondary'):
  tr=[r for r in train if r['window']==win];te=[r for r in test if r['window']==win]
  split_metrics[win]={}
  for feature in ('tokens','credit_rate_units','cost_usd'):
   split_metrics[win][feature]={'train':one_x(tr,feature),'holdout':one_x(te,feature),'train_plans':sorted({r['plan'] for r in tr}),'holdout_plans':sorted({r['plan'] for r in te})}
 # Per window details, retained as a transparent inspectable source for exclusions and attribution.
 out={'source_db':'provided SQLite backup','period':{'turns_start':turns[0]['ts'] if turns else None,'turns_end':turns[-1]['ts'] if turns else None,'snapshot_start':samples[0]['ts'] if samples else None,'snapshot_end':samples[-1]['ts'] if samples else None},'snapshot_points':len(samples),'three_hour_intervals':len(allwins),'activity_intervals':len(use),'codex_models':bymodel,'holdout_comparison':metrics,'holdout_by_window_type':split_metrics,'windows':allwins}
 (ROOT/'codex_analysis.json').write_text(json.dumps(out,indent=2,ensure_ascii=False)+'\n')
 for m,v in bymodel.items():print(m,json.dumps(v,ensure_ascii=False))
 print('holdout',json.dumps(metrics,ensure_ascii=False,indent=2))
 print('plus-post-reset')
 for r in allwins:
  if r['window']=='secondary' and r['plan']=='plus' and r['start']>='2026-09-26T14:34:35':
   active={m:a['rows'] for m,a in r['model_usage'].items() if a['rows']}
   print(r['start'],r['end'],r['delta_pp'],r['tokens'],r['credit_rate_units'],active)
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('db',help='SQLite backup created by backup_live_db.py');main(ap.parse_args().db)
