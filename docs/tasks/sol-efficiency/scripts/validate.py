"""Validate tool->tool_result pairing. Compare FIFO vs strict-adjacency."""
import sqlite3, collections, re, json

db = sqlite3.connect("file:/tmp/orch.db?mode=ro", uri=True)
sess = {r[0]: (r[1], r[2], r[3]) for r in db.execute(
    "SELECT id,name,role,backend_type FROM sessions")}

rows = db.execute("SELECT id,session_id,type,content FROM logs "
                  "WHERE type IN ('tool','tool_result') ORDER BY session_id,id").fetchall()

# structural: per session, the tool/result interleaving pattern
pat = collections.Counter()
cur, seq = None, []
runs = collections.Counter()
for r in rows:
    if r[1] != cur:
        cur = r[1]
    pat[r[2]] += 1

# measure: consecutive runs of same type (run length 1 = strict alternation)
cur, last, run = None, None, 0
runstats = collections.Counter()
for r in rows:
    if r[1] != cur:
        if run: runstats[(last, min(run, 6))] += 1
        cur, last, run = r[1], r[2], 1
        continue
    if r[2] == last:
        run += 1
    else:
        runstats[(last, min(run, 6))] += 1
        last, run = r[2], 1
if run: runstats[(last, min(run, 6))] += 1
print("run-length of consecutive same-type rows (tool / tool_result):")
for k in sorted(runstats):
    print(f"   {k[0]:12} run={k[1]}{'+' if k[1]==6 else ''}: {runstats[k]}")

# strict adjacency pairing: tool immediately followed by tool_result
strict = {}
prev = None
for r in rows:
    if prev and prev[1] == r[1] and prev[2] == "tool" and r[2] == "tool_result":
        strict[prev[0]] = len(r[3])
    prev = r
print(f"\nstrictly-paired tool calls: {len(strict)} of "
      f"{sum(1 for r in rows if r[2]=='tool')} tool rows "
      f"({100*len(strict)/sum(1 for r in rows if r[2]=='tool'):.1f}%)")

# verify semantically: git status --short results should look like porcelain
GS = re.compile(r"^\s*(git status --short|/usr/bin/zsh -lc ['\"]git status --short['\"])\s*$")
ok = bad = 0
for r in rows:
    if r[2] != "tool" or not r[3].startswith("Bash"): continue
    try: inp = json.loads(r[3][6:])
    except Exception: continue
    cmd = inp.get("command", "")
    if "git status" not in cmd or len(cmd) > 70: continue
    res = strict.get(r[0])
    if res is None: continue
    # fetch text
    t = db.execute("SELECT content FROM logs WHERE id>? AND session_id=? AND type='tool_result' "
                   "ORDER BY id LIMIT 1", (r[0], r[1])).fetchone()
    txt = t[0] if t else ""
    looks = all(re.match(r"^[ MARD?!U]{1,2}\s", ln) for ln in txt.splitlines()[:5] if ln.strip())
    if looks: ok += 1
    else:
        bad += 1
        if bad <= 4:
            print(f"   MISMATCH cmd={cmd[:60]!r} -> {txt[:80]!r}")
print(f"semantic check on short 'git status' cmds: consistent={ok} mismatched={bad}")

# recompute per-tool bytes using STRICT pairing only, Sol workers
agg = collections.defaultdict(lambda: [0, 0, 0])
tot = collections.Counter()
for r in rows:
    if r[2] != "tool": continue
    nm, rl, bk = sess.get(r[1], ("?", "?", "?"))
    if bk != "codex" or rl in ("orchestrator", "sub-orchestrator"): continue
    tool = r[3].split(":")[0][:34]
    tot["calls"] += 1
    if r[0] in strict:
        agg[tool][0] += 1
        agg[tool][1] += strict[r[0]]
        tot["paired"] += 1
        tot["bytes"] += strict[r[0]]
    agg[tool][2] += len(r[3])
print(f"\nSOL workers STRICT: calls={tot['calls']} paired={tot['paired']} "
      f"({100*tot['paired']/tot['calls']:.0f}%) out_bytes={tot['bytes']/1e6:.2f}MB")
print(f"{'tool':34} {'paired':>6} {'out_kB':>9} {'%out':>6} {'avg_out':>8} {'in_kB':>8}")
for k, e in sorted(agg.items(), key=lambda x: -x[1][1])[:14]:
    print(f"{k:34} {e[0]:6} {e[1]/1024:9.0f} {100*e[1]/max(tot['bytes'],1):6.1f} "
          f"{e[1]/max(e[0],1):8.0f} {e[2]/1024:8.0f}")
