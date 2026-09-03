"""Per-turn economics with phase attribution for the 2026-08-11 cohort.

Turn = user_message ... status 'turn ended'. Phase = state machine over 'text' markers
(RESEARCH DONE -> plan, PLAN READY -> impl, DONE # -> done). Cost/tokens joined from
turn_usage by event_id (194/194 matched today). Read-only URI, live WAL DB.
"""
import re, sqlite3, sys
from datetime import datetime

DB = "/home/kesha/orchestra/data/orchestra.db"
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
SINCE = sys.argv[1] if len(sys.argv) > 1 else "2026-08-11"

usage = {r[0]: r[1:] for r in con.execute(
    "select event_id, model, runtime, cost_usd, input_tokens, output_tokens,"
    " cache_read_tokens, cache_create_tokens, quota_five_hour_pct, quota_seven_day_pct"
    " from turn_usage where ts>=? and event_id<>''", (SINCE,))}

rows = con.execute(
    """select s.name, s.role, s.effort, l.ts, l.type, l.content, l.event_id
       from logs l join sessions s on s.id=l.session_id
       where l.ts>=? and s.id in (select distinct session_id from turn_usage where ts>=?)
       order by s.name, l.id""", (SINCE, SINCE)).fetchall()

RE_END = re.compile(r"turn ended \(")
RE_TASK = re.compile(r"#(\d+)")
def ts(s): return datetime.fromisoformat(s.replace(" ", "T"))

by = {}
for name, role, effort, t, typ, content, eid in rows:
    by.setdefault((name, role, effort), []).append((ts(t), typ, content, eid))

print("session\trole\teffort\tmodel\tphase\tmin\ttools\twebtools\tcost\tin\tout\tcache_r\tcache_c\tmarker")
for (name, role, effort), evs in by.items():
    phase = "P1-research" if role in ("full-cycle",) else "single"
    task = ""
    cur = None
    for t, typ, content, eid in evs:
        if typ == "user_message" and cur is None:
            # новая задача после DONE возвращает воркера в P1 (persistent-воркеры
            # делают по несколько задач подряд; без сброса всё после первого DONE
            # схлопывается в один бессмысленный бакет)
            m = RE_TASK.search(content[:400])
            if phase == "done" and role == "full-cycle" and m and m.group(1) != task:
                task, phase = m.group(1), "P1-research"
            cur = {"start": t, "tools": 0, "web": 0, "marker": ""}
        elif cur is not None and typ == "tool":
            cur["tools"] += 1
            h = content[:80]
            if ("WebSearch" in h or "WebFetch" in h or "websearch" in h
                    or "r.jina.ai" in content[:400]):
                cur["web"] += 1
        elif cur is not None and typ == "text":
            head = content[:400].upper()
            m = RE_TASK.search(content[:400])
            if m and any(g in head for g in ("RESEARCH DONE", "PLAN READY", "DONE #")):
                task = m.group(1)
            if "RESEARCH DONE" in head: cur["marker"] = "RESEARCH-DONE"
            elif "PLAN READY" in head: cur["marker"] = "PLAN-READY"
            elif re.search(r"\bDONE #", head): cur["marker"] = "DONE"
        elif typ == "status" and cur is not None and RE_END.search(content):
            u = usage.get(eid)
            mins = (t - cur["start"]).total_seconds() / 60
            model, rt, cost, i, o, cr, cc = (u[0], u[1], u[2], u[3], u[4], u[5], u[6]) if u else ("?", "?", 0, 0, 0, 0, 0)
            print(f"{name}\t{role}\t{effort}\t{model}\t{phase}\t{mins:.0f}\t{cur['tools']}\t{cur['web']}"
                  f"\t{cost:.2f}\t{i}\t{o}\t{cr}\t{cc}\t{cur['marker']}")
            if cur["marker"] == "RESEARCH-DONE": phase = "P2-plan"
            elif cur["marker"] == "PLAN-READY": phase = "P3-impl"
            elif cur["marker"] == "DONE": phase = "done"
            cur = None
