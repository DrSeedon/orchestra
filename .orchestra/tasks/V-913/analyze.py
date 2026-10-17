"""V-906 analysis. Prints tables; writes results.csv. Usage: python analyze.py"""
import csv, glob, json, math, random, re
from collections import defaultdict
from pathlib import Path
H = Path(__file__).parent
rows = {}
for f in glob.glob(str(H / "raw" / "*.json")):
    r = json.load(open(f)); rows[r["run_id"]] = r
FIRST = {"python", "python3", "pytest", "uv", "node", "sqlite3", "bash", "sh", "timeout", "env", "PYTHONPATH"}
def cmd_is_repro(c):
    c = re.sub(r"^\s*/bin/bash -lc\s*", "", c.strip()).strip("'\"")
    for seg in re.split(r"&&|;|\|\||\n", c):
        w = seg.strip().split()
        w = [x for x in w if "=" not in x.split("/")[0] or x.startswith("-")] if w else w
        if not w: continue
        h = w[0].rsplit("/", 1)[-1]
        if h in FIRST or h.startswith("python"): return True
        if h == "git" and len(w) > 1 and w[1] in ("init", "worktree", "diff", "commit", "merge", "checkout", "add", "log", "status"): return True
    return False

grades = defaultdict(dict)
for f in glob.glob(str(H / "grades" / "rc-*.json")):
    g = json.load(open(f))
    if g["ok"]: grades[g["run_id"]][g["judge"]] = g["grade"]

def cross_judge(model): return "sonnet" if model == "luna" else "luna"

def cell(r):
    gs = grades.get(r["run_id"], {})
    c = gs.get(cross_judge(r["model"])); s = gs.get(r["model"])
    both = [x for x in (c, s) if x]
    return dict(correct_cross=None if not c else int(c["primary"] == 1),
                correct_same=None if not s else int(s["primary"] == 1),
                correct_any=None if not both else int(any(x["primary"] == 1 for x in both)),
                decoy=None if not c else int(bool(c.get("decoy_main"))),
                repro_claim=None if not c else c.get("reproduction"),
                attempt_cmds=sum(cmd_is_repro(x) for x in r["commands"]),
                attempt_files=len(r["files_created"]))

cells = []
for r in rows.values():
    if not r["ok"]: continue
    c = cell(r) if r["group"] != "C" else {}
    cells.append({**{k: r[k] for k in ("run_id", "task", "group", "arm", "model", "rep", "paid_tokens", "turns", "contamination_flag", "seconds")}, **c})
with open(H / "results.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=sorted({k for c in cells for k in c})); w.writeheader(); w.writerows(cells)

def by(group, arm=None, model=None):
    return [c for c in cells if c["group"] == group and (arm is None or c["arm"] == arm) and (model is None or c["model"] == model)]

def sign_p(b, c):
    n = b + c
    if n == 0: return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)

rng = random.Random(906)
def geo_ci(pairs):
    if not pairs: return None
    lr = [math.log(b / a) for a, b in pairs if a > 0 and b > 0]
    if not lr: return None
    m = sum(lr) / len(lr); bs = []
    for _ in range(4000):
        s = [rng.choice(lr) for _ in lr]; bs.append(sum(s) / len(s))
    bs.sort(); return math.exp(m), math.exp(bs[100]), math.exp(bs[3899])

def pair_cells(group, model=None):
    d = defaultdict(dict)
    for c in cells:
        if c["group"] == group and (model is None or c["model"] == model): d[(c["task"], c["model"], c["rep"])][c["arm"]] = c
    return [v for v in d.values() if "A" in v and "R" in v]

print("== correct (cross-model grader), per group x arm x model")
for grp in ("T", "K"):
    for model in (None, "luna", "sonnet"):
        for key in ("correct_cross", "correct_same", "correct_any", "decoy"):
            out = []
            for arm in ("A", "R"):
                cs = [c[key] for c in by(grp, arm, model) if c.get(key) is not None]
                out.append(f"{arm} {sum(cs)}/{len(cs)}")
            pc = pair_cells(grp, model)
            b = sum(1 for p in pc if p["R"].get(key) == 1 and p["A"].get(key) == 0)
            cc = sum(1 for p in pc if p["A"].get(key) == 1 and p["R"].get(key) == 0)
            print(f"{grp} {model or 'all':7} {key:14} {out[0]:8} {out[1]:8}  R-only {b} A-only {cc} p={sign_p(b, cc):.2f}")

print("\n== per task (cross-model correct, A vs R, both models, 2 reps -> /4)")
for t in sorted({c["task"] for c in cells if c["group"] in ("T", "K")}):
    a = [c["correct_cross"] for c in cells if c["task"] == t and c["arm"] == "A" and c["correct_cross"] is not None]
    r = [c["correct_cross"] for c in cells if c["task"] == t and c["arm"] == "R" and c["correct_cross"] is not None]
    print(f"{t}: A {sum(a)}/{len(a)}  R {sum(r)}/{len(r)}")

print("\n== reproduction")
for grp in ("T", "K"):
    for model in ("luna", "sonnet"):
        for arm in ("A", "R"):
            cs = by(grp, arm, model)
            if not cs: continue
            n = len(cs)
            att = sum(1 for c in cs if c["attempt_cmds"] > 0)
            files = sum(1 for c in cs if c["attempt_files"] > 0)
            claim = defaultdict(int)
            for c in cs: claim[c.get("repro_claim")] += 1
            print(f"{grp} {model:6} {arm}: n={n} ran-commands {att}, files-created {files}, mean repro cmds {sum(c['attempt_cmds'] for c in cs)/n:.1f}, claims {dict(claim)}")

print("\n== paid tokens and turns (sum; geo ratio R/A over matched cells, 95% bootstrap)")
for grp in ("T", "K", "C"):
    for model in (None, "luna", "sonnet"):
        pc = pair_cells(grp, model)
        sa = sum(p["A"]["paid_tokens"] for p in pc); sr = sum(p["R"]["paid_tokens"] for p in pc)
        ta = sum(p["A"]["turns"] or 0 for p in pc); tr = sum(p["R"]["turns"] or 0 for p in pc)
        g = geo_ci([(p["A"]["paid_tokens"], p["R"]["paid_tokens"]) for p in pc])
        gt = geo_ci([(p["A"]["turns"], p["R"]["turns"]) for p in pc if p["A"]["turns"] and p["R"]["turns"]])
        print(f"{grp} {model or 'all':7} n={len(pc)} A {sa} R {sr} (x{(sr/sa if sa else float('nan')):.2f}) geo " + ("x%.2f [%.2f; %.2f]" % g if g else "-") +
              f" | turns A {ta} R {tr} geo " + ("x%.2f [%.2f; %.2f]" % gt if gt else "-"))

print("\n== creative: win-rate of R over A")
dec = []
for f in glob.glob(str(H / "grades" / "cr-*.json")):
    g = json.load(open(f))
    if g["ok"]: dec.append(g)
def wr(ds):
    n = len(ds); w = sum(1 for d in ds if d["a_wins"] is False)
    return w, n
for label, ds in (("all", dec), ("luna authors", [d for d in dec if d["author_model"] == "luna"]), ("sonnet authors", [d for d in dec if d["author_model"] == "sonnet"]),
                  ("cross-only", [d for d in dec if d["judge"] != d["author_model"]])):
    w, n = wr(ds)
    print(f"{label}: R wins {w}/{n} = {w/n if n else float('nan'):.2f}")
pairs = defaultdict(list)
for d in dec: pairs[(d["task"], d["author_model"], d["rep"])].append(d)
rw = sum(1 for v in pairs.values() if sum(1 for d in v if d["a_wins"] is False) > len(v) / 2)
aw = sum(1 for v in pairs.values() if sum(1 for d in v if d["a_wins"] is True) > len(v) / 2)
print(f"pairs: R {rw} / A {aw} / tie {len(pairs)-rw-aw}, p={sign_p(rw, aw):.2f}")
for t in sorted({d['task'] for d in dec}):
    w, n = wr([d for d in dec if d["task"] == t]); print(f"  {t}: R wins {w}/{n}")
print("\ncontamination flags:", sum(1 for c in cells if c["contamination_flag"]), "of", len(cells))
