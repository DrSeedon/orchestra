"""#269 — сообщение, пришедшее во время рестарта, не теряется и не задваивается.

Гейт приёма отвергает только МУТИРУЮЩИЕ HTTP-вызовы, а сообщение из Telegram по HTTP не идёт
вовсе: мост живёт в этом же процессе и кладёт его прямо в сессию, которая через секунду
умрёт. Для человека это неотличимо от «агент прочитал и не ответил».
"""
import asyncio
import logging
import sqlite3

import pytest


class _Chat:
    id = 42


class _Msg:
    chat = _Chat()
    message_thread_id = 7

    @property
    def from_user(self):
        return None


class _Manager:
    """Двойник с ЯВНЫМИ полями: `MagicMock` завёл бы любой запрошенный атрибут сам."""

    def __init__(self, fail_on: str = ""):
        self.sent: list[tuple[str, str]] = []
        self.fail_on = fail_on

    async def send(self, session_id: str, message: str, *, provenance) -> None:
        assert provenance.origin == "user"
        if self.fail_on and self.fail_on in message:
            raise RuntimeError("backend is not up yet")
        self.sent.append((session_id, message))


@pytest.fixture
def inbox(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.DB_PATH", tmp_path / "t.db")
    from app.db import init_db

    init_db()
    from app import restart_inbox

    return restart_inbox


@pytest.mark.asyncio
async def test_269_message_during_restart_is_queued_instead_of_pushed(inbox, monkeypatch):
    """Закрытый приём → в очередь и человеку сказали; открытый → обычная доставка.

    Плечо с ОТКРЫТЫМ гейтом обязательно: без него реализация «всегда в очередь» проходит
    оракул, а в проде это значит, что живые сообщения перестали доходить вовсе.
    """
    import app.main as app_main
    import app.tg_bridge as tb

    told = []
    manager = _Manager()
    monkeypatch.setattr(tb, "_manager", manager)
    monkeypatch.setattr(tb, "bot", object())
    monkeypatch.setattr(tb, "_tg_send_safe",
                        lambda chat_id, text, **kw: told.append(text) or _noop())

    monkeypatch.setattr(app_main, "manager", manager)
    monkeypatch.setattr(app_main, "_restart_inbox_drain", None)

    app_main.close_mutating_admission()
    try:
        await tb._flush_batch("sid-1", [(_Msg(), "ау", None)])
        assert manager.sent == [], "во время рестарта сообщение не уходит в умирающую сессию"
        queued = inbox.pending()
        assert len(queued) == 1 and "ау" in queued[0]["body"]
        assert queued[0]["session_id"] == "sid-1"
        assert queued[0]["chat_id"] == 42 and queued[0]["thread_id"] == 7
        assert told and "перезапус" in told[0].lower(), "юзеру обязаны сказать, что приняли"
    finally:
        app_main.open_mutating_admission()
    await _settle_drain(app_main)

    # control arm: гейт открыт — работает как раньше, в очередь ничего не ложится
    await tb._flush_batch("sid-1", [(_Msg(), "обычное", None)])
    assert [m for _s, m in manager.sent if "обычное" in m], "с открытым гейтом доставка живая"
    assert inbox.pending() == [], "живое сообщение не должно попадать в очередь рестарта"


@pytest.mark.asyncio
async def test_269_queued_messages_are_delivered_once_after_startup(inbox):
    manager = _Manager()
    inbox.enqueue("sid-1", "[10:00] ау")
    inbox.enqueue("sid-2", "[10:01] и мне")

    assert await inbox.deliver_pending(manager) == 2
    assert [s for s, _m in manager.sent] == ["sid-1", "sid-2"]
    assert inbox.pending() == []

    # второй подъём не обязан ничего находить: доставленное помечено
    assert await inbox.deliver_pending(manager) == 0
    assert len(manager.sent) == 2, "повторный дренаж задвоил бы сообщение"


@pytest.mark.asyncio
async def test_269_failed_delivery_stays_queued_for_the_next_start(inbox):
    """Направление отказа: лучше дубль, чем потеря. Пометка — только ПОСЛЕ доставки.

    Пометить сначала — значит потерять сообщение ровно тогда, когда процесс наименее
    устойчив (#158: флаг «уже обработано», погашенный до самого действия).
    """
    failing = _Manager(fail_on="ау")
    inbox.enqueue("sid-1", "[10:00] ау")
    inbox.enqueue("sid-2", "[10:01] и мне")

    assert await inbox.deliver_pending(failing) == 1
    still = inbox.pending()
    assert len(still) == 1 and still[0]["session_id"] == "sid-1", (
        "не доставленное обязано остаться в очереди, иначе оно исчезло навсегда")

    recovered = _Manager()
    assert await inbox.deliver_pending(recovered) == 1
    assert [s for s, _m in recovered.sent] == ["sid-1"]
    assert inbox.pending() == []


@pytest.mark.asyncio
async def test_269_aborted_restart_still_delivers_what_it_promised(inbox, monkeypatch):
    """B1: рестарта не случилось — приём открыли обратно, процесс жив, доставить обязаны.

    `restart_preflight` при недодренированном хвосте (409), сторож и упавший путь рестарта
    открывают приём, не убивая процесс. Дренаж, привязанный к СТАРТУ процесса, в этом
    сценарии не зовётся вовсе: юзеру сказали «отдам, как вернусь», а возвращаться неоткуда.
    """
    import app.main as app_main
    import app.tg_bridge as tb

    manager = _Manager()
    monkeypatch.setattr(tb, "_manager", manager)
    monkeypatch.setattr(tb, "bot", object())
    monkeypatch.setattr(tb, "_tg_send_safe", lambda chat_id, text, **kw: _noop())
    monkeypatch.setattr(app_main, "manager", manager)
    monkeypatch.setattr(app_main, "_restart_inbox_drain", None)

    app_main.close_mutating_admission()
    await tb._flush_batch("sid-1", [(_Msg(), "ау", None)])
    assert len(inbox.pending()) == 1

    # рестарт отменён: приём открыт, процесс НЕ перезапускался
    app_main.open_mutating_admission()
    await _settle_drain(app_main)

    assert [s for s, _m in manager.sent] == ["sid-1"], (
        "обещание доставить привязано к открытию приёма, а не к старту процесса")
    assert inbox.pending() == []


@pytest.mark.asyncio
async def test_269_message_for_a_session_that_never_came_back_is_given_up_and_reported(
        inbox, monkeypatch):
    """H2: адресата больше нет — сказать юзеру и перестать воскрешать строку.

    Без потолка попыток строка молча воскресает при каждом открытии приёма до конца жизни БД,
    и человек так и не узнаёт, что его сообщение никто не получил.
    """
    import app.tg_bridge as tb

    class _Gone:
        async def send(self, session_id, message, *, provenance):
            assert provenance.origin == "user"
            raise KeyError(f"session not found: {session_id}")

    reported = []
    monkeypatch.setattr(tb, "report_inbox_undeliverable",
                        lambda chat_id, thread_id, body, detail:
                        reported.append((chat_id, body, detail)) or _noop())

    inbox.enqueue("sid-gone", "[10:00] ау", chat_id=42, thread_id=7)
    gone = _Gone()
    for _attempt in range(inbox.MAX_ATTEMPTS - 1):
        assert await inbox.deliver_pending(gone) == 0
        assert len(inbox.pending()) == 1, "до потолка попыток строка ещё ждёт"
        assert reported == [], "рано сдаваться: сессия могла не успеть подняться"

    assert await inbox.deliver_pending(gone) == 0
    assert inbox.pending() == [], "после потолка строка больше не воскресает"
    assert len(reported) == 1
    chat_id, body, detail = reported[0]
    assert chat_id == 42 and "ау" in body, "юзеру возвращают текст, а не только факт отказа"
    assert "KeyError" in detail


@pytest.mark.asyncio
async def test_269_a_hanging_delivery_does_not_block_the_rest_of_the_queue(inbox, monkeypatch):
    """L2: поштучность спасает от ИСКЛЮЧЕНИЯ, но не от ЗАВИСАНИЯ.

    Прогон ограничен по времени намеренно: регрессия обязана краснеть, а не висеть.
    """
    monkeypatch.setattr(inbox, "DELIVERY_TIMEOUT_S", 0.05)

    class _Hangs:
        def __init__(self):
            self.sent = []

        async def send(self, session_id, message, *, provenance):
            assert provenance.origin == "user"
            if session_id == "sid-hangs":
                await asyncio.sleep(30)
            self.sent.append(session_id)

    inbox.enqueue("sid-hangs", "[10:00] первое")
    inbox.enqueue("sid-2", "[10:01] второе")

    manager = _Hangs()
    assert await asyncio.wait_for(inbox.deliver_pending(manager), timeout=5) == 1
    assert manager.sent == ["sid-2"], "повисшая строка не имеет права съесть очередь"
    assert [row["session_id"] for row in inbox.pending()] == ["sid-hangs"]


@pytest.mark.asyncio
async def test_269_drain_failure_is_loud(inbox, monkeypatch, caplog):
    """M1: отказ всего дренажа — единственный исход, который иначе никто бы не заметил."""
    def explode():
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(inbox, "pending", explode)
    with caplog.at_level(logging.ERROR):
        assert await inbox.deliver_pending(_Manager()) == 0
    assert any("could not read the queue" in record.message for record in caplog.records)


async def _settle_drain(app_main) -> None:
    task = app_main._restart_inbox_drain
    assert task is not None, "открытие приёма обязано запустить дренаж"
    await task


async def _noop():
    return None
