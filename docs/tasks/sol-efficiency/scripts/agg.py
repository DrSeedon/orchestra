import csv, collections, statistics as st

C = list(csv.DictReader(open("/tmp/solan/calls.tsv"), delimiter="\t"))
T = list(csv.DictReader(open("/tmp/solan/turns.tsv"), delimiter="\t"))
for c in C:
    c["in_bytes"] = int(c["in_bytes"])
    c["out_bytes"] = int(c["out_bytes"]) if c["out_bytes"] else 0
    c["img"] = int(c["img"])
    c["cmd_len"] = int(c["cmd_len"])
for t in T:
    t["cost"] = float(t["cost"]); t["inner"] = int(t["inner"])


def grp(recs):
    return recs


def bucket(c):
    return c["backend"] + "/" + ("orch" if c["role"] in ("orchestrator", "sub-orchestrator") else "worker")


print("=== 1. tool mix by backend+kind (worker roles only) ===")
for b in ("codex/worker", "claude/worker", "codex/orch", "claude/orch"):
    sub = [c for c in C if bucket(c) == b]
    if not sub:
        continue
    tot_out = sum(c["out_bytes"] for c in sub)
    tot_in = sum(c["in_bytes"] for c in sub)
    print(f"\n-- {b}: {len(sub)} calls, in {tot_in/1e6:.2f}MB, out {tot_out/1e6:.2f}MB, "
          f"sessions={len(set(c['sname'] for c in sub))}")
    d = collections.defaultdict(lambda: [0, 0, 0, 0])
    for c in sub:
        e = d[c["tool"]]
        e[0] += 1; e[1] += c["in_bytes"]; e[2] += c["out_bytes"]; e[3] += c["img"]
    print(f"{'tool':32} {'n':>5} {'%n':>5} {'in_kB':>8} {'out_kB':>9} {'%out':>6} {'avg_out':>8} {'img':>4}")
    for k, e in sorted(d.items(), key=lambda x: -x[1][2])[:16]:
        print(f"{k[:32]:32} {e[0]:5} {100*e[0]/len(sub):5.1f} {e[1]/1024:8.0f} "
              f"{e[2]/1024:9.0f} {100*e[2]/max(tot_out,1):6.1f} {e[2]/max(e[0],1):8.0f} {e[3]:4}")
