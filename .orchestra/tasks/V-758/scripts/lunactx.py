import json,glob,os,re,collections
res={}
for f in glob.glob(os.path.expanduser('~/.codex/sessions/2026/10/*/*.jsonl')):
    try: first=open(f).readline()
    except: continue
    m=re.search(r'data/v758/(wt|wt-small)/([\w\-]+)',first)
    if not m: continue
    label=m[2]
    reqs=[];pc=[]
    for line in open(f):
        if '"token_count"' not in line: continue
        try:e=json.loads(line)
        except: continue
        p=e['payload']; info=p.get('info')
        if info: reqs.append(info['last_token_usage']['input_tokens'])
        rl=p.get('rate_limits') or {}
        if rl.get('primary'): pc.append((rl['primary']['used_percent'],rl['secondary']['used_percent'],e['timestamp']))
    res[label]=dict(requests=len(reqs),over100k=sum(r>100000 for r in reqs),max_in=max(reqs) if reqs else 0,first_pc=pc[0] if pc else None,last_pc=pc[-1] if pc else None)
json.dump(res,open('luna_ctx.json','w'),indent=1)
for k in sorted(res):
    if 'luna' in k and not k.startswith('S'): print(k,res[k])
