"""Цикл предупреждения о недельной квоте (#186, тикет T4).

Главный критерий приёмки — объём: на реплее реальной аварийной недели ровно ОДНО
сообщение, на спокойных ноль. Предупреждение, приходящее каждые пять минут, перестают
читать, и тогда его всё равно что нет.
"""

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import app.quota_alert as quota_alert
from app.quota_alert import DELIVERY_BUDGET_SECONDS, evaluate_and_notify
from tests.test_quota_runway import WEEKS


RESET = datetime(2026, 8, 11, 7, 0, tzinfo=timezone.utc)
WINDOW_START = RESET - timedelta(days=7)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.DB_PATH", tmp_path / "test.db")
    from app.db import init_db

    init_db()
    return tmp_path / "test.db"


class Recorder:
    """Подставной отправитель: считает сообщения и умеет отказывать/висеть."""

    def __init__(self, *, result=None, hang=False, raises=None):
        self.messages: list[str] = []
        self.result = result if result is not None else {"ok": True, "message_id": 1}
        self.hang = hang
        self.raises = raises

    async def __call__(self, text, *, scope, sender):
        self.messages.append(text)
        if self.hang:
            await asyncio.sleep(3600)
        if self.raises:
            raise self.raises
        return self.result


def _write(db, rows):
    conn = sqlite3.connect(str(db))
    for ts, pct in rows:
        conn.execute(
            "INSERT INTO usage_snapshots (ts, five_hour_pct, seven_day_pct,"
            " five_hour_resets_at, seven_day_resets_at, total_cost_usd, active_agents)"
            " VALUES (?, 0, ?, '', ?, 0, 0)",
            (ts.isoformat(), pct, RESET.isoformat()),
        )
    conn.commit()
    conn.close()


def _anthropic(pct, reset_at=RESET):
    return {"seven_day": {"utilization": pct, "resets_at": reset_at.isoformat()}}


def _replay(db, week_key, send):
    """Прогнать ВСЕ часовые точки недели через цикл, как это делает опрос."""
    start_text, series = WEEKS[week_key]
    start = datetime.fromisoformat(start_text).replace(tzinfo=timezone.utc)
    reset = start + timedelta(days=7)
    hours = sorted(series)
    for hour in hours:
        ts = start + timedelta(hours=hour)
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT INTO usage_snapshots (ts, five_hour_pct, seven_day_pct,"
            " five_hour_resets_at, seven_day_resets_at, total_cost_usd, active_agents)"
            " VALUES (?, 0, ?, '', ?, 0, 0)",
            (ts.isoformat(), float(series[hour]), reset.isoformat()),
        )
        conn.commit()
        conn.close()
        asyncio.run(evaluate_and_notify(
            {"seven_day": {"utilization": float(series[hour]),
                           "resets_at": reset.isoformat()}},
            now=ts, send=send,
        ))
    return send


# --- AC-1: объём сообщений на реплее реальных недель ----------------------------------

def test_incident_week_produces_exactly_one_message(db):
    send = _replay(db, "04.08 Max20", Recorder())
    assert len(send.messages) == 1, send.messages
    assert "Недельная квота Claude" in send.messages[0]


@pytest.mark.parametrize("week", ["21.07 Max5", "28.07 Max5→20"])
def test_calm_weeks_produce_no_messages(db, week):
    send = _replay(db, week, Recorder())
    assert send.messages == []


def test_all_four_weeks_stay_within_three_messages(db, tmp_path, monkeypatch):
    """Верхняя граница из ресёрча: 1–3 сообщения в неделю, иначе их перестанут читать."""
    total = 0
    for index, week in enumerate(sorted(WEEKS)):
        monkeypatch.setattr("app.db.DB_PATH", tmp_path / f"w{index}.db")
        from app.db import init_db

        init_db()
        total += len(_replay(tmp_path / f"w{index}.db", week, Recorder()).messages)
    assert total <= 3, f"{total} сообщений за четыре недели"


# --- AC-2: содержимое сообщения --------------------------------------------------------

def test_message_carries_pace_norm_and_forecast(db):
    send = _replay(db, "04.08 Max20", Recorder())
    text = send.messages[0]
    assert "pp за рабочий час" in text
    assert "нормативе" in text
    assert "кончится" in text
    assert "до сброса" in text


# --- AC-3: падение оценки не роняет вызывающего ---------------------------------------

def test_broken_delivery_does_not_raise(db):
    _write(db, [(WINDOW_START, 0.0), (WINDOW_START + timedelta(hours=20), 60.0)])
    send = Recorder(raises=RuntimeError("bridge exploded"))
    result = asyncio.run(evaluate_and_notify(
        _anthropic(60.0), now=WINDOW_START + timedelta(hours=20), send=send,
    ))
    assert result["state"] == "alert_pending", "неудачная отправка не должна считаться доставкой"


def test_garbage_reset_at_does_not_raise(db):
    _write(db, [(WINDOW_START, 0.0), (WINDOW_START + timedelta(hours=20), 60.0)])
    payload = {"seven_day": {"utilization": 60.0, "resets_at": "не дата"}}
    result = asyncio.run(evaluate_and_notify(
        payload, now=WINDOW_START + timedelta(hours=20), send=Recorder(),
    ))
    assert isinstance(result, dict)


# --- AC-4: бюджет доставки -------------------------------------------------------------

def test_hanging_delivery_is_bounded_and_retried(db):
    """Зависший мост не имеет права задержать общий цикл снимков.

    Внешний `wait_for` здесь обязателен, а не для красоты: без него снятие бюджета
    внутри `quota_alert` вешает ВЕСЬ сьют вместо того, чтобы покраснеть, — а повисший
    тест рано или поздно заскипают и регрессию перестанут ловить.
    """
    _write(db, [(WINDOW_START, 0.0), (WINDOW_START + timedelta(hours=20), 60.0)])
    send = Recorder(hang=True)

    async def run():
        loop = asyncio.get_running_loop()
        started = loop.time()
        result = await asyncio.wait_for(
            evaluate_and_notify(
                _anthropic(60.0), now=WINDOW_START + timedelta(hours=20), send=send,
            ),
            timeout=DELIVERY_BUDGET_SECONDS + 5,
        )
        return result, loop.time() - started

    try:
        result, elapsed = asyncio.run(run())
    except asyncio.TimeoutError:
        pytest.fail("доставка не ограничена бюджетом — цикл снимков будет ждать мост")
    assert elapsed < DELIVERY_BUDGET_SECONDS + 5
    assert result["state"] == "alert_pending", "таймаут — не доставка"


# --- AC-5: рестарт между переходом и доставкой не теряет предупреждение ---------------

def test_failed_delivery_is_retried_on_the_next_cycle(db):
    _write(db, [(WINDOW_START, 0.0), (WINDOW_START + timedelta(hours=20), 60.0)])
    now = WINDOW_START + timedelta(hours=20)

    failing = Recorder(result={"error": "TG bridge not active"})
    first = asyncio.run(evaluate_and_notify(_anthropic(60.0), now=now, send=failing))
    assert first["state"] == "alert_pending"

    working = Recorder()
    second = asyncio.run(evaluate_and_notify(
        _anthropic(60.0), now=now + timedelta(minutes=5), send=working,
    ))
    assert second["state"] == "alert_delivered"
    assert len(working.messages) == 1


def test_delivered_alert_is_not_sent_again(db):
    _write(db, [(WINDOW_START, 0.0), (WINDOW_START + timedelta(hours=20), 60.0)])
    now = WINDOW_START + timedelta(hours=20)
    send = Recorder()
    for minute in (0, 5, 10, 15):
        asyncio.run(evaluate_and_notify(
            _anthropic(60.0 + minute * 0.1), now=now + timedelta(minutes=minute), send=send,
        ))
    assert len(send.messages) == 1, send.messages


# --- AC-6: молчание источника ----------------------------------------------------------

def test_silence_is_announced_once_after_the_grace_period(db):
    send = Recorder()
    base = WINDOW_START + timedelta(hours=10)
    asyncio.run(evaluate_and_notify(None, now=base, send=send))
    assert send.messages == [], "с первого пропуска молчать"

    asyncio.run(evaluate_and_notify(None, now=base + timedelta(minutes=31), send=send))
    assert len(send.messages) == 1
    assert "не отвечает" in send.messages[0]

    asyncio.run(evaluate_and_notify(None, now=base + timedelta(minutes=60), send=send))
    assert len(send.messages) == 1, "повтор про то же молчание"

    # После возврата данных состояние обнуляется, и новое молчание должно снова
    # уметь объявляться ровно один раз.
    asyncio.run(evaluate_and_notify(_anthropic(5.0), now=base + timedelta(minutes=35), send=send))
    assert len(send.messages) == 1

    asyncio.run(evaluate_and_notify(None, now=base + timedelta(minutes=40), send=send))
    assert len(send.messages) == 1
    asyncio.run(evaluate_and_notify(None, now=base + timedelta(minutes=70), send=send))
    assert len(send.messages) == 2


def test_data_returning_says_nothing(db):
    send = Recorder()
    base = WINDOW_START + timedelta(hours=10)
    asyncio.run(evaluate_and_notify(None, now=base, send=send))
    asyncio.run(evaluate_and_notify(None, now=base + timedelta(minutes=31), send=send))
    _write(db, [(WINDOW_START, 0.0), (base + timedelta(minutes=35), 5.0)])
    asyncio.run(evaluate_and_notify(
        _anthropic(5.0), now=base + timedelta(minutes=35), send=send,
    ))
    assert len(send.messages) == 1, "«снова работает» — не новость"


# --- AC-8: восстановление через границу окна -------------------------------------------

def test_undelivered_alert_of_a_past_window_is_dropped_not_sent_late(db):
    """Сервис пролежал через сброс — предупреждение о прошлой неделе дезинформирует."""
    _write(db, [(WINDOW_START, 0.0), (WINDOW_START + timedelta(hours=20), 60.0)])
    failing = Recorder(result={"error": "down"})
    asyncio.run(evaluate_and_notify(
        _anthropic(60.0), now=WINDOW_START + timedelta(hours=20), send=failing,
    ))

    next_reset = RESET + timedelta(days=7)
    _write(db, [(RESET + timedelta(hours=1), 2.0)])
    conn = sqlite3.connect(str(db))
    conn.execute(
        "UPDATE usage_snapshots SET seven_day_resets_at = ? WHERE ts > ?",
        (next_reset.isoformat(), RESET.isoformat()),
    )
    conn.commit()
    conn.close()

    send = Recorder()
    asyncio.run(evaluate_and_notify(
        {"seven_day": {"utilization": 2.0, "resets_at": next_reset.isoformat()}},
        now=RESET + timedelta(hours=1), send=send,
    ))
    assert send.messages == [], "старое предупреждение уехало с опозданием на неделю"

    from app.db import alert_pending

    assert alert_pending(WINDOW_START.isoformat()) is False


# --- по ревью T4: молчание с неудачной доставкой не теряется навсегда ------------------

def test_failed_silence_delivery_is_retried_not_lost(db):
    """Латч молчания берётся ДО отправки; без освобождения сообщение не прозвучит никогда."""
    base = WINDOW_START + timedelta(hours=10)
    failing = Recorder(result={"error": "TG bridge not active"})
    asyncio.run(evaluate_and_notify(None, now=base, send=failing))
    result = asyncio.run(evaluate_and_notify(
        None, now=base + timedelta(minutes=31), send=failing,
    ))
    assert result["state"] == "silence_pending"

    working = Recorder()
    again = asyncio.run(evaluate_and_notify(
        None, now=base + timedelta(minutes=36), send=working,
    ))
    assert again["state"] == "silence_announced"
    assert len(working.messages) == 1


def test_hanging_silence_delivery_is_bounded(db):
    """Зависший мост на ВЕТКЕ МОЛЧАНИЯ тоже не имеет права держать общий цикл."""
    base = WINDOW_START + timedelta(hours=10)
    send = Recorder(hang=True)
    asyncio.run(evaluate_and_notify(None, now=base, send=send))

    async def run():
        return await asyncio.wait_for(
            evaluate_and_notify(None, now=base + timedelta(minutes=31), send=send),
            timeout=DELIVERY_BUDGET_SECONDS + 5,
        )

    try:
        result = asyncio.run(run())
    except asyncio.TimeoutError:
        pytest.fail("доставка молчания не ограничена бюджетом")
    assert result["state"] == "silence_pending"


def test_no_exception_escapes_into_the_snapshot_loop(db):
    """NaN приезжает прямо из ответа провайдера: `json.loads` принимает его по умолчанию."""
    _write(db, [(WINDOW_START, 0.0), (WINDOW_START + timedelta(hours=20), 60.0)])
    result = asyncio.run(evaluate_and_notify(
        {"seven_day": {"utilization": float("nan"), "resets_at": RESET.isoformat()}},
        now=WINDOW_START + timedelta(hours=20), send=Recorder(),
    ))
    assert result["state"] == "error"
    assert "ValueError" in result["error"]


def test_non_dict_payload_does_not_raise(db):
    for payload in ("строка", 42, [], None):
        result = asyncio.run(evaluate_and_notify(
            payload, now=WINDOW_START + timedelta(hours=2), send=Recorder(),
        ))
        assert isinstance(result, dict)


def test_only_one_of_two_concurrent_passes_sends(db):
    """Заявка на отправку берётся атомарно — иначе оба прохода увидят pending и отправят.

    Отправитель ЗАДЕРЖИВАЕТСЯ до явного разрешения: без этого исход решает планировщик,
    и тест проходит даже на реализации через `alert_pending` — проверено мутацией.
    Задержка гарантирует, что второй проход доберётся до заявки, пока первый ещё не
    отметил доставку.
    """
    _write(db, [(WINDOW_START, 0.0), (WINDOW_START + timedelta(hours=20), 60.0)])
    now = WINDOW_START + timedelta(hours=20)
    sent: list[str] = []

    async def run():
        gate = asyncio.Event()
        entered = asyncio.Event()

        async def blocking_send(text, *, scope, sender):
            sent.append(text)
            entered.set()
            await gate.wait()
            return {"ok": True, "message_id": 1}

        first = asyncio.create_task(
            evaluate_and_notify(_anthropic(60.0), now=now, send=blocking_send))
        await entered.wait()          # первый уже внутри отправки и ещё не отметил доставку
        second = await evaluate_and_notify(_anthropic(60.0), now=now, send=blocking_send)
        gate.set()
        return await first, second

    first_result, second_result = asyncio.run(run())
    assert first_result["state"] == "alert_delivered"
    assert second_result["state"] == "quiet", second_result
    assert len(sent) == 1, sent


def test_two_threads_claiming_delivery_have_one_winner(db):
    """Тот же инвариант на уровне БД, без планировщика asyncio."""
    import threading

    from app.db import alert_claim_delivery, alert_state_advance

    window = RESET.isoformat()
    alert_state_advance(window, WINDOW_START.isoformat())

    barrier = threading.Barrier(8)
    results: list = [None] * 8

    def worker(index: int) -> None:
        barrier.wait(timeout=10)
        results[index] = alert_claim_delivery(window, WINDOW_START.isoformat(), 120.0)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert sum(1 for value in results if value is True) == 1, results


def test_expired_claim_is_taken_over_so_the_alert_is_not_lost(db):
    """Процесс упал между заявкой и отправкой — право обязано вернуться следующему циклу."""
    from app.db import alert_claim_delivery, alert_state_advance

    window = RESET.isoformat()
    alert_state_advance(window, WINDOW_START.isoformat())
    assert alert_claim_delivery(window, WINDOW_START.isoformat(), 120.0) is True
    assert alert_claim_delivery(window, (WINDOW_START + timedelta(seconds=60)).isoformat(), 120.0) is False
    assert alert_claim_delivery(window, (WINDOW_START + timedelta(seconds=300)).isoformat(), 120.0) is True


# --- развязка доставки от сбора снимков (по раунду 2 ревью) ---------------------------

def test_schedule_returns_immediately_and_does_not_wait_for_delivery(db):
    """Цикл снимков не ждёт ни SQLite, ни TG: планируем и сразу возвращаемся.

    `to_thread` защищает петлю событий, но не длительность цикла — шесть соединений
    по 5 с busy timeout плюс 10 с доставки складывались бы в полминуты задержки снимка.
    """
    _write(db, [(WINDOW_START, 0.0), (WINDOW_START + timedelta(hours=20), 60.0)])

    async def run():
        loop = asyncio.get_running_loop()
        started = loop.time()
        launched = quota_alert.schedule_evaluation(_anthropic(60.0))
        elapsed = loop.time() - started
        if quota_alert._running:
            await asyncio.wait_for(quota_alert._running, timeout=30)
        return launched, elapsed

    launched, elapsed = asyncio.run(run())
    assert launched is True
    assert elapsed < 0.05, f"планирование заняло {elapsed:.3f} с — это уже ожидание"


def test_second_tick_is_skipped_while_the_first_is_still_running(db):
    """Пропускаем, а не копим очередь: следующий тик через 300 с посчитает по свежим данным."""
    _write(db, [(WINDOW_START, 0.0), (WINDOW_START + timedelta(hours=20), 60.0)])

    async def run():
        quota_alert._running = asyncio.create_task(asyncio.sleep(5))
        try:
            return quota_alert.schedule_evaluation(_anthropic(60.0))
        finally:
            quota_alert._running.cancel()

    assert asyncio.run(run()) is False


def test_schedule_starts_again_once_the_previous_pass_finished(db):
    async def run():
        quota_alert._running = None
        first = quota_alert.schedule_evaluation(None)
        await asyncio.wait_for(quota_alert._running, timeout=30)
        second = quota_alert.schedule_evaluation(None)
        await asyncio.wait_for(quota_alert._running, timeout=30)
        return first, second

    assert asyncio.run(run()) == (True, True)


def test_stuck_evaluation_is_abandoned_so_the_feature_never_goes_silent(db):
    """Зависшая оценка не имеет права выключить предупреждения навсегда.

    Точная последовательность из ревью: отправитель глотает отмену → `wait_for` ждёт
    завершения отмены → `_deliver` не возвращается → `done()` навсегда False → каждый
    следующий тик пропускается. Сторожу для решения нужно ровно одно: задача не завершена
    и висит дольше потолка. Моделируем это Future, который не завершится сам.
    """
    async def run():
        loop = asyncio.get_running_loop()
        stuck = loop.create_future()
        quota_alert._running = stuck

        quota_alert._running_since = loop.time()
        skipped = quota_alert.schedule_evaluation(None)

        quota_alert._running_since = loop.time() - quota_alert.STUCK_EVALUATION_SECONDS - 1
        restarted = quota_alert.schedule_evaluation(None)
        replaced = quota_alert._running is not stuck
        if restarted:
            await asyncio.wait_for(quota_alert._running, timeout=30)
        if not stuck.done():
            stuck.cancel()
        return skipped, restarted, replaced

    skipped, restarted, replaced = asyncio.run(run())
    assert skipped is False, "свежая оценка должна была пропустить тик"
    assert restarted is True, "зависшая оценка выключила предупреждения навсегда"
    assert replaced is True
