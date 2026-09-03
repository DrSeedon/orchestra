import json,re,collections,statistics
ev=json.load(open("/tmp/fcaudit/events.json"))
FCNAMES=set("""polish-tg research-sol-efficiency research-review-value feat-usage-analytics research-codex-sleep
upgrade-claude5 research-opus5 research-codex-cost research-html-eff investigate-restart research-models
research-subscription sensar-roadmap mobile-os-strategy codex-limits-source codex-limits-official
research-codex-abuse research-spark research-codex-cache feat-inscryption-ai""".split())
msgs=collections.defaultdict(list)
for ts,ag,tool,args in ev:
    if "send_message" not in tool: continue
    try:
        a=json.loads(args); m=a.get("message",""); to=a.get("to","")
    except Exception: continue
    base=ag.split(':')[-1]
    kind='FC' if any(n==base or n in ag for n in FCNAMES) else 'OTHER'
    msgs[kind].append((len(m),m,ag,to))
for k in msgs:
    L=[x[0] for x in msgs[k]]
    print(f"{k}: n={len(L)} median={statistics.median(L):.0f} mean={statistics.mean(L):.0f} p90={sorted(L)[int(len(L)*.9)]} max={max(L)}")
done=[x for x in msgs['FC'] if re.search(r'^DONE|DONE #|RESEARCH DONE|PLAN READY',x[1])]
L=[x[0] for x in done]
print(f"\nFC gate/DONE reports: n={len(L)} median={statistics.median(L):.0f} p90={sorted(L)[int(len(L)*.9)]} max={max(L)}")
print("\n=== 3 самых длинных отчёта (первые 700 симв) ===")
for ln,m,ag,to in sorted(done,key=lambda x:-x[0])[:3]:
    print(f"\n--- {ag} → {to} ({ln} симв)\n{m[:700]}")
