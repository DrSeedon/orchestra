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
    и внешний ``while True`` цикл в ``_persistent_event_loop`` крутится в hot-loop,
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
def _hermetic_dashboard_env(monkeypatch):
    """Тест не должен зависеть от того, на чьей машине он запущен.

    Источника протечки два, и гасить надо оба:
    1) systemd-юнит Orchestra подаёт ``EnvironmentFile=.env``, поэтому у агента
       ``DASHBOARD_USER`` уже лежит в ``os.environ`` — файла в чекауте при этом нет
       (проверено: чистый клон main без .env всё равно давал 401);
    2) ``lifespan`` зовёт ``load_dotenv()``, который затянет ``.env`` обратно уже
       после любой предварительной очистки.

    С включённым auth все запросы к ``/api/`` получают 401 вместо ожидаемого кода:
    на CI такие тесты зелёные, у владельца красные. Тест, зависящий от чужого
    окружения, хуже красного — он не воспроизводится.

    Нужен включённый auth внутри теста — выставь переменные своим ``monkeypatch.setenv``.
    """
    import dotenv

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    for key in ("DASHBOARD_USER", "DASHBOARD_PASSWORD", "OWNER_MODE"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _no_tg_bridge(monkeypatch):
    """Не зовём реальный Telegram Bot API в обычных тестах.

    Без этого ``TestClient(app)`` через lifespan() запускает aiogram-polling,
    который ждёт ответ от TG и блокирует тесты на минуты.
    """
    import app.tg_bridge as tb
    monkeypatch.setattr(tb, "start_bridge", AsyncMock())
    monkeypatch.setattr(tb, "stop_bridge", AsyncMock())


# Маркер → (заголовок, чем объяснить пропуск). Такие тесты проверяют то, что заглушками не
# проверяется, а молчаливый `skipped` даёт ту же зелёную сводку, что и пройденный тест.
_LOUD_SKIPS = {
    "needs_two_users": (
        "ПРОПУЩЕНЫ ПРОВЕРКИ ВЛАДЕНИЯ ФАЙЛАМИ",
        "нет беспарольного sudo. Владение файлами нельзя проверить заглушками — "
        "нужны два реальных владельца.",
    ),
    "needs_model": (
        "ПРОПУЩЕН РЕАЛЬНЫЙ СЛОЙ RAG",
        "в этом окружении нет эмбеддера. Индексация, чанкинг и поиск заглушками не "
        "моделируются — правка RAG этим прогоном НЕ проверена. Ставить deps в worktree НЕ "
        "надо, прогнать интерпретатором сервера:\n"
        "  /home/kesha/orchestra/.venv/bin/python -m pytest tests/test_rag.py",
    ),
}


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Кричать о пропущенных тестах, чей пропуск неотличим от успеха.

    Печатаем отдельной строкой, сколько именно проверок НЕ выполнялось и почему.
    """
    for marker, (headline, why) in _LOUD_SKIPS.items():
        skipped = [
            report for report in terminalreporter.stats.get("skipped", [])
            if marker in getattr(report, "keywords", {})
        ]
        if not skipped:
            continue
        names = ", ".join(sorted(report.nodeid.split("::")[-1] for report in skipped))
        terminalreporter.write_sep("=", headline, red=True, bold=True)
        terminalreporter.write_line(f"{len(skipped)} теста(ов) не выполнялись: {why}", red=True)
        terminalreporter.write_line(f"  {names}", red=True)


@pytest.fixture(autouse=True)
def _isolate_worktree_root(tmp_path, monkeypatch):
    """Никакой тест не должен видеть НАСТОЯЩИЙ каталог worktrees.

    Страховка после #62: `TestClient(app)` поднимает lifespan, а тот запускал уборку
    рабочих копий. Тест с временной БД и настоящим WORKTREE_ROOT удалял чистые worktree'ы
    всех проектов — воспроизведено, зелёный `pytest tests/test_build_signal.py` стирал
    приманки. Первичная защита — уборка не стартует под pytest (`app/manager.py`), эта
    фикстура прикрывает следующий тест, который забудет про изоляцию.

    Тестам, которым нужен свой корень, ничего не мешает переопределить его своим
    monkeypatch — он ляжет поверх.
    """
    root = tmp_path / "_isolated_worktrees"
    root.mkdir(exist_ok=True)
    monkeypatch.setattr("app.workspace.WORKTREE_ROOT", root)
