"""V-643: прототип агентного сжатия для одной живой сессии (вне прод-пути compact()).

    python agentic_compact.py <session_name> [--scope S] [--db data/snap.db] [--method hybrid|seq3] [--out DIR]

Берёт журнал сессии от последней преамбулы компакта до конца из КОПИИ БД, раскладывает
его файлами (journal/chunk_*.md + journal.jsonl) и гоняет выбранный метод той же моделью,
на которой шла сессия. Печатает путь к summary.md и цену. Прод-компакт не вызывается.
"""
import argparse
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import bench  # noqa: E402
import extract  # noqa: E402
import methods  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--scope", default="")
    ap.add_argument("--db", default=str(extract.DB))
    ap.add_argument("--method", default="hybrid", choices=["hybrid", "seq3"])
    ap.add_argument("--out", default="")
    a = ap.parse_args()

    db = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    q = "select id,model from sessions where name=?" + (" and scope=?" if a.scope else "")
    sid, model = db.execute(q, (a.session, a.scope) if a.scope else (a.session,)).fetchone()
    start = db.execute("select coalesce(max(id),0) from logs where session_id=? and type='user_message' "
                       "and content like '[PREVIOUS CONTEXT SUMMARY%'", (sid,)).fetchone()[0]
    rows = extract.seg_rows(db, sid, start, 10**12)

    out = Path(a.out or tempfile.mkdtemp(prefix="agentic-compact-"))
    extract.OUT = out / "cases"
    case = f"{a.session}-live"
    extract.write_case(case, dict(cid=None, sid=sid, name=a.session, model=model), rows, "", "")
    case_dir = extract.OUT / case
    sbx = out / "sandbox"
    import shutil
    shutil.copytree(case_dir / "journal", sbx / "journal")
    ctx = dict(case_dir=case_dir, sandbox=sbx, claude=bench.claude, label=f"live:{a.method}:{a.session}")
    if a.method == "hybrid":
        draft, recs = methods.METHODS["oneshot"](ctx)
        (sbx / "summary.md").write_text(draft)
        for i, p in enumerate([methods.AUDIT, methods.FINAL], 2):
            _, rec = bench.claude(p.format(n=i, cap=20000), sbx, model=model, tools=methods.TOOLS,
                                  label=f"{ctx['label']}:p{i}")
            recs.append(rec)
        summary = (sbx / "summary.md").read_text()
    else:
        summary, recs = methods.METHODS["seq3"](ctx)
    print(json.dumps(dict(summary=str(sbx / "summary.md"), chars=len(summary),
                          cost=round(sum(r["cost"] for r in recs), 3),
                          sec=round(sum(r["sec"] for r in recs), 1)), ensure_ascii=False))


if __name__ == "__main__":
    main()
