"""V-911 analysis. Primary (fixed in protocol.md): C-A paired coverage difference over cells (task x model x rep),
coverage = cross-grader (grader model != author model) mean over findings; 95% CI by task-clustered bootstrap
(resample the 12 tasks, take all their cells). Secondary: same-model grader, mean of both graders, per model, per task,
sign test over tasks, simple cell bootstrap. Paid tokens: ratio of sums C/A (primary) + task-clustered CI + geometric mean."""
import json, glob, math, random, csv, sys
from pathlib import Path
H = Path(__file__).parent
SUFFIX = sys.argv[1] if len(sys.argv) > 1 else ""
raw = {r["run_id"]: r for r in (json.load(open(f)) for f in glob.glob(str(H / "raw/*.json")))}
gr = {}
for f in glob.glob(str(H / "grades/res-*.json")):
    d = json.load(open(f))
    if d["ok"]: gr.setdefault(d["run_id"], {})[d["judge"]] = sum(d["scores"]) / len(d["scores"])
random.seed(911)
NB = 10000

cells = {}
failed = []
for rid, r in raw.items():
    if r["stage"] != "exec": continue
    key = (r["task"], r["model"], r["rep"], r["arm"])
    if not r["ok"]: failed.append(key); continue
    g = gr.get(rid, {})
    other = "sonnet" if r["model"] == "luna" else "luna"
    cells[key] = dict(run=rid, paid=r["paid_tokens"], turns=r["turns"] or 0, usd=r["cost_usd_api_equiv"] or 0,
                      words=len((r["final_text"] or "").split()), flag=r["contamination_flag"],
                      cross=g.get(other), same=g.get(r["model"]), mean=(sum(g.values()) / len(g)) if len(g) == 2 else None,
                      ext=("external" in (r["final_text"] or "").lower() and "check" in (r["final_text"] or "").lower()))
with open(H / f"results{SUFFIX}.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["task", "model", "rep", "arm", "cov_cross", "cov_same", "cov_mean", "paid_tokens", "turns", "words", "flag", "run"])
    for k in sorted(cells):
        c = cells[k]; w.writerow([*k, c["cross"], c["same"], c["mean"], c["paid"], c["turns"], c["words"], c["flag"], c["run"]])

def pairs(metric, model=None):
    """list of (task, diff) for cells with both arms graded"""
    out = []
    for k, c in cells.items():
        if k[3] != "C" or (model and k[1] != model): continue
        a = cells.get(k[:3] + ("A",))
        if a and c[metric] is not None and a[metric] is not None: out.append((k[0], c[metric] - a[metric]))
    return out

def cluster_boot(items, stat):
    tasks = sorted({t for t, _ in items}); by = {t: [x for tt, x in items if tt == t] for t in tasks}
    bs = []
    for _ in range(NB):
        sample = [random.choice(tasks) for _ in tasks]
        bs.append(stat([x for t in sample for x in by[t]]))
    bs.sort(); return bs[int(.025 * NB)], bs[int(.975 * NB)]
def mean(v): return sum(v) / len(v)
def sd(v): m = mean(v); return (sum((x - m) ** 2 for x in v) / (len(v) - 1)) ** .5 if len(v) > 1 else float("nan")
def sign_p(k, n): return min(1.0, 2 * sum(math.comb(n, i) for i in range(0, min(k, n - k) + 1)) / 2 ** n) if n else 1.0
def L(s): print(s)

L(f"cells ok={len(cells)} failed={failed}")
L("== COVERAGE by arm (mean over cells) ==")
for metric in ("cross", "same", "mean"):
    for arm in "AC":
        for model in (None, "luna", "sonnet"):
            xs = [c[metric] for k, c in cells.items() if k[3] == arm and c[metric] is not None and (model is None or k[1] == model)]
            if xs: L(f"{metric:5s} {arm} model={model} n={len(xs)} mean={mean(xs):.3f}")
L("== C - A PAIRED ==")
for metric in ("cross", "same", "mean"):
    for model in (None, "luna", "sonnet"):
        d = pairs(metric, model)
        if not d: continue
        v = [x for _, x in d]; lo, hi = cluster_boot(d, mean)
        pos = sum(x > 0 for x in v); neg = sum(x < 0 for x in v)
        tm = {}
        for t, x in d: tm.setdefault(t, []).append(x)
        tmv = [mean(x) for x in tm.values()]; tp = sum(x > 0 for x in tmv); tn = sum(x < 0 for x in tmv)
        L(f"{metric:5s} model={model} n_cells={len(v)} n_tasks={len(tm)} diff={mean(v):+.3f} cluster95=[{lo:+.3f},{hi:+.3f}] sd_cell={sd(v):.3f} "
          f"cells up/down/tie={pos}/{neg}/{len(v)-pos-neg} tasks up/down={tp}/{tn} task-sign-p={sign_p(min(tp,tn),tp+tn):.3f} task-diff-sd={sd(tmv):.3f}")
L("-- per task C-A (cross) --")
d = pairs("cross"); tm = {}
for t, x in d: tm.setdefault(t, []).append(x)
for t in sorted(tm): L(f"   {t}: {mean(tm[t]):+.3f} (n={len(tm[t])}) A={mean([c['cross'] for k,c in cells.items() if k[0]==t and k[3]=='A' and c['cross'] is not None]):.2f}")
L("== PAID TOKENS ==")
def ratio_sums(sample_cells):
    a = sum(cells[k[:3] + ("A",)]["paid"] for k in sample_cells); c = sum(cells[k]["paid"] for k in sample_cells); return c / a
ck = [k for k in cells if k[3] == "C" and k[:3] + ("A",) in cells]
for model in (None, "luna", "sonnet"):
    ks = [k for k in ck if model is None or k[1] == model]
    tasks = sorted({k[0] for k in ks}); byt = {t: [k for k in ks if k[0] == t] for t in tasks}
    bs = sorted(ratio_sums([k for t in [random.choice(tasks) for _ in tasks] for k in byt[t]]) for _ in range(NB))
    gms = [math.log(cells[k]["paid"] / cells[k[:3] + ("A",)]["paid"]) for k in ks]
    L(f"model={model} n={len(ks)} ratio_of_sums C/A={ratio_sums(ks):.3f} cluster95=[{bs[int(.025*NB)]:.3f},{bs[int(.975*NB)]:.3f}] geomean={math.exp(mean(gms)):.3f}")
for arm in "AC":
    ks = [k for k in cells if k[3] == arm]
    L(f"{arm}: paid_sum={sum(cells[k]['paid'] for k in ks)} turns={sum(cells[k]['turns'] for k in ks)} usd_api_eq={sum(cells[k]['usd'] for k in ks):.2f} mean_words={mean([cells[k]['words'] for k in ks]):.0f}")
L(f"contamination flagged: A={sum(c['flag'] for k,c in cells.items() if k[3]=='A')} C={sum(c['flag'] for k,c in cells.items() if k[3]=='C')}")
L(f"answers that mention an external check (arm visible to grader?): A={sum(c['ext'] for k,c in cells.items() if k[3]=='A')} C={sum(c['ext'] for k,c in cells.items() if k[3]=='C')}")
L("== DECISION (protocol.md) ==")
d = pairs("cross"); v = [x for _, x in d]; lo, hi = cluster_boot(d, mean)
ks = ck; tasks = sorted({k[0] for k in ks}); byt = {t: [k for k in ks if k[0] == t] for t in tasks}
rs = ratio_sums(ks)
L(f"gain>=+0.10: {mean(v):+.3f} -> {mean(v) >= 0.10}; CI lower>0: {lo:+.3f} -> {lo > 0}; paid ratio<=1.2: {rs:.3f} -> {rs <= 1.2}; ALL: {mean(v) >= 0.10 and lo > 0 and rs <= 1.2}")
