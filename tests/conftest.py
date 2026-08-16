"""Глобальные фикстуры для тестов orchestra.

Основные unit-тесты не должны зависеть от внешних интеграций (Telegram, сеть).
Здесь — общие autouse-моки, которые отрезают такие пути по умолчанию.

Интеграционные тесты (если появятся) пусть включают реальный bridge явно
через свою фикстуру или маркер.
"""

import os
import sqlite3
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import unquote, urlsplit

import pytest


def _sqlite_file_path(database, *, uri=False):
    try:
        raw = os.fsdecode(os.fspath(database))
    except TypeError:
        return None
    if uri and raw.startswith("file:"):
        parsed = urlsplit(raw)
        if parsed.netloc and parsed.hostname != "localhost":
            return None
        raw = unquote(parsed.path)
    if raw == ":memory:":
        return None
    return Path(raw).resolve()


def _guard_sqlite_connect(connect, production_path):
    production_path = production_path.resolve()

    def guarded(database, *args, **kwargs):
        uri = kwargs.get("uri", args[6] if len(args) > 6 else False)
        if _sqlite_file_path(database, uri=uri) == production_path:
            raise AssertionError(
                f"test attempted to open production database: {production_path}"
            )
        return connect(database, *args, **kwargs)

    guarded._orchestra_production_db_guard = production_path
    return guarded


@pytest.fixture(autouse=True)
def _isolate_production_db(tmp_path):
    """A missing local patch must fail before SQLite can touch the production DB."""
    from app import db

    production_path = db._DEFAULT_DB_PATH.resolve()
    isolated_path = tmp_path / "orchestra.db"
    with pytest.MonkeyPatch.context() as guard_patch:
        guard_patch.setattr(db, "DB_PATH", isolated_path)
        guard_patch.setenv("ORCHESTRA_DB_PATH", str(isolated_path))
        guard_patch.setattr(
            sqlite3,
            "connect",
            _guard_sqlite_connect(sqlite3.connect, production_path),
        )
        yield


@pytest.fixture(autouse=True)
def _stable_worker_quota(request, monkeypatch):
    """Ordinary tests never read live subscription telemetry."""
    if request.node.path.name in {"test_quota_gate.py", "test_usage_readiness.py"}:
        return
    from app import quota_gate

    async def available(model: str, observation_loader=None):
        try:
            resolved = quota_gate.evaluate_worker_admission(
                model,
                {
                    "anthropic": {"label": "Claude", "windows": [{
                        "window_minutes": 10080, "utilization": 0,
                    }]},
                    "codex": {"label": "Codex", "windows": [{
                        "window_minutes": 10080, "utilization": 0,
                    }]},
                    "codex_spark": {"label": "Codex Spark", "windows": [{
                        "window_minutes": 10080, "utilization": 0,
                    }]},
                },
                {
                    "anthropic": time.time(),
                    "codex": time.time(),
                    "codex_spark": time.time(),
                },
            )
        except Exception:
            raise
        return resolved

    monkeypatch.setattr(quota_gate, "get_worker_admission", available)


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
    for key in (
        "DASHBOARD_USER",
        "DASHBOARD_PASSWORD",
        "OWNER_MODE",
        "ARTIFACT_PUBLIC_LINKS_ENABLED",
        "PUBLIC_BASE_URL",
        "ARTIFACT_LINK_SECRET",
        "ARTIFACT_DEFAULT_TTL_SECONDS",
        "ARTIFACT_MAX_TTL_SECONDS",
        "ARTIFACT_MAX_BYTES",
        "STATE_DIRECTORY",
        "XDG_STATE_HOME",
    ):
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
