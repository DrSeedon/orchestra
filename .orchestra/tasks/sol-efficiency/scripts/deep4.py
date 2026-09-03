import csv, collections, re, sqlite3, json

db = sqlite3.connect("file:/tmp/orch.db?mode=ro", uri=True)
C = list(csv.DictReader(open("/tmp/solan/calls.tsv"), delimiter="\t"))
for c in C:
    for k in ("in_bytes", "img", "cmd_len", "turn"):
        c[k] = int(c[k])
    c["out_bytes"] = int(c["out_bytes"]) if c["out_bytes"] else 0
    c["orch"] = c["role"] in ("orchestrator", "sub-orchestrator")
SOLW = [c for c in C if c["backend"] == "codex" and not c["orch"]]

print("### Q. What is inside the fat results? (first 200 chars, shape only)")
for cid in (2, 3, 4):
    pass
targets = [c["id"] for c in sorted(SOLW, key=lambda x: -x["out_bytes"])[:6]]
for tid in targets:
    row = db.execute("SELECT content FROM logs WHERE type='tool_result' AND id>? ORDER BY id LIMIT 1", (tid,)).fetchone()
    cmdrow = db.execute("SELECT content FROM logs WHERE id=?", (tid,)).fetchone()
    txt = row[0] if row else ""
    lines = txt.count("\n")
    print(f"\n-- call id={tid} result_len={len(txt)} lines={lines} avg_line={len(txt)/max(lines,1):.0f}")
    print("   HEAD:", txt[:180].replace("\n", " ⏎ "))
    print("   TAIL:", txt[-120:].replace("\n", " ⏎ "))

print("\n### R. git status weight: how many bytes do bare 'git status' segments return")
gs = [c for c in SOLW if c["tool"] == "Bash" and "git status" in c["cmd"]]
print(f"n={len(gs)} out_total={sum(c['out_bytes'] for c in gs)/1024:.0f}kB "
      f"med={sorted(c['out_bytes'] for c in gs)[len(gs)//2]} max={max(c['out_bytes'] for c in gs)}")
solo = [c for c in gs if len(c["cmd"]) < 80]
print(f"   'git status' as (nearly) the whole command: n={len(solo)} "
      f"out={sum(c['out_bytes'] for c in solo)/1024:.0f}kB med={sorted(c['out_bytes'] for c in solo)[len(solo)//2] if solo else 0}")
fat = [c for c in gs if c["out_bytes"] > 20000]
print(f"   git-status calls >20kB: {len(fat)} totalling {sum(c['out_bytes'] for c in fat)/1024:.0f}kB")
for c in fat[:6]:
    print(f"      {c['out_bytes']:7} [{c['sname'][:20]}] {c['cmd'][:90]}")

print("\n### S. ViewImage — does the image enter context for Sol?")
vi = [c for c in SOLW if c["tool"] == "ViewImage"]
print(f"n={len(vi)} out med={sorted(c['out_bytes'] for c in vi)[len(vi)//2]} "
      f"max={max(c['out_bytes'] for c in vi)} total={sum(c['out_bytes'] for c in vi)/1024:.0f}kB")
r = db.execute("SELECT content FROM logs WHERE type='tool_result' AND id>? ORDER BY id LIMIT 1", (vi[0]["id"],)).fetchone()
print("   sample:", (r[0][:200] if r else "").replace("\n", " ⏎ "))

print("\n### T. Duplicate file WINDOWS: same file+same byte-range vs different window")
RANGE = re.compile(r"sed\s+-n\s+'([\d,]+)p'\s+(\S+)")
per = collections.defaultdict(collections.Counter)
for c in SOLW:
    if c["tool"] != "Bash": continue
    for m in RANGE.finditer(c["cmd"]):
        per[(c["sname"], m.group(2).split("/")[-1])][m.group(1)] += 1
tot_w = sum(sum(v.values()) for v in per.values())
same_w = sum(sum(n - 1 for n in v.values() if n > 1) for v in per.values())
diff_w = sum(len(v) - 1 for v in per.values() if len(v) > 1)
print(f"sed-window fetches={tot_w}  exact-same-window repeats={same_w} "
      f"different-window revisits={diff_w}")
for k, v in sorted(per.items(), key=lambda kv: -sum(kv[1].values()))[:8]:
    print(f"   {sum(v.values()):3} fetches, {len(v)} distinct windows [{k[0][:18]}] {k[1][:34]} "
          f"dups={[w for w,n in v.items() if n>1][:4]}")

print("\n### U. Reorientation after an interrupted/failed turn: first 3 calls of next turn")
T = list(csv.DictReader(open("/tmp/solan/turns.tsv"), delimiter="\t"))
for t in T:
    t["cost"] = float(t["cost"]); t["turn"] = int(t["turn"])
    t["orch"] = t["role"] in ("orchestrator", "sub-orchestrator")
bykey = collections.defaultdict(list)
for c in C: bykey[(c["sid"], c["turn"])].append(c)
sol = [t for t in T if t["backend"] == "codex" and not t["orch"]]
bad = {(t["sid"], t["turn"] + 1) for t in sol if t["reason"] in ("interrupted", "error", "tool_use")}
REO = re.compile(r"git status|git diff|git log|pwd|^ls |rg --files|git branch|git rev-parse|wc -l")
after_c, after_b, base_c, base_b, nafter, nbase = 0, 0, 0, 0, 0, 0
for t in sol:
    cl = sorted(bykey.get((t["sid"], t["turn"]), []), key=lambda x: int(x["id"]))[:4]
    hit = sum(1 for c in cl if c["tool"] == "Bash" and REO.search(c["cmd"]))
    byt = sum(c["out_bytes"] for c in cl if c["tool"] == "Bash" and REO.search(c["cmd"]))
    if (t["sid"], t["turn"]) in bad:
        after_c += hit; after_b += byt; nafter += 1
    else:
        base_c += hit; base_b += byt; nbase += 1
print(f"turns after a broken turn: n={nafter} reorient-in-first-4-calls={after_c} "
      f"({after_c/max(nafter,1):.2f}/turn) bytes={after_b/1024:.0f}kB")
print(f"other turns:               n={nbase} reorient-in-first-4-calls={base_c} "
      f"({base_c/max(nbase,1):.2f}/turn) bytes={base_b/1024:.0f}kB")

print("\n### V. sleep detail: when, and adjacency to codex_review")
rows = db.execute("""SELECT l.id,l.ts,s.name,l.content FROM logs l JOIN sessions s ON s.id=l.session_id
   WHERE l.type='tool' AND s.backend_type='codex' AND l.content LIKE 'Bash%sleep %' ORDER BY l.id""").fetchall()
print("total sleep bash calls:", len(rows))
d = collections.Counter(r[1][:10] for r in rows)
print("  by day:", dict(d))
dur = collections.Counter()
for r in rows:
    m = re.search(r"sleep (\d+)", r[3])
    if m: dur[int(m.group(1))] += 1
print("  durations:", dict(sorted(dur.items())))
print("  total wall seconds slept:", sum(int(re.search(r'sleep (\d+)', r[3]).group(1))
                                        for r in rows if re.search(r'sleep (\d+)', r[3])))
byname = collections.Counter(r[2] for r in rows)
print("  by session:", byname.most_common(8))
