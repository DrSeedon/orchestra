"""Before/after replay of real search_logs calls on the live DB (read-only)."""
import importlib.util, json, re, sqlite3, statistics, sys, time
from pathlib import Path
sys.path.insert(0, ".")
from app import db as new
spec = importlib.util.spec_from_file_location("app._db_old", "/tmp/_db_old.py")
old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
LIVE = "file:/home/kesha/orchestra/data/orchestra.db?mode=ro"

def ro(path=None):
    c = sqlite3.connect(LIVE, uri=True, factory=new.OwnedConnection)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA busy_timeout=5000")
    return c
new._conn = ro; old._conn = ro
src = ro()
rows = src.execute("""select l.id, l.content, s.scope from logs l join sessions s on s.id=l.session_id
  where l.type='tool' and l.content like 'mcp__orchestra__search_logs%'
  and l.ts>date('now','-14 day') order by l.id""").fetchall()
calls = []
for r in rows:
    try:
        p = json.loads(r["content"].split(":", 1)[1])
    except Exception:
        continue
    if not p.get("query"): continue
    calls.append((r["id"], p, r["scope"]))
step = max(1, len(calls) // 20)
sample = calls[::step][:20]
print(f"calls in 14d: {len(calls)}, sampled {len(sample)}")
out = []
for cid, p, scope in sample:
    kw = dict(scope=None if p.get("all_projects") else scope, agent=p.get("agent"),
              date_from=p.get("date_from"), date_to=p.get("date_to"), limit=min(int(p.get("limit", 20)), 50))
    res = {}
    for name, mod, extra in (("old", old, {}), ("new", new, {}), ("new_all", new, {"kinds": "all"})):
        t = time.perf_counter()
        r = mod.search_logs(p["query"], **kw, **extra)
        res[name] = (r, time.perf_counter() - t)
    out.append((cid, p, res))
    o, n = res["old"][0], res["new"][0]
    print(cid, repr(p["query"][:22]), (p.get("date_from") or "-")[5:], (p.get("date_to") or "-")[5:], "|", o["scanned"], int(o["scan_truncated"]), (o["oldest_scanned"] or "-")[:16], f"{res['old'][1]:.2f}", "|", n["scanned"], int(n["scan_truncated"]), (n["oldest_scanned"] or "-")[:16], f"{res['new'][1]:.2f}"); continue
    print(cid, repr(p["query"][:30]), p.get("date_from"), p.get("date_to"),
          "| old", o["scanned"], o["scan_truncated"], len(o["results"]), f"{res['old'][1]:.2f}s",
          "| new", n["scanned"], n["scan_truncated"], len(n["results"]), n["oldest_scanned"], f"{res['new'][1]:.2f}s")

f = lambda k, i: [x[2][k][0]["scan_truncated"] for x in out]
print("truncated old", sum(f("old",0)), "new", sum(f("new",0)), "of", len(out))
for k in ("old","new"):
    t = [x[2][k][1] for x in out]
    print(k, "median s", round(statistics.median(t),3), "mean", round(statistics.mean(t),3), "max", round(max(t),3))
