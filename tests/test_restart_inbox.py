"""#269 — сообщение, пришедшее во время рестарта, не теряется и не задваивается.

Гейт приёма отвергает только МУТИРУЮЩИЕ HTTP-вызовы, а сообщение из Telegram по HTTP не идёт
вовсе: мост живёт в этом же процессе и кладёт его прямо в сессию, которая через секунду
умрёт. Для человека это неотличимо от «агент прочитал и не ответил».
"""
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

    async def send(self, session_id: str, message: str) -> None:
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

    app_main.close_mutating_admission()
    try:
        await tb._flush_batch("sid-1", [(_Msg(), "ау", None)])
    finally:
        app_main.open_mutating_admission()

    assert manager.sent == [], "во время рестарта сообщение не должно уходить в умирающую сессию"
    queued = inbox.pending()
    assert len(queued) == 1 and "ау" in queued[0]["body"]
    assert queued[0]["session_id"] == "sid-1"
    assert queued[0]["chat_id"] == 42 and queued[0]["thread_id"] == 7
    assert told and "перезапус" in told[0].lower(), "юзеру обязаны сказать, что приняли"

    # control arm: гейт открыт — работает как раньше, очередь не растёт
    await tb._flush_batch("sid-1", [(_Msg(), "обычное", None)])
    assert [m for _s, m in manager.sent if "обычное" in m], "с открытым гейтом доставка живая"
    assert len(inbox.pending()) == 1, "живое сообщение не должно попадать в очередь рестарта"


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


async def _noop():
    return None
