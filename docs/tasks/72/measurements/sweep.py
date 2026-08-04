#!/usr/bin/env python3
"""#72 — прогон по ВСЕМ сессиям живой БД: сколько порций до 100 строк и какая худшая порция.

Копия живой БД, не фикстура: размер сообщения гуляет на три порядка, и выборка из пяти
агентов не показывает хвост.
"""
import gzip, json, shutil, sys, tempfile, pathlib
sys.path.insert(0, ".")
src = "/home/kesha/orchestra/data/orchestra.db"
dst = pathlib.Path(tempfile.mkdtemp()) / "o.db"
shutil.copy(src, dst)
import app.db as db
db.DB_PATH = dst

WIRE = 1.18          # nginx жмёт слабее локального gzip -6: 145.5 КБ по проводу против 123.1
BUDGET = 24000
PAGE, CHUNK, MAX_CHUNKS = 100, 25, 12


def gz(rows):
    return len(gzip.compress(json.dumps(rows, ensure_ascii=False, separators=(',', ':')).encode(), 6)) / 1024


rows_by_sess = {r["id"]: r["n"] for r in db._conn().execute(
    "SELECT session_id AS id, COUNT(*) n FROM logs GROUP BY session_id")}
names = {r["id"]: r["name"] for r in db._conn().execute("SELECT id, name FROM sessions")}

print(f"{'агент':24s} {'строк':>6s} {'одним':>8s} {'порций':>7s} {'строк':>6s} {'худшая':>8s} {'по проводу':>11s}")
worst_all, over = 0, []
for sid, n in sorted(rows_by_sess.items(), key=lambda x: -x[1]):
    if sid not in names:
        continue
    one = gz(db.get_logs_before(sid, 2**31 - 1, PAGE))
    before, got, sizes = 2**31 - 1, 0, []
    for _ in range(MAX_CHUNKS):
        need = min(PAGE - got, CHUNK)
        if need <= 0:
            break
        part = db.get_logs_before(sid, before, need, BUDGET)
        if not part:
            break
        sizes.append(gz(part))
        got += len(part)
        before = min(r["id"] for r in part)
    worst = max(sizes, default=0)
    worst_all = max(worst_all, worst)
    if worst * WIRE > 15:
        over.append((names[sid], worst * WIRE))
    print(f"{names[sid]:24s} {n:6d} {one:7.1f}К {len(sizes):7d} {got:6d} {worst:7.1f}К {worst*WIRE:10.1f}К")

print(f"\nхудшая порция по всем сессиям: {worst_all:.1f} КБ локально ≈ {worst_all*WIRE:.1f} КБ по проводу")
print(f"сессий, где порция превышает 15 КБ по проводу: {len(over)}" + (f" — {over}" if over else ""))
