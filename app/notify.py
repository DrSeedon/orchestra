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
                             what: str, reason: str) -> str:
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
        return outcome
    logger.warning("undelivered %s for %s: reported to %s", what, worker, orch["name"])
    return f"сообщено оркестратору {orch['name']}"
