import json,re,collections
ev=json.load(open("/tmp/fcaudit/events.json"))
calls=[]
for ts,ag,tool,args in ev:
    if "codex_review" not in tool: continue
    try:a=json.loads(args)
    except Exception:a={}
    calls.append((ts,ag,a.get("output","?"),a.get("resume",False),(a.get("context") or "")))
BOUND=re.compile(r'do not run|don\'t run|do NOT (read|inspect|call|scan|browse)|only this|bounded|no shell|without running|do not scan|не запускай|только этот файл|terse|concise|max \d+ findings',re.I)
byout=collections.defaultdict(list)
for ts,ag,out,res,ctx in calls: byout[(ag,out)].append((ts,res,ctx))
r1_bound=r1_un=0; late_bound=0; chains_late=[]
for k,v in byout.items():
    v.sort()
    if BOUND.search(v[0][2]): r1_bound+=1
    else: r1_un+=1
    if len(v)>1 and not BOUND.search(v[0][2]) and any(BOUND.search(c) for _,_,c in v[1:]):
        late_bound+=1; chains_late.append(k)
print(f"всего цепочек: {len(byout)}")
print(f"  R1 уже с ограничителями (do-not-run/bounded/terse): {r1_bound}")
print(f"  R1 без ограничителей: {r1_un}")
print(f"  цепочек где ограничители появились ТОЛЬКО после первого раунда: {late_bound}")
print("\nпримеры (агент :: файл):")
for a,f in chains_late[:14]: print("  ",a[:34],"::",f.split('/')[-1])
# timeouts overall
TO=re.compile(r'timed out|timeout|no artifact|transport|websocket|FINAL RETRY|connection refused',re.I)
n_to=sum(1 for _,_,_,_,c in calls if TO.search(c))
print(f"\nвызовов codex_review, чей context упоминает сбой предыдущего прогона: {n_to} из {len(calls)}")
