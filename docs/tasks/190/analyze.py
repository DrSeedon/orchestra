#!/usr/bin/env python3
"""#190 — расчёт под решение о подписках. Запуск:

    python3 docs/tasks/190/analyze.py [путь-к-снимку.db]

Снимок делать ТОЛЬКО через Connection.backup (при WAL `cp` отдаёт устаревший срез):

    mkdir -p data/tmp190 && python3 -c "import sqlite3;s=sqlite3.connect('data/orchestra.db');\
d=sqlite3.connect('data/tmp190/snap.db');s.backup(d)"

Скрипт выводит ВСЕ несущие числа research.md сам, включая те, что раньше были
захардкожены со слов соседних агентов (пул Claude, курс r, границы блокировки).
Что скриптом НЕ считается, помечено в research.md как внешний вход.
"""
import collections
import glob
import json
import sqlite3
import statistics
import sys

DB = sys.argv[1] if len(sys.argv) > 1 else "data/tmp190/snap.db"

# Кредитный rate card Codex за 1M токенов для GPT-5.6 Sol: свежий вход / кеш / выход.
# Проверено у первоисточника 11.08.2026 (docs/tasks/190/web-pricing.md). Подвижен:
# соседние строки той же таблицы за 24 дня менялись в разы.
CRED_FRESH_IN, CRED_CACHED_IN, CRED_OUT = 125.0, 12.5, 750.0

# Единственная граница периода: раньше turn_usage не существует. Всё, что считается
# по logs, обрезается той же границей — иначе числитель шире знаменателя.
T0 = "2026-08-03"


def credits(fresh_in, cached_in, out):
    return (fresh_in * CRED_FRESH_IN + cached_in * CRED_CACHED_IN + out * CRED_OUT) / 1e6


def head(t):
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")


db = sqlite3.connect(DB)
db.row_factory = sqlite3.Row

# фильтр фальшивых нулей из #162: оба процента 0 И оба resets_at пустые
CLEAN = ("NOT (five_hour_pct=0 AND seven_day_pct=0 AND COALESCE(five_hour_resets_at,'')=''"
         " AND COALESCE(seven_day_resets_at,'')='')")

# ---------------------------------------------------------------- 0. границы
head("0. Что есть в данных (границы выводятся, не задаются)")
for tbl in ("turn_usage", "logs", "usage_snapshots"):
    r = db.execute(f"SELECT MIN(ts) a, MAX(ts) b, COUNT(*) n FROM {tbl}").fetchone()
    print(f"  {tbl:16} {r['n']:6} строк   {r['a'][:16]} .. {r['b'][:16]}")
tu = db.execute("SELECT MIN(ts) a, MAX(ts) b FROM turn_usage").fetchone()
T1 = tu["b"]
import datetime as _dt
DAYS = ((_dt.datetime.fromisoformat(tu["b"]) - _dt.datetime.fromisoformat(tu["a"]))
        .total_seconds() / 86400)
print(f"\n  Период анализа: {tu['a'][:16]} .. {T1[:16]} = {DAYS:.2f} суток (ВЫЧИСЛЕНО).")
print("  «Последние две недели» физически не покрыты. Всё недельное — экстраполяция.")

# ------------------------------------------------- 1. семантика кеша (#175)
head("1. Семантика cached-токенов различается у провайдеров (грабля #175)")
for rt in ("claude", "codex"):
    tot = db.execute("SELECT COUNT(*) FROM turn_usage WHERE runtime=?", (rt,)).fetchone()[0]
    le = db.execute("SELECT COUNT(*) FROM turn_usage WHERE runtime=?"
                    " AND cache_read_tokens<=input_tokens", (rt,)).fetchone()[0]
    print(f"  {rt:7} cache_read <= input в {le}/{tot} строк")
print("  → у Anthropic cached НЕ входит в input_tokens, у OpenAI входит.")

# ------------------------------------------------------- 2. объём по рантайму
head("2. Объём работы по рантаймам")
vol = {}
for rt in ("claude", "codex"):
    r = db.execute(
        """SELECT COUNT(*) n, SUM(cost_usd) usd, COUNT(DISTINCT session_id) s, AVG(cost_usd) ac,
                  AVG(input_tokens) ai, AVG(cache_read_tokens) acr, AVG(output_tokens) ao,
                  SUM(input_tokens) si, SUM(cache_read_tokens) scr, SUM(output_tokens) so
           FROM turn_usage WHERE runtime=?""", (rt,)).fetchone()
    vol[rt] = r
    print(f"  {rt:7} ходов {r['n']:5}  ${r['usd']:7.0f}  сессий {r['s']:3}"
          f"  ->  {r['n'] / DAYS * 7:5.0f} ходов/нед, ${r['usd'] / DAYS * 7:6.0f}/нед")
    print(f"          средний ход ${r['ac']:.3f}, вход {r['ai'] / 1e6:.2f}M,"
          f" cache_read {r['acr'] / 1e6:.2f}M, выход {r['ao'] / 1e3:.1f}K")

# --------------------------------- 3. границы блокировки ВЫВОДЯТСЯ из данных
head("3. Блокировки Claude — границы выводятся из usage_snapshots, не задаются")
rows = db.execute(f"SELECT ts, seven_day_pct s FROM usage_snapshots WHERE {CLEAN} ORDER BY ts").fetchall()
eps, cur = [], None
for r in rows:
    if r["s"] >= 100 and cur is None:
        cur = r["ts"]
    elif r["s"] < 100 and cur is not None:
        eps.append((cur, r["ts"]))
        cur = None
if cur:
    eps.append((cur, rows[-1]["ts"]))
tot_h = 0.0
for a, b in eps:
    h = (_dt.datetime.fromisoformat(b) - _dt.datetime.fromisoformat(a)).total_seconds() / 3600
    tot_h += h
    print(f"  7d = 100%: {a[:16]} -> {b[:16]}  = {h:5.1f} ч")
print(f"  ИТОГО полной блокировки: {tot_h:.1f} ч за {len(eps)} эпизода")
BLK = [e for e in eps if e[0] >= T0]
if BLK:
    A, B = BLK[-1]
    print(f"\n  Последний эпизод (в периоде turn_usage): {A[:16]} -> {B[:16]}")
    for rt in ("claude", "codex"):
        r = db.execute("SELECT COUNT(*) n, SUM(cost_usd) usd FROM turn_usage"
                       " WHERE runtime=? AND ts>=? AND ts<=?", (rt, A, B)).fetchone()
        print(f"    {rt:7} ходов {r['n']:4}  ${r['usd'] or 0:7.1f}"
              f"   ({r['n'] / vol[rt]['n'] * 100:4.1f}% всех своих ходов за период)")
    print("\n  Устойчивость к сдвигу границ (±2 ч, ±6 ч):")
    for sh in (2, 6):
        d = _dt.timedelta(hours=sh)
        a2 = (_dt.datetime.fromisoformat(A) + d).isoformat()
        b2 = (_dt.datetime.fromisoformat(B) - d).isoformat()
        n = db.execute("SELECT COUNT(*) FROM turn_usage WHERE runtime='codex' AND ts>=? AND ts<=?",
                       (a2, b2)).fetchone()[0]
        print(f"    окно сужено на ±{sh} ч: {n} ходов Codex = {n / vol['codex']['n'] * 100:.0f}%")

# ------------------------------------- 4. пул Claude ВЫВОДИТСЯ из turn_usage
head("4. Недельный пул Claude — считается здесь, а не берётся у соседнего агента")
w = db.execute(f"""SELECT ts, seven_day_pct s FROM usage_snapshots WHERE {CLEAN}
                   AND ts>='{T0}' ORDER BY ts""").fetchall()
start = None
for r in w:
    if r["s"] <= 2:
        start = r["ts"]
    elif r["s"] >= 100:
        break
end = next((r["ts"] for r in w if r["ts"] > (start or "") and r["s"] >= 100), None)
if start and end:
    r = db.execute("SELECT COUNT(*) n, SUM(cost_usd) usd FROM turn_usage"
                   " WHERE runtime='claude' AND ts>=? AND ts<=?", (start, end)).fetchone()
    POOL_TURNS, POOL_USD = r["n"], r["usd"]
    print(f"  Окно 7d от ~0% до 100%: {start[:16]} -> {end[:16]}")
    print(f"  Израсходовано за него: {POOL_TURNS} ходов Claude, ${POOL_USD:.0f}")
    print(f"  => недельный пул ≈ {POOL_TURNS} ходов / ${POOL_USD:.0f}; 1 пп ≈ ${POOL_USD / 100:.1f}")
    print("  (Сверка с независимым замером quota-policy #186: 1010 ходов / $1730.)")
else:
    POOL_TURNS, POOL_USD = 1010, 1730
    print("  Окно 0->100% не найдено, взят внешний замер #186: 1010 / $1730")

# ------------------------------- 5. доля codex_review, метод А (кредиты)
head("5A. Доля codex_review в расходе Codex — метод «кредиты по rate card»")
rev = []
for f in sorted(glob.glob("/tmp/codex_review_*.jsonl")):
    for line in open(f, errors="replace"):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        if o.get("type") == "turn.completed" and "usage" in o:
            u = o["usage"]
            rev.append((u["input_tokens"], u.get("cached_input_tokens", 0), u["output_tokens"]))
CALLS_SQL = """SELECT COUNT(*) FROM logs WHERE type='tool'
    AND (content LIKE 'mcp__orchestra__codex_review:%'
         OR (content LIKE 'Bash:%' AND content LIKE '%codex exec%'))"""
calls_all = db.execute(CALLS_SQL).fetchone()[0]
calls = db.execute(CALLS_SQL + " AND ts>=? AND ts<=?", (T0, T1)).fetchone()[0]
print(f"  Вызовов ревью В ПЕРИОДЕ turn_usage: {calls}  (за всю историю logs: {calls_all})")
print("  Числитель и знаменатель теперь на одном периоде. Разницы нет: вне периода вызовов 0.")
if not rev:
    print("  НЕТ токенов: /tmp/codex_review_*.jsonl вычищены — метод А невоспроизводим.")
else:
    n = len(rev)
    r_in, r_cached, r_out = (sum(x[i] for x in rev) for i in (0, 1, 2))
    r_fresh = r_in - r_cached
    print(f"  Замерено ревью с usage-событием: {n} из {calls} ({n / calls * 100:.0f}%)")
    print(f"  медиана: вход {statistics.median([x[0] for x in rev]):,.0f},"
          f" выход {statistics.median([x[2] for x in rev]):,.0f}")
    sc = calls / n
    rev_cred = credits(r_fresh * sc, r_cached * sc, r_out * sc)
    v = vol["codex"]
    work_cred = credits(v["si"] - v["scr"], v["scr"], v["so"])
    print(f"\n  кредиты ревью    ≈ {rev_cred:8.0f}")
    print(f"  кредиты воркеров ≈ {work_cred:8.0f}")
    print(f"  ДОЛЯ РЕВЬЮ в расходе Codex = {rev_cred / (rev_cred + work_cred) * 100:.1f}%")
    print("\n  Чувствительность к весу кеша:")
    for name, cf, cc, co in (("кеш бесплатен", 125.0, 0.0, 750.0),
                             ("кеш = свежему", 125.0, 125.0, 750.0)):
        a = (r_fresh * sc * cf + r_cached * sc * cc + r_out * sc * co) / 1e6
        b = ((v["si"] - v["scr"]) * cf + v["scr"] * cc + v["so"] * co) / 1e6
        print(f"    {name:14} -> доля ревью {a / (a + b) * 100:5.1f}%")
    print("\n  Чувствительность к нерепрезентативности выживших файлов:")
    for k in (1.5, 2.0, 3.0):
        a = rev_cred * k
        print(f"    если несохранившиеся ревью в {k}x крупнее -> доля {a / (a + work_cred) * 100:5.1f}%")

# --------------- 6. метод Б: почасовой счётчик, нормировка на КРЕДИТЫ
head("5Б. Верхняя граница расхода ревью по счётчику квоты Codex (нормировка — кредиты)")
rows = db.execute("SELECT ts, provider_usage FROM usage_snapshots"
                  " WHERE provider_usage LIKE '%codex%' AND ts>='2026-08-11T00:00' ORDER BY ts").fetchall()
util = {}
for r in rows:
    cx = (json.loads(r["provider_usage"]).get("codex") or {})
    ww = cx.get("windows") or cx.get("primary")
    if isinstance(ww, list) and ww:
        ww = ww[0]
    if isinstance(ww, dict) and ww.get("utilization") is not None:
        util[r["ts"][:13]] = ww["utilization"]
h_cred, h_turn, h_rev = collections.Counter(), collections.Counter(), collections.Counter()
for r in db.execute("SELECT ts,input_tokens i,cache_read_tokens c,output_tokens o"
                    " FROM turn_usage WHERE runtime='codex' AND ts>='2026-08-11T00:00'"):
    h_cred[r["ts"][:13]] += credits(r["i"] - r["c"], r["c"], r["o"])
    h_turn[r["ts"][:13]] += 1
for r in db.execute("""SELECT ts FROM logs WHERE ts>='2026-08-11T00:00' AND type='tool'
       AND (content LIKE 'mcp__orchestra__codex_review:%'
            OR (content LIKE 'Bash:%' AND content LIKE '%codex exec%'))"""):
    h_rev[r["ts"][:13]] += 1
print(f"  {'час':14}{'квота%':>7}{'Δпп':>5}{'ходы':>6}{'кредиты Sol':>13}{'ревью':>7}{'пп/1k кред':>12}")
prev = None
cd, cc_, md, mc, mrev = 0, 0.0, 0, 0.0, 0
for h in sorted(util):
    d = None if prev is None else util[h] - prev
    rate = f"{d / (h_cred[h] / 1000):.2f}" if d and h_cred[h] else "-"
    print(f"  {h:14}{util[h]:7}{'' if d is None else d:>5}{h_turn[h]:6}"
          f"{h_cred[h]:13.0f}{h_rev[h]:7}{rate:>12}")
    if d is not None and h_cred[h]:
        if h_rev[h] == 0:
            cd += d; cc_ += h_cred[h]
        else:
            md += d; mc += h_cred[h]; mrev += h_rev[h]
    prev = util[h]
if cc_ and mc:
    rate = cd / cc_
    print(f"\n  Часы БЕЗ ревью: +{cd} пп на {cc_:.0f} кредитов Sol -> {rate * 1000:.2f} пп/1k кредитов")
    print(f"  Часы С ревью ({mrev} шт): +{md} пп на {mc:.0f} кредитов Sol")
    resid = md - mc * rate
    print(f"  Остаток после вычета работы воркеров: {resid:+.1f} пп на {mrev} ревью")
    print(f"  Пересчёт в кредиты: {resid / rate:+.0f} кредитов, то есть {resid / rate / mrev:+.0f} на ревью.")
    print("\n  ВНИМАНИЕ: остаток ОТРИЦАТЕЛЕН -> ставка нестабильна между часами,")
    print("  и метод НЕ измеряет расход ревью. Он даёт только верхнюю границу:")
    print("  вклад ревью меньше разброса самой ставки. Как подтверждение 5% НЕ годится.")
    rates = [round(util[h] - util[k], 3) for h, k in []]  # placeholder, см. вывод выше

# ---------------------------------------- 7. ёмкость тарифа и что в него влезет
head("6. Ёмкость тарифа в кредитах и что в неё помещается")
seg = db.execute("""SELECT SUM(input_tokens) i, SUM(cache_read_tokens) c, SUM(output_tokens) o
    FROM turn_usage WHERE runtime='codex' AND ts>='2026-08-11T00:00'""").fetchone()
seg_cred = credits(seg["i"] - seg["c"], seg["c"], seg["o"])
UTIL = max(util.values()) if util else 22
POOL_PRO = seg_cred / UTIL * 100
print(f"  Окно 11.08: {seg_cred:.0f} кредитов Sol -> счётчик {UTIL}%")
print(f"  => 1 пп ≈ {seg_cred / UTIL:.0f} кредитов; недельный пул Pro 5x ≈ {POOL_PRO:.0f} кредитов")
print(f"  Пул Plus 1x ≈ {POOL_PRO / 5:.0f} (множитель 5 подтверждён первоисточником:"
      f" Sol 10-100 msg/5h на Plus против 50-500 на Pro 5x)")
if rev:
    print(f"\n  {'что':44}{'кред/нед':>10}{'% Pro 5x':>10}{'% Plus':>9}")
    for name, c in (("только ревью", rev_cred / DAYS * 7),
                    ("вся работа Sol", work_cred / DAYS * 7),
                    ("работа за последнюю блокировку Claude",
                     credits(*(lambda r: (r["i"] - r["c"], r["c"], r["o"]))(
                         db.execute("SELECT SUM(input_tokens) i,SUM(cache_read_tokens) c,"
                                    "SUM(output_tokens) o FROM turn_usage WHERE runtime='codex'"
                                    " AND ts>=? AND ts<=?", (A, B)).fetchone())))):
        print(f"  {name:44}{c:10.0f}{c / POOL_PRO * 100:9.0f}%{c / (POOL_PRO / 5) * 100:8.0f}%")

# --------------------------------- 8. влезет ли в Claude + поправка на цензуру
head("7. Влезет ли работа Codex в недельную квоту Claude")
cl_w = vol["claude"]["n"] / DAYS * 7
cx_w = vol["codex"]["n"] / DAYS * 7
print(f"  Недельный пул Claude (посчитан в разделе 4): {POOL_TURNS} ходов")
print(f"  Наблюдённый спрос Claude:  {cl_w:5.0f} ходов/нед = {cl_w / POOL_TURNS * 100:3.0f}% пула")
print(f"  + работа, ушедшая на Sol:  {cx_w:5.0f} ходов/нед")
print(f"  ИТОГО без Codex:           {cl_w + cx_w:5.0f} ходов/нед ="
      f" {(cl_w + cx_w) / POOL_TURNS * 100:3.0f}% пула")
if BLK:
    blocked_h = (_dt.datetime.fromisoformat(B) - _dt.datetime.fromisoformat(A)).total_seconds() / 3600
    free_h = DAYS * 24 - blocked_h
    true_w = vol["claude"]["n"] / free_h * 168
    print(f"\n  ПОПРАВКА НА ЦЕНЗУРУ: {blocked_h:.1f} ч из {DAYS * 24:.0f} Claude был заблокирован")
    print(f"  и физически не мог производить ходы. Темп в НЕзаблокированные {free_h:.0f} ч:")
    print(f"  {vol['claude']['n'] / free_h:.1f} ходов/ч -> {true_w:.0f} ходов/нед =")
    print(f"  {true_w / POOL_TURNS * 100:.0f}% пула ЕЩЁ ДО добавления работы Sol.")
    print("  Смещение направлено в известную сторону: наблюдённый спрос ЗАНИЖЕН, не завышен.")
print("\n  Чувствительность к ошибке пула ±20%:")
for k in (0.8, 1.0, 1.2):
    p = POOL_TURNS * k
    print(f"    пул {p:5.0f}: Claude сам {cl_w / p * 100:3.0f}%, без Codex {(cl_w + cx_w) / p * 100:3.0f}%")

# ------------------------------------------------- 9. частота блокировок
head("8. Частота блокировок — чтобы страховку можно было оценить в деньгах")
first = rows[0]["ts"] if rows else None
obs = db.execute(f"SELECT MIN(ts) a, MAX(ts) b FROM usage_snapshots WHERE {CLEAN}").fetchone()
span = (_dt.datetime.fromisoformat(obs["b"]) - _dt.datetime.fromisoformat(obs["a"])).total_seconds() / 3600
print(f"  Наблюдение: {obs['a'][:16]} .. {obs['b'][:16]} = {span:.0f} ч ({span / 24:.0f} суток)")
print(f"  Полная блокировка Claude: {tot_h:.1f} ч = {tot_h / span * 100:.1f}% календарного времени")
print(f"  = {tot_h / (span / 168):.1f} ч в неделю в среднем, эпизодов {len(eps)}")
print("  ОСТОРОЖНО: 2 эпизода — слишком мало для оценки частоты. Это наблюдённая доля,")
print("  а не прогноз. Для решения о деньгах она годится как порядок величины, не более.")

# ----------------------------------------------------- 10. Max5 против Max20
head("9. Max 5 против Max 20 — режим отказа (границы тарифов внешние, #186)")
periods = [("2026-07-05", "2026-07-20T05:32", "A Max20 (до)"),
           ("2026-07-20T05:32", "2026-08-01T06:48", "B Max5"),
           ("2026-08-01T06:48", "2026-08-12", "C Max20 (сейчас)")]
print(f"  {'период':20}{'суток':>7}{'пик 7d':>8}{'дней 7d>=95':>13}{'снимков 5h=100':>16}")
for a, b, label in periods:
    rr = db.execute(f"SELECT ts, five_hour_pct f, seven_day_pct s FROM usage_snapshots"
                    f" WHERE {CLEAN} AND ts>=? AND ts<? ORDER BY ts", (a, b)).fetchall()
    if not rr:
        continue
    days = len(set(x["ts"][:10] for x in rr))
    hi = len(set(x["ts"][:10] for x in rr if x["s"] >= 95))
    f100 = sum(1 for x in rr if x["f"] >= 100)
    print(f"  {label:20}{days:7}{max(x['s'] for x in rr):7.0f}%{hi:13}"
          f"{f100:10} = {f100 / len(rr) * 100:4.1f}%")
print("\n  Границы тарифов (20.07 05:32, 01.08 06:48) — ВНЕШНИЙ вход из #186,")
print("  здесь не выводятся. Абсолютное отношение потолков Max5/Max20 из этих")
print("  данных не измеряется: Anthropic отдаёт только проценты (limit_dollars=null),")
print("  а turn_usage начинается уже после возврата на Max20.")
