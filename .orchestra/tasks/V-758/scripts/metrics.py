import json,glob,os,re,statistics as st,sys
sys.path.insert(0,'.')
from ctx import calls
V='/home/kesha/orchestra/data/v656-bench/runs'
rows=[]
def share(label,base):
    d=os.path.expanduser(f'~/.claude/projects/-home-kesha-orchestra-data-{base}-{label}')
    us=calls(glob.glob(d+'/*.jsonl'))
    if not us: return None,None
    ps=[u.get('input_tokens',0)+u.get('cache_read_input_tokens',0)+u.get('cache_creation_input_tokens',0) for u in us]
    return len(us), sum(p>100000 for p in ps)
def tshare(path):
    if not os.path.exists(path): return None,None
    seen={}
    for line in open(path):
        try:r=json.loads(line)
        except: continue
        m=r.get('message') or {}
        if r.get('type')=='assistant' and 'usage' in m: seen[m.get('id') or r.get('uuid')]=m['usage']
    ps=[u.get('input_tokens',0)+u.get('cache_read_input_tokens',0)+u.get('cache_creation_input_tokens',0) for u in seen.values()]
    return (len(ps), sum(p>100000 for p in ps)) if ps else (None,None)
def claude_row(d,label,family,effort,rnd,share_fn):
    try: j=json.load(open(d+'/result.json'))
    except Exception: return dict(label=label,family=family,effort=effort,round=rnd,timeout=True)
    mu=j['modelUsage']; u=j['usage']
    out=sum(v['outputTokens'] for v in mu.values()); cost=sum(v['costUSD'] for v in mu.values())
    inp=sum(v['inputTokens'] for v in mu.values()); cc=sum(v['cacheCreationInputTokens'] for v in mu.values()); cr=sum(v['cacheReadInputTokens'] for v in mu.values())
    sec=int(re.search(r'seconds=(\d+)',open(d+'/run.txt').read())[1])
    api=j.get('duration_api_ms') or 0
    n,o=share_fn()
    lim='weekly limit' in (j.get('result') or '')
    return dict(label=label,limit=lim,task=label.split('-')[0],family=family,effort=effort,round=rnd,turns=j.get('num_turns'),calls=n,over100k=o,out=out,cost=cost,sec=sec,api_s=api/1000,tps=out/(api/1000) if api else None,inp=inp,cc=cc,cr=cr,pp_cc=0.604*cc/1e6,pp_full=(0.811*cc+1.81*out+6.57*inp+0.00352*cr)/1e6)
for d in sorted(glob.glob('runs/*')):
    l=os.path.basename(d)
    if 'luna' in l:
        try: ev=[json.loads(x) for x in open(d+'/result.jsonl') if x.startswith('{')]
        except Exception: continue
        us=[e['usage'] for e in ev if e.get('type')=='turn.completed']
        if not us: continue
        u=us[-1]; sec=int(re.search(r'seconds=(\d+)',open(d+'/run.txt').read())[1])
        i=u['input_tokens']; c=u['cached_input_tokens']; o=u['output_tokens']
        cost=((i-c)*0.10+c*0.01+o*0.50)/1e6
        rows.append(dict(label=l,task=l.split('-')[0],family='luna',effort='default',round='r2' if l.endswith('r2') else 'r1',turns=len(us),out=o,cost=cost,sec=sec,inp=i,cr=c,cc=0,pp_cc=None,pp_full=None,pp_codex=(i+o)/32.3e6,reason=u.get('reasoning_output_tokens')))
        continue
    m=re.match(r'(\w+)-h55-(\w+?)(-r2)?$',l)
    eff,rnd=m[2],'r2' if m[3] else 'r1'
    rows.append(claude_row(d,l,'haiku',eff,rnd,lambda d=d: tshare(d+'/transcript.jsonl')))
for fam,tag in (('sonnet','s55'),('opus','o55')):
    for eff in ('low','medium','high'):
        for t in ('pidfd','steer','costbase','stall','ident'):
            for r,sfx in (('r1',''),('r2','-r2')):
                l=f'{t}-{tag}-{eff}{sfx}'; d=f'{V}/{l}'
                if os.path.isdir(d) and os.path.exists(d+'/result.json'):
                    rows.append(claude_row(d,l,fam,eff,r,lambda l=l: share(l,'v656')))
json.dump(rows,open('metrics.json','w'),indent=1)
print(len(rows))
