import sqlite3, csv, collections, re, statistics, subprocess

db = sqlite3.connect("file:/tmp/orch.db?mode=ro", uri=True)
T = list(csv.DictReader(open("/tmp/solan/turns_strict.tsv"), delimiter="\t"))
for t in T:
    t["cost"] = float(t["cost_usd"]); t["turn"] = int(t["turn"])
    t["orch"] = t["role"] in ("orchestrator", "sub-orchestrator")
C = list(csv.DictReader(open("/tmp/solan/calls_strict.tsv"), delimiter="\t"))
for c in C:
    c["in_bytes"] = int(c["in_bytes"]); c["turn"] = int(c["turn"])
    c["ob"] = int(c["out_bytes"]) if c["out_bytes"] else 0
    c["orch"] = c["role"] in ("orchestrator", "sub-orchestrator")

print("### W. Sol vs Claude worker: turn economics side by side")
for lbl, bkd in (("SOL", "codex"), ("CLAUDE", "claude")):
    tt = [t for t in T if t["backend"] == bkd and not t["orch"]]
    cc = [c for c in C if c["backend"] == bkd and not c["orch"]]
    per = collections.Counter()
    for c in cc: per[(c["session"], c["turn"])] += 1
    npt = [v for v in per.values()]
    costs = [t["cost"] for t in tt if t["cost"] > 0]
    print(f"{lbl:7} turns={len(tt)} sessions={len(set(t['session'] for t in tt))} "
          f"$total={sum(t['cost'] for t in tt):7.2f} $mean={statistics.mean(costs):5.2f} "
          f"$med={statistics.median(costs):5.2f} calls/turn mean={statistics.mean(npt):5.1f} "
          f"med={statistics.median(npt):5.1f} p90={sorted(npt)[int(len(npt)*.9)]}")

print("\n### X. 'interrupted' turns: were they steered by an incoming message?")
steer = db.execute("""SELECT s.name, COUNT(*) FROM logs l JOIN sessions s ON s.id=l.session_id
  WHERE l.type='status' AND l.content LIKE '%steered into active Codex turn%' GROUP BY 1
  ORDER BY 2 DESC""").fetchall()
print("  'message steered into active Codex turn' by session:", steer[:8])
print("  total steer events:", sum(r[1] for r in steer))
sol = [t for t in T if t["backend"] == "codex" and not t["orch"]]
inter = [t for t in sol if t["reason"] == "interrupted"]
print(f"  interrupted Sol turns: {len(inter)} / {len(sol)}  ${sum(t['cost'] for t in inter):.2f}")
per = collections.Counter()
for c in C:
    if c["backend"] == "codex" and not c["orch"]: per[(c["session"], c["turn"])] += 1
ic = [per.get((t["session"], t["turn"]), 0) for t in inter]
ec = [per.get((t["session"], t["turn"]), 0) for t in sol if t["reason"] == "end_turn"]
print(f"  calls/turn: interrupted mean={statistics.mean(ic):.1f}  end_turn mean={statistics.mean(ec):.1f}")
print(f"  $/turn:     interrupted mean={statistics.mean([t['cost'] for t in inter]):.2f}  "
      f"end_turn mean={statistics.mean([t['cost'] for t in sol if t['reason']=='end_turn']):.2f}")
print(f"  $/call:     interrupted={sum(t['cost'] for t in inter)/max(sum(ic),1):.3f}  "
      f"end_turn={sum(t['cost'] for t in sol if t['reason']=='end_turn')/max(sum(ec),1):.3f}")

print("\n### Y. did the sleep fix (d19ad34) land? sleeps before/after commit ts")
ct = subprocess.run(["git", "-C", "/mnt/data/Projects/Python/orchestra", "show", "-s",
                     "--format=%cI", "d19ad34"], capture_output=True, text=True).stdout.strip()
print("  d19ad34 committed at:", ct or "(not found)")
rows = db.execute("""SELECT l.ts,s.name,l.content FROM logs l JOIN sessions s ON s.id=l.session_id
   WHERE l.type='tool' AND s.backend_type='codex' AND l.content LIKE 'Bash%sleep %' ORDER BY l.ts""").fetchall()
if ct:
    before = [r for r in rows if r[0] < ct]
    after = [r for r in rows if r[0] >= ct]
    print(f"  sleeps before commit: {len(before)}   after commit: {len(after)}")
    print(f"  after-commit sessions: {collections.Counter(r[1] for r in after).most_common(6)}")
    secs = lambda rs: sum(int(m.group(1)) for r in rs if (m := re.search(r'sleep (\d+)', r[2])))
    print(f"  wall seconds slept: before={secs(before)} after={secs(after)}")

print("\n### Z. codex exec nested inside Bash (Sol shelling out to another Codex)")
nested = [c for c in C if c["backend"] == "codex" and c["tool"] == "Bash"
          and re.search(r"\bcodex (exec|app-server|--version|resume)", c["cmd"])]
print(f"  n={len(nested)} out={sum(c['ob'] for c in nested)/1024:.0f}kB "
      f"in={sum(c['in_bytes'] for c in nested)/1024:.0f}kB")
for c in sorted(nested, key=lambda x: -x["ob"])[:6]:
    print(f"    {c['ob']:7}B [{c['session'][:20]:20}] {c['cmd'][:100]}")
tot_sol_out = sum(c["ob"] for c in C if c["backend"] == "codex" and not c["orch"])
print(f"  = {100*sum(c['ob'] for c in nested)/tot_sol_out:.1f}% of all Sol-worker output bytes")

print("\n### AA. Sol GOOD patterns — quantified")
S = [c for c in C if c["backend"] == "codex" and not c["orch"]]
B = [c for c in S if c["tool"] == "Bash"]
multi = [c for c in B if c["cmd"].count("\\n") >= 1 or "&&" in c["cmd"] or ";" in c["cmd"]]
print(f"  batched bash (multi-command in ONE call): {len(multi)}/{len(B)} = {100*len(multi)/len(B):.0f}%")
print(f"     avg commands per batched call ~ "
      f"{statistics.mean([c['cmd'].count(chr(92)+'n')+c['cmd'].count('&&')+1 for c in multi]):.1f}")
CB = [c for c in C if c["backend"] == "claude" and not c["orch"] and c["tool"] == "Bash"]
cmulti = [c for c in CB if c["cmd"].count("\\n") >= 1 or "&&" in c["cmd"] or ";" in c["cmd"]]
print(f"  Claude batched bash: {len(cmulti)}/{len(CB)} = {100*len(cmulti)/max(len(CB),1):.0f}%")
print(f"  Sol edit tools: FileChange={sum(1 for c in S if c['tool']=='FileChange')} "
      f"Edit={sum(1 for c in S if c['tool']=='Edit')} Write={sum(1 for c in S if c['tool']=='Write')}")
CW = [c for c in C if c["backend"] == "claude" and not c["orch"]]
print(f"  Claude edit tools: Edit={sum(1 for c in CW if c['tool']=='Edit')} "
      f"Write={sum(1 for c in CW if c['tool']=='Write')} "
      f"(Write in_bytes={sum(c['in_bytes'] for c in CW if c['tool']=='Write')/1024:.0f}kB)")
print(f"  serena usage: Sol={sum(1 for c in S if 'serena' in c['tool'])} "
      f"Claude={sum(1 for c in CW if 'serena' in c['tool'])}")
print(f"  narration (text rows): ", end="")
for bkd in ("codex", "claude"):
    r = db.execute("""SELECT COUNT(*), SUM(LENGTH(l.content)) FROM logs l JOIN sessions s ON s.id=l.session_id
      WHERE l.type='text' AND s.backend_type=? AND s.role NOT IN ('orchestrator','sub-orchestrator')""",
      (bkd,)).fetchone()
    print(f"{bkd}: n={r[0]} bytes={(r[1] or 0)/1024:.0f}kB  ", end="")
print()
