"""V-643: сводные таблицы для отчёта из data/v643 (оценки, цены, реальные компакты).

python analyze.py > results/analysis.md
"""
import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import bench  # noqa: E402

DEV = ["Orchestra-orchestrator-427977", "seo-cro-435842", "oge-russkiy-425581", "University-orchestrator-403387"]
HOLD = ["katya-work-orchestrator-441732", "cog-second-brain-orchestrator-421326", "designer-447804",
        "bizdev-390824", "slipways-437565"]
# Opus 5.5 по ответам CLI (list): чтение кеша ~$0.2/M, выход ~$20/M, запись 1h-кеша ~$8/M.
READ, OUT, WRITE = 0.2e-6, 20e-6, 8e-6


def real_meta(case):
    """Реальный компакт в копии БД: размер контекста, время, размер сводки."""
    cid = int(case.rsplit("-", 1)[1])
    db = sqlite3.connect(f"file:{bench.ROOT/'data'/'snap.db'}?mode=ro", uri=True)
    sid = db.execute("select session_id from logs where id=?", (cid,)).fetchone()[0]
    rows = db.execute("select ts,content from logs where session_id=? and id between ? and ? and type='status' "
                      "and content like 'compact %' order by id", (sid, cid - 300, cid + 15)).fetchall()
    start = [r for r in rows if r[1].startswith("compact started")][-1]
    done = [r for r in rows if r[1].startswith("compact done")]
    m = re.search(r"pre (\d+)", done[-1][1]) if done else None
    pre = int(m.group(1)) if m else None
    from datetime import datetime
    sec = (datetime.fromisoformat(done[-1][0]) - datetime.fromisoformat(start[0])).total_seconds() if done else None
    return pre, sec


def load(method, case):
    run = bench.RUNS / method / case
    if not (run / "judge.json").exists():
        return None
    return dict(acc=bench.score(method, case, bench.easy_ids(case)),
                judge=json.loads((run / "judge.json").read_text()),
                answers=json.loads((run / "answers.json").read_text()),
                meta=json.loads((run / "compress.json").read_text()))


def table(cases, methods, title):
    print(f"\n### {title}\n")
    print("| метод | " + " | ".join(c.rsplit("-", 1)[0] for c in cases) + " | среднее | уверенно неверных | сводка, симв. | $ сжатия | сек |")
    print("|" + "---|" * (len(cases) + 6))
    for m in methods:
        cells, accs, wrong, ch, co, se = [], [], 0, [], [], []
        for c in cases:
            r = load(m, c)
            if r is None:
                cells.append("—"); continue
            r2 = load(m + "_r2", c)
            a = r["acc"][0] if r2 is None else (r["acc"][0] + r2["acc"][0]) / 2
            cells.append(f"{a:.2f}"); accs.append(a); wrong += r["acc"][1]
            ch.append(r["meta"]["summary_chars"]); co.append(r["meta"]["cost"]); se.append(r["meta"]["sec"])
            if m == "hybrid":  # время черновика считается отдельно
                se[-1] += json.loads((bench.RUNS / "oneshot" / c / "compress.json").read_text())["sec"]
            if m == "real":
                pre, sec = real_meta(c)
                co[-1] = pre * READ + r["meta"]["summary_chars"] / 3 * OUT
                se[-1] = sec or 0
        if not accs:
            continue
        print(f"| {m} | " + " | ".join(cells) + f" | **{sum(accs)/len(accs):.3f}** | {wrong} | "
              f"{sum(ch)//len(ch)} | {sum(co)/len(co):.2f} | {sum(se)/len(se):.0f} |")


def by_category(cases, methods):
    print("\n### Точность по категориям вопросов (все кейсы, где метод есть)\n")
    cats = sorted({q["category"] for c in cases for q in json.loads((bench.EVAL / c / "questions.json").read_text())})
    print("| метод | " + " | ".join(cats) + " |")
    print("|" + "---|" * (len(cats) + 1))
    for m in methods:
        s, n = defaultdict(float), defaultdict(int)
        for c in cases:
            r = load(m, c)
            if r is None:
                continue
            easy = bench.easy_ids(c)
            for q in json.loads((bench.EVAL / c / "questions.json").read_text()):
                if q["id"] in easy:
                    continue
                s[q["category"]] += max(r["judge"].get(q["id"], {}).get("score", 0), 0)
                n[q["category"]] += 1
        print(f"| {m} | " + " | ".join(f"{s[k]/n[k]:.2f} ({n[k]})" if n[k] else "—" for k in cats) + " |")


def losses(cases, a, b, limit=12):
    """Факты, которые метод a потерял, а b сохранил (score a<=0, b==1)."""
    print(f"\n### Потеряно в `{a}`, сохранено в `{b}`\n")
    k = 0
    for c in cases:
        ra, rb = load(a, c), load(b, c)
        if not ra or not rb:
            continue
        for q in json.loads((bench.EVAL / c / "questions.json").read_text()):
            sa = ra["judge"].get(q["id"], {}).get("score", 0)
            sb = rb["judge"].get(q["id"], {}).get("score", 0)
            if sa <= 0 and sb == 1 and q.get("importance", 2) >= 2 and k < limit:
                k += 1
                print(f"- **{c.rsplit('-',1)[0]} / {q['category']}** — {q['question']}\n"
                      f"  - эталон: {q['gold']}\n  - `{a}`: {str(ra['answers'].get(q['id']))[:220]}\n"
                      f"  - `{b}`: {str(rb['answers'].get(q['id']))[:220]}")


if __name__ == "__main__":
    ms = ["real", "oneshot", "seq3", "mapred3", "hybrid"]
    table(DEV, ms, "Dev (4 кейса, на них подбирались варианты; real/oneshot/seq3 — среднее двух оценок)")
    table(HOLD, ms, "Holdout (5 кейсов, не использовались при подборе)")
    table(DEV + HOLD, ["real", "oneshot", "hybrid"], "Все 9 кейсов")
    by_category(DEV + HOLD, ms)
    losses(DEV + HOLD, "real", "hybrid")
    losses(DEV + HOLD, "hybrid", "real", limit=8)
    losses(DEV + HOLD, "oneshot", "hybrid", limit=8)
