"""V-963: таблицы по data/v963/runs: old против new на одинаковых входах."""
import json, math, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
R = ROOT / "data" / "v963" / "runs"
STRONG = re.compile(r"НЕ применять|не применять|не считать|не найден|не подтверждены?\b.*(?:источник|журнал)|без уточнения", re.I)
WEAK = re.compile(r"исполнение не подтвержд|не подтвержд|unconfirmed|unverified", re.I)
TOK = ["ФЛОКС-26", "КОРУНД-59", "RB-2204", "draft-6978", "backup/kv129", "omega-4", "#ops-95", "/srv/stage_52", "index_63.csv"]


def wilson(k, n, z=1.96):
    if n == 0: return (0, 0)
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def fmt(k, n):
    lo, hi = wilson(k, n); return f"{k}/{n} = {k/n:.0%} [{lo:.0%}–{hi:.0%}]"


def load(arm, case):
    out = []
    for d in sorted((R / arm / case).glob("r*")):
        if not (d / "judge.json").exists(): continue
        j = json.load(open(d / "judge.json")); q = {x["id"]: x for x in json.load(open(d / "qs.json"))}
        s = (d / "summary.md").read_text()
        facts = [v["score"] for k, v in j.items() if k in q and q[k]["kind"] == "fact"]
        lines = s.splitlines()
        near = [l for i, l in enumerate(lines) if any(t in l for t in TOK)]
        ctx = []
        for i, l in enumerate(lines):
            if any(t in l for t in TOK):
                ctx.append(" ".join(lines[max(0, i - 2): i + 2]))
        out.append(dict(run=d.name, facts_ok=sum(x == 1 for x in facts), n_facts=len(facts),
                        cancel=j.get("x_cancel", {}).get("score"), replace=j.get("x_replace", {}).get("score"),
                        ctrl_bad=sum(v["score"] < 0 for k, v in j.items() if k in q and q[k]["kind"] == "control"),
                        strong=any(STRONG.search(c) for c in ctx), weak=any(WEAK.search(c) for c in ctx),
                        chars=len(s), cost=json.load(open(d / "compress.json"))["cost"]))
    return out


if __name__ == "__main__":
    for case, variant in [(c, v) for v in ("_plain", "") for c in ("uni", "gm")]:
        print(f"\n=== кейс {case}, {'входы как в V-961 (без вставок)' if variant else 'в сегмент 4 вставлены сообщения отмены и замены'} (шаг №4, сводка №3 из V-961 base)")
        for arm in (f"old{variant}", f"new{variant}"):
            r = load(arm, case); n = len(r)
            if not n: continue
            coll = sum(x["facts_ok"] <= x["n_facts"] // 2 for x in r)
            part = sum(0 < x["n_facts"] - x["facts_ok"] and x["facts_ok"] > x["n_facts"] // 2 for x in r)
            full = sum(x["facts_ok"] == x["n_facts"] for x in r)
            tot_ok = sum(x["facts_ok"] for x in r); tot = sum(x["n_facts"] for x in r)
            print(f"{arm}: прогонов {n}; все факты верны {fmt(full, n)}; обрушение (<=50% фактов) {fmt(coll, n)}; частичная потеря {fmt(part, n)}")
            if variant:
                print(f"     фактов верно {fmt(tot_ok, tot)}; "
                      f"пометка «не применять/не найден/без уточнения» рядом с правилами {fmt(sum(x['strong'] for x in r), n)}; слабая «не подтверждено» {fmt(sum(x['weak'] for x in r), n)}; "
                      f"выдумка на контроле {sum(x['ctrl_bad'] for x in r)}; знаков медиана {sorted(x['chars'] for x in r)[n//2]} (мин {min(x['chars'] for x in r)}, макс {max(x['chars'] for x in r)}); $ {sum(x['cost'] for x in r):.1f}")
                continue
            print(f"     фактов верно {fmt(tot_ok, tot)}; отмена показана верно {fmt(sum(x['cancel'] == 1 for x in r), n)}; "
                  f"отмена воскрешена (-1) {fmt(sum(x['cancel'] < 0 for x in r), n)}; замена верна {fmt(sum(x['replace'] == 1 for x in r), n)}; старое значение (-1) {fmt(sum(x['replace'] < 0 for x in r), n)}")
            print(f"     пометка «не применять/не найден/без уточнения» рядом с правилами {fmt(sum(x['strong'] for x in r), n)}; слабая «не подтверждено» {fmt(sum(x['weak'] for x in r), n)}; "
                  f"выдумка на контроле {sum(x['ctrl_bad'] for x in r)}; знаков медиана {sorted(x['chars'] for x in r)[n//2]} (мин {min(x['chars'] for x in r)}, макс {max(x['chars'] for x in r)}); $ {sum(x['cost'] for x in r):.1f}")
