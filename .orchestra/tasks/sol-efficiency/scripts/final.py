"""Regenerate with STRICT adjacency pairing (88.7% coverage) + final tables."""
import sqlite3, json, re, collections, hashlib, statistics, os

OUT = "/tmp/solan"
db = sqlite3.connect("file:/tmp/orch.db?mode=ro", uri=True)
sess = {r[0]: dict(name=r[1], role=r[2], backend=r[3], model=r[4])
        for r in db.execute("SELECT id,name,role,backend_type,model FROM sessions")}
TURN_RE = re.compile(r"turn ended \(([^,]+), (\d+) turns, \$([\d.]+) turn, \$([\d.]+) ctx, "
                     r"\$([\d.]+) session, \$([\d.]+) total(?: ctx:(\d+)%)?\)")

rows = db.execute("SELECT id,session_id,ts,type,content FROM logs "
                  "WHERE type IN ('tool','tool_result','status','error','text','user_message') "
                  "ORDER BY session_id,id").fetchall()

calls, turns = [], []
prev = None
turn_idx = collections.defaultdict(int)
for r in rows:
    rid, sid, ts, typ, content = r
    s = sess.get(sid, {})
    if typ == "tool":
        name = content.split(":")[0][:36]
        inp = None
        try: inp = json.loads(content[len(name) + 1:])
        except Exception: pass
        cmd = (inp or {}).get("command", "") if name == "Bash" else ""
        tgt = (inp or {}).get("file_path", "") if isinstance(inp, dict) else ""
        calls.append(dict(id=rid, sid=sid, sname=s.get("name"), role=s.get("role"),
                          backend=s.get("backend"), ts=ts, turn=turn_idx[sid], tool=name,
                          in_bytes=len(content), out_bytes=None, cmd=cmd or "", target=tgt or ""))
    elif typ == "tool_result":
        if prev and prev[1] == sid and prev[3] == "tool" and calls and calls[-1]["id"] == prev[0]:
            calls[-1]["out_bytes"] = len(content)
    elif typ == "status" and content.startswith("turn ended"):
        m = TURN_RE.search(content)
        if m:
            turns.append(dict(sid=sid, sname=s.get("name"), role=s.get("role"),
                              backend=s.get("backend"), model=s.get("model"), ts=ts,
                              turn=turn_idx[sid], reason=m.group(1), inner=int(m.group(2)),
                              cost=float(m.group(3)), ctx_pct=int(m.group(7)) if m.group(7) else ""))
        turn_idx[sid] += 1
    prev = r

for c in calls:
    c["orch"] = c["role"] in ("orchestrator", "sub-orchestrator")
    c["paired"] = c["out_bytes"] is not None
    c["ob"] = c["out_bytes"] or 0
SOLW = [c for c in calls if c["backend"] == "codex" and not c["orch"]]
CLAW = [c for c in calls if c["backend"] == "claude" and not c["orch"]]

with open(f"{OUT}/calls_strict.tsv", "w") as f:
    f.write("id\tsession\trole\tbackend\tts\tturn\ttool\tin_bytes\tout_bytes\tpaired\ttarget\tcmd\n")
    for c in calls:
        f.write("\t".join(str(x) for x in [
            c["id"], c["sname"], c["role"], c["backend"], c["ts"], c["turn"], c["tool"],
            c["in_bytes"], c["out_bytes"] if c["paired"] else "", int(c["paired"]),
            c["target"].replace("\t", " "),
            c["cmd"].replace("\t", " ").replace("\n", "\\n")[:600]]) + "\n")
with open(f"{OUT}/turns_strict.tsv", "w") as f:
    f.write("session\trole\tbackend\tmodel\tts\tturn\treason\tinner\tcost_usd\tctx_pct\n")
    for t in turns:
        f.write("\t".join(str(x) for x in [t["sname"], t["role"], t["backend"], t["model"],
                t["ts"], t["turn"], t["reason"], t["inner"], t["cost"], t["ctx_pct"]]) + "\n")

print("=== TABLE 1: tool mix, strict pairing ===")
for lbl, S in (("SOL worker", SOLW), ("CLAUDE worker", CLAW)):
    tb = sum(c["ob"] for c in S); ti = sum(c["in_bytes"] for c in S)
    print(f"\n-- {lbl}: calls={len(S)} paired={sum(c['paired'] for c in S)} "
          f"in={ti/1024:.0f}kB out={tb/1024:.0f}kB sessions={len(set(c['sname'] for c in S))}")
    d = collections.defaultdict(lambda: [0, 0, 0])
    for c in S:
        e = d[c["tool"]]; e[0] += 1; e[1] += c["ob"]; e[2] += c["in_bytes"]
    print(f"{'tool':34} {'n':>5} {'%n':>5} {'out_kB':>8} {'%out':>6} {'avg_out':>8} {'in_kB':>7} {'%in':>5}")
    for k, e in sorted(d.items(), key=lambda x: -(x[1][1] + x[1][2]))[:12]:
        print(f"{k:34} {e[0]:5} {100*e[0]/len(S):5.1f} {e[1]/1024:8.0f} "
              f"{100*e[1]/max(tb,1):6.1f} {e[1]/max(e[0],1):8.0f} {e[2]/1024:7.0f} {100*e[2]/max(ti,1):5.1f}")

print("\n=== TABLE 2: byte concentration (Sol worker, paired only) ===")
P = sorted([c for c in SOLW if c["paired"]], key=lambda x: -x["ob"])
tb = sum(c["ob"] for c in P)
print(f"paired calls={len(P)} out={tb/1e6:.2f}MB median={P[len(P)//2]['ob']}B")
for p in (0.01, 0.05, 0.10, 0.25, 0.50):
    n = max(1, int(len(P) * p))
    print(f"   top {int(p*100):3}% ({n:4} calls) = {100*sum(c['ob'] for c in P[:n])/tb:5.1f}% of bytes")
print(f"   calls >20kB: {sum(1 for c in P if c['ob']>20000)} = "
      f"{100*sum(c['ob'] for c in P if c['ob']>20000)/tb:.1f}% of bytes")
print(f"   calls >50kB: {sum(1 for c in P if c['ob']>50000)} = "
      f"{100*sum(c['ob'] for c in P if c['ob']>50000)/tb:.1f}% of bytes")

print("\n=== TABLE 3: top-15 fattest Sol results (strict) ===")
for c in P[:15]:
    print(f"{c['ob']:7} {100*c['ob']/tb:5.2f}% {c['tool'][:22]:22} [{c['sname'][:20]:20}] "
          f"{(c['cmd'] or c['target'])[:95]}")

print("\n=== TABLE 4: unbounded-search diagnosis (Sol Bash) ===")
B = [c for c in SOLW if c["tool"] == "Bash" and c["paired"]]
tbb = sum(c["ob"] for c in B)
def has_limit(cmd):
    return bool(re.search(r"\|\s*(head|tail)\b|\bhead -|-m ?\d|--max-count|LIMIT \d|\bsed -n", cmd))
search = [c for c in B if re.search(r"\brg\b|\bgrep\b|\bfind\b", c["cmd"])]
nl = [c for c in search if not has_limit(c["cmd"])]
wl = [c for c in search if has_limit(c["cmd"])]
print(f"bash={len(B)} out={tbb/1024:.0f}kB")
print(f"  search-shaped (rg/grep/find): n={len(search)} out={sum(c['ob'] for c in search)/1024:.0f}kB "
      f"({100*sum(c['ob'] for c in search)/tbb:.0f}% of bash bytes)")
print(f"    WITHOUT any limit: n={len(nl)} out={sum(c['ob'] for c in nl)/1024:.0f}kB "
      f"avg={sum(c['ob'] for c in nl)/max(len(nl),1):.0f}B "
      f"p95={sorted(c['ob'] for c in nl)[int(len(nl)*.95)] if nl else 0}")
print(f"    WITH head/limit:   n={len(wl)} out={sum(c['ob'] for c in wl)/1024:.0f}kB "
      f"avg={sum(c['ob'] for c in wl)/max(len(wl),1):.0f}B")
print(f"  >20kB bash results: {sum(1 for c in B if c['ob']>20000)}, of which search-shaped "
      f"{sum(1 for c in B if c['ob']>20000 and re.search(r'rg|grep|find', c['cmd']))}")

print("\n=== TABLE 5: cost drivers (Sol worker turns) ===")
bk = collections.defaultdict(list)
for c in calls: bk[(c["sid"], c["turn"])].append(c)
pts = []
for t in turns:
    if t["backend"] != "codex" or t["role"] in ("orchestrator", "sub-orchestrator"): continue
    cl = bk.get((t["sid"], t["turn"]), [])
    if t["cost"] <= 0: continue
    pts.append((t, len(cl), sum(c["ob"] for c in cl), sum(c["in_bytes"] for c in cl)))
def corr(a, b):
    ma, mb = statistics.mean(a), statistics.mean(b)
    n = sum((x-ma)*(y-mb) for x, y in zip(a, b))
    d = (sum((x-ma)**2 for x in a)*sum((y-mb)**2 for y in b))**.5
    return n/d if d else 0
co = [p[0]["cost"] for p in pts]
print(f"n={len(pts)} turns  mean=${statistics.mean(co):.2f} median=${statistics.median(co):.2f} "
      f"max=${max(co):.2f}")
print(f"  corr(n_calls, $)      = {corr([p[1] for p in pts], co):.3f}")
print(f"  corr(out_bytes, $)    = {corr([p[2] for p in pts], co):.3f}")
print(f"  corr(in_bytes, $)     = {corr([p[3] for p in pts], co):.3f}")
print(f"  corr(out+in bytes, $) = {corr([p[2]+p[3] for p in pts], co):.3f}")
print(f"  $/call implied (mean$ / mean calls) = "
      f"${statistics.mean(co)/statistics.mean([p[1] for p in pts]):.3f}")
# cost per call bucket
buck = collections.defaultdict(list)
for t, n, ob, ib in pts:
    b = "1-10" if n <= 10 else "11-25" if n <= 25 else "26-50" if n <= 50 else "51+"
    buck[b].append(t["cost"])
for b in ("1-10", "11-25", "26-50", "51+"):
    v = buck.get(b, [])
    if v: print(f"    calls {b:6}: n={len(v):3} mean ${statistics.mean(v):5.2f} total ${sum(v):7.2f}")
