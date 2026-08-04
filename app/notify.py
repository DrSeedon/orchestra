"""Уведомление о НЕдоставке: у потерянного сообщения обязан быть адресат (#30).

Адресат — оркестратор того же scope: он ставил работу, ему и решать, что делать.
Получателя по умолчанию здесь НЕТ намеренно: выдуманный адресат хуже отсутствующего,
потому что создаёт ложное ощущение, что кто-то узнал. Нет оркестратора — так и говорим.
"""
import logging

logger = logging.getLogger(__name__)


def orchestrator_for_scope(scope: str) -> dict | None:
    from app.db import get_all_sessions

    scope = (scope or "").rstrip("/")
    for row in get_all_sessions():
        if (
            bool(row.get("is_orchestrator"))
            and (row.get("scope") or "").rstrip("/") == scope
            and (row.get("status") or "") != "archived"
        ):
            return row
    return None


async def report_undelivered(session_manager, *, scope: str, worker: str,
                             what: str, reason: str, dedupe_key: str = "") -> str:
    """Сообщить оркестратору scope о недоставке. Возвращает, что фактически вышло.

    Рекурсии нет: если не доставлено само уведомление, второго уведомления не будет —
    только строка в журнале.
    """
    orch = orchestrator_for_scope(scope)
    if not orch:
        outcome = f"некому сообщить: в scope {scope} нет оркестратора (воркер {worker})"
        logger.warning("undelivered %s for %s: %s", what, worker, outcome)
        return outcome
    text = (
        f"НЕДОСТАВКА: {what} для воркера {worker} не доставлено.\n"
        f"Причина: {reason}\n"
        f"Работа воркера стоит. Повтор — твоё решение, автоматического ретрая нет."
    )
    try:
        await session_manager.send(orch["id"], text)
    except Exception as error:
        outcome = (f"уведомить {orch['name']} не удалось: "
                   f"{type(error).__name__}: {error}")
        logger.warning("undelivered %s for %s: %s", what, worker, outcome)
        # Строку в истории видит человек, факт в очереди — сам агент, со следующим
        # успешным сообщением (#50). Без ключа очередь не заводим: невидимая склейка
        # двух разных событий в одно хуже двух записей.
        if dedupe_key:
            _queue_fact(orch["id"], dedupe_key,
                        f"{what} для воркера «{worker}» не доставлено: {reason}")
        return outcome
    logger.warning("undelivered %s for %s: reported to %s", what, worker, orch["name"])
    return f"сообщено оркестратору {orch['name']}"


async def notify_bug_report(session_manager, *, scope: str, reporter: str,
                            title: str, record_id: str) -> str:
    """Сказать оркестратору scope, что в его проекте подан баг-репорт (#56).

    Раньше репорт просто ложился в приватный стор: ни уведомления, ни отметки о прочтении.
    Семь штук пролежали двое суток, включая репорты оркестраторов чужих проектов.

    Уведомление шлётся РОВНО один раз, при публикации записи; ретраев нет намеренно —
    повтор POST создаёт вторую запись, и два уведомления на два репорта это правда,
    а не дубль. Автору собственного репорта не шлём: он и так знает.
    """
    orch = orchestrator_for_scope(scope)
    if not orch:
        outcome = f"некому сообщить: в scope {scope} нет оркестратора"
        logger.warning("bug report %s from %s: %s", record_id, reporter, outcome)
        return outcome
    if orch["name"] == reporter:
        return f"не отправлено: {reporter} — автор репорта и адресат одновременно"
    text = (
        f"BUG REPORT в твоём scope: «{title}»\n"
        f"Подал: {reporter}. Запись: {record_id}.\n"
        f"Полный текст — GET /api/report_bug. Разбор и приоритет — на тебе; "
        f"платформа его только зарегистрировала."
    )
    try:
        await session_manager.send(orch["id"], text)
    except Exception as error:
        outcome = f"уведомить {orch['name']} не удалось: {type(error).__name__}: {error}"
        logger.warning("bug report %s from %s: %s", record_id, reporter, outcome)
        _record_undelivered_bug(orch, reporter, title, record_id, outcome)
        return outcome
    logger.info("bug report %s from %s reported to %s", record_id, reporter, orch["name"])
    return f"сообщено оркестратору {orch['name']}"


def _record_undelivered_bug(orch: dict, reporter: str, title: str,
                            record_id: str, outcome: str) -> None:
    """След, не зависящий от сломанного канала (#47): в истории сессии адресата.

    До самого агента запись не доедет — `system` в контекст не попадает, это проверено
    в #47. Её читает человек в дашборде, и это лучшее, что доступно, когда доставка
    отказала: сам репорт при этом уже лежит в сторе и не потерян.
    """
    from datetime import datetime, timezone

    from app.db import add_log

    try:
        add_log(
            orch["id"], datetime.now(timezone.utc), "system",
            f"[доставка] уведомление о баг-репорте «{title}» (запись {record_id}, "
            f"подал {reporter}) не доставлено: {outcome}. Сам репорт в сторе, "
            f"читать: GET /api/report_bug",
        )
        _queue_fact(orch["id"], f"bug:{record_id}",
                    f"уведомление о баг-репорте «{title}» (подал {reporter}) "
                    f"не доставлено; сам репорт в сторе: GET /api/report_bug")
    except Exception as log_error:
        logger.warning("could not record undelivered bug notice for %s: %s: %s",
                       orch["name"], type(log_error).__name__, log_error)


def _queue_fact(session_id: str, dedupe_key: str, text: str) -> None:
    """Поставить факт в очередь адресата, не мешая основному пути при сбое."""
    from app.db import enqueue_fact

    try:
        enqueue_fact(session_id, dedupe_key, text)
    except Exception as error:
        logger.warning("could not queue fact %s for %s: %s: %s",
                       dedupe_key, session_id, type(error).__name__, error)
