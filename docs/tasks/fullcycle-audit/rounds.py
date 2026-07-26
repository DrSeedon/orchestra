import json,collections,re
ev=json.load(open("/tmp/fcaudit/events.json"))
calls=[e for e in ev if "codex_review" in e[2]]
byout=collections.defaultdict(list)
for ts,ag,tool,args in calls:
    try: a=json.loads(args)
    except Exception: a={}
    byout[(ag,a.get("output","CODEX_REVIEW.md"))].append((ts,(a.get("context") or "")))
RETRY=re.compile(r'timed out|timeout|prior timeout|transport-only|websocket|FINAL RETRY|produced no (review )?artifact|no artifact was written|Resume after|retry after|connection refused|Retry ', re.I)
DEBATE=re.compile(r'round \d|re-review after fixes|counterargument|counter-argument|I (revised|updated|fixed|applied|accepted)|prior finding', re.I)
stats=collections.Counter(); detail=[]
for k,v in byout.items():
    v.sort()
    n=len(v)
    if n<2: stats['single']+=1; continue
    r=sum(1 for ts,c in v[1:] if RETRY.search(c))
    d=sum(1 for ts,c in v[1:] if not RETRY.search(c) and DEBATE.search(c))
    o=(n-1)-r-d
    stats['chains_multi']+=1; stats['extra_rounds']+=n-1
    stats['retry_rounds']+=r; stats['debate_rounds']+=d; stats['other_rounds']+=o
    detail.append((k[0],k[1].split('/')[-1],n,r,d,o))
print(stats)
print(f"\n{'agent':28s} {'file':28s} tot retry debate other")
for a,f,n,r,d,o in sorted(detail,key=lambda x:-x[2]):
    print(f"{a[:28]:28s} {f[:28]:28s} {n:3d} {r:5d} {d:6d} {o:5d}")
