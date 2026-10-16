import json, glob, csv, random, math
from pathlib import Path
H = Path(__file__).parent
rows = {r["run_id"]: r for r in (json.load(open(f)) for f in glob.glob(str(H / "raw/*.json")))}
out = []
cells = {}
for t in ["O1","O2","O3","O4","C1","C2","C3","C4"]:
    for m in ["luna","sonnet"]:
        for arm in "ABC":
            if arm == "B":
                rw, ex = rows[f"B-rw-{t}-{m}"], rows[f"B-{t}-{m}"]
                parts = [rw, ex]
            else:
                ex = rows[f"{arm}-{t}-{m}"]; parts = [ex]
            c = dict(task=t, kind=ex["kind"], arm=arm, model=m, accepted=int(ex["accepted"]),
                     paid_tokens=sum(p["paid_tokens"] for p in parts), turns=sum(p["turns"] or 0 for p in parts),
                     output_tokens=sum(p["output_tokens"] for p in parts),
                     cost_usd_api_equiv=round(sum(p["cost_usd_api_equiv"] or 0 for p in parts), 4),
                     run_ids="+".join(p["run_id"] for p in parts), all_ok=all(p["ok"] for p in parts),
                     rewrite_paid=parts[0]["paid_tokens"] if arm == "B" else 0)
            cells[(t, m, arm)] = c; out.append(c)
with open(H / "results.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(out[0])); w.writeheader(); w.writerows(out)

def binom_two(k, n):  # exact two-sided sign test p
    p = sum(math.comb(n, i) for i in range(0, min(k, n - k) + 1)) / 2 ** n
    return min(1.0, 2 * p)
def acc(kind, arm, model=None):
    return sum(c["accepted"] for c in out if c["kind"] == kind and c["arm"] == arm and (model is None or c["model"] == model))
def mcn(kind, a, b):
    bw = sum(1 for (t,m,arm),c in cells.items() if arm == b and c["kind"]==kind and c["accepted"] and not cells[(t,m,a)]["accepted"])
    aw = sum(1 for (t,m,arm),c in cells.items() if arm == a and c["kind"]==kind and c["accepted"] and not cells[(t,m,b)]["accepted"])
    return aw, bw, binom_two(min(aw,bw), aw+bw) if aw+bw else 1.0
def ratios(a, b, model=None, kind=None):
    return [cells[(t,m,b)]["paid_tokens"]/cells[(t,m,a)]["paid_tokens"] for (t,m,arm) in cells
            if arm == a and (model is None or m == model) and (kind is None or cells[(t,m,a)]["kind"]==kind)]
random.seed(1)
def boot(xs):
    gm = lambda v: math.exp(sum(math.log(x) for x in v)/len(v))
    bs = sorted(gm([random.choice(xs) for _ in xs]) for _ in range(5000))
    return gm(xs), bs[125], bs[4874]
print("ACCEPTED (of 8 per kind x arm; per model of 4)")
for kind in ("open","closed"):
    for arm in "ABC":
        print(kind, arm, acc(kind,arm), "luna", acc(kind,arm,"luna"), "sonnet", acc(kind,arm,"sonnet"))
for kind in ("open","closed"):
    for a,b in (("A","B"),("A","C")):
        print(f"{kind} {a} vs {b}: discordant A-only/B-only/p =", mcn(kind,a,b))
print("PAID TOKENS total")
for arm in "ABC":
    for kind in ("open","closed",None):
        s = sum(c["paid_tokens"] for c in out if c["arm"]==arm and (kind is None or c["kind"]==kind)); print(arm, kind, s)
print("B rewrite share", sum(c["rewrite_paid"] for c in out)/sum(c["paid_tokens"] for c in out if c["arm"]=="B"))
for b in "BC":
    for model in (None,"luna","sonnet"):
        for kind in (None,"open","closed"):
            g,lo,hi = boot(ratios("A",b,model,kind)); print(f"geo ratio paid {b}/A model={model} kind={kind}: {g:.2f} [{lo:.2f},{hi:.2f}] n={len(ratios('A',b,model,kind))}")
    sa = sum(c["paid_tokens"] for c in out if c["arm"]=="A"); sb=sum(c["paid_tokens"] for c in out if c["arm"]==b)
    print(b, "total ratio", sb/sa)
print("TURNS total", {arm: sum(c["turns"] for c in out if c["arm"]==arm) for arm in "ABC"})
