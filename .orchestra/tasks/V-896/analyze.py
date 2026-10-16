import json, glob, math, random, csv
from pathlib import Path
H = Path(__file__).parent
raw = {r["run_id"]: r for r in (json.load(open(f)) for f in glob.glob(str(H / "raw/*.json")))}
res_g = {}
for f in glob.glob(str(H / "grades/res-*.json")):
    d = json.load(open(f))
    if d["ok"]: res_g.setdefault(d["run_id"], {})[d["judge"]] = sum(d["scores"]) / len(d["scores"])
cr = [json.load(open(f)) for f in glob.glob(str(H / "grades/cr-*.json"))]
random.seed(7)
def boot_mean(xs, n=5000):
    if not xs: return (float("nan"),) * 3
    bs = sorted(sum(random.choice(xs) for _ in xs) / len(xs) for _ in range(n))
    return sum(xs) / len(xs), bs[int(.025 * n)], bs[int(.975 * n)]
def gm(v): return math.exp(sum(math.log(x) for x in v) / len(v))
def boot_gm(xs, n=5000):
    bs = sorted(gm([random.choice(xs) for _ in xs]) for _ in range(n)); return gm(xs), bs[int(.025 * n)], bs[int(.975 * n)]
def sign_p(k, n):
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(0, min(k, n - k) + 1)) / 2 ** n) if n else 1.0

# cells
cells = {}
for rid, r in raw.items():
    if r["stage"] != "exec": continue
    key = (r["task"], r["model"], r["rep"], r["arm"])
    parts = [r] + ([raw[f"B-rw-{r['task']}-{r['model']}-r{r['rep']}"]] if r["arm"] == "B" else [])
    cells[key] = dict(run=rid, kind=r["kind"], ok=r["ok"] and all(p["ok"] for p in parts),
                      paid=sum(p["paid_tokens"] for p in parts), turns=sum(p["turns"] or 0 for p in parts),
                      out=sum(p["output_tokens"] for p in parts), usd=sum(p["cost_usd_api_equiv"] or 0 for p in parts),
                      words=len((r["final_text"] or "").split()), flag=r["contamination_flag"])
    g = res_g.get(rid)
    if g:
        cells[key]["cov"] = sum(g.values()) / len(g)
        cells[key]["cov_cross"] = g.get("sonnet" if r["model"] == "luna" else "luna")
with open(H / "results.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["task", "model", "rep", "arm", "kind", "coverage", "coverage_cross", "paid_tokens", "turns", "words", "ok", "flag", "run"])
    for k in sorted(cells):
        c = cells[k]; w.writerow([*k, c["kind"], c.get("cov"), c.get("cov_cross"), c["paid"], c["turns"], c["words"], c["ok"], c["flag"], c["run"]])

def line(s): print(s)
line("== RESEARCH coverage (mean of 6 findings, mean of 2 graders) ==")
for arm in "ABC":
    for model in (None, "luna", "sonnet"):
        xs = [c["cov"] for k, c in cells.items() if k[3] == arm and c["kind"] == "research" and "cov" in c and (model is None or k[1] == model)]
        m, lo, hi = boot_mean(xs); line(f"{arm} model={model} n={len(xs)} mean={m:.3f} [{lo:.3f},{hi:.3f}]")
    for t in ("R1", "R2", "R3"):
        xs = [c["cov"] for k, c in cells.items() if k[3] == arm and k[0] == t and "cov" in c]
        line(f"   {arm} {t} n={len(xs)} mean={sum(xs)/len(xs):.3f} vals={[round(x,2) for x in xs]}")
line("-- paired differences vs A (cell = task x model x rep) --")
for arm in "BC":
    d = []
    for k, c in cells.items():
        if k[3] == arm and c["kind"] == "research" and "cov" in c and "cov" in cells.get(k[:3] + ("A",), {}):
            d.append(c["cov"] - cells[k[:3] + ("A",)]["cov"])
    m, lo, hi = boot_mean(d); pos = sum(x > 0 for x in d); neg = sum(x < 0 for x in d)
    line(f"{arm}-A n={len(d)} mean diff={m:+.3f} [{lo:+.3f},{hi:+.3f}] up/down/tie={pos}/{neg}/{len(d)-pos-neg} sign p={sign_p(min(pos,neg),pos+neg):.3f} sd={ (sum((x-m)**2 for x in d)/(len(d)-1))**.5 if len(d)>1 else float('nan'):.3f}")
line("-- cross-only grader (grader model != author model) --")
for arm in "ABC":
    xs = [c["cov_cross"] for k, c in cells.items() if k[3] == arm and c["kind"] == "research" and c.get("cov_cross") is not None]
    line(f"{arm} n={len(xs)} mean={sum(xs)/len(xs):.3f}")
line("== CREATIVE win-rate of arm over A (decision = pair x judge) ==")
for other in "BC":
    for label, f in (("all", lambda x: True), ("cross-only", lambda x: x["judge"] != x["author_model"]),
                     ("luna authors", lambda x: x["author_model"] == "luna"), ("sonnet authors", lambda x: x["author_model"] == "sonnet")):
        xs = [0 if x["a_wins"] else 1 for x in cr if x["ok"] and x["other"] == other and f(x)]
        m, lo, hi = boot_mean(xs); line(f"{other} vs A {label}: n={len(xs)} win={m:.3f} [{lo:.3f},{hi:.3f}]")
    # pair level: mean over 2 judges
    pairs = {}
    for x in cr:
        if x["ok"] and x["other"] == other: pairs.setdefault((x["task"], x["author_model"], x["rep"]), []).append(0 if x["a_wins"] else 1)
    pv = [sum(v) / len(v) for v in pairs.values()]
    wins = sum(p > .5 for p in pv); losses = sum(p < .5 for p in pv)
    agree = sum(len(set(v)) == 1 for v in pairs.values() if len(v) == 2) / max(1, sum(len(v) == 2 for v in pairs.values()))
    line(f"   pair-level (n={len(pv)}): {other} wins/losses/split={wins}/{losses}/{len(pv)-wins-losses} sign p={sign_p(min(wins,losses),wins+losses):.3f}; judge agreement={agree:.2f}")
    for t in sorted({k[0] for k in pairs}):
        v = [sum(p) / len(p) for k, p in pairs.items() if k[0] == t]; line(f"   {t}: {other} win share {sum(v)/len(v):.2f} (n pairs {len(v)})")
pos_bias = [x for x in cr if x["ok"]]
line(f"position: A shown as Y won {sum(1 for x in pos_bias if x['a_shown_as']=='Y' and x['a_wins'])}/{sum(1 for x in pos_bias if x['a_shown_as']=='Y')}, shown as X won {sum(1 for x in pos_bias if x['a_shown_as']=='X' and x['a_wins'])}/{sum(1 for x in pos_bias if x['a_shown_as']=='X')}")
line("words per answer (creative):")
for arm in "ABC":
    xs = [c["words"] for k, c in cells.items() if k[3] == arm and c["kind"] == "creative"]; line(f"   {arm} mean words={sum(xs)/len(xs):.0f}")
line("== PAID TOKENS ==")
for kind in (None, "research", "creative"):
    for arm in "ABC":
        s = sum(c["paid"] for k, c in cells.items() if k[3] == arm and (kind is None or c["kind"] == kind))
        t = sum(c["turns"] for k, c in cells.items() if k[3] == arm and (kind is None or c["kind"] == kind))
        u = sum(c["usd"] for k, c in cells.items() if k[3] == arm and (kind is None or c["kind"] == kind))
        line(f"{kind} {arm}: paid={s} turns={t} usd_api_eq={u:.2f}")
    for arm in "BC":
        for model in (None, "luna", "sonnet"):
            rs = [c["paid"] / cells[k[:3] + ("A",)]["paid"] for k, c in cells.items() if k[3] == arm and (kind is None or c["kind"] == kind) and (model is None or k[1] == model)]
            g, lo, hi = boot_gm(rs); line(f"   geo paid {arm}/A kind={kind} model={model}: {g:.2f} [{lo:.2f},{hi:.2f}] n={len(rs)}")
rw = sum(raw[r]["paid_tokens"] for r in raw if r.startswith("B-rw-")); bt = sum(c["paid"] for k, c in cells.items() if k[3] == "B")
line(f"rewrite share of B tokens: {rw/bt:.2f}")
line(f"failed cells: {[k for k,c in cells.items() if not c['ok']]}; contamination flagged: {sum(c['flag'] for c in cells.values())}")
