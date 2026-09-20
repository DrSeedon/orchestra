import sqlite3, json, datetime as dt
db=sqlite3.connect("file:data/orchestra.db?mode=ro", uri=True)
P=lambda s: dt.datetime.fromisoformat(s.replace("Z","+00:00"))
ser=[]
for ts,pu in db.execute("select ts, provider_usage from usage_snapshots where ts>'2026-08-01' order by id"):
    try: c=json.loads(pu).get("codex") or {}
    except Exception: continue
    ws=[w for w in c.get("windows",[]) if w.get("window_minutes")==10080]
    if not ws or ws[0].get("utilization") is None or not ws[0].get("resets_at"): continue
    ser.append((P(ts), ws[0]["utilization"], P(ws[0]["resets_at"]), c.get("plan_type")))
events=[]   # (ts_before, ts_after, u_before, sched_before, sched_after, plan)
for i in range(1,len(ser)):
    (t0,u0,r0,p0),(t1,u1,r1,p1)=ser[i-1],ser[i]
    if u1==0 and u0>=5 and (t1-t0).total_seconds()<900:
        events.append((t0,t1,u0,r0,r1,p1))
print("ХРОНИКА СБРОСОВ НЕДЕЛЬНОГО ОКНА CODEX")
print(f"{'когда (UTC)':16} {'план':6} {'было%':>5} {'старый сброс':12} {'новый сброс':12} {'сдвиг,ч':>7}  тип")
prev=None
for t0,t1,u0,r0,r1,p in events:
    early=(r0-t1).total_seconds()/3600
    kind="штатный" if abs(early)<0.5 else f"ДОСРОЧНЫЙ"
    print(f"{t1.strftime('%d.%m %H:%M'):16} {str(p)[:6]:6} {u0:5} {r0.strftime('%d.%m %H:%M'):12} {r1.strftime('%d.%m %H:%M'):12} {(r1-r0).total_seconds()/3600:7.1f}  {kind} (раньше срока на {early:.1f} ч)" if kind!="штатный" else f"{t1.strftime('%d.%m %H:%M'):16} {str(p)[:6]:6} {u0:5} {r0.strftime('%d.%m %H:%M'):12} {r1.strftime('%d.%m %H:%M'):12} {(r1-r0).total_seconds()/3600:7.1f}  штатный")
print()
# burn per window between events
bounds=[e[1] for e in events]
print(f"{'окно с':14} {'по':14} {'старт':9} {'план':6} {'дошло до%':>9} {'Mtok':>9} {'usd':>8} {'ходов':>6} {'Mtok/пп':>8}")
for i,b in enumerate(bounds):
    end = bounds[i+1] if i+1<len(bounds) else ser[-1][0]
    us=[u for t,u,r,p in ser if b<=t<=end]
    mx=max(us) if us else 0
    tok=db.execute("select coalesce(sum(input_tokens),0)/1e6, coalesce(sum(cost_usd),0), count(*) from turn_usage where runtime='codex' and ts>=? and ts<?",(b.isoformat(),end.isoformat())).fetchone()
    kind = "штат" if abs((events[i][3]-b).total_seconds())<1800 else "досроч"
    plan = events[i][5]
    print(f"{b.strftime('%d.%m %H:%M'):14} {end.strftime('%d.%m %H:%M'):14} {kind:9} {str(plan)[:6]:6} {mx:9} {tok[0]:9.1f} {tok[1]:8.2f} {tok[2]:6} {(tok[0]/mx if mx else 0):8.2f}")
