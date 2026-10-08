import json,glob,os,re
rows=[]
for d in sorted(glob.glob('runs/*')):
    l=os.path.basename(d)
    try: rt=open(d+'/run.txt').read()
    except: continue
    if 'done' not in rt: continue
    m=re.match(r'(hang|xh)-(\w+)-(\w+)-(\w+)-(r\d)',l)
    kind,task,eff,arm,rnd=m.groups()
    r=dict(label=l,kind=kind,task=task,eff=eff,arm=arm,rnd=rnd,sec=int(re.search(r'seconds=(\d+)',rt)[1]),linger='linger=1' in rt,timeout='timeout=1' in rt)
    try:
        j=json.load(open(d+'/result.json')); mu=j['modelUsage']
        r.update(cost=sum(v['costUSD'] for v in mu.values()),out=sum(v['outputTokens'] for v in mu.values()),api=j.get('duration_api_ms',0)/1000,
                 final=(j.get('result') or '')[:80])
        r['tps']=r['out']/r['api'] if r['api'] else None
    except Exception: r['nores']=True
    seen={}
    try:
        from datetime import datetime
        allr=[json.loads(l) for l in open(d+'/transcript.jsonl')]
        tss=[x['timestamp'] for x in allr if 'timestamp' in x]
        pt=lambda t: datetime.fromisoformat(t.replace('Z','+00:00')).timestamp()
        cut=pt(max(tss))-r['sec']-90
        allr=[x for x in allr if 'timestamp' not in x or pt(x['timestamp'])>=cut]
        for x in allr:
            mm=x.get('message') or {}
            if x.get('type')=='assistant' and 'usage' in mm: seen[mm.get('id') or x.get('uuid')]=mm['usage']
        ps=[u.get('input_tokens',0)+u.get('cache_read_input_tokens',0)+u.get('cache_creation_input_tokens',0) for u in seen.values()]
        r['reqs']=len(ps); r['over100k']=sum(p>100000 for p in ps)
        names=[b['name'] for x in allr for b in ((x.get('message') or {}).get('content') or []) if isinstance(b,dict) and b.get('type')=='tool_use']
        r['bg']=sum(n in('Monitor','ScheduleWakeup','CronCreate') for n in names)
    except Exception as e: pass
    t=open(d+'/oracle_tests.txt').read()
    pm=re.search(r'(\d+) passed',t); fm=re.search(r'(\d+) failed',t)
    r['oracle']=(int(pm[1]) if pm else 0, (int(fm[1]) if fm else 0))
    rows.append(r)
json.dump(rows,open('m2.json','w'),indent=1)
for r in rows: print(r['label'],r['sec'],'L' if r['linger'] else '', 'T' if r['timeout'] else '', round(r.get('cost',0),2),r.get('out'),r.get('reqs'),r.get('over100k'),'bg',r.get('bg'),r['oracle'],round(r['tps']) if r.get('tps') else None)
