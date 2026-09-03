import json,collections,re
ev=json.load(open("/tmp/fcaudit/events.json"))
calls=[e for e in ev if "codex_review" in e[2]]
print("total codex_review calls:",len(calls))
byout=collections.defaultdict(list)
for ts,ag,tool,args in calls:
    try: a=json.loads(args)
    except Exception: a={}
    out=a.get("output","CODEX_REVIEW.md")
    byout[(ag,out)].append((ts,a.get("resume",False),a.get("mode",""),(a.get("context") or "")[:400],a.get("target","")))
rounds=collections.Counter()
for k,v in byout.items():
    rounds[len(v)]+=1
print("\nsessions-per-output-file distribution (=rounds):")
for n in sorted(rounds): print(f"  {n} round(s): {rounds[n]} debate chains")
print("\n=== chains with >=2 rounds ===")
for (ag,out),v in sorted(byout.items(), key=lambda x:-len(x[1])):
    if len(v)<2: continue
    print(f"\n--- {ag} :: {out} ({len(v)} rounds)")
    for i,(ts,res,mode,ctx,tgt) in enumerate(sorted(v),1):
        print(f"  R{i} {ts[:19]} resume={res} mode={mode} target={tgt[:50]}")
        print(f"      ctx: {ctx[:260]}")
