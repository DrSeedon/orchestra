"""Offline exploratory regressions; standard library only. No provider calls."""
import bisect, collections, csv, datetime as dt, gzip, itertools, json, math, pathlib, random, statistics as st
P=pathlib.Path(__file__).resolve().parent
D=json.load(gzip.open(P/'telemetry.json.gz'))
def ts(v):return dt.datetime.fromisoformat(v.replace('Z','+00:00')).timestamp()
T=D['turns'];S=D['snapshots'];K=['input_tokens','cache_read_tokens','cache_create_tokens','output_tokens']
for r in T+S:r['time']=ts(r['ts'])
times=[r['time'] for r in T]
def solve(a,b):
 a=[list(row)+[v] for row,v in zip(a,b)];n=len(b)
 for i in range(n):
  k=max(range(i,n),key=lambda k:abs(a[k][i]));a[i],a[k]=a[k],a[i]
  if abs(a[i][i])<1e-12:raise ValueError('singular')
  v=a[i][i];a[i]=[z/v for z in a[i]]
  for k in range(n):
   if k!=i:
    v=a[k][i];a[k]=[z-v*w for z,w in zip(a[k],a[i])]
 return [r[-1] for r in a]
def ols(X,y):
 p=len(X[0]);sc=[math.sqrt(sum(r[j]**2 for r in X)) or 1 for j in range(p)]
 z=[[v/s for v,s in zip(r,sc)] for r in X]
 b=solve([[sum(r[i]*r[j] for r in z) for j in range(p)] for i in range(p)],[sum(r[i]*v for r,v in zip(z,y)) for i in range(p)])
 return [v/s for v,s in zip(b,sc)]
def predict(X,b):return [sum(v*w for v,w in zip(r,b)) for r in X]
def fit(X,y):
 b=ols(X,y);pr=predict(X,b);sse=sum((v-w)**2 for v,w in zip(y,pr));sst=sum((v-st.mean(y))**2 for v in y)
 return {'coef':b,'rmse':math.sqrt(sse/len(y)),'r2':1-sse/sst if sst else None}
def nnls(X,y):
 p=len(X[0]);best=None
 for n in range(1,p+1):
  for ix in itertools.combinations(range(p),n):
   try:b=ols([[r[i] for i in ix] for r in X],y)
   except ValueError:continue
   if min(b)<0:continue
   full=[0.]*p
   for i,v in zip(ix,b):full[i]=v
   err=sum((v-w)**2 for v,w in zip(y,predict(X,full)))
   if best is None or err<best[0]:best=(err,full)
 return best[1]
def intervals(hours=3,shift=0):
 out=[];start=None;prev=None
 for r in S:
  q=r['seven_day_pct'];reset=(r['seven_day_resets_at'] or '')[:10]
  good=q is not None and 0<=q<100 and reset and r['time']>=times[0]
  broken=prev is not None and (r['time']-prev['time']>900 or reset!=(prev['seven_day_resets_at'] or '')[:10] or q is None or prev['seven_day_pct'] is None or q<prev['seven_day_pct'])
  if not good:start=None;prev=r;continue
  if start is None or broken:start=r
  if r['time']-start['time']>=hours*3600:
   a=bisect.bisect_right(times,start['time']-shift);b=bisect.bisect_right(times,r['time']-shift);tt=T[a:b]
   out.append({'start':start['ts'],'end':r['ts'],'day':start['ts'][:10],'reset':reset,'hours':(r['time']-start['time'])/3600,'delta':q-start['seven_day_pct'],'n':len(tt),'haiku':sum('haiku' in v['model'] for v in tt),'cost':sum(v['cost_usd'] or 0 for v in tt),**{k:sum(v[k] for v in tt)/1e6 for k in K}})
   start=r
  prev=r
 return out
allresults={}
for h in [1,3,6]:
 for shift in ([0,-300,-900,300,900] if h==3 else [0]):
  rows=intervals(h,shift);use=[r for r in rows if r['n'] and not r['haiku'] and sum(r[k] for k in K)>0]
  X=[[r[k] for k in K] for r in use];y=[r['delta'] for r in use]
  res={'n':len(use),'quota_sum':sum(y),'tokens_M':[sum(r[k] for r in use) for k in K],'zero_turn_positive': [r for r in rows if not r['n'] and r['delta']>0],'ols':fit(X,y),'nnls':nnls(X,y),'api_cost':fit([[r['cost']] for r in use],y),'free_cache_equal_write_input_output5':fit([[r[K[0]]+r[K[2]]+5*r[K[3]]] for r in use],y),'ols_intercept':fit([[1]+r for r in X],y),'api_1h_recomputed':fit([[5*r[K[0]]+.5*r[K[1]]+10*r[K[2]]+25*r[K[3]]] for r in use],y),'api_5m_recomputed':fit([[5*r[K[0]]+.5*r[K[1]]+6.25*r[K[2]]+25*r[K[3]]] for r in use],y),'no_read':fit([[r[k] for k in K if k!='cache_read_tokens'] for r in use],y)}
  if h==3 and shift==0:
   with (P/'intervals.csv').open('w') as f:
    w=csv.DictWriter(f,fieldnames=rows[0],lineterminator="\n");w.writeheader();w.writerows(rows)
   rng=random.Random(541);days=sorted({r['day'] for r in use});byday={d:[r for r in use if r['day']==d] for d in days};boots=[]
   for _ in range(400):
    sample=[r for d in rng.choices(days,k=len(days)) for r in byday[d]]
    try:boots.append(ols([[r[k] for k in K] for r in sample],[r['delta'] for r in sample]))
    except ValueError:pass
   res['day_bootstrap_95']=[[sorted(b[i] for b in boots)[int(.025*len(boots))],sorted(b[i] for b in boots)[int(.975*len(boots))]] for i in range(4)]
   res['by_reset']={}
   for d in sorted({r['reset'] for r in use}):
    rr=[r for r in use if r['reset']==d]
    if len(rr)>5:
     res['by_reset'][d]={'n':len(rr),'ols':fit([[r[k] for k in K] for r in rr],[r['delta'] for r in rr])}
   res['correlations']=[[st.correlation([r[a] for r in use],[r[b] for r in use]) for b in K] for a in K]
   # Whole days held out, three different hypotheses evaluated on identical folds.
   cv={k:[] for k in ['ols','no_read','api_cost','api_1h_recomputed','api_5m_recomputed','free_cache_equal_write_input_output5']}
   for day in days:
    tr=[r for r in use if r['day']!=day];te=[r for r in use if r['day']==day]
    for mode in cv:
     def features(r):
      if mode=='api_cost':return [r['cost']]
      if mode.startswith('api_'):return [5*r[K[0]]+.5*r[K[1]]+(10 if mode=='api_1h_recomputed' else 6.25)*r[K[2]]+25*r[K[3]]]
      if mode=='free_cache_equal_write_input_output5':return [r[K[0]]+r[K[2]]+5*r[K[3]]]
      return [r[k] for k in K if mode!='no_read' or k!='cache_read_tokens']
     b=ols([features(r) for r in tr],[r['delta'] for r in tr]);cv[mode].extend((r['delta']-sum(v*w for v,w in zip(features(r),b)))**2 for r in te)
   res['heldout_day_rmse']={k:math.sqrt(st.mean(v)) for k,v in cv.items()}
  allresults[f'{h}h_shift{shift}']=res
(P/'regression.json').write_text(json.dumps(allresults,indent=2)+'\n')
for key,r in allresults.items():print(key,json.dumps({k:v for k,v in r.items() if k not in ['zero_turn_positive','by_reset','correlations']},ensure_ascii=False))
print('by_reset',json.dumps(allresults['3h_shift0']['by_reset']))
print('correlations',allresults['3h_shift0']['correlations'])
print('no-turn increases',[(r['start'],r['end'],r['delta']) for r in allresults['1h_shift0']['zero_turn_positive']])
