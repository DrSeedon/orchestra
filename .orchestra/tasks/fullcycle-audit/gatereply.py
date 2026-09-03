import json,re
from datetime import datetime
ev=json.load(open("/tmp/fcaudit/events.json"))
inb=json.load(open("/tmp/fcaudit/inbound.json"))
def T(s):
    try:return datetime.fromisoformat(s.replace("Z","+00:00"))
    except Exception:return None
GATE=re.compile(r'RESEARCH DONE|PLAN READY|Awaiting approval|awaiting approval',re.I)
gates=[]
for ts,ag,tool,args in ev:
    if "send_message" not in tool or not GATE.search(args): continue
    try:msg=json.loads(args).get("message","")
    except Exception:msg=args
    if not GATE.search(msg): continue
    gates.append((ts,ag,msg))
inb_by={}
for ts,ag,txt in inb: inb_by.setdefault(ag,[]).append((ts,txt))
print(f"gates found: {len(gates)}\n")
for ts,ag,msg in sorted(gates):
    kind="RESEARCH" if "RESEARCH DONE" in msg else ("PLAN" if "PLAN READY" in msg else "OTHER")
    reps=[x for x in inb_by.get(ag,[]) if x[0]>ts]
    rep=reps[0] if reps else None
    dt=""
    if rep and T(ts) and T(rep[0]): dt=f"+{(T(rep[0])-T(ts)).total_seconds()/60:.0f}min"
    print(f"### {ts[:16]} {ag[:30]} [{kind}] msglen={len(msg)}")
    print(f"    REPLY {dt}: {(rep[1][:330] if rep else '— НЕТ ОТВЕТА —')}".replace("\n"," | "))
    print()
