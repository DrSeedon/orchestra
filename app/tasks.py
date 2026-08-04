"""Фоновые задачи, которые не могут упасть молча (#30).

`asyncio.create_task` без забора результата — это класс дефектов, а не место: исключение
всплывает в задачу и там кончается. Замер #30: сообщение юзера из Telegram терялось так,
что в чат не уходило НИЧЕГО, а единственным следом была строка `Task exception was never
retrieved`, которую asyncio печатает при сборке мусора.

`add_done_callback(множество.discard)` от этого НЕ спасает: он снимает задачу с учёта,
но `t.exception()` не читает — то есть выглядит как уборка, а работает как глушитель.
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

_supervised: set[asyncio.Task] = set()


def spawn_supervised(coro, what: str) -> asyncio.Task:
    """`create_task`, у которого падение обязано быть слышно.

    what — что именно запускается, человеческими словами: это попадёт в журнал вместо
    безымянного `Task-17`.
    """
    task = asyncio.create_task(coro)
    _supervised.add(task)

    def _done(finished: asyncio.Task) -> None:
        _supervised.discard(finished)
        if finished.cancelled():
            return
        error = finished.exception()
        if error is not None:
            logger.warning("background task failed: %s — %s: %s",
                           what, type(error).__name__, error)

    task.add_done_callback(_done)
    return task
