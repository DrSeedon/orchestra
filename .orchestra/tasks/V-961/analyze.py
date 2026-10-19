"""V-961: сводка кривых по judge.json. Строгий успех = score 1; 'часть' = 0.5; wrong = -1."""
import json, math, re, sys
from collections import defaultdict
from pathlib import Path
R = Path(__file__).resolve().parents[3] / "data" / "v961" / "runs"
CASES = ["gm", "uni", "rilsy", "gamelab", "lituroki"]
CLS = ["requirement", "number", "id_path", "prohibition", "open_item"]

def wilson(k, n, z=1.96):
    if n == 0: return (0, 0)
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)

def load(arm, case, k):
    d = R / arm / case / (f"hop{k}" if k else "")
    if not (d / "judge.json").exists(): return None
    j = json.load(open(d / "judge.json")); qs = {q["id"]: q for q in json.load(open(d / "qs.json"))}
    order = list(qs)
    norm = {}
    for n, (i, v) in enumerate(j.items(), 1):
        i = i[2:] if i.startswith("q_") else i
        if i not in qs and re.fullmatch(r"q\d+", i) and len(j) == len(qs):
            i = order[int(i[1:]) - 1]
        norm[i] = v
    return [(qs[i], v["score"]) for i, v in norm.items() if i in qs]

def agg(arm, k, cases=CASES):
    out = defaultdict(lambda: [0, 0, 0, 0, 0])  # n, full, half, zero, wrong
    for c in cases:
        r = load(arm, c, k)
        if r is None: continue
        for q, s in r:
            key = q["cls"] if q["kind"] == "fact" else "CONTROL"
            for kk in (key, "ALL_FACTS" if q["kind"] == "fact" else "CONTROL"):
                a = out[kk]; a[0] += 1; a[1] += s == 1; a[2] += s == 0.5; a[3] += s == 0; a[4] += s < 0
    return out

def fmt(a):
    lo, hi = wilson(a[1], a[0]); return f"{a[1]}/{a[0]} = {a[1]/a[0]:.0%} [{lo:.0%}–{hi:.0%}]"

if __name__ == "__main__":
    for arm in ("base", "copy"):
        print(f"\n=== arm {arm}: доля строго верных (score 1) фактов; контроль = доля верных UNKNOWN")
        print("hop\t" + "\t".join(CLS + ["ALL_FACTS", "CONTROL"]))
        for k in (1, 2, 3, 4):
            a = agg(arm if (arm == "base" or k > 1) else "base", k)
            if not a: continue
            print(k, *[fmt(a[c]) for c in CLS + ["ALL_FACTS", "CONTROL"]], sep="\t")
        print("wrong (-1) на фактах по hop:", {k: agg(arm if (arm == "base" or k > 1) else "base", k)["ALL_FACTS"][4] for k in (1, 2, 3, 4)},
              "| на контроле (выдумка):", {k: agg(arm if (arm == "base" or k > 1) else "base", k)["CONTROL"][4] for k in (1, 2, 3, 4)})
    a = agg("tailonly", 0); print("\ntailonly (только хвост):", {c: fmt(a[c]) for c in ("ALL_FACTS", "CONTROL")})
    print("\nпо кейсам, доля фактов score=1 (base / copy):")
    for c in CASES:
        row = []
        for k in (1, 2, 3, 4):
            b = agg("base", k, [c])["ALL_FACTS"]; cp = agg("copy" if k > 1 else "base", k, [c])["ALL_FACTS"]
            row.append(f"hop{k} {b[1]}/{b[0]} / {cp[1]}/{cp[0]}")
        print(c, " | ".join(row))
    print("\nдлины сводок (знаков) base / copy:")
    for c in CASES:
        row = []
        for k in (1, 2, 3, 4):
            m = lambda arm: json.load(open(R / arm / c / f"hop{k}" / "compress.json"))["summary_chars"]
            row.append(f"{m('base')}" + (f"/{m('copy')}" if k > 1 else ""))
        print(c, row)
    tot = sum(json.loads(l)["cost"] for l in open(R.parent / "ledger.jsonl")); print("\nledger total API-eq $", round(tot, 2))

    print("\nМеханическая проверка (без судьи): ключевой токен факта есть в тексте сводки; доля по классам")
    for arm in ("base", "copy"):
        for k in (1, 2, 3, 4):
            tot = defaultdict(lambda: [0, 0])
            for c in CASES:
                a = arm if (arm == "base" or k > 1) else "base"
                f = R / a / c / f"hop{k}" / "summary.md"
                facts = json.load(open(R.parent / "cases" / c / "facts.json"))
                text = f.read_text()
                for x in facts:
                    for key in (x["cls"], "ALL"):
                        tot[key][0] += 1; tot[key][1] += all(t in text for t in x["must_contain"])
            print(arm, k, {c: f"{v[1]}/{v[0]}" for c, v in tot.items()})

    print("\nПовторы шага 4 при тех же входах (сводка hop3 исходного плеча): факты score=1 из 15 по кейсам")
    for src in ("base", "copy"):
        for c in CASES:
            row = []
            for tag in [src] + [f"{src}_r{r}" for r in range(1, 6)]:
                a = agg(tag, 4, [c])["ALL_FACTS"]
                if a[0]: row.append(f"{a[1]}/{a[0]}")
            print(src, c, row)
