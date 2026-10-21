import json,glob,os,collections,sqlite3,re
db=sqlite3.connect("file:/home/kesha/orchestra/data/orchestra.db?mode=ro",uri=True)
known=set()
for sid,hist in db.execute("select session_id,session_id_history from sessions"):
    if sid: known.add(sid)
    try:
        for h in json.loads(hist or '[]'): known.add(h.get('session_id',''))
    except: pass
files=glob.glob(os.path.expanduser("~/.codex/sessions/*/*/*/*.jsonl"))+glob.glob(os.path.expanduser("~/.orchestra/codex-home/*/sessions/*/*/*/*.jsonl"))
seen={}
cat=collections.defaultdict(lambda:[0,0,0,0]);ex=collections.defaultdict(list)
for f in files:
    m=re.search(r'rollout-[\dT-]+-([0-9a-f-]{36})\.jsonl',f); tid=m.group(1)
    last=None;cwd='';ts=''
    for line in open(f,errors='ignore'):
        try:o=json.loads(line)
        except:continue
        p=o.get('payload',{})
        if o.get('type')=='session_meta': cwd=p.get('cwd','');ts=o.get('timestamp','')
        if p.get('type')=='token_count' and p.get('info'): last=p['info']['total_token_usage']
    if not last or ts<'2026-08-05': continue
    key=tid
    if key in seen and seen[key]>=last.get('total_tokens',0): continue
    seen[key]=last.get('total_tokens',0)
    c='known' if tid in known else 'unknown'
    k=c+(':WT' if 'worktrees' in cwd else ':data/tmp/bench' if ('/tmp' in cwd or '/data/' in cwd or 'bench' in cwd) else ':other')
    a=cat[k];a[0]+=1;a[1]+=last.get('input_tokens',0);a[2]+=last.get('output_tokens',0);a[3]+=last.get('cached_input_tokens',0)
    ex[k].append((last.get('input_tokens',0)+last.get('output_tokens',0),cwd,ts[:10]))
for k,a in sorted(cat.items()): print(k,"files",a[0],"in(M)",round(a[1]/1e6),"out(M)",round(a[2]/1e6,1),"cached(M)",round(a[3]/1e6))
for k in ex: print(k,sorted(ex[k],reverse=True)[:2])
print(db.execute("select round(sum(input_tokens)/1e6),round(sum(output_tokens)/1e6,1),round(sum(cache_read_tokens)/1e6) from turn_usage where runtime='codex'").fetchall())
