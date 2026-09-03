"""T6 (#314): журнал срабатываний — без него §5.3 research невыполним в принципе.

Замороженный RED-оракул гейта плана. Смысл тикета целиком в будущем: через 9 недельных окон
надо будет посчитать, сколько срабатываний были ложными. Если строка не хранит РЕВИЗИЮ порога,
задним числом нельзя отличить «порог ошибся» от «порог был другой» — оператор правит порог
горячо (T2), поэтому за два месяца он почти наверняка изменится.

Требование про `revision` поставлено оркестратором отдельно и вынесено в самостоятельный тест.
"""

import app.db as db

WINDOW = "2026-08-25T07:00:00+00:00"


def _record(**overrides):
    """Записать одно срабатывание. Имена полей — контракт тикета."""
    payload = {
        "window_id": WINDOW,
        "binding_constraint": "runway_deficit",
        "deficit": 41.0,
        "pace": 2.2,
        "work_used": 36.0,
        "work_hours_left": 60.0,
        "utilization": 78.0,
        "threshold": 34.0,
        "threshold_revision": 7,
        "outcome": "degraded_to_luna",
    }
    payload.update(overrides)
    recorder = getattr(db, "record_runway_decision", None)
    assert recorder is not None, "app.db.record_runway_decision не существует"
    recorder(**payload)
    return payload


def _rows():
    reader = getattr(db, "runway_decision_rows", None)
    assert reader is not None, "app.db.runway_decision_rows не существует"
    return reader(limit=50)


def test_degrade_writes_decision_row():
    """Срабатывание оставляет строку — иначе считать через два месяца будет нечего."""
    _record()
    rows = _rows()
    assert len(rows) == 1
    assert rows[0]["window_id"] == WINDOW
    assert rows[0]["binding_constraint"] == "runway_deficit"


def test_row_records_threshold_revision():
    """В строке лежит РЕВИЗИЯ порога, а не только его значение.

    Значение без ревизии неотличимо от значения, изменённого оператором в тот же день:
    оба прочитаются как «порог был 34». Ревизия — единственная связь строки с той версией
    политики, при которой решение принималось.
    """
    _record(threshold_revision=11)
    row = _rows()[0]
    assert row["threshold_revision"] == 11
    assert row["threshold"] == 34.0


def test_log_records_non_degrading_evaluations_too():
    """Слепота и «ничего не связывает» тоже пишутся.

    Иначе знаменатель неизвестен: доля ложных срабатываний считается от ЧИСЛА ОЦЕНОК, а не
    от числа срабатываний, и журнал, хранящий только сработавшие, завышает её произвольно.
    """
    _record(binding_constraint="blind_no_pace", outcome="no_action", deficit=None, pace=None)
    _record(binding_constraint="none", outcome="no_action")
    kinds = {row["binding_constraint"] for row in _rows()}
    assert {"blind_no_pace", "none"} <= kinds


def test_rows_are_append_only():
    """Строку журнала нельзя переписать: иначе ретроспектива подделывается молча."""
    _record()
    row = _rows()[0]
    mutator = getattr(db, "runway_decision_rows", None)
    assert mutator is not None
    # Прямой UPDATE обязан быть отбит триггером, как у соседних таблиц контроллера.
    import sqlite3

    with db._conn() as conn:
        try:
            conn.execute("UPDATE runway_decisions SET outcome = 'tampered'")
        except sqlite3.DatabaseError:
            return
    assert _rows()[0]["outcome"] == row["outcome"], "строка журнала оказалась изменяемой"
