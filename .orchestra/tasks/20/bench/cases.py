"""Четыре типовых случая из реальных отчётов 03.08.2026 — общий вход для всех рендереров.

Источники:
  C1 — docs/tasks/13/report.md, таблица «диапазон / байт ДО / байт ПОСЛЕ»
  C2 — docs/tasks/3/measurements/canary-rag-on-baseline.log (verbatim)
  C3 — data/orchestra.db, usage_snapshots за последние 7 суток (usage_7d.json)
  C4 — docs/tasks/16/bench.md §2 + состояние индекса
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))

PALETTE = {
    "bg": "#0a0e17",
    "surface": "#0f172a",
    "border": "#334155",
    "ink": "#e2e8f0",
    "ink_soft": "#a6b3c6",
    "ink_faint": "#8595ab",
    "accent": "#818cf8",
    "accent_alt": "#38bdf8",
    "ok": "#22c55e",
    "warn": "#eab308",
    "danger": "#ef4444",
}

# C1 — до/после по 4 диапазонам, байты тела ответа
C1 = {
    "kind": "bars",
    "title": "Вес ответа /api/usage/history",
    "subtitle": "год: 4.25 МБ → 0.86 МБ (4.95×)",
    "unit": "МБ",
    "categories": ["1 сут", "7 сут", "30 сут", "год"],
    "series": [
        {"name": "до", "values": [0.178, 1.057, 4.248, 4.248], "color": PALETTE["danger"]},
        {"name": "после", "values": [0.173, 0.413, 0.857, 0.857], "color": PALETTE["ok"]},
    ],
}

# C2 — распределение латентности /api/models, лог-шкала, порог фронта 2000 мс
C2 = {
    "kind": "bars_log",
    "title": "Латентность /api/models, 120 с × 200 мс",
    "subtitle": "p99 3425 мс против 124 мс у контрольного процесса",
    "unit": "мс",
    "categories": ["p50", "p90", "p99", "max"],
    "series": [
        {"name": "orchestra", "values": [14.2, 130.1, 3425.5, 5715.7], "color": PALETTE["danger"]},
        {"name": "control", "values": [3.3, 14.1, 124.1, 1264.4], "color": PALETTE["accent_alt"]},
    ],
    "threshold": {"value": 2000, "label": "порог фронта 2 с"},
}


def c3():
    """Ряд во времени с реальными провалами: 5h/7d usage за 7 суток."""
    rows = json.load(open(os.path.join(HERE, "usage_7d.json")))
    return {
        "kind": "timeseries",
        "title": "Расход лимита Claude, 7 суток",
        "subtitle": "54 провала в снимках за 29 суток, самый длинный 9 ч 11 мин",
        "unit": "%",
        "gap_minutes": 12,
        "series": [
            {"name": "5h окно", "color": PALETTE["accent_alt"],
             "points": [(r[0], r[1]) for r in rows]},
            {"name": "7d окно", "color": PALETTE["warn"],
             "points": [(r[0], r[2]) for r in rows]},
        ],
    }


# C4 — состояние: сколько файлов реально проиндексировано
C4 = {
    "kind": "scorecard",
    "title": "Индекс RAG против диска",
    "subtitle": "в индексе 78 % корпуса, плюс 17 записей о несуществующих файлах",
    "metrics": [
        {"label": ".md на диске", "value": "401", "note": "5.54 МБ", "color": PALETTE["ink"]},
        {"label": "в индексе", "value": "315", "note": "78 %", "color": PALETTE["warn"]},
        {"label": "не проиндексировано", "value": "86", "note": "≈60 мин эмбеддинга", "color": PALETTE["danger"]},
        {"label": "фантомов", "value": "17", "note": "файла нет, запись есть", "color": PALETTE["danger"]},
    ],
}

ALL = {"c1_bars": C1, "c2_log": C2, "c3_series": None, "c4_score": C4}


def all_cases():
    cases = dict(ALL)
    cases["c3_series"] = c3()
    return cases
