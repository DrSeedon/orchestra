import sqlite3, bisect, collections, statistics as st
db=sqlite3.connect("file:data/orchestra.db?mode=ro", uri=True)
orch={r[0]:r[1] for r in db.execute("select id,name from sessions where is_orchestrator=1")}
msgs=collections.defaultdict(list)
for sid, ts, content in db.execute("select session_id, ts, substr(content,1,40) from logs where type='user_message'"):
    if sid in orch: msgs[sid].append((ts, content))
for v in msgs.values(): v.sort()
def kind(c):
    if c.startswith("[Background job"): return "фон"
    if c.startswith("[from:"): return "агент"
    if c.startswith("[Orchestra platform note"): return "платформа"
    return "человек"
rows=collections.defaultdict(list)
unmatched=0
for sid, ts, cost, model in db.execute("select session_id, ts, cost_usd, model from turn_usage"):
    if sid not in orch: continue
    arr=msgs.get(sid) or []
    i=bisect.bisect_left(arr,(ts,))-1
    if i<0: unmatched+=1; continue
    wk=ts[:4]+"-W"+__import__("datetime").datetime.fromisoformat(ts).strftime("%W")
    rows[(wk,kind(arr[i][1]))].append(cost)
print(f"{'неделя':9} {'триггер':10} {'ходов':>6} {'средний $':>9} {'медиана $':>9} {'сумма $':>8}")
for (wk,k),v in sorted(rows.items()):
    print(f"{wk:9} {k:10} {len(v):6} {sum(v)/len(v):9.3f} {st.median(v):9.3f} {sum(v):8.1f}")
print("без предшествующего сообщения:", unmatched)
