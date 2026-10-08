import json,glob,os,sys
def calls(jsonl_files):
    seen={}
    for f in jsonl_files:
        for line in open(f):
            try:r=json.loads(line)
            except: continue
            m=r.get('message') or {}
            if r.get('type')!='assistant' or 'usage' not in m: continue
            mid=m.get('id') or r.get('uuid')
            seen[mid]=m['usage']   # last record per message id has final output_tokens
    return list(seen.values())
def stats(label, base='wt', proj=os.path.expanduser('~/.claude/projects')):
    d=f"{proj}/-home-kesha-orchestra-data-v758-{base}-{label}"
    fs=glob.glob(d+'/*.jsonl')
    us=calls(fs)
    if not us: return None
    ps=[u.get('input_tokens',0)+u.get('cache_read_input_tokens',0)+u.get('cache_creation_input_tokens',0) for u in us]
    over=sum(p>100000 for p in ps)
    # tiered price: >100k x5 on all categories
    cost=0
    for u,p in zip(us,ps):
        k=5 if p>100000 else 1
        cost+=k*(u.get('input_tokens',0)*0.10+u.get('cache_creation_input_tokens',0)*0.125+u.get('cache_read_input_tokens',0)*0.01+u.get('output_tokens',0)*0.50)/1e6
    flat=sum((u.get('input_tokens',0)*0.10+u.get('cache_creation_input_tokens',0)*0.125+u.get('cache_read_input_tokens',0)*0.01+u.get('output_tokens',0)*0.50)/1e6 for u in us)
    return dict(calls=len(us),over100k=over,max_prompt=max(ps),cost_tier=cost,cost_flat=flat)
if __name__=='__main__':
    for l in sys.argv[1:]: print(l,stats(l))
