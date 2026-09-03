import json,re,collections
from datetime import datetime
ev=json.load(open("/tmp/fcaudit/events.json"))
inb=json.load(open("/tmp/fcaudit/inbound.json"))
GATE=re.compile(r'RESEARCH DONE|PLAN READY|Awaiting approval|awaiting approval',re.I)
gates=[]
for ts,ag,tool,args in ev:
    if "send_message" not in tool: continue
    try:msg=json.loads(args).get("message","")
    except Exception:continue
    if GATE.search(msg): gates.append((ts,ag,msg))
inb_by=collections.defaultdict(list)
for ts,ag,txt in inb: inb_by[ag].append((ts,txt))
DEC=re.compile(r'вариант|option [ab]|выбираю|решени|не тро|сначала|порядок|уточнени|но |однако|не делай|учти|границ|требовани|scope|decision|instead|D1|прав|ошиб|нет,|не согласен|переделай|Одно |Требования',re.I)
STAMP=re.compile(r'^\s*(\[from:[^\]]+\]\s*)?(✅\s*)?(APPROVED?|APPROVE|Research approved|Plan approved|План апрувлен|Апрувлю|Го|Go|ДОБРО|Proceed)\b',re.I)
c=collections.Counter(); samples=collections.defaultdict(list)
for ts,ag,msg in sorted(gates):
    reps=[x for x in inb_by.get(ag,[]) if x[0]>ts]
    if not reps: c['no_reply']+=1; continue
    r=reps[0][1]
    if r.startswith("[Orchestra platform note") or r.startswith("Base directory") or "[Request interrupted" in r[:40] or r.startswith("[system]"):
        c['noise/interrupt']+=1; continue
    if r.startswith("[from:") and "[auto-report]" in r[:120]: c['auto-report_noise']+=1; continue
    body=r
    if DEC.search(body) and len(body)>250: c['DECISION']+=1; samples['DECISION'].append((ag,body[:110]))
    elif STAMP.search(body) and len(body)<=250: c['RUBBER_STAMP']+=1; samples['RUBBER_STAMP'].append((ag,body[:110]))
    elif len(body)<=250: c['short_other']+=1; samples['short_other'].append((ag,body[:110]))
    else: c['long_other']+=1; samples['long_other'].append((ag,body[:110]))
print("GATE REPLY CLASSIFICATION (n=%d)"%len(gates))
for k,v in c.most_common(): print(f"  {k:20s} {v}")
print("\n-- RUBBER_STAMP examples:")
for a,b in samples['RUBBER_STAMP'][:8]: print("   *",b.replace("\n"," ")[:100])
print("\n-- short_other examples:")
for a,b in samples['short_other'][:8]: print("   *",b.replace("\n"," ")[:100])
