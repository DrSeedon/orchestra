import json,glob,collections,re,math
R='/home/kesha/orchestra/.orchestra/private/V-1098/runs/'
rows=[]
for d in sorted(glob.glob(R+'main-*/arms/*')):
    run=d.split('runs/')[1].split('/')[0]; arm=d.rsplit('/',1)[1]
    r=json.load(open(d+'/result.json')); p=r.get('process',{}); a=p.get('accounting',{})
    out=open(d+'/execution/stdout.jsonl').read() if True else ''
    quota='hit your usage limit' in out and '"turn.failed"' in out
    try: o=json.loads(open(d+'/oracle/execution/stdout.jsonl').read().strip().splitlines()[-1])
    except Exception: o={}
    u=a.get('usage',{})
    rows.append(dict(run=run,task=run.split('-',2)[2],rep=run.split('-')[1],arm=arm,valid=r.get('valid',True) and not quota and not r.get('error'),quota=quota,
      passed=r.get('oracle_pass',False),secs=p.get('wall_seconds'),cost=a.get('cost_usd'),inp=u.get('input_tokens'),out=u.get('output_tokens'),
      calls=o.get('tool_calls'),inv=o.get('invalid_citations'),fc=o.get('false_completion'),parsed=o.get('parsed'),score=o.get('check_score'),
      viol=(r.get('audit') or {}).get('violations'),oos=r.get('out_of_scope'),exit=p.get('returncode'),compl=p.get('completion')))
json.dump(rows,open(R+'../main-summary.json','w'),indent=1)
def wilson(k,n):
    if n==0: return (0,0)
    z=1.96;ph=k/n;d=1+z*z/n;c=ph+z*z/(2*n);m=z*math.sqrt(ph*(1-ph)/n+z*z/(4*n*n));return ((c-m)/d,(c+m)/d)
arms=['terra-high','terra-xhigh','luna-high']
print('runs',len(rows),'invalid',[(r['run'],r['arm'],r['quota'],r['viol']) for r in rows if not r['valid']])
def med(x): x=sorted(v for v in x if v is not None); return x[len(x)//2] if x else None
for a in arms:
    rs=[r for r in rows if r['arm']==a and r['valid']]; k=sum(r['passed'] for r in rs); lo,hi=wilson(k,len(rs))
    print(f"{a}: valid {len(rs)} pass {k} ({k/len(rs):.0%}, 95%CI {lo:.0%}-{hi:.0%}) med_s {med([r['secs'] for r in rs]):.1f} mean_cost {sum(r['cost'] for r in rs)/len(rs):.4f} total_cost {sum(r['cost'] for r in rs):.3f} med_calls {med([r['calls'] for r in rs])} inv_cit {sum(r['inv'] or 0 for r in rs)} false_compl {sum(bool(r['fc']) for r in rs)} unparsed {sum(not r['parsed'] for r in rs)} out_tok_med {med([r['out'] for r in rs])} in_tok_med {med([r['inp'] for r in rs])} mean_score {sum(r['score'] or 0 for r in rs)/len(rs):.2f}")
print('per task pass (k/n):')
for t in sorted({r['task'] for r in rows}):
    print(t,{a:f"{sum(r['passed'] for r in rows if r['task']==t and r['arm']==a and r['valid'])}/{sum(1 for r in rows if r['task']==t and r['arm']==a and r['valid'])}" for a in arms})
