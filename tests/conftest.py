"""Глобальные фикстуры для тестов orchestra.

Основные unit-тесты не должны зависеть от внешних интеграций (Telegram, сеть).
Здесь — общие autouse-моки, которые отрезают такие пути по умолчанию.

Интеграционные тесты (если появятся) пусть включают реальный bridge явно
через свою фикстуру или маркер.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


async def _empty_events():
    """Async iterator для мока backend.events(): ждёт cancellation, не yield'ит.

    Просто ``if False: yield`` создаёт пустой генератор — он завершается мгновенно,
    и внешний ``while True`` цикл в ``_claude_event_loop`` крутится в hot-loop,
    не давая ``cancel()`` шанса сработать. Поэтому мы ждём вечно и завершаемся
    по CancelledError, имитируя живой backend, который просто молчит.
    """
    import asyncio
    try:
        await asyncio.Event().wait()  # ждём вечно
    except asyncio.CancelledError:
        return
    if False:
        yield  # never reached — нужно только чтобы это был async generator


def make_backend_mock() -> AsyncMock:
    """Стандартный мок для AgentSession._make_backend().

    Включает все методы текущего интерфейса backend (connect/send/disconnect/
    interrupt/reconnect) и корректный async iterator events().
    """
    m = AsyncMock(
        connect=AsyncMock(), send=AsyncMock(), disconnect=AsyncMock(),
        interrupt=AsyncMock(), reconnect=AsyncMock(),
    )
    m.events = MagicMock(side_effect=lambda: _empty_events())
    return m


@pytest.fixture(autouse=True)
def _no_tg_bridge(monkeypatch):
    """Не зовём реальный Telegram Bot API в обычных тестах.

    Без этого ``TestClient(app)`` через lifespan() запускает aiogram-polling,
    который ждёт ответ от TG и блокирует тесты на минуты.
    """
    import app.tg_bridge as tb
    monkeypatch.setattr(tb, "start_bridge", AsyncMock())
    monkeypatch.setattr(tb, "stop_bridge", AsyncMock())
