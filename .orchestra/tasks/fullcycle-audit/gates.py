import json,re,collections
from datetime import datetime
ev=json.load(open("/tmp/fcaudit/events.json"))
def T(s):
    try: return datetime.fromisoformat(s.replace("Z","+00:00"))
    except Exception: return None
FC=set("""audit-fullcycle feat-inscryption-ai polish-tg research-sol-efficiency research-review-value
feat-usage-analytics research-codex-sleep upgrade-claude5 research-opus5 research-codex-cost research-html-eff
investigate-restart research-models pricing-research feat-ru-jobs feat-outreach-audit research-subscription
sensar-product-platform sensar-concrete-roadmap sensar-client-offer audit-both-projects sensar-roadmap
mobile-os-strategy codex-limits-community codex-limits-source codex-limits-official research-codex-abuse
research-spark research-self-improve research-deepgram research-tg-messages research-codex-cache
research-sol-models research-codex-orchestration research-precompact mass-job-hunter research-grok-build sol-pilot""".split())
byag=collections.defaultdict(list)
for ts,ag,tool,args in ev:
    short=ag.split('-',0)[0] if False else ag
    byag[ag].append((ts,tool,args))
GATE=re.compile(r'RESEARCH DONE|PLAN READY|Awaiting approval|awaiting approval|ожида\w+ (апрув|одобрен)|жду апрув', re.I)
rows=[]
for ag,lst in byag.items():
    base=ag.split(':')[-1]
    if not any(f in ag for f in FC): continue
    for i,(ts,tool,args) in enumerate(lst):
        if "send_message" not in tool: continue
        if not GATE.search(args): continue
        nxt=lst[i+1] if i+1<len(lst) else None
        gap=None
        if nxt and T(ts) and T(nxt[0]): gap=(T(nxt[0])-T(ts)).total_seconds()
        try: msg=json.loads(args).get("message","")
        except Exception: msg=args
        kind="RESEARCH" if "RESEARCH DONE" in msg else ("PLAN" if "PLAN READY" in msg else "OTHER")
        rows.append((ts,ag,kind,gap,len(msg),nxt[1] if nxt else None))
rows.sort()
print(f"{'ts':20s} {'agent':26s} {'gate':9s} {'gap_s':>9s} {'msglen':>6s} next_tool")
for ts,ag,k,gap,ln,nt in rows:
    g = f"{gap:9.0f}" if gap is not None else "     None"
    print(f"{ts[:19]:20s} {ag[:26]:26s} {k:9s} {g} {ln:6d} {nt}")
print(f"\ntotal gate messages: {len(rows)}")
import statistics
gaps=[r[3] for r in rows if r[3] is not None]
if gaps:
    print("gap median s:",statistics.median(gaps))
    print("stops <60s (не остановился):",sum(1 for g in gaps if g<60))
    print("stops 60-600s:",sum(1 for g in gaps if 60<=g<600))
    print("stops >600s (реальное ожидание):",sum(1 for g in gaps if g>=600))
