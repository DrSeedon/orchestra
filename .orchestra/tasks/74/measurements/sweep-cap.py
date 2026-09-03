#!/usr/bin/env python3
"""#74 — худшая порция истории по ВСЕМ сессиям живой БД: до потолка строки и после.

Идём по ВСЕЙ истории каждой сессии, а не по последней сотне строк: жирные строки лежат
где угодно, юзер доходит до них кнопкой «ещё». Замер только по последней сотне обманет —
на снимке БД от 04.08 у seo-cro блоб на 651 КБ уже выпал из последних 100 строк, и «до»
выглядело бы безобидными 8.8 КБ.

Метод #72: копия живой БД, порции как их берёт клиент (25 строк, бюджет 24 000 Б),
локальный gzip -6 приводится к проводу коэффициентом ×1.18 (nginx жмёт слабее: 145.5 КБ
по проводу против 123.1 локально на одном ответе).
"""
import gzip, json, shutil, sys, tempfile, pathlib
sys.path.insert(0, ".")
dst = pathlib.Path(tempfile.mkdtemp()) / "o.db"
shutil.copy("/home/kesha/orchestra/data/orchestra.db", dst)
import app.db as db
db.DB_PATH = dst

WIRE, BUDGET, CHUNK, MAX_CHUNKS = 1.18, 24000, 25, 400
CAP = int(sys.argv[1]) if len(sys.argv) > 1 else 16384
if len(sys.argv) > 2:
    BUDGET = int(sys.argv[2])


def gz(rows):
    return len(gzip.compress(json.dumps(rows, ensure_ascii=False, separators=(',', ':')).encode(), 6)) / 1024


def worst(sid, cap):
    before, got, sizes, cut = 2**31 - 1, 0, [], 0
    for _ in range(MAX_CHUNKS):
        part = db.get_logs_before(sid, before, CHUNK, BUDGET, cap)
        if not part:
            break
        sizes.append(gz(part))
        cut += sum(1 for r in part if "trunc" in r)
        got += len(part)
        before = min(r["id"] for r in part)
    return max(sizes, default=0), got, cut


names = {r["id"]: r["name"] for r in db._conn().execute("SELECT id, name FROM sessions")}
counts = {r["id"]: r["n"] for r in db._conn().execute(
    "SELECT session_id AS id, COUNT(*) n FROM logs GROUP BY session_id")}

print(f"потолок строки {CAP} Б\n")
print(f"{'агент':24s} {'без потолка':>13s} {'с потолком':>12s} {'обрезано строк':>15s}")
worst_before = worst_after = 0
over = []
for sid, n in sorted(counts.items(), key=lambda x: -x[1]):
    if sid not in names:
        continue
    w0, _, _ = worst(sid, 0)
    w1, got, cut = worst(sid, CAP)
    worst_before, worst_after = max(worst_before, w0), max(worst_after, w1)
    if w1 * WIRE > 15:
        over.append((names[sid], round(w1 * WIRE, 1)))
    print(f"{names[sid]:24s} {w0*WIRE:11.1f}КБ {w1*WIRE:10.1f}КБ {cut:12d}/{got}")

print(f"\nхудшая порция во всей БД: {worst_before*WIRE:.1f} КБ → {worst_after*WIRE:.1f} КБ по проводу")
print(f"сессий с порцией > 15 КБ: {len(over)}" + (f" — {over}" if over else ""))
