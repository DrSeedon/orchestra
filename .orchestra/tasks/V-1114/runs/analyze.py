import json, random, glob, sys
from pathlib import Path
from collections import defaultdict
RUNS = Path(__file__).parent
bank = {c["id"]: c for c in json.loads((RUNS.parent/"bank.json").read_text())}
sleep = json.loads((RUNS/"sleep_frozen/manifest.json").read_text())
ARMS = ["full/W0","full/W1","S1/W0","S2/W0","S2/W1","S3/W1"]
acc = defaultdict(lambda: defaultdict(list))   # arm -> qid -> [0/1 per rep]
errs = defaultdict(lambda: defaultdict(list))  # arm -> qid -> [(rep, chosen_orig)]
use = defaultdict(lambda: [0,0,0,0,0.0,0,0])   # in,out,cr,cw,usd,calls,invalid
for f in sorted(glob.glob(str(RUNS/"raw/*.json"))):
    r = json.load(open(f)); m = json.load(open(RUNS/"maps"/f"{r['key']}.json")); arm = m["arm"]
    u = use[arm]; u[5] += 1
    for row in r["usage_rows"][:1]:
        for i in range(4): u[i] += row[i] or 0
        u[4] += row[4] or 0
    ans = {a["id"]: a for a in (r["response"] or {}).get("answers", []) if isinstance(a, dict) and "id" in a}
    if set(ans) != set(m["maps"]): u[6] += 1
    for qid, mp in m["maps"].items():
        ch = mp.get(ans.get(qid, {}).get("choice"), "INVALID")
        ok = int(ch == bank[qid]["expected"])
        acc[arm][qid].append(ok)
        if not ok: errs[arm][qid].append((m["rep"], ch))
def per_q(arm, kind=None):
    return {q: sum(v)/len(v) for q, v in acc[arm].items() if kind is None or bank[q]["kind"] == kind}
def boot(d1, d2, n=5000):
    qs = sorted(set(d1) & set(d2)); diffs = [d1[q]-d2[q] for q in qs]
    rng = random.Random(7); means = []
    for _ in range(n):
        s = [diffs[rng.randrange(len(diffs))] for _ in diffs]; means.append(sum(s)/len(s))
    means.sort(); return sum(diffs)/len(diffs), means[int(.025*n)], means[int(.975*n)], len(qs)
out = []
out.append("| Плечо | Память, байт | Факты (24) | Поведение (16) | Всего (40) | вызовов | вход | вывод | cache read | cache write | API-экв. $ |")
out.append("|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|")
mem = {"full":42431}; 
for k,v in sleep.items(): mem[k] = v["memory_bytes"]
for a in ARMS:
    f, b, t = per_q(a,"fact"), per_q(a,"behavior"), per_q(a); u = use[a]
    mean = lambda d: sum(d.values())/max(len(d),1)
    nrep = max((len(v) for v in acc[a].values()), default=0)
    out.append(f"| {a} | {mem[a.split('/')[0]]} | {mean(f)*24:.2f}/24 | {mean(b)*16:.2f}/16 | {mean(t)*40:.2f}/40 | {u[5]} | {u[0]} | {u[1]} | {u[2]} | {u[3]} | {u[4]:.2f} |")
out.append("\n(значения — средние по повторам на вопрос, умноженные на число вопросов; повторов на плечо: " + ", ".join(f"{a}={max((len(v) for v in acc[a].values()), default=0)}" for a in ARMS) + ")\n")
out.append("Парные различия (по вопросам; среднее по вопросам доли верных, bootstrap 95% по вопросам, 5000 перевыборок):\n")
out.append("| Сравнение | Δ (все 40) | 95% CI | Δ факты | CI | Δ поведение | CI |")
out.append("|---|--:|---|--:|---|--:|---|")
pairs = [("full/W1","full/W0"),("S1/W0","full/W0"),("S2/W0","full/W0"),("S2/W1","full/W0"),("S3/W1","full/W0"),("S2/W1","full/W1"),("S3/W1","full/W1"),("S2/W1","S2/W0"),("S2/W0","S1/W0")]
for x, y in pairs:
    row = f"| {x} − {y} |"
    for kind in (None, "fact", "behavior"):
        d, lo, hi, n = boot(per_q(x,kind), per_q(y,kind)); row += f" {d:+.3f} | [{lo:+.3f}; {hi:+.3f}] |"
    out.append(row)
out.append("\nОшибки по плечам (id вопроса: повтор→выбранный исходный вариант; эталон в скобках; поведенческие помечены B):\n")
for a in ARMS:
    items = []
    for q in sorted(errs[a]):
        kinds = "B" if bank[q]["kind"] == "behavior" else "F"
        items.append(f"{q}[{kinds}] ({bank[q]['expected']}) " + ",".join(f"r{r}→{c}" for r, c in errs[a][q]) + f" из {len(acc[a][q])}")
    out.append(f"- **{a}**: " + ("; ".join(items) if items else "ошибок нет"))
out.append("\nНевалидных ответов (неполный набор id): " + ", ".join(f"{a}={use[a][6]}" for a in ARMS))
tot_cw = sum(u[3] for u in use.values()); out.append(f"\nИтого cache write на стенде (без сна): {tot_cw}; по формуле KB 0,6 п.п./М → {tot_cw/1e6*0.6:.2f} п.п. недели")
(RUNS/"results.md").write_text("\n".join(out)); print("\n".join(out))
