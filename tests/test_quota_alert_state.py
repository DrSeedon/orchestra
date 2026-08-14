"""Храповик предупреждения и латч молчания (#186, тикет T3).

Ключевая проверка тикета — та, что бьёт по БАЗЕ в обход всех функций модуля. Проверка
храповика через собственные функции проверяет дисциплину кода, а не схему: ровно на этом
план и попался в первой редакции, где откат «был невозможен из-за PRIMARY KEY».
"""

import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import pytest


GRACE = 1800.0
WINDOW = "2026-08-11T07:00:00+00:00"
NEXT_WINDOW = "2026-08-18T07:00:00+00:00"
T0 = datetime(2026, 8, 11, 10, 0, tzinfo=timezone.utc)


def _iso(offset_seconds: float = 0.0) -> str:
    return (T0 + timedelta(seconds=offset_seconds)).isoformat()


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.DB_PATH", tmp_path / "test.db")
    from app.db import init_db

    init_db()
    return tmp_path / "test.db"


# --- AC-1: переход случается ровно один раз -------------------------------------------

def test_first_advance_happens_and_the_second_does_not(db):
    from app.db import alert_state_advance

    assert alert_state_advance(WINDOW, _iso()) is True
    assert alert_state_advance(WINDOW, _iso(300)) is False
    assert alert_state_advance(WINDOW, _iso(600)) is False


def test_advance_does_not_reset_the_delivery_mark(db):
    """Повторный вызов не должен «оживлять» уже доставленное сообщение."""
    from app.db import alert_mark_delivered, alert_pending, alert_state_advance

    alert_state_advance(WINDOW, _iso())
    alert_mark_delivered(WINDOW, _iso(60))
    assert alert_pending(WINDOW) is False

    alert_state_advance(WINDOW, _iso(300))
    assert alert_pending(WINDOW) is False


# --- AC-2: откат отвергает БАЗА, а не Python ------------------------------------------

def test_direct_sql_downgrade_is_rejected_by_the_database(db):
    """Прямой UPDATE в обход всех функций модуля обязан упасть.

    Это и есть проверка того, что храповик держит схема. Через `alert_state_advance`
    такой тест доказывал бы лишь, что функция написана правильно сегодня.
    """
    from app.db import alert_state_advance

    alert_state_advance(WINDOW, _iso())
    conn = sqlite3.connect(str(db))
    with pytest.raises(sqlite3.IntegrityError, match="downgrade"):
        conn.execute("UPDATE quota_alert_state SET state = 'ok' WHERE window_id = ?", (WINDOW,))
    conn.close()


def test_impossible_state_value_is_rejected_by_the_check(db):
    conn = sqlite3.connect(str(db))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO quota_alert_state (window_id, state, changed_at)"
            " VALUES (?, 'whatever', ?)",
            (WINDOW, _iso()),
        )
    conn.close()


def test_insert_or_replace_cannot_unlatch_the_window(db):
    """`INSERT OR REPLACE` = DELETE + INSERT, поэтому BEFORE UPDATE на нём не срабатывает.

    Ровно этим одна строка SQL возвращала окно в `ok` в обход храповика.
    """
    from app.db import alert_state_advance

    alert_state_advance(WINDOW, _iso())
    conn = sqlite3.connect(str(db))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT OR REPLACE INTO quota_alert_state (window_id, state, changed_at)"
            " VALUES (?, 'ok', ?)",
            (WINDOW, _iso(60)),
        )
    conn.close()


def test_deleting_an_alerted_row_is_rejected(db):
    """Удаление снимает храповик И уносит отметку о доставке.

    Тогда повтор перестаёт распознаваться как повтор, а история окна начинает
    утверждать, что тревоги не было вовсе.
    """
    from app.db import alert_state_advance

    alert_state_advance(WINDOW, _iso())
    conn = sqlite3.connect(str(db))
    with pytest.raises(sqlite3.IntegrityError, match="deleted"):
        conn.execute("DELETE FROM quota_alert_state WHERE window_id = ?", (WINDOW,))
    conn.close()


def test_renaming_the_window_of_an_alerted_row_is_rejected(db):
    """Расцепить строку с окном можно, не трогая state вовсе.

    `UPDATE ... SET window_id = 'другое'` оставляет `alert`, все триггеры на state молчат,
    а исходное окно остаётся без записи — и предупреждение по нему пройдёт заново.
    """
    from app.db import alert_state_advance

    alert_state_advance(WINDOW, _iso())
    conn = sqlite3.connect(str(db))
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE quota_alert_state SET window_id = ? WHERE window_id = ?",
            (NEXT_WINDOW, WINDOW),
        )
    conn.close()
    assert alert_state_advance(WINDOW, _iso(60)) is False


def test_update_or_replace_cannot_take_over_an_alerted_window(db):
    """Самый неочевидный обход: переименование НЕ-тревожной строки поверх тревожной.

    Исходная строка в состоянии `ok`, поэтому триггер неизменяемости молчит; разрешение
    конфликта удаляет тревожную строку вместе с отметкой о доставке (delete-триггеры на
    этом пути не выполняются), и окно оказывается в `ok`.
    """
    from app.db import alert_mark_delivered, alert_state_advance

    alert_state_advance(WINDOW, _iso())
    alert_mark_delivered(WINDOW, _iso(30))

    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO quota_alert_state (window_id, state, changed_at) VALUES (?, 'ok', ?)",
        (NEXT_WINDOW, _iso(60)),
    )
    with pytest.raises(sqlite3.IntegrityError, match="replaced"):
        conn.execute(
            "UPDATE OR REPLACE quota_alert_state SET window_id = ? WHERE window_id = ?",
            (WINDOW, NEXT_WINDOW),
        )
    conn.rollback()
    conn.close()
    assert alert_state_advance(WINDOW, _iso(120)) is False, "храповик снят"


def test_renaming_into_a_free_window_still_works(db):
    """Триггер не должен запрещать законное переименование в свободное окно."""
    from app.db import alert_state_advance

    alert_state_advance(WINDOW, _iso())
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO quota_alert_state (window_id, state, changed_at) VALUES ('spare', 'ok', ?)",
        (_iso(60),),
    )
    conn.execute("UPDATE quota_alert_state SET window_id = ? WHERE window_id = 'spare'",
                 (NEXT_WINDOW,))
    conn.commit()
    conn.close()


@pytest.mark.parametrize("column", ["delivered_at", "discarded_at"])
def test_delivery_record_cannot_be_reset_to_null(db, column):
    """Обнуление отметки воскрешает уже закрытое предупреждение — и оно уходит дважды."""
    from app.db import alert_discard_stale, alert_mark_delivered, alert_state_advance

    alert_state_advance(WINDOW, _iso())
    if column == "delivered_at":
        alert_mark_delivered(WINDOW, _iso(30))
    else:
        alert_discard_stale(NEXT_WINDOW, _iso(30), 120.0)

    conn = sqlite3.connect(str(db))
    with pytest.raises(sqlite3.IntegrityError, match="durable"):
        conn.execute(f"UPDATE quota_alert_state SET {column} = NULL WHERE window_id = ?",
                     (WINDOW,))
    conn.close()


def test_marking_delivery_on_a_fresh_row_is_still_allowed(db):
    """Обратный путь NULL → значение обязан работать: это нормальная жизнь таблицы."""
    from app.db import alert_mark_delivered, alert_pending, alert_state_advance

    alert_state_advance(WINDOW, _iso())
    alert_mark_delivered(WINDOW, _iso(30))
    assert alert_pending(WINDOW) is False


def test_state_stays_alert_after_a_rejected_downgrade(db):
    from app.db import alert_state_advance

    alert_state_advance(WINDOW, _iso())
    conn = sqlite3.connect(str(db))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE quota_alert_state SET state = 'ok'")
    conn.close()
    assert alert_state_advance(WINDOW, _iso(300)) is False


# --- AC-3: новое окно начинается с чистого листа --------------------------------------

def test_a_new_window_starts_over(db):
    from app.db import alert_pending, alert_state_advance

    alert_state_advance(WINDOW, _iso())
    assert alert_state_advance(NEXT_WINDOW, _iso(600)) is True
    assert alert_pending(NEXT_WINDOW) is True


# --- AC-4: конкурентные вызовы дают ровно одного победителя ---------------------------

def _race(call, workers: int = 8):
    """Запустить `call` из нескольких потоков одновременно, на барьере.

    Барьер обязателен: последовательный прогон «двух соединений» доказывает лишь, что
    второй вызов видит результат первого, а гонку не воспроизводит вовсе.
    """
    barrier = threading.Barrier(workers)
    results: list = [None] * workers
    errors: list = []

    def worker(index: int) -> None:
        try:
            barrier.wait(timeout=10)
            results[index] = call()
        except Exception as error:  # noqa: BLE001 — тест обязан показать класс исключения
            errors.append(f"{type(error).__name__}: {error}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    return results, errors


def test_concurrent_advance_produces_exactly_one_winner(db):
    """Восемь потоков зовут ПУБЛИЧНУЮ функцию одновременно — победитель ровно один.

    Прежняя версия этого теста была двумя последовательными соединениями со СКОПИРОВАННЫМ
    внутрь UPSERT'ом: она проходила бы и на реализации «SELECT, потом INSERT/UPDATE»,
    то есть не проверяла ни атомарность, ни саму функцию.
    """
    from app.db import alert_state_advance

    results, errors = _race(lambda: alert_state_advance(WINDOW, _iso()))
    assert not errors, errors
    assert sum(1 for value in results if value is True) == 1, results
    assert all(value is not None for value in results), "поток не доработал"

    conn = sqlite3.connect(str(db))
    assert conn.execute("SELECT COUNT(*) FROM quota_alert_state").fetchone()[0] == 1
    conn.close()


def test_concurrent_silence_notification_has_one_winner(db):
    """То же для молчания: два «пора сказать» = два сообщения об одном и том же."""
    from app.db import silence_observe

    silence_observe(has_data=False, now=_iso(), grace_seconds=GRACE)
    results, errors = _race(
        lambda: silence_observe(has_data=False, now=_iso(GRACE + 1), grace_seconds=GRACE)
    )
    assert not errors, errors
    assert sum(1 for value in results if value is True) == 1, results


def test_concurrent_first_silence_poll_does_not_raise(db):
    """Старт эпизода из нескольких потоков: вставку выигрывает один, остальные молчат."""
    from app.db import silence_observe

    results, errors = _race(
        lambda: silence_observe(has_data=False, now=_iso(), grace_seconds=GRACE)
    )
    assert not errors, errors
    assert not any(results), "молчание объявлено раньше grace-периода"


# --- доставка: at-least-once в пределах окна ------------------------------------------

def test_pending_until_delivered(db):
    from app.db import alert_mark_delivered, alert_pending, alert_state_advance

    assert alert_pending(WINDOW) is False, "перехода не было — доставлять нечего"
    alert_state_advance(WINDOW, _iso())
    assert alert_pending(WINDOW) is True
    alert_mark_delivered(WINDOW, _iso(30))
    assert alert_pending(WINDOW) is False


def test_crash_before_delivery_is_retried_not_lost(db):
    """Переход записан, отправка не состоялась → следующий цикл обязан повторить."""
    from app.db import alert_pending, alert_state_advance

    alert_state_advance(WINDOW, _iso())
    # «падение»: отметки о доставке нет
    assert alert_pending(WINDOW) is True
    assert alert_pending(WINDOW) is True, "повтор не должен зависеть от числа проверок"


def test_stale_undelivered_alert_of_a_past_window_is_discarded_loudly(db):
    """Сервис пролежал через сброс: предупреждение о прошлой неделе — дезинформация."""
    from app.db import alert_discard_stale, alert_pending, alert_state_advance

    alert_state_advance(WINDOW, _iso())
    discarded = alert_discard_stale(NEXT_WINDOW, _iso(86400), 120.0)
    assert discarded == [WINDOW], "отброшенное окно обязано попасть в журнал"
    assert alert_pending(WINDOW) is False


def test_discard_does_not_touch_the_current_window(db):
    from app.db import alert_discard_stale, alert_pending, alert_state_advance

    alert_state_advance(WINDOW, _iso())
    assert alert_discard_stale(WINDOW, _iso(60), 120.0) == []
    assert alert_pending(WINDOW) is True


def test_discard_ignores_already_delivered_rows(db):
    from app.db import alert_discard_stale, alert_mark_delivered, alert_state_advance

    alert_state_advance(WINDOW, _iso())
    alert_mark_delivered(WINDOW, _iso(30))
    assert alert_discard_stale(NEXT_WINDOW, _iso(86400), 120.0) == []


# --- AC-5, AC-6: молчание источника ---------------------------------------------------

def test_single_missed_poll_does_not_announce_silence(db):
    """Источник молчал 381 раз из 8804, почти всегда одиночными пропусками."""
    from app.db import silence_observe

    assert silence_observe(has_data=False, now=_iso(), grace_seconds=GRACE) is False
    assert silence_observe(has_data=False, now=_iso(300), grace_seconds=GRACE) is False


def test_silence_claim_is_taken_once_and_then_confirmed_forever(db):
    """Заявка берётся один раз; после ДОКАЗАННОЙ доставки не берётся уже никогда."""
    from app.db import silence_mark_announced, silence_observe

    silence_observe(has_data=False, now=_iso(), grace_seconds=GRACE)
    assert silence_observe(has_data=False, now=_iso(GRACE + 1), grace_seconds=GRACE) is True
    assert silence_observe(has_data=False, now=_iso(GRACE + 30), grace_seconds=GRACE) is False
    silence_mark_announced(_iso(GRACE + 40))
    assert silence_observe(has_data=False, now=_iso(GRACE + 9000), grace_seconds=GRACE) is False


def test_mark_announced_can_restore_missing_state_row(db):
    """Если запись стирается или не успела создаться, `mark_announced` создаст её атомарно."""
    from app.db import silence_mark_announced

    silence_mark_announced(_iso())
    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT announced_at, silence_since, notified_at FROM quota_silence WHERE id = 1"
    ).fetchone()
    conn.close()
    assert row is not None
    announced_at, silence_since, notified_at = row
    assert announced_at is not None
    assert silence_since is not None
    assert notified_at is None


def test_silence_claim_expires_if_delivery_never_confirmed(db):
    """Процесс умер между заявкой и отправкой — сообщение обязано прозвучать позже.

    Смерть процесса ничего не возвращает, поэтому `silence_release` тут бессилен: спасает
    только истечение аренды. Без него молчание считалось бы объявленным навсегда.
    """
    from app.db import silence_observe

    silence_observe(has_data=False, now=_iso(), grace_seconds=GRACE)
    assert silence_observe(has_data=False, now=_iso(GRACE + 1), grace_seconds=GRACE) is True
    # «процесс умер»: ни подтверждения, ни освобождения
    assert silence_observe(has_data=False, now=_iso(GRACE + 60), grace_seconds=GRACE) is False
    assert silence_observe(has_data=False, now=_iso(GRACE + 400), grace_seconds=GRACE) is True


def test_exact_grace_boundary_fires(db):
    """Ровно `grace_seconds` — уже пора. Граница включающая, и она не должна быть лотереей.

    Прежняя версия сравнивала через `julianday`, и ровно 1800 секунд давали
    1800.00001341105: срабатывало, но по случайности знака ошибки. Проигранная лотерея
    отложила бы сообщение на целый опрос.
    """
    from app.db import silence_observe

    silence_observe(has_data=False, now=_iso(), grace_seconds=GRACE)
    assert silence_observe(has_data=False, now=_iso(GRACE), grace_seconds=GRACE) is True


def test_one_second_before_the_boundary_stays_silent(db):
    from app.db import silence_observe

    silence_observe(has_data=False, now=_iso(), grace_seconds=GRACE)
    assert silence_observe(has_data=False, now=_iso(GRACE - 1), grace_seconds=GRACE) is False


def test_grace_comparison_survives_a_non_utc_timestamp(db):
    """Тот же момент в другом смещении обязан дать тот же ответ."""
    from app.db import silence_observe

    tz3 = timezone(timedelta(hours=3))
    silence_observe(has_data=False, now=T0.astimezone(tz3).isoformat(), grace_seconds=GRACE)
    later = (T0 + timedelta(seconds=GRACE)).astimezone(tz3).isoformat()
    assert silence_observe(has_data=False, now=later, grace_seconds=GRACE) is True


def test_grace_comparison_survives_MIXED_offsets(db):
    """Эпизод начат в +03:00, следующий опрос пришёл в UTC — самый опасный случай.

    Одинаковые смещения сравниваются как строки правильно по случайности; ломается
    именно смесь. Без нормализации в UTC `"…13:00:00+03:00" <= "…10:00:00+00:00"` ложно,
    и сообщение не уходит НИКОГДА — то есть тревога молча выключена.
    """
    from app.db import silence_observe

    tz3 = timezone(timedelta(hours=3))
    silence_observe(has_data=False, now=T0.astimezone(tz3).isoformat(), grace_seconds=GRACE)
    later_utc = (T0 + timedelta(seconds=GRACE + 60)).isoformat()
    assert silence_observe(has_data=False, now=later_utc, grace_seconds=GRACE) is True


def test_data_returning_clears_the_state_without_a_message(db):
    from app.db import silence_observe

    from app.db import silence_mark_announced

    silence_observe(has_data=False, now=_iso(), grace_seconds=GRACE)
    silence_observe(has_data=False, now=_iso(GRACE + 1), grace_seconds=GRACE)
    silence_mark_announced(_iso(GRACE + 2))
    assert silence_observe(has_data=True, now=_iso(GRACE + 60), grace_seconds=GRACE) is False
    # новое молчание — новый отсчёт, а не продолжение прежнего
    assert silence_observe(has_data=False, now=_iso(GRACE + 120), grace_seconds=GRACE) is False
    assert silence_observe(has_data=False, now=_iso(2 * GRACE + 200), grace_seconds=GRACE) is True


def test_silence_table_never_grows_past_one_row(db):
    from app.db import silence_observe

    for i in range(10):
        silence_observe(has_data=bool(i % 2), now=_iso(i * 60), grace_seconds=GRACE)
    conn = sqlite3.connect(str(db))
    assert conn.execute("SELECT COUNT(*) FROM quota_silence").fetchone()[0] <= 1
    conn.close()


# --- AC-7: латчи не затирают друг друга -----------------------------------------------

def test_alert_survives_a_silence_episode_and_does_not_fire_twice(db):
    """Последовательность alert → молчание → данные вернулись.

    Латч бюджета обязан остаться, второго предупреждения быть не должно. Ровно ради
    этого молчание и вынесено в отдельную таблицу.
    """
    from app.db import alert_mark_delivered, alert_pending, alert_state_advance, silence_observe

    assert alert_state_advance(WINDOW, _iso()) is True
    alert_mark_delivered(WINDOW, _iso(10))

    silence_observe(has_data=False, now=_iso(60), grace_seconds=GRACE)
    assert silence_observe(has_data=False, now=_iso(GRACE + 60), grace_seconds=GRACE) is True
    assert silence_observe(has_data=True, now=_iso(GRACE + 120), grace_seconds=GRACE) is False

    assert alert_state_advance(WINDOW, _iso(GRACE + 180)) is False, "второе предупреждение"
    assert alert_pending(WINDOW) is False


def test_live_claim_is_not_discarded_as_stale(db):
    """Отправка по старому окну в полёте — отбрасывать её нельзя.

    Иначе строка получит и `discarded_at` от нового цикла, и `delivered_at` от
    вернувшегося старого — то есть будет утверждать обе судьбы разом.
    """
    from app.db import alert_claim_delivery, alert_discard_stale, alert_state_advance

    alert_state_advance(WINDOW, _iso())
    assert alert_claim_delivery(WINDOW, _iso(1), 120.0) is True
    assert alert_discard_stale(NEXT_WINDOW, _iso(5), 120.0) == [], "отброшено с живой арендой"
    # аренда истекла — теперь отбросить можно
    assert alert_discard_stale(NEXT_WINDOW, _iso(300), 120.0) == [WINDOW]


def test_discarded_row_cannot_become_delivered(db):
    """Сообщение уже ушло, но врать в базе об этом всё равно нельзя."""
    from app.db import alert_discard_stale, alert_mark_delivered, alert_state_advance

    alert_state_advance(WINDOW, _iso())
    assert alert_discard_stale(NEXT_WINDOW, _iso(300), 120.0) == [WINDOW]
    alert_mark_delivered(WINDOW, _iso(310))
    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT delivered_at, discarded_at FROM quota_alert_state WHERE window_id = ?",
        (WINDOW,),
    ).fetchone()
    conn.close()
    assert row[0] is None and row[1] is not None, "строка утверждает обе судьбы"
