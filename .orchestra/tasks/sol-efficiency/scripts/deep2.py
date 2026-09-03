import csv, collections, re

C = list(csv.DictReader(open("/tmp/solan/calls.tsv"), delimiter="\t"))
for c in C:
    for k in ("in_bytes", "img", "cmd_len", "turn"):
        c[k] = int(c[k])
    c["out_bytes"] = int(c["out_bytes"]) if c["out_bytes"] else 0
    c["orch"] = c["role"] in ("orchestrator", "sub-orchestrator")
SOLW = [c for c in C if c["backend"] == "codex" and not c["orch"]]
CLAW = [c for c in C if c["backend"] == "claude" and not c["orch"]]

print("### G. THE TAIL: top-25 single tool results, Sol workers")
tot = sum(c["out_bytes"] for c in SOLW)
print(f"(total Sol worker tool_result bytes = {tot/1e6:.2f}MB)")
for c in sorted(SOLW, key=lambda x: -x["out_bytes"])[:25]:
    print(f"{c['out_bytes']:8} {100*c['out_bytes']/tot:5.2f}% {c['tool'][:26]:26} "
          f"[{c['sname'][:20]:20}] {(c['cmd'] or c['target'])[:105]}")
top25 = sum(c["out_bytes"] for c in sorted(SOLW, key=lambda x: -x["out_bytes"])[:25])
top1p = sorted(SOLW, key=lambda x: -x["out_bytes"])[:max(1, len(SOLW)//100)]
print(f"top25 calls = {100*top25/tot:.1f}% of all Sol output bytes")
print(f"top 1% of calls ({len(top1p)}) = {100*sum(c['out_bytes'] for c in top1p)/tot:.1f}%")
dec = sorted(SOLW, key=lambda x: -x["out_bytes"])
for p in (0.05, 0.10, 0.25, 0.50):
    n = int(len(dec) * p)
    print(f"   top {int(p*100):3}% of calls -> {100*sum(c['out_bytes'] for c in dec[:n])/tot:.1f}% of bytes")

print("\n### H. File fetches, fixed regex (sed -n RANGE path | cat | head | tail)")
PAT = re.compile(r"\b(?:sed\s+-n\s+(?:'[^']*'|\"[^\"]*\"|\S+)|cat|head|tail|nl|bat)\s+"
                 r"(?:-[\w-]+\s+|'[^']*'\s+)*['\"]?([~/\w.\-]*[\w.\-]+\.\w{1,5})")
for label, S in (("SOL", SOLW), ("CLAUDE", CLAW)):
    per = collections.defaultdict(list)
    for c in S:
        if c["tool"] in ("Read", "ViewImage") and c["target"]:
            per[(c["sname"], c["target"].split("/")[-1])].append(c)
        elif c["tool"] == "Bash":
            for m in PAT.finditer(c["cmd"]):
                per[(c["sname"], m.group(1).split("/")[-1])].append(c)
    tot_f = sum(len(v) for v in per.values())
    rep = sum(len(v) - 1 for v in per.values() if len(v) > 1)
    print(f"{label}: fetches={tot_f} distinct_files={len(per)} repeat_fetches={rep} "
          f"({100*rep/max(tot_f,1):.1f}%)")
    for (sn, fp), v in sorted(per.items(), key=lambda kv: -len(kv[1]))[:10]:
        if len(v) > 1:
            print(f"   x{len(v):3} [{sn[:22]:22}] {fp[:45]}")

print("\n### I. FileChange fat cases (in>20kB or out>20kB)")
fc = [c for c in SOLW if c["tool"] == "FileChange"]
fat = [c for c in fc if c["in_bytes"] > 20000 or c["out_bytes"] > 20000]
print(f"n_fat={len(fat)}/{len(fc)}  their in={sum(c['in_bytes'] for c in fat)/1024:.0f}kB "
      f"out={sum(c['out_bytes'] for c in fat)/1024:.0f}kB "
      f"(= {100*sum(c['in_bytes']+c['out_bytes'] for c in fat)/sum(c['in_bytes']+c['out_bytes'] for c in fc):.0f}% of FileChange traffic)")
for c in sorted(fat, key=lambda x: -(x["in_bytes"] + x["out_bytes"]))[:10]:
    print(f"   in={c['in_bytes']:6} out={c['out_bytes']:6} [{c['sname'][:20]}] {c['target'][:60]}")

print("\n### J. per-session Sol density: calls/turn, bytes/turn")
T = list(csv.DictReader(open("/tmp/solan/turns.tsv"), delimiter="\t"))
for t in T:
    t["cost"] = float(t["cost"]); t["inner"] = int(t["inner"])
ts = collections.defaultdict(list)
for t in T:
    if t["role"] not in ("orchestrator", "sub-orchestrator"):
        ts[(t["backend"], t["sname"])].append(t)
cs = collections.defaultdict(list)
for c in C:
    if not c["orch"]:
        cs[(c["backend"], c["sname"])].append(c)
print(f"{'backend':7} {'session':26} {'turns':>5} {'$sum':>7} {'$med':>6} {'$max':>7} {'calls':>6} {'c/turn':>6} {'out_MB':>7} {'kB/call':>7}")
rowsx = []
for k, v in sorted(ts.items(), key=lambda kv: -sum(t["cost"] for t in kv[1])):
    cl = cs.get(k, [])
    costs = sorted(t["cost"] for t in v)
    rowsx.append((k[0], k[1], len(v), sum(costs), costs[len(costs)//2], max(costs),
                  len(cl), len(cl)/max(len(v),1),
                  sum(c["out_bytes"] for c in cl)/1e6,
                  sum(c["out_bytes"] for c in cl)/max(len(cl),1)/1024))
for r in rowsx[:22]:
    print(f"{r[0]:7} {r[1][:26]:26} {r[2]:5} {r[3]:7.2f} {r[4]:6.2f} {r[5]:7.2f} {r[6]:6} {r[7]:6.1f} {r[8]:7.2f} {r[9]:7.1f}")
with open("/tmp/solan/sessions.tsv", "w") as f:
    f.write("backend\tsession\tturns\tcost_sum\tcost_med\tcost_max\tcalls\tcalls_per_turn\tout_MB\tkB_per_call\n")
    for r in rowsx:
        f.write("\t".join(str(x) for x in r) + "\n")
