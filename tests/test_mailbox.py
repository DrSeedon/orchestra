"""#231 T2/T3 — ящик: сообщение может НЕ будить, и разгружается в конце оплаченного хода.

Красные по замыслу до реализации.

Зачем: доставка у нас = активация, режима «не будить» нет. Замер (research.md §3.1):
средняя цена одного обращения к модели $0.117–0.182, а медианный ход, который развернёт
пробуждение, — $0.59–1.96, при медианном ВХОДЕ в 137 токенов. То есть за 137 токенов
содержания платится полное перечитывание контекста получателя.

T3 отдельно закрывает граблю #158: цикл умеет ПЕРЕИГРЫВАТЬ вход, поэтому флаг «доставлено»
гасится ПОСЛЕ фактической выдачи, а не в момент обнаружения. Тестом закрыты оба направления —
и потеря, и дубль.
"""
import asyncio

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.DB_PATH", tmp_path / "mailbox.db")
    import app.db as _db
    _db.init_db()
    return _db


class _FakeSession:
    loaded = False
    worktree_path = None

    def __init__(self, name, sid="sid-1"):
        self.id = sid
        self.name = name
        self.scope = "/repo"
        self.parent_name = "parent"
        self.last_task_sender = None


class _SpyManager:
    def __init__(self):
        self.sent = []

    async def ensure_loaded(self, name, scope=None):
        return _FakeSession(name)

    async def ensure_loaded_any(self, name):
        return _FakeSession(name)

    async def send(self, session_id, msg):
        self.sent.append((session_id, msg))

    def _context_warning(self, sender):
        return ""


@pytest.fixture
def spy(monkeypatch):
    m = _SpyManager()
    monkeypatch.setattr("app.routes.sessions.manager", m)
    return m


def _mailbox():
    import importlib
    try:
        return importlib.import_module("app.mailbox")
    except ModuleNotFoundError as exc:
        pytest.fail(f"модуля app.mailbox не существует: {exc}")


# --- T2: отправка без пробуждения ------------------------------------------

def test_t2_no_wake_stores_and_does_not_activate(db, spy):
    """ПЕРЕЗАМОРОЖЕН 12.08 по находке F3 ревью реализации (`codex-review-impl.md`).

    Прежняя редакция требовала класть в ящик сообщение получателю, которого НЕТ среди
    живых сессий, и никого не будить. Это тихая потеря: конца хода у такого получателя
    может не быть никогда, а `wake=False` пробуждения не создаёт по построению.
    Заменено: в ящик — только когда мы ЗНАЕМ, что получатель ЗАНЯТ и ход у него кончится.
    Случай «получателя нет среди живых» переехал в `test_t2_unknown_recipient_is_woken`
    с обратным ожиданием. Старая редакция недействительна, не восстанавливать.
    """
    from app.routes.sessions import SendRequest, send_message

    assert "wake" in SendRequest.model_fields, (
        "у SendRequest нет поля wake — режима «не будить» не существует"
    )

    class _Busy:
        name = "recipient"
        scope = "/repo"
        status = "running"

    spy.sessions = {"x": _Busy()}
    res = asyncio.run(send_message("recipient", SendRequest(
        message="факт для соседа", scope="/repo", sender="peer", wake=False,
    )))
    assert res.get("ok") is True, f"роут отверг wake=False: {res}"
    assert spy.sent == [], (
        f"wake=False всё равно разбудил получателя: {spy.sent}"
    )

    mb = _mailbox()
    pending = mb.pending("recipient", "/repo")
    assert len(pending) == 1, f"в ящике {len(pending)} сообщений, ожидалось 1"
    assert pending[0]["body"] == "факт для соседа"
    assert pending[0]["sender"] == "peer"


def test_t2_default_still_wakes(db, spy):
    """Обратная совместимость MCP↔route: живые процессы `mcp_stdio.py` поля не пошлют,
    и поведение по умолчанию обязано остаться прежним (грабля #215/#217)."""
    from app.routes.sessions import SendRequest, send_message

    asyncio.run(send_message("recipient", SendRequest(
        message="обычное", scope="/repo", sender="peer",
    )))
    assert len(spy.sent) == 1, "сообщение без флага перестало будить получателя"
    assert _mailbox().pending("recipient", "/repo") == [], (
        "обычное сообщение осело в ящике вместо доставки"
    )


# --- T3: разгрузка в конце хода, ровно один раз -----------------------------

def test_t3_pending_does_not_quench_itself(db):
    """Чтение ящика не гасит его. Гасит только явная отметка — иначе на переигранном
    входе (#158) сообщение исчезает молча."""
    mb = _mailbox()
    mb.enqueue(recipient="w", scope="/repo", sender="peer", body="один")
    first = mb.pending("w", "/repo")
    second = mb.pending("w", "/repo")
    assert len(first) == 1 and len(second) == 1, (
        "повторное чтение ящика потеряло сообщение — флаг гасится при обнаружении"
    )
    mb.mark_delivered([first[0]["id"]])
    assert mb.pending("w", "/repo") == [], "явная отметка не погасила сообщение"


class _NoHibernate:
    def schedule(self):
        return None


def _run_all(coros):
    async def _go():
        for c in coros:
            await c
    asyncio.run(_go())


class _S:
    """Двойник сессии. Явный класс, а не MagicMock: код ВЕТВИТСЯ по атрибутам,
    а мок создаёт любой запрошенный атрибут истинным и уводит ветку не туда (#220)."""

    def __init__(self, name):
        self.name = name
        self.scope = "/repo"
        self.status = "idle"
        self.is_orchestrator = False
        self._compact_ack_event = None
        self._turn_gen = 0
        self._compact_ack_gen = -1
        self.spawned = []
        self.sent = []
        self.send_raises = False
        self.logged = []
        # Реальные атрибуты хвоста `after_turn_idle_actions` (`session_turns.py:516`):
        # там УЖЕ есть выдача накопленного — `_pending_messages` + `_flush_pending()`,
        # только в памяти процесса. Ящик добавляет к этому долговечность.
        self._pending_messages = []
        self._hibernate = _NoHibernate()

    def _spawn_bg(self, coro):
        self.spawned.append(coro)

    async def _notify_scope_idle(self):
        return None

    def _log(self, kind: str, text: str) -> None:
        # Настоящая `AgentSession` это умеет; двойник обязан не расходиться с ней в
        # том, что прод-путь ЗОВЁТ. Добавлено после первого прогона T3: без метода
        # падение было про двойника, а не про поведение.
        self.logged.append((kind, text))

    async def send(self, message: str) -> None:
        if self.send_raises:
            raise RuntimeError("инъекция не удалась")
        self.sent.append(message)


def _drain(s, monkeypatch, reported):
    from app.session_turns import TurnManager
    tm = TurnManager(s)
    monkeypatch.setattr(tm, "fire_auto_report", lambda: reported.append(1))
    tm.after_turn_idle_actions(10, allow_precompact=False)
    return tm


def test_t3_drains_at_turn_end_instead_of_waking(db, monkeypatch):
    """Прод-путь, а не примитив (#219): зовётся `after_turn_idle_actions` — тот самый
    метод, который сегодня уводит сессию в idle и шлёт авто-отчёт.

    Проверяется НЕ «что-то заспавнилось» (первая редакция так и делала, и её справедливо
    отвергло ревью: любая посторонняя корутина проходила), а что накопленное ДОЕХАЛО
    до `session.send` — того самого шва, через который инжектит `_auto_continue`.
    """
    mb = _mailbox()
    mb.enqueue(recipient="w", scope="/repo", sender="peer", body="накопленное")

    s, reported = _S("w"), []
    _drain(s, monkeypatch, reported)

    assert reported == [], (
        "при непустом ящике сработал авто-отчёт — родитель разбужен зря, "
        "а накопленное так и не выдано"
    )
    _run_all(s.spawned)
    assert any("накопленное" in m for m in s.sent), (
        f"тело из ящика не доехало до session.send; отправлено: {s.sent}"
    )
    assert mb.pending("w", "/repo") == [], (
        "после успешной выдачи сообщение осталось в ящике — оно будет выдаваться вечно"
    )


def test_t3_empty_mailbox_keeps_todays_behaviour(db, monkeypatch):
    """Обратная сторона: пустой ящик ничего не меняет, авто-отчёт как сегодня."""
    s, reported = _S("w-empty"), []
    _drain(s, monkeypatch, reported)
    assert reported == [1], (
        "при пустом ящике авто-отчёт не сработал — правка задела обычный путь"
    )


def test_t3_undelivered_survives_a_dropped_continuation(db, monkeypatch):
    """Зеркальное направление грабли #158: продолжение не доехало (краш, рестарт) —
    сообщение обязано ОСТАТЬСЯ в ящике, а не считаться выданным."""
    mb = _mailbox()
    mb.enqueue(recipient="w2", scope="/repo", sender="peer", body="не потеряй")

    s = _S("w2")
    _drain(s, monkeypatch, [])
    for coro in s.spawned:
        coro.close()          # продолжение НЕ исполняется

    assert len(mb.pending("w2", "/repo")) == 1, (
        "сообщение погашено до фактической выдачи — на повторе оно исчезнет молча (#158)"
    )


def test_t3_failed_injection_keeps_message(db, monkeypatch):
    """Третье направление: выдача началась и УПАЛА. Сообщение остаётся."""
    mb = _mailbox()
    mb.enqueue(recipient="w3", scope="/repo", sender="peer", body="упавшее")

    s = _S("w3")
    s.send_raises = True
    _drain(s, monkeypatch, [])
    for coro in s.spawned:
        try:
            asyncio.run(coro)
        except Exception:
            pass

    assert len(mb.pending("w3", "/repo")) == 1, (
        "сообщение погашено, хотя инъекция упала"
    )


# --- Закрытие находок ревью реализации (codex-review-impl.md) ---------------

def test_impl1_concurrent_claim_does_not_double_deliver(db):
    """blocking 1: два одновременных конца хода читали одно и то же и слали дважды.
    Аренда берётся одной транзакцией — второй забирающий получает пусто."""
    mb = _mailbox()
    mb.enqueue(recipient="w", scope="/repo", sender="peer", body="одно")
    first = mb.claim("w", "/repo")
    second = mb.claim("w", "/repo")
    assert len(first) == 1, "первый забор не получил сообщение"
    assert second == [], "второй забор получил ТО ЖЕ сообщение — будет выдано дважды"
    assert len(mb.pending("w", "/repo")) == 1, "аренда не должна считаться выдачей"


def test_impl1_stale_lease_is_reclaimable(db):
    """Обратная сторона аренды: владелец умер — сообщение не заперто навсегда."""
    mb = _mailbox()
    mb.enqueue(recipient="w", scope="/repo", sender="peer", body="одно")
    mb.claim("w", "/repo")
    assert mb.claim("w", "/repo", lease_seconds=0.0), (
        "протухшая аренда не переоткрылась — сообщение заперто навсегда"
    )


def test_impl3_failed_delivery_returns_rows_and_plays_idle_tail(db, monkeypatch):
    """blocking 3: при сбое выдачи сессия оставалась без авто-отчёта и гибернации,
    а сообщения — без следующего конца хода, который мог бы их выдать."""
    mb = _mailbox()
    mb.enqueue(recipient="w9", scope="/repo", sender="peer", body="упавшее")

    s, reported = _S("w9"), []
    _drain(s, monkeypatch, reported)
    s.send_raises = True
    for coro in s.spawned:
        try:
            asyncio.run(coro)
        except Exception:
            pass

    assert len(mb.pending("w9", "/repo")) == 1, "сообщение пропало при сбое выдачи"
    assert mb.claim("w9", "/repo"), (
        "строка осталась под арендой мёртвой попытки — следующий ход её не увидит"
    )
    assert reported == [1], (
        "после сбоя выдачи не доигран обычный хвост простоя: авто-отчёта нет"
    )


def test_impl3_escalates_to_normal_delivery_when_continuation_fails(db, monkeypatch):
    """Возврат строк в ящик сам по себе не спасает: следующего конца хода может не
    случиться никогда. Поэтому при сбое продолжения идёт обычная доставка."""
    mb = _mailbox()
    mb.enqueue(recipient="w10", scope="/repo", sender="peer", body="эскалируемое")

    delivered = []

    class _Mgr:
        async def send(self, session_id, msg):
            delivered.append((session_id, msg))

    monkeypatch.setattr("app.deps.manager", _Mgr())
    s = _S("w10")
    s.id = "sid-w10"
    s.send_raises = True
    _drain(s, monkeypatch, [])
    for coro in s.spawned:
        try:
            asyncio.run(coro)
        except Exception:
            pass

    assert delivered, "продолжение упало, а обычная доставка не сработала"
    assert "эскалируемое" in delivered[0][1]
    assert mb.pending("w10", "/repo") == [], (
        "сообщение доставлено обычным путём, но осталось в ящике — будет выдано дважды"
    )


def test_t2_idle_recipient_is_woken_not_queued(db, spy, monkeypatch):
    """Экономия применяется только к ЗАНЯТОМУ получателю: у простаивающего может не
    быть следующего конца хода, и сообщение залегло бы навсегда."""
    from app.routes.sessions import SendRequest, send_message

    class _Idle:
        name = "recipient"
        scope = "/repo"
        status = "idle"

    spy.sessions = {"x": _Idle()}
    asyncio.run(send_message("recipient", SendRequest(
        message="важное", scope="/repo", sender="peer", wake=False,
    )))
    assert len(spy.sent) == 1, "простаивающий получатель не разбужен — сообщение залегло"
    assert _mailbox().pending("recipient", "/repo") == []


def test_t2_busy_recipient_is_queued(db, spy):
    """Обратная сторона: занятый получатель — именно тот случай, ради которого
    режим существует (замер §3.6: 23.9% ходов уже склеивают лишние сообщения даром)."""
    from app.routes.sessions import SendRequest, send_message

    class _Busy:
        name = "recipient"
        scope = "/repo"
        status = "running"

    spy.sessions = {"x": _Busy()}
    asyncio.run(send_message("recipient", SendRequest(
        message="подождёт", scope="/repo", sender="peer", wake=False,
    )))
    assert spy.sent == [], "занятый получатель разбужен — экономии нет"
    assert len(_mailbox().pending("recipient", "/repo")) == 1


def test_impl_cancelled_delivery_releases_the_claim(db, monkeypatch):
    """`asyncio.CancelledError` не наследует `Exception` — без отдельной ветки отмена
    оставляла бы строки под арендой до её протухания (находка раунда 3)."""
    mb = _mailbox()
    mb.enqueue(recipient="w11", scope="/repo", sender="peer", body="отменённое")

    s = _S("w11")

    async def _cancel(_msg):
        raise asyncio.CancelledError()

    s.send = _cancel
    _drain(s, monkeypatch, [])
    for coro in s.spawned:
        try:
            asyncio.run(coro)
        except asyncio.CancelledError:
            pass

    assert mb.claim("w11", "/repo"), (
        "после отмены строка осталась под арендой — до её протухания никто не заберёт"
    )


def test_t2_unknown_recipient_is_woken(db, spy):
    """Замена снятой части старого оракула (F3): получателя нет среди живых сессий →
    конца хода у него не будет, значит ящик = тихая потеря. Будим, как раньше."""
    from app.routes.sessions import SendRequest, send_message

    asyncio.run(send_message("recipient", SendRequest(
        message="важное", scope="/repo", sender="peer", wake=False,
    )))
    assert len(spy.sent) == 1, (
        "неизвестный получатель не разбужен — сообщение залегло в ящике навсегда"
    )
    assert _mailbox().pending("recipient", "/repo") == []
