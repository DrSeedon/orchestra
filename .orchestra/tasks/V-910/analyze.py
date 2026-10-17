"""V-910 analysis: A (runs in raw_a/) vs B (b_results.json) against reference.json, per the frozen protocol."""
import json, glob, random, statistics as st
from pathlib import Path
H = Path(__file__).parent
ref = json.load(open(H / "reference.json")); Q = {k: v for k, v in ref.items()}
B = json.load(open(H / "b_results.json")) if (H / "b_results.json").exists() else {}
runs = [json.load(open(f)) for f in sorted(glob.glob(str(H / "raw_a/*.json")))]
def norm(p):
    p = p.strip().strip("`'\"")
    i = p.find(".orchestra/")
    return p[i:] if i >= 0 else p
def hit(run, strict=True):
    acc = set(Q[run["qid"]]["acceptable"])
    ok = any(norm(f) in acc for f in run["files"])
    return int(ok and (run["search_calls"] <= 3 or not strict))
bad = [r["run_id"] for r in runs if (not r["ok"]) or r["contamination_flag"]]
runs = [r for r in runs if r["ok"] and not r["contamination_flag"]]
def a_by_q(models=("luna", "sonnet"), strict=True):
    d = {}
    for r in runs:
        if r["model"] in models: d.setdefault(r["qid"], []).append(hit(r, strict))
    return {k: sum(v) / len(v) for k, v in d.items()}
def b_hit(qid, key="hybrid5"):
    return int(any(f in set(Q[qid]["acceptable"]) for f in B[qid][key])) if B else None
def mrr(qid, key="hybrid10"):
    acc = set(Q[qid]["acceptable"])
    for i, f in enumerate(B[qid][key]):
        if f in acc: return 1 / (i + 1)
    return 0
def mean(x): x = list(x); return sum(x) / len(x) if x else float("nan")
def signflip_p(d, n=400000, seed=910):
    rng = random.Random(seed); obs = mean(d); nz = [x for x in d if x != 0]
    if not nz: return 1.0
    cnt = 0
    for _ in range(n):
        s = sum(x if rng.random() < .5 else -x for x in nz) / len(d)
        if s >= obs - 1e-12: cnt += 1
    return cnt / n
def boot(d, n=20000, seed=7):
    rng = random.Random(seed); m = sorted(mean(rng.choices(d, k=len(d))) for _ in range(n)); return m[int(.025 * n)], m[int(.975 * n)]
out = []
P = lambda *a: out.append(" ".join(str(x) for x in a))
P(f"runs used {len(runs)}, excluded (failed/contaminated): {bad}")
for kind in ("P", "D", "S"):
    ids = [q for q in Q if Q[q]["kind"] == kind]
    P(f"\n== kind {kind} (n={len(ids)})")
    for name, models in (("A pooled", ("luna", "sonnet")), ("A luna", ("luna",)), ("A sonnet", ("sonnet",))):
        a = a_by_q(models); al = a_by_q(models, strict=False)
        P(f"{name}: strict {mean(a[q] for q in ids if q in a):.3f}  lenient(file only) {mean(al[q] for q in ids if q in al):.3f}  (questions with runs: {sum(1 for q in ids if q in a)})")
    if B:
        for key in ("hybrid5", "vec5", "fts5", "hybrid10"):
            P(f"B {key}: {mean(b_hit(q, key) for q in ids):.3f}")
        P(f"B hybrid MRR@10: {mean(mrr(q) for q in ids):.3f}; top-1: {mean(int(B[q]['hybrid5'][:1] and B[q]['hybrid5'][0] in set(Q[q]['acceptable'])) for q in ids):.3f}")
if B:
    ids = [q for q in Q if Q[q]["kind"] == "P"]
    for name, models in (("pooled", ("luna", "sonnet")), ("luna", ("luna",)), ("sonnet", ("sonnet",))):
        a = a_by_q(models); d = [b_hit(q) - a[q] for q in ids if q in a]
        lo, hi = boot(d); p = signflip_p(d)
        P(f"\nPRIMARY ({name}) n={len(d)}: mean d = B5 - A_strict = {mean(d):+.3f}  CI95 [{lo:+.3f}, {hi:+.3f}]  one-sided sign-flip p = {p:.4f}  threshold +0.20: {'MET' if mean(d)>=.2 and p<.05 else 'NOT met'}")
        al = a_by_q(models, strict=False); d2 = [b_hit(q) - al[q] for q in ids if q in al]
        P(f"   sensitivity vs A lenient (ignore budget): mean d = {mean(d2):+.3f}  p = {signflip_p(d2):.4f}")
        miss = [q for q in ids if a.get(q, 1) < 1]
        P(f"   stratum A misses (A<1) n={len(miss)}: A = {mean(a[q] for q in miss):.3f}, B5 = {mean(b_hit(q) for q in miss):.3f}")
    # per-question table
    a = a_by_q(); P("\nper P question: A_pooled strict / B5 / B-vec5 / B-fts5")
    for q in ids: P(q, f"{a.get(q, float('nan')):.2f}", b_hit(q), b_hit(q, "vec5"), b_hit(q, "fts5"))
# cost
P("\ncost per run (paid tokens; cache read excluded) and calls")
for m in ("luna", "sonnet"):
    rs = [r for r in runs if r["model"] == m]
    if rs: P(m, "n", len(rs), "paid mean", round(mean(r["paid_tokens"] for r in rs)), "median", round(st.median(r["paid_tokens"] for r in rs)),
             "search calls mean", round(mean(r["search_calls"] for r in rs), 2), "over budget >3:", sum(r["search_calls"] > 3 for r in rs), "seconds mean", round(mean(r["seconds"] for r in rs)))
# KB vs report split for P
if B:
    for grp, f in (("KB", lambda q: q.startswith("K")), ("reports", lambda q: q.startswith("R"))):
        ids = [q for q in Q if Q[q]["kind"] == "P" and f(q)]; a = a_by_q()
        P(f"\nP/{grp} n={len(ids)}: A {mean(a[q] for q in ids if q in a):.3f}  B5 {mean(b_hit(q) for q in ids):.3f}")
(H / "analysis.txt").write_text("\n".join(out)); print("\n".join(out))
