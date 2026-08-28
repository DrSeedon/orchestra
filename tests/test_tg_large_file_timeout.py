"""Большой файл из Telegram не должен теряться по таймауту сессии.

28.08.2026: .wav на 518 326 700 Б (494 МБ) не дошёл до агента — `get_file` упал на
60 948 мс, ровно дефолтные 60 с aiogram. Файл при этом УЖЕ лежал на диске в
`data/tg-bot-api/.../documents/file_1210.wav`: ждали мы свой локальный Bot API,
который дописывал файл, а не сеть Telegram. Юзер увидел «file: too large» —
сообщение, которое врало про причину.
"""

import inspect
import pathlib


def test_local_api_session_raises_the_default_timeout():
    """Сессия к локальному Bot API создаётся с явным таймаутом, а не с дефолтом 60 с.

    Читаем ФАЙЛ, а не импортированный модуль: `app.tg_bridge` в общем прогоне бывает
    замокан соседними тестами, и `inspect.getsource` тогда падает на AsyncMock.
    """
    source = pathlib.Path("app/tg_bridge.py").read_text(encoding="utf-8")

    assert "AiohttpSession(api=server, timeout=" in source, (
        "сессия к Local Bot API обязана задавать timeout явно: дефолт aiogram 60 с "
        "теряет большие файлы, которые сервер ещё дописывает на диск"
    )
    line = next(l for l in source.splitlines() if "AiohttpSession(api=server" in l)
    value = int(line.split("timeout=")[1].split(")")[0])
    assert value >= 600, f"бюджет {value} с мал для файлов в сотни МБ"


def test_session_timeout_is_the_value_requests_actually_use():
    """Проверка, что параметр не декоративный: `make_request` берёт именно `self.timeout`."""
    from aiogram.client.session.aiohttp import AiohttpSession

    body = inspect.getsource(AiohttpSession.make_request)

    assert "timeout=self.timeout if timeout is None else timeout" in body
    # И что именно этот путь порождает текст, который увидели в журнале.
    assert 'message="Request timeout error"' in body
