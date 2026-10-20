"""V-961: перенос результатов из data/v961 (gitignored) в results/ перед удалением сырья.

Сохраняется: оценки по каждому вопросу каждого прогона (evals.jsonl), сводки каждого шага (маскированные по форме,
как в V-643/export.py), метаданные кейсов и посаженные факты, позиции посадки, черновики пробы, логи фаз.
Не сохраняется (личные данные сессий, восстанавливается по session_id и preamble_ids из БД командой stand.py prep):
segments.json, tails.json, pre0.txt, snap.db, песочницы.
"""
import importlib.util
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SRC = ROOT / "data" / "v961"
DST = HERE / "results"
spec = importlib.util.spec_from_file_location("exp643", ROOT / ".orchestra" / "tasks" / "V-643" / "export.py")
exp643 = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(ROOT))
spec.loader.exec_module(exp643)
clean = exp643.clean


def main():
    hits = 0
    rows = []
    for d in sorted(SRC.glob("runs/*/*/hop*")) + sorted(SRC.glob("runs/tailonly/*")):
        if not (d / "judge.json").exists():
            continue
        arm = d.parts[-3] if d.name.startswith("hop") else "tailonly"
        case = d.parts[-2] if d.name.startswith("hop") else d.name
        hop = int(d.name[3:]) if d.name.startswith("hop") else 0
        j = json.loads((d / "judge.json").read_text())
        qs = {q["id"]: q for q in json.loads((d / "qs.json").read_text())}
        ans = json.loads((d / "answers.json").read_text())
        order = list(qs)
        pos = {f"q{n}": k for n, k in enumerate(order, 1)}
        ans = {pos.get(k, k): v for k, v in ans.items()} if not any(k in qs for k in ans) else ans
        for k, v in j.items():
            k2 = k[2:] if k.startswith("q_") else pos.get(k, k) if len(j) == len(qs) else k
            if k2 not in qs:
                continue
            q = qs[k2]
            a, h = clean(str(ans.get(k2, "")))
            hits += h
            rows.append(dict(arm=arm, case=case, hop=hop, qid=k2, kind=q["kind"], cls=q["cls"], score=v["score"], why=v.get("why"), gold=q["gold"], answer=a))
        if d.name.startswith("hop") and (d / "summary.md").exists():
            out = DST / "summaries" / arm / case / f"hop{hop}.md"
            out.parent.mkdir(parents=True, exist_ok=True)
            text, h = clean((d / "summary.md").read_text())
            hits += h
            out.write_text(text)
            for extra in ("block.txt",):
                if (d / extra).exists():
                    t, h = clean((d / extra).read_text()); hits += h
                    (out.parent / f"hop{hop}.block.txt").write_text(t)
            if (d / "compress.json").exists():
                shutil.copy(d / "compress.json", out.parent / f"hop{hop}.compress.json")
    (DST / "evals.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    for c in sorted((SRC / "cases").iterdir()):
        o = DST / "cases" / c.name
        o.mkdir(parents=True, exist_ok=True)
        for f in ("meta.json", "controls.json"):
            shutil.copy(c / f, o / f)
        segs = json.loads((c / "segments.json").read_text())
        planted = [dict(id=r["id"], position_in_segment1=i, message=r["content"]) for i, r in enumerate(segs[0]) if "p" in str(r["id"]) and r["type"] == "user_message" and str(r["id"])[-1].isdigit() and "p" in str(r["id"])]
        (o / "planted_messages.json").write_text(json.dumps(planted, ensure_ascii=False, indent=1))
    pr = DST / "probe"
    pr.mkdir(exist_ok=True)
    for f in sorted((SRC / "probe").glob("draft*.md")):
        t, h = clean(f.read_text()); hits += h
        (pr / f.name).write_text(t)
    for f in ("phaseA.log", "phaseB.log", "repeat.log", "rejudge.log", "rejudge2.log", "smoke.log", "analysis.txt"):
        if (SRC / f).exists():
            t, h = clean((SRC / f).read_text()); hits += h
            (DST / "logs").mkdir(exist_ok=True)
            (DST / "logs" / f).write_text(t)
    print("rows", len(rows), "masked", hits)


if __name__ == "__main__":
    main()
