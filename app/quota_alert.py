"""Раннее предупреждение о недельной квоте Claude: оценить, зафиксировать, сказать (#186).

Один проход = один вызов `evaluate_and_notify` из цикла снимков, строго ПОСЛЕ записи снимка.
Здесь собрано всё, что решает и доставляет; в маршруте остаётся одна строка вызова.

Порог живёт здесь, а не в метрике: `quota_runway` отдаёт измерение, а сравнивать с ним
каждый потребитель волен по-своему (у роутера #187 свой конфиг).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.quota_runway import (
    DEFAULT_ALERT_DEFICIT_HOURS,
    SUSTAINABLE_PACE_PP_PER_WORK_HOUR,
    as_utc,
    moment_after_working_hours,
    next_weekly_reset,
    weekly_runway,
)

logger = logging.getLogger(__name__)

ALERT_DEFICIT_HOURS = DEFAULT_ALERT_DEFICIT_HOURS

# Источник не отвечал 381 раз из 8804, и почти всегда это одиночные пропуски. Говорить
# с первого — превратить редкое сообщение в шум, а его перестанут читать.
NO_DATA_GRACE_SECONDS = 1800.0

# Доставка идёт внутри общего цикла снимков. `_tg_send_safe` ждёт диспетчер и сеть, поэтому
# без потолка медленная очередь TG задержала бы сам сбор снимков — а на нём висят дашборд,
# `quota_headroom` и вход #187. Таймаут ничего не теряет: `delivered_at` остаётся пустым,
# и следующий проход через 300 с повторит.
DELIVERY_BUDGET_SECONDS = 10.0

# Аренда права на отправку. Переживший её проход (упал процесс, оборвался ход) отдаёт
# право следующему циклу: без срока висящая заявка заблокировала бы повтор навсегда.
DELIVERY_LEASE_SECONDS = 120.0

_SCOPE = "/home/kesha/orchestra"
_SENDER = "Orchestra-orchestrator"


def _utilization(window: object) -> float | None:
    if not isinstance(window, dict):
        return None
    value = window.get("utilization")
    return float(value) if isinstance(value, (int, float)) else None


def _reset_at(window: object) -> datetime | None:
    if not isinstance(window, dict):
        return None
    raw = window.get("resets_at")
    if not raw:
        return None
    try:
        return as_utc(datetime.fromisoformat(str(raw).replace("Z", "+00:00")), "resets_at")
    except ValueError as error:
        logger.warning("quota alert: resets_at неразбираем (%r): %s: %s",
                       raw, type(error).__name__, error)
        return None


def _alert_text(verdict, reset_at: datetime, now: datetime) -> str:
    wall = moment_after_working_hours(now, verdict.runway_hours)
    when = wall.strftime("%a %d.%m %H:%M UTC") if wall else "до конца окна"
    return (
        "⚠️ Недельная квота Claude: текущий темп не доживёт до сброса.\n\n"
        f"Темп: {verdict.pace:.2f} pp за рабочий час при нормативе "
        f"{SUSTAINABLE_PACE_PP_PER_WORK_HOUR:.2f}.\n"
        f"При нём Claude кончится {when} — это за {verdict.deficit:.0f} рабочих часов "
        f"до сброса {reset_at.strftime('%a %d.%m %H:%M UTC')}.\n\n"
        "Чтобы дожить: убрать тяжёлое с Claude или увести на Codex. "
        "На 95% включится жёсткий гейт, после него остаток доедается сутками."
    )


def _silence_text(minutes: float) -> str:
    return (
        f"🔇 Квота Anthropic не отвечает {minutes:.0f} минут — политика недельного окна "
        "не считается. Это не «всё хорошо», это отсутствие данных."
    )


_running: asyncio.Task | None = None
_running_since: float = 0.0

# Дольше одного цикла опроса оценка идти не может: бюджет доставки 10 с, всё остальное —
# арифметика и короткие запросы. Провисела дольше — значит зависла на чём-то, что не
# уважает отмену. Такую бросаем и начинаем заново, иначе один застрявший проход выключил
# бы предупреждения НАВСЕГДА: `done()` у него никогда не станет True.
STUCK_EVALUATION_SECONDS = 300.0


def schedule_evaluation(anthropic: dict | None) -> bool:
    """Запустить оценку ФОНОМ и вернуться немедленно. True — запустили, False — пропустили.

    Это точка вызова из цикла снимков, и она принципиально не `await`: сбор снимков не
    должен ждать ни доставку, ни SQLite. `asyncio.to_thread` защищает петлю событий, но не
    длительность самого цикла — до шести соединений подряд, каждое с пятисекундным busy
    timeout, плюс десять секунд бюджета доставки складывались бы в полминуты задержки
    снимка под конкуренцией за запись. А на снимках висят дашборд, `quota_headroom` и #187.

    Предыдущий проход ещё идёт → этот пропускаем. Очередь здесь не нужна: следующий тик
    через 300 с всё равно посчитает по свежим данным, а `delivered_at` не даст потерять
    недоставленное. Ссылку на задачу держим глобально — иначе сборщик мусора может
    уничтожить её на полпути.
    """
    global _running, _running_since
    loop = asyncio.get_running_loop()
    if _running is not None and not _running.done():
        age = loop.time() - _running_since
        if age < STUCK_EVALUATION_SECONDS:
            logger.warning("quota alert: предыдущая оценка ещё идёт, тик пропущен")
            return False
        # Отмену запрашиваем, но НЕ ждём: задача, не уважающая отмену, иначе продержала бы
        # ссылку вечно. Бросаем её и заводим новую — потеря одного прохода дешевле, чем
        # молча выключенное предупреждение.
        logger.error("quota alert: оценка висит %.0f с, бросаем её и начинаем заново", age)
        _running.cancel()
    _running = asyncio.create_task(evaluate_and_notify(anthropic))
    _running_since = loop.time()
    return True


async def evaluate_and_notify(anthropic: dict | None, *, now: datetime | None = None,
                              send=None) -> dict:
    """Оценить недельное окно и, если состояние сменилось, сказать об этом один раз.

    **Ни одно исключение наружу не выходит.** Вызывающий сидит в общем цикле снимков, и
    его падение остановило бы сбор данных для дашборда, `quota_headroom` и #187. Раньше
    обёрнута была только доставка, а поднять могли и `as_utc`, и `_checked_pct` внутри
    метрики (на `NaN` из ответа провайдера), и разбор базы, и любой запрос к БД.
    """
    try:
        return await _evaluate(anthropic, now=now, send=send)
    except Exception as error:  # noqa: BLE001 — граница общего рантайма, класс в журнал
        logger.warning("quota alert: цикл не отработал — %s: %s",
                       type(error).__name__, error, exc_info=True)
        return {"state": "error", "error": f"{type(error).__name__}: {error}"}


async def _evaluate(anthropic: dict | None, *, now: datetime | None, send) -> dict:
    now = as_utc(now or datetime.now(timezone.utc), "now")
    stamp = now.isoformat()
    if send is None:
        from app.tg_bridge import send_text_to_tg

        send = send_text_to_tg

    from app.db import (
        alert_claim_delivery,
        alert_discard_stale,
        alert_mark_delivered,
        alert_state_advance,
        runway_window_start_pct,
        silence_mark_announced,
        silence_observe,
        silence_release,
    )

    seven_day = (anthropic or {}).get("seven_day") if isinstance(anthropic, dict) else None
    utilization = _utilization(seven_day)

    # Вся синхронная работа с SQLite — одним заходом в поток. На петле событий она стоила
    # бы до шести соединений подряд, каждое с пятисекундным busy timeout: бюджет доставки
    # в 10 с такой стойл не ограничивает вовсе, а тормозит он общий цикл снимков.
    def _sync_stage_one():
        announce = silence_observe(has_data=utilization is not None, now=stamp,
                                   grace_seconds=NO_DATA_GRACE_SECONDS,
                                   lease_seconds=DELIVERY_LEASE_SECONDS)
        if utilization is None:
            return announce, None, None, ()
        reset_at = _reset_at(seven_day) or next_weekly_reset(now)
        baseline = runway_window_start_pct(reset_at)
        verdict = weekly_runway(
            utilization=utilization,
            window_start_pct=baseline[0] if baseline else None,
            window_start_at=datetime.fromisoformat(baseline[1]) if baseline else None,
            now=now,
            reset_at=reset_at,
        )
        stale = ()
        if verdict.state == "data":
            stale = tuple(alert_discard_stale(verdict.window_id, stamp, DELIVERY_LEASE_SECONDS))
        return announce, reset_at, verdict, stale

    announce, reset_at, verdict, stale = await asyncio.to_thread(_sync_stage_one)

    if announce:
        if await _deliver(send, _silence_text(NO_DATA_GRACE_SECONDS / 60)):
            await asyncio.to_thread(silence_mark_announced, stamp)
            return {"state": "silence_announced"}
        # Латч уже взят, а сообщение не ушло: без освобождения молчание считалось бы
        # объявленным навсегда и НИКОГДА бы не прозвучало. Отпускаем — повторим циклом позже.
        await asyncio.to_thread(silence_release, stamp)
        return {"state": "silence_pending"}

    if utilization is None:
        return {"state": "no_data"}

    # Предупреждение о неделе, которая уже кончилась, — дезинформация. Отбрасываем явно
    # и с записью в журнал: молчаливый дроп запрещён.
    for window_id in stale:
        logger.warning("quota alert: предупреждение за окно %s не доставлено и уже неактуально",
                       window_id)

    if verdict.state != "data" or verdict.deficit is None:
        return {"state": verdict.state, "reason": verdict.reason}

    def _claim() -> bool:
        if verdict.deficit > ALERT_DEFICIT_HOURS:
            alert_state_advance(verdict.window_id, stamp)
        # Право отправить берётся атомарно, а не выводится из «строка ещё висит».
        # Иначе два одновременных прохода оба увидели бы `alert_pending` и оба отправили:
        # единственный победитель `alert_state_advance` этого не предотвращает, потому что
        # проигравший всё равно видит непустой pending.
        return alert_claim_delivery(verdict.window_id, stamp, DELIVERY_LEASE_SECONDS)

    if not await asyncio.to_thread(_claim):
        return {"state": "quiet", "deficit": verdict.deficit}

    if await _deliver(send, _alert_text(verdict, reset_at, now)):
        await asyncio.to_thread(alert_mark_delivered, verdict.window_id, stamp)
        return {"state": "alert_delivered", "deficit": verdict.deficit}
    return {"state": "alert_pending", "deficit": verdict.deficit}


async def _deliver(send, text: str) -> bool:
    """Отправить под потолком времени. True — только по доказанному успеху."""
    try:
        result = await asyncio.wait_for(
            send(text, scope=_SCOPE, sender=_SENDER), timeout=DELIVERY_BUDGET_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("quota alert: доставка не уложилась в %.0f с, повтор следующим циклом",
                       DELIVERY_BUDGET_SECONDS)
        return False
    except Exception as error:  # noqa: BLE001 — класс исключения обязан попасть в журнал
        logger.warning("quota alert: доставка не удалась — %s: %s",
                       type(error).__name__, error)
        return False
    if isinstance(result, dict) and result.get("ok"):
        return True
    logger.warning("quota alert: доставка отклонена — %r", result)
    return False
