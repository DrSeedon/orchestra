#!/usr/bin/env python3
"""#72 — какой бюджет байт на порцию держит ответ под порогом. Считаем по живой БД (копия).

Коэффициент wire/local: nginx жмёт слабее локального gzip -6 — на холодной синхронизации
145.5 КБ по проводу против 123.1 КБ локально, то есть ×1.18. Порог 15 КБ по проводу
означает ~12.7 КБ локально.
"""
import gzip, json, shutil, sys, tempfile, pathlib
sys.path.insert(0, ".")
src = "/home/kesha/orchestra/data/orchestra.db"
dst = pathlib.Path(tempfile.mkdtemp()) / "o.db"
shutil.copy(src, dst)
import app.db as db
db.DB_PATH = dst

WIRE = 1.18


def gz(rows):
    return len(gzip.compress(json.dumps(rows, ensure_ascii=False, separators=(',', ':')).encode(), 6)) / 1024


def page(session_id, budget, limit=25, pages=4):
    before, out = 2**31 - 1, []
    for _ in range(pages):
        rows = db.get_logs_before(session_id, before, limit, budget) if budget else db.get_logs_before(session_id, before, limit)
        if not rows:
            break
        out.append((len(rows), gz(rows)))
        before = min(r["id"] for r in rows)
    return out


sessions = {r["name"]: r["id"] for r in db._conn().execute("SELECT id, name FROM sessions")}
names = sys.argv[1:] or ["Orchestra-orchestrator", "frontend", "back", "perf", "feat-instant"]
for budget in (0, 60000, 40000, 24000):
    print(f"\nбюджет content {budget or '—'} Б на порцию:")
    for n in names:
        if n not in sessions:
            continue
        pg = page(sessions[n], budget)
        worst = max((k for _, k in pg), default=0)
        print(f"  {n:22s} порции: " + ", ".join(f"{c}стр/{k:.1f}КБ" for c, k in pg)
              + f"  → худшая {worst:5.1f} КБ локально ≈ {worst*WIRE:5.1f} КБ по проводу")
