import csv, collections, re, sqlite3

C = list(csv.DictReader(open("/tmp/solan/calls.tsv"), delimiter="\t"))
for c in C:
    for k in ("in_bytes", "img", "cmd_len", "turn"):
        c[k] = int(c[k])
    c["out_bytes"] = int(c["out_bytes"]) if c["out_bytes"] else 0
    c["orch"] = c["role"] in ("orchestrator", "sub-orchestrator")
T = list(csv.DictReader(open("/tmp/solan/turns.tsv"), delimiter="\t"))
for t in T:
    t["cost"] = float(t["cost"]); t["inner"] = int(t["inner"]); t["turn"] = int(t["turn"])
    t["orch"] = t["role"] in ("orchestrator", "sub-orchestrator")

bykey = collections.defaultdict(list)
for c in C:
    bykey[(c["sid"], c["turn"])].append(c)

print("### K. Turn reason distribution (cost of non-clean endings)")
for lbl, sel in (("SOL-worker", lambda t: t["backend"] == "codex" and not t["orch"]),
                 ("CLAUDE-worker", lambda t: t["backend"] == "claude" and not t["orch"])):
    sub = [t for t in T if sel(t)]
    if not sub: continue
    tot = sum(t["cost"] for t in sub)
    print(f"-- {lbl}: {len(sub)} turns, ${tot:.2f}")
    d = collections.defaultdict(lambda: [0, 0.0])
    for t in sub:
        e = d[t["reason"]]; e[0] += 1; e[1] += t["cost"]
    for k, e in sorted(d.items(), key=lambda x: -x[1][1]):
        print(f"   {k:28} n={e[0]:4} ${e[1]:8.2f} ({100*e[1]/tot:5.1f}%) avg ${e[1]/e[0]:.2f}")

print("\n### L. TOP-10 most expensive Sol-worker turns, itemised")
sol = sorted([t for t in T if t["backend"] == "codex" and not t["orch"]], key=lambda t: -t["cost"])
for t in sol[:10]:
    cl = bykey.get((t["sid"], t["turn"]), [])
    ob = sum(c["out_bytes"] for c in cl); ib = sum(c["in_bytes"] for c in cl)
    mix = collections.Counter(c["tool"] for c in cl)
    print(f"\n${t['cost']:.2f} [{t['sname']}] turn#{t['turn']} reason={t['reason']} "
          f"inner={t['inner']} ctx={t['ctx_pct']}% calls={len(cl)} in={ib/1024:.0f}kB out={ob/1024:.0f}kB")
    print("   mix: " + ", ".join(f"{k}×{v}" for k, v in mix.most_common(7)))
    for c in sorted(cl, key=lambda x: -x["out_bytes"])[:4]:
        print(f"     {c['out_bytes']:7}B {c['tool'][:22]:22} {(c['cmd'] or c['target'])[:88]}")

print("\n### M. Cost vs bytes correlation — is $ driven by tool bytes at all?")
import statistics
pts = [(sum(c["out_bytes"] + c["in_bytes"] for c in bykey.get((t["sid"], t["turn"]), [])),
        len(bykey.get((t["sid"], t["turn"]), [])), t["cost"], t["inner"])
       for t in T if t["backend"] == "codex" and not t["orch"] and t["cost"] > 0]
def corr(a, b):
    ma, mb = statistics.mean(a), statistics.mean(b)
    num = sum((x-ma)*(y-mb) for x, y in zip(a, b))
    den = (sum((x-ma)**2 for x in a) * sum((y-mb)**2 for y in b)) ** .5
    return num/den if den else 0
by = [p[0] for p in pts]; ca = [p[1] for p in pts]; co = [p[2] for p in pts]; ih = [p[3] for p in pts]
print(f"n={len(pts)} corr(bytes,$)={corr(by,co):.3f} corr(calls,$)={corr(ca,co):.3f} "
      f"corr(inner_turns,$)={corr(ih,co):.3f}")
print(f"   mean $/turn={statistics.mean(co):.2f} mean calls={statistics.mean(ca):.1f} "
      f"mean kB={statistics.mean(by)/1024:.0f}")

print("\n### N. tool_errors + error log rows by backend")
db = sqlite3.connect("file:/tmp/orch.db?mode=ro", uri=True)
for r in db.execute("SELECT tool_name, COUNT(*) FROM tool_errors GROUP BY 1 ORDER BY 2 DESC LIMIT 10"):
    print("   tool_errors", r)
print("   total tool_errors:", db.execute("SELECT COUNT(*) FROM tool_errors").fetchone())
for r in db.execute("""SELECT s.backend_type, COUNT(*) FROM logs l JOIN sessions s ON s.id=l.session_id
                       WHERE l.type='error' GROUP BY 1"""):
    print("   error rows", r)
print("\n   error text top kinds:")
for r in db.execute("""SELECT SUBSTR(l.content,1,70) k, s.backend_type, COUNT(*) FROM logs l
                       JOIN sessions s ON s.id=l.session_id WHERE l.type='error'
                       GROUP BY k,2 ORDER BY 3 DESC LIMIT 12"""):
    print("   ", r[2], r[1], r[0].replace("\n", " "))

print("\n### O. Retry-shaped repeats: near-identical consecutive bash (same first 40 chars)")
for lbl, bk in (("SOL", "codex"), ("CLAUDE", "claude")):
    b = [c for c in C if c["backend"] == bk and not c["orch"] and c["tool"] == "Bash" and c["cmd"]]
    per = collections.defaultdict(list)
    for c in b: per[c["sname"]].append(c)
    near = 0; nb = 0
    for sn, v in per.items():
        v.sort(key=lambda x: int(x["id"]))
        for a, z in zip(v, v[1:]):
            pa, pz = a["cmd"][:60], z["cmd"][:60]
            if pa == pz and a["cmd"] != z["cmd"]:
                near += 1; nb += z["out_bytes"]
    print(f"{lbl}: consecutive near-identical (same 60-char prefix, different tail) = {near} "
          f"out={nb/1024:.0f}kB")

print("\n### P. sleep calls over time (was fixed d19ad34 today)")
for r in db.execute("""SELECT DATE(l.ts) d, COUNT(*) FROM logs l JOIN sessions s ON s.id=l.session_id
      WHERE l.type='tool' AND s.backend_type='codex' AND l.content LIKE '%sleep %'
      GROUP BY d ORDER BY d"""):
    print("   ", r)
