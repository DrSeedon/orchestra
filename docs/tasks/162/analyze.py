"""#162 — курс обмена между 5h и 7d окнами Claude по истории usage_snapshots.

Читает СНИМОК живой БД (сделан через sqlite3.Connection.backup), не саму БД.
Запуск:  python3 docs/tasks/162/analyze.py [snapshot.db]
"""
import json
import sqlite3
import statistics
import sys
from datetime import datetime, timedelta

DB = sys.argv[1] if len(sys.argv) > 1 else "/home/kesha/orchestra/data/tmp162/snap.db"
GAP = 1800  # пары дальше 30 мин друг от друга не считаем: между ними мог быть сброс окна


def load(db):
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    raw = [dict(r) for r in c.execute("SELECT * FROM usage_snapshots ORDER BY ts")]
    rows, dropped_null, dropped_fake = [], 0, 0
    for r in raw:
        if r["five_hour_pct"] is None or r["seven_day_pct"] is None:
            dropped_null += 1               # #150: источник молчал, доказано
            continue
        if (r["five_hour_pct"] == 0 and r["seven_day_pct"] == 0
                and not (r["five_hour_resets_at"] or "")
                and not (r["seven_day_resets_at"] or "")):
            dropped_fake += 1               # оба нуля + оба стампа пусты, см. валидацию ниже
            continue
        rows.append({
            "ts": datetime.fromisoformat(r["ts"]),
            "p5": float(r["five_hour_pct"]),
            "p7": float(r["seven_day_pct"]),
            "pu": r["provider_usage"],
        })
    return rows, dropped_null, dropped_fake, raw


def rate(rows, lo=None, hi=None, max_d5=None):
    """Агрегатный курс: Σ положительных приращений 7d на Σ приращений 5h."""
    s5 = s7 = 0.0
    n = 0
    for a, b in zip(rows, rows[1:]):
        if (b["ts"] - a["ts"]).total_seconds() > GAP:
            continue
        if lo and a["ts"] < lo:
            continue
        if hi and b["ts"] > hi:
            continue
        d5, d7 = max(0.0, b["p5"] - a["p5"]), max(0.0, b["p7"] - a["p7"])
        if max_d5 is not None and d5 > max_d5:
            continue
        s5 += d5
        s7 += d7
        n += 1
    return s5, s7, n


def line(title, s5, s7, n):
    if not s5 or not s7:
        print(f"{title:<52} нет данных (Σd5={s5:.0f} Σd7={s7:.0f})")
        return None
    r = s7 / s5
    print(f"{title:<52} Σd5={s5:7.0f} Σd7={s7:6.0f}  r={r:.4f}  N=1/r={1 / r:5.2f}  пар={n}")
    return r


def main():
    rows, dn, df, raw = load(DB)
    print(f"снимков всего {len(raw)}, отброшено NULL(#150) {dn}, "
          f"отброшено «оба нуля + оба стампа пусты» {df}, в работе {len(rows)}")
    print(f"период {rows[0]['ts']:%Y-%m-%d %H:%M} .. {rows[-1]['ts']:%Y-%m-%d %H:%M} UTC")

    # --- валидация фильтра фейковых нулей на строках, где anthropic ТОЧНО ответил ---
    proven = [r for r in raw if r["provider_usage"] not in ("", "{}")
              and (json.loads(r["provider_usage"]).get("anthropic") or {}).get("windows")]
    fp = [r for r in proven if r["five_hour_pct"] == 0 and r["seven_day_pct"] == 0
          and not (r["five_hour_resets_at"] or "") and not (r["seven_day_resets_at"] or "")]
    print(f"валидация фильтра: строк с доказанным ответом anthropic {len(proven)}, "
          f"из них признак срабатывает на {len(fp)} (ложных срабатываний)")

    print("\n=== A. Курс r = Δ7d / Δ5h (п.п. недельного за 1 п.п. пятичасового) ===")
    base = line("вся история", *rate(rows))
    line("без пар с Δ5h>30 п.п. за шаг (страховка от скачков)", *rate(rows, max_d5=30))
    line("только с 21.07 (после эпохи фейковых нулей)",
         *rate(rows, lo=datetime.fromisoformat("2026-07-21T00:00:00+00:00")))
    line("только с 03.08 (есть provider_usage, ответ доказан)",
         *rate(rows, lo=datetime.fromisoformat("2026-08-03T00:00:00+00:00")))

    print("\n=== B. Дрейф курса: по календарным дням (агрегат внутри дня) ===")
    days = {}
    for a, b in zip(rows, rows[1:]):
        if (b["ts"] - a["ts"]).total_seconds() > GAP:
            continue
        d = a["ts"].date()
        days.setdefault(d, [0.0, 0.0])
        days[d][0] += max(0.0, b["p5"] - a["p5"])
        days[d][1] += max(0.0, b["p7"] - a["p7"])
    day_r = []
    for d in sorted(days):
        d5, d7 = days[d]
        if d5 >= 30 and d7 > 0:  # день с заметным расходом, иначе курс — шум квантования
            day_r.append((d, d7 / d5, d5, d7))
    for d, r, d5, d7 in day_r:
        print(f"  {d}  Σd5={d5:6.0f} Σd7={d7:5.0f}  r={r:.4f}  N={1 / r:5.2f}")
    if day_r:
        rs = sorted(r for _, r, _, _ in day_r)
        print(f"  дней с расходом >=30 п.п. 5h: {len(rs)}; медиана r={statistics.median(rs):.4f} "
              f"(N={1 / statistics.median(rs):.2f}), min={rs[0]:.4f} (N={1 / rs[0]:.1f}), "
              f"max={rs[-1]:.4f} (N={1 / rs[-1]:.1f})")
        half = len(day_r) // 2
        a = statistics.median([r for _, r, _, _ in day_r[:half]])
        b = statistics.median([r for _, r, _, _ in day_r[half:]])
        print(f"  медиана r первой половины периода {a:.4f} (N={1 / a:.2f}), "
              f"второй {b:.4f} (N={1 / b:.2f})")

    # --- C. независимый якорь: доллары из turn_usage (с 03.08) ---
    print("\n=== C. Независимая оценка через $ наших ходов (turn_usage, только runtime=claude) ===")
    c = sqlite3.connect(DB)
    turns = [(datetime.fromisoformat(t), float(cost)) for t, cost in c.execute(
        "SELECT ts, cost_usd FROM turn_usage WHERE runtime='claude' ORDER BY ts")]
    if turns:
        t0 = turns[0][0]
        window = [r for r in rows if r["ts"] >= t0]
        s5 = s7 = money = 0.0
        ti = 0
        for a, b in zip(window, window[1:]):
            if (b["ts"] - a["ts"]).total_seconds() > GAP:
                continue
            while ti < len(turns) and turns[ti][0] < a["ts"]:
                ti += 1
            cost = 0.0
            j = ti
            while j < len(turns) and turns[j][0] <= b["ts"]:
                cost += turns[j][1]
                j += 1
            s5 += max(0.0, b["p5"] - a["p5"])
            s7 += max(0.0, b["p7"] - a["p7"])
            money += cost
        print(f"  период {t0:%m-%d %H:%M}..{window[-1]['ts']:%m-%d %H:%M}: "
              f"Claude-ходов ${money:.2f}, Σd5={s5:.0f} п.п., Σd7={s7:.0f} п.п.")
        if s5 and s7:
            print(f"  $/п.п. 5h = {money / s5:.3f}   $/п.п. 7d = {money / s7:.3f}   "
                  f"N = {(money / s7) / (money / s5):.2f}")
            print(f"  → полное 5h-окно ≈ ${money / s5 * 100:.0f} наших ходов, "
                  f"недельный лимит ≈ ${money / s7 * 100:.0f} (нижняя оценка: "
                  f"ручное и ноутбучное потребление в turn_usage не попадает)")

    # --- D. гипотеза юзера ---
    print("\n=== D. Гипотеза: остаток недельного < цены одного полного 5h ===")
    for r in (base, 1 / 12, 1 / 6):
        cost = 100.0 * r
        hits = [x for x in rows if (100.0 - x["p7"]) < cost]
        mis = [x for x in hits if (100.0 - x["p5"]) > (100.0 - x["p7"]) / r + 1]
        print(f"  r={r:.4f} (N={1 / r:.2f}): порог остатка {cost:.1f} п.п.; "
              f"снимков под порогом {len(hits)} ({100 * len(hits) / len(rows):.1f}%), "
              f"из них 5h завышает свободное: {len(mis)}")
    r = base
    cost = 100.0 * r
    hits = [x for x in rows if (100.0 - x["p7"]) < cost]
    if hits:
        eps, cur = [], [hits[0]]
        for a, b in zip(hits, hits[1:]):
            if (b["ts"] - a["ts"]).total_seconds() > GAP:
                eps.append(cur)
                cur = []
            cur.append(b)
        eps.append(cur)
        print(f"  эпизодов (разрыв >30 мин = новый): {len(eps)}")
        for e in eps:
            dur = (e[-1]["ts"] - e[0]["ts"]).total_seconds() / 3600
            worst = max(e, key=lambda x: (100 - x["p5"]) - (100 - x["p7"]) / r)
            real = (100 - worst["p7"]) / r
            print(f"   {e[0]['ts']:%m-%d %H:%M}..{e[-1]['ts']:%m-%d %H:%M} UTC "
                  f"({dur:5.1f} ч, {len(e):4d} снимков) — худший момент: 5h показывает "
                  f"{100 - worst['p5']:3.0f}% свободно, по недельному доступно "
                  f"{real:4.1f}% (7d={worst['p7']:.0f}%)")
        tot = sum((e[-1]["ts"] - e[0]["ts"]).total_seconds() for e in eps) / 3600
        print(f"  суммарно под порогом: {tot:.1f} ч из "
              f"{(rows[-1]['ts'] - rows[0]['ts']).total_seconds() / 3600:.0f} ч наблюдения")

    # --- D2. режимы курса и проверка формулы вне выборки ---
    def P(s):
        return datetime.fromisoformat(s + "+00:00")

    print("\n=== D2. Три режима курса (границы — по разрывам в данных) ===")
    eras = [("A 05.07–20.07", "2026-07-05T00:00:00", "2026-07-20T05:30:00"),
            ("B 20.07–01.08", "2026-07-20T05:30:00", "2026-08-01T06:45:00"),
            ("C 01.08–07.08", "2026-08-01T06:45:00", "2026-08-08T00:00:00")]
    era_r = {}
    for name, lo, hi in eras:
        s5, s7, _ = rate(rows, lo=P(lo), hi=P(hi))
        era_r[name[0]] = s7 / s5
        seg = [x for x in rows if P(lo) <= x["ts"] <= P(hi)]
        print(f"  {name}: Σd5={s5:6.0f} Σd7={s7:5.0f} r={s7 / s5:.4f} N={s5 / s7:5.2f}; "
              f"покрыто {len(seg) * 5 / 60:5.0f} ч, 5h>=99%: {sum(1 for x in seg if x['p5'] >= 99) * 5 / 60:5.1f} ч, "
              f"7d>=90%: {sum(1 for x in seg if x['p7'] >= 90) * 5 / 60:5.1f} ч")

    print("\n=== D3. Скользящая оценка r (точки каждые 2 ч с 03.08) ===")
    pts = [x for i, x in enumerate(rows) if x["ts"] >= P("2026-08-03T00:00:00") and i % 24 == 0]
    for win_h in (24, 48, 72, 168):
        out = []
        for x in pts:
            s5, s7, _ = rate(rows, lo=x["ts"] - timedelta(hours=win_h), hi=x["ts"])
            if s5 >= 30 and s7 > 0:
                out.append(s7 / s5)
        if out:
            o = sorted(out)
            print(f"  окно {win_h:3d} ч: точек {len(o)}, медиана r={o[len(o) // 2]:.4f} "
                  f"(N={1 / o[len(o) // 2]:.2f}), p10={o[len(o) // 10]:.4f}, p90={o[9 * len(o) // 10]:.4f}")

    print("\n=== D4. Проверка формулы вне выборки: предсказание vs факт ===")
    for level in (90, 95):
        for i in range(1, len(rows) - 1):
            if not (rows[i]["p7"] >= level > rows[i - 1]["p7"]):
                continue
            t, p7 = rows[i]["ts"], rows[i]["p7"]
            era = "A" if t < P("2026-07-20T05:30:00") else ("B" if t < P("2026-08-01T06:45:00") else "C")
            spent, j = 0.0, i
            while j < len(rows) - 1:
                a, b = rows[j], rows[j + 1]
                if (b["ts"] - a["ts"]).total_seconds() > 1800 or b["p7"] < a["p7"] - 0.5:
                    break
                spent += max(0.0, b["p5"] - a["p5"])
                j += 1
                if b["p7"] >= 100:
                    break
            print(f"  {t:%m-%d %H:%M} эра {era} 7d={p7:.0f}%: предсказано {(100 - p7) / era_r[era]:5.1f} п.п. 5h, "
                  f"фактически {spent:5.1f} до 7d={rows[j]['p7']:.0f}% за {(rows[j]['ts'] - t).total_seconds() / 3600:.1f} ч")

    print("\n=== D5. Дрожит ли счётчик (иначе Σ приращений завышена) ===")
    cnt = {"5h_small": 0, "5h_big": 0, "7d_small": 0, "7d_big": 0}
    pairs = 0
    for a, b in zip(rows, rows[1:]):
        if (b["ts"] - a["ts"]).total_seconds() > GAP:
            continue
        pairs += 1
        for tag, x, y in (("5h", a["p5"], b["p5"]), ("7d", a["p7"], b["p7"])):
            if y < x:
                cnt[f"{tag}_{'small' if x - y <= 2 else 'big'}"] += 1
    print(f"  пар {pairs}; падения 1–2 п.п. (дрожание): 5h={cnt['5h_small']}, 7d={cnt['7d_small']}; "
          f"крупные (сброс окна): 5h={cnt['5h_big']}, 7d={cnt['7d_big']}")

    # --- E. другие провайдеры ---
    print("\n=== E. Другие рантаймы (provider_usage, с 03.08) ===")
    prov = {}
    for row in rows:
        if not row["pu"] or row["pu"] == "{}":
            continue
        for pid, p in json.loads(row["pu"]).items():
            wins = {w["id"]: w for w in p.get("windows", [])}
            if wins:
                prov.setdefault(pid, []).append((row["ts"], wins))
    for pid, series in sorted(prov.items()):
        shapes = {}
        for _, wins in series:
            key = tuple(sorted((w["id"], w["window_minutes"]) for w in wins.values()))
            shapes[key] = shapes.get(key, 0) + 1
        print(f"  {pid}: снимков {len(series)}; окна {shapes}")
        tot = {}
        for (t1, w1), (t2, w2) in zip(series, series[1:]):
            if (t2 - t1).total_seconds() > GAP:
                continue
            for k in set(w1) & set(w2):
                tot.setdefault(k, 0.0)
                tot[k] += max(0.0, w2[k]["utilization"] - w1[k]["utilization"])
        print(f"     расход по окнам: { {k: round(v) for k, v in tot.items()} }")
        if len(tot) == 2 and all(tot.values()):
            short = min(tot, key=lambda k: [w for _, w in series if k in w][0][k]["window_minutes"])
            long_ = [k for k in tot if k != short][0]
            print(f"     r({long_}/{short}) = {tot[long_] / tot[short]:.4f} "
                  f"→ N = {tot[short] / tot[long_]:.2f}")


if __name__ == "__main__":
    main()
