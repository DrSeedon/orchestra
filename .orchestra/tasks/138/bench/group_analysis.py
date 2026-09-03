"""#138 — Is retrieval quality a function of the gold chunk's RHETORICAL FORM?

Reuses per-query RR already measured in #134 (no embedder, no DB, no cost).
Labels are pre-registered in labels.json, assigned from chunk TEXT before this ran.

Pass/fail fixed before running (per #135 discipline):
  a group difference counts only if it exceeds the metric's own split-half noise
  on this sample (median 0.1048). Otherwise: NOT PROVEN.
"""
import json, os, random, statistics as st
from itertools import combinations

HERE = os.path.dirname(os.path.abspath(__file__))
R134 = os.path.join(HERE, "..", "..", "134", "bench", "retrieval_results.json")
LABELS = os.path.join(HERE, "labels.json")

detail = json.load(open(R134))["detail"]
labels = {x["i"]: x["label"] for x in json.load(open(LABELS))["labels"]}
assert len(detail) == len(labels) == 28

ARMS = ["vec", "fts", "hybrid", "hybrid_rr_api"]
rows = []
for i, d in enumerate(detail):
    rows.append({"i": i, "q": d["q"], "label": labels[i],
                 **{a: d[a]["rr"] for a in ARMS},
                 **{a + "_rank": d[a]["rank"] for a in ARMS}})

groups = sorted({r["label"] for r in rows})
print("=== per-group MRR by arm (n=28, gold-form grouping pre-registered) ===")
hdr = f"{'group':<15}{'n':>3}" + "".join(f"{a:>16}" for a in ARMS)
print(hdr)
for g in groups:
    sub = [r for r in rows if r["label"] == g]
    line = f"{g:<15}{len(sub):>3}"
    for a in ARMS:
        line += f"{st.mean(r[a] for r in sub):>16.4f}"
    print(line)
line = f"{'ALL':<15}{len(rows):>3}"
for a in ARMS:
    line += f"{st.mean(r[a] for r in rows):>16.4f}"
print(line)

print("\n=== R@5 (hit rate) per group, prod hybrid ===")
for g in groups:
    sub = [r for r in rows if r["label"] == g]
    hits = sum(1 for r in sub if r["hybrid"] > 0)
    print(f"{g:<15} {hits}/{len(sub)} = {hits/len(sub):.2f}")

# --- permutation test: is the group split explaining more than a random split of the same sizes?
def group_spread(assign, arm):
    """Max-min of group means under a given label assignment."""
    ms = []
    for g in groups:
        vals = [rows[i][arm] for i, lb in enumerate(assign) if lb == g]
        ms.append(st.mean(vals))
    return max(ms) - min(ms)

random.seed(1138)
print("\n=== permutation test (20000 shuffles of the SAME label multiset) ===")
true_assign = [r["label"] for r in rows]
for arm in ARMS:
    obs = group_spread(true_assign, arm)
    shuf = list(true_assign)
    cnt = 0
    N = 20000
    for _ in range(N):
        random.shuffle(shuf)
        if group_spread(shuf, arm) >= obs:
            cnt += 1
    print(f"{arm:<16} observed spread={obs:.4f}  p={cnt/N:.4f}")

# --- pairwise group deltas vs the #135 noise floor
NOISE = 0.1048
print(f"\n=== pairwise group deltas vs #135 split-half noise floor ({NOISE}) ===")
for arm in ARMS:
    print(f"-- {arm}")
    for a, b in combinations(groups, 2):
        ma = st.mean(r[arm] for r in rows if r["label"] == a)
        mb = st.mean(r[arm] for r in rows if r["label"] == b)
        d = ma - mb
        verdict = "EXCEEDS noise" if abs(d) > NOISE else "below noise -> NOT PROVEN"
        print(f"   {a:>14} - {b:<14} = {d:+.4f}   {verdict}")

# --- own noise floor recomputed for THIS grouping question:
# split each group in half 20000x, how far apart do the halves land?
print("\n=== split-half noise WITHIN each group (20000 reps, prod hybrid) ===")
for g in groups:
    vals = [r["hybrid"] for r in rows if r["label"] == g]
    if len(vals) < 4:
        print(f"{g:<15} n={len(vals)} too small to split honestly")
        continue
    gaps = []
    for _ in range(20000):
        v = vals[:]
        random.shuffle(v)
        h = len(v) // 2
        gaps.append(abs(st.mean(v[:h]) - st.mean(v[h:2*h])))
    gaps.sort()
    print(f"{g:<15} n={len(vals)} median|gap|={gaps[len(gaps)//2]:.4f} "
          f"p90={gaps[int(.9*len(gaps))]:.4f}")

print("\n=== per-query dump (sorted by label) ===")
for g in groups:
    for r in sorted([r for r in rows if r["label"] == g], key=lambda x: x["i"]):
        print(f"{g:<15} Q{r['i']:<3} hyb_rank={r['hybrid_rank']:<3} "
              f"api_rank={r['hybrid_rr_api_rank']:<3} rr={r['hybrid']:.3f}  {r['q'][:52]}")
