"""#162 — курс обмена 5h↔7d и реальный потолок пятичасового окна.

Проверка идёт в ОБЕ стороны: не только «при anthropic поле есть», но и «при чужих
рантаймах его нет». Гейт, проверенный только с одной стороны, зеленеет в пустой комнате.
"""

from datetime import datetime, timedelta, timezone

import pytest

from app.routes.system import _quota_headroom


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.DB_PATH", tmp_path / "test.db")
    from app.db import init_db
    init_db()


def _write(rows, start=None):
    """rows: (минута_от_старта, p5, p7, r5, r7). None в процентах = NULL."""
    import sqlite3

    from app.db import DB_PATH
    base = start or (datetime.now(timezone.utc) - timedelta(hours=6))
    conn = sqlite3.connect(str(DB_PATH))
    for minute, p5, p7, r5, r7 in rows:
        conn.execute(
            "INSERT INTO usage_snapshots (ts, five_hour_pct, seven_day_pct,"
            " five_hour_resets_at, seven_day_resets_at, total_cost_usd, active_agents)"
            " VALUES (?,?,?,?,?,0,0)",
            ((base + timedelta(minutes=minute)).isoformat(), p5, p7, r5, r7),
        )
    conn.commit()
    conn.close()


RESET5, RESET7 = "2026-08-07T14:00:00+00:00", "2026-08-11T07:00:00+00:00"


def test_rate_is_ratio_of_consumed_points(db):
    """40 п.п. пятичасового и 5 п.п. недельного → курс 0.125, то есть 8 окон в неделе."""
    from app.db import usage_exchange_rate
    _write([(i * 5, i * 4, i * 0.5, RESET5, RESET7) for i in range(11)])
    measured = usage_exchange_rate(72)
    assert measured["five_hour_pct_sum"] == pytest.approx(40.0)
    assert measured["seven_day_pct_sum"] == pytest.approx(5.0)
    assert measured["rate"] == pytest.approx(0.125)


def test_fake_zero_row_is_not_counted_as_consumption(db):
    """Строка «оба нуля и оба resets_at пустые» — молчание источника, а не расход.

    Если её не отфильтровать, восстановление счётчика с нуля читается как +40 п.п. 5h
    и +5 п.п. 7d: суммы удваиваются. Курс при этом уцелеет, а вот все производные
    от объёма выборки — нет, поэтому проверяем суммы, а не только отношение.
    """
    from app.db import usage_exchange_rate
    rows = [(i * 5, i * 4, i * 0.5, RESET5, RESET7) for i in range(11)]
    rows.insert(5, (27, 0, 0, "", ""))          # источник молчал (до #150)
    rows.insert(9, (47, None, None, "", ""))    # источник молчал (после #150)
    _write(rows)
    measured = usage_exchange_rate(72)
    assert measured["five_hour_pct_sum"] == pytest.approx(40.0)
    assert measured["seven_day_pct_sum"] == pytest.approx(5.0)


def test_gap_longer_than_30_min_is_not_a_delta(db):
    """За разрывом мог уместиться сброс окна: разность процентов там не равна расходу."""
    from app.db import usage_exchange_rate
    _write([(0, 10, 10, RESET5, RESET7), (5, 45, 13, RESET5, RESET7),
            (300, 90, 20, RESET5, RESET7), (305, 94, 21, RESET5, RESET7)])
    measured = usage_exchange_rate(72)
    assert measured["five_hour_pct_sum"] == pytest.approx(39.0)  # 35 + 4, скачок 45 не в счёт
    assert measured["seven_day_pct_sum"] == pytest.approx(4.0)   # 3 + 1, скачок 7 не в счёт


def test_too_little_data_returns_none_not_last_known(db):
    """Курс дважды менялся вдвое — подставлять последнее известное нельзя.

    Второй случай обязателен: при недельном тике гард «Σd7 == 0» уже не спасает, и
    отсутствие порога по Σd5 вылезло бы курсом, посчитанным по двум процентам.
    """
    from app.db import usage_exchange_rate
    _write([(0, 1, 1, RESET5, RESET7), (5, 3, 1, RESET5, RESET7)])
    assert usage_exchange_rate(72) is None


def test_tiny_sample_with_weekly_tick_is_still_none(db):
    from app.db import usage_exchange_rate
    _write([(0, 1, 1, RESET5, RESET7), (5, 3, 2, RESET5, RESET7)])
    assert usage_exchange_rate(72) is None  # Σd5 = 2 п.п. — курс на таком не считается


def test_only_trailing_window_is_used(db):
    """Старее окна оценки — не наши данные, даже если строки лежат в той же таблице."""
    from app.db import usage_exchange_rate
    old = datetime.now(timezone.utc) - timedelta(days=10)
    _write([(i * 5, i * 4, i * 0.5, RESET5, RESET7) for i in range(11)], start=old)
    assert usage_exchange_rate(72) is None


def test_headroom_locks_the_part_weekly_will_not_give(db):
    """Живой случай 07.08: 5h показывает 91 % свободно, недельный даёт взять 61."""
    _write([(i * 5, i * 4, i * 0.5, RESET5, RESET7) for i in range(11)])  # курс 0.125
    head = _quota_headroom({"five_hour": {"utilization": 9.0},
                            "seven_day": {"utilization": 92.0}})
    assert head["rate"] == pytest.approx(0.125)
    assert head["available_pct"] == pytest.approx(64.0)   # (100-92)/0.125
    assert head["locked_pct"] == pytest.approx(27.0)      # 91 - 64
    assert head["windows_left"] == pytest.approx(0.64)


def test_headroom_never_exceeds_the_five_hour_window_itself(db):
    """Недельный свободен → потолок ставит само пятичасовое окно, заперто ничего."""
    _write([(i * 5, i * 4, i * 0.5, RESET5, RESET7) for i in range(11)])
    head = _quota_headroom({"five_hour": {"utilization": 43.0},
                            "seven_day": {"utilization": 20.0}})
    assert head["available_pct"] == pytest.approx(57.0)
    assert head["locked_pct"] == pytest.approx(0.0)
    assert head["windows_left"] == pytest.approx(6.4)


def test_silent_for_foreign_runtimes(db):
    """Пустая комната: у codex и grok второго окна нет, считать нечего — None.

    Обратная сторона того же гейта, что и в тесте выше: без неё «поле есть у anthropic»
    прошло бы и при выводе, посчитанном по чужим окнам.
    """
    _write([(i * 5, i * 4, i * 0.5, RESET5, RESET7) for i in range(11)])
    assert _quota_headroom(None) is None
    assert _quota_headroom({}) is None
    assert _quota_headroom({"five_hour": {"utilization": 9.0}}) is None
    assert _quota_headroom({"primary": {"utilization": 100, "window_minutes": 10080}}) is None


def test_no_rate_no_headroom(db):
    """Курса нет → и потолка нет. Молчим, а не показываем выдуманное число."""
    _write([(0, 1, 1, RESET5, RESET7), (5, 3, 1, RESET5, RESET7)])
    assert _quota_headroom({"five_hour": {"utilization": 9.0},
                            "seven_day": {"utilization": 92.0}}) is None
