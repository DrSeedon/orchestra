"""#231 T1/T6 — включение барьера и веер через редьюсера.

Красные по замыслу до реализации; оракул принадлежит дорогой стороне (#210).
Вторая редакция: первая была отвергнута ревью плана (`codex-review-plan.md`) —
тест «дедлайн переопределяется» проходил при реализации, которая аргумент игнорирует,
а T6 был помечен `oracle: none` при существующей детерминированной проверке.

Барьер (`app/fan_barrier.py`) написан и смержен в #219, но `open_fan()` не зовёт ни один
прод-путь. Здесь проверяется ВХОД и адресат релиза, а не сам барьер: его поведение уже
закрыто 18 тестами в `tests/test_fan_barrier.py`.

Дедлайн проверяется числом, потому что это НЕ «разумное значение», а точка на измеренной
кривой (`docs/tasks/231/research.md` §3.7): 5 мин → 2.06% расхода платформы, 30 мин → 4.35%,
60 мин → 4.94%.
"""
import asyncio

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.DB_PATH", tmp_path / "fan-enable.db")
    import app.db as _db
    _db.init_db()
    return _db


class _FakeSession:
    loaded = False
    worktree_path = None

    def __init__(self, name):
        self.id = f"sid-{name}"
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


def _report(child, message="report"):
    from app.routes.sessions import SendRequest, send_message
    return asyncio.run(send_message("parent", SendRequest(
        message=message, scope="/repo", sender=child, message_kind="done",
    )))


# --- T1: вход в барьер ------------------------------------------------------

def test_t1_open_fan_route_exists_and_buffers_children(db):
    import app.fan_barrier as fb
    from app.routes import sessions as rs

    assert hasattr(rs, "DEFAULT_FAN_DEADLINE_SECONDS"), (
        "нет константы дедлайна: значение выдумает исполнитель"
    )
    assert rs.DEFAULT_FAN_DEADLINE_SECONDS == 1800.0, (
        f"дедлайн по умолчанию {rs.DEFAULT_FAN_DEADLINE_SECONDS}, ожидалось 1800.0 "
        "(точка 30 мин на кривой research.md §3.7)"
    )
    assert hasattr(rs, "open_fan"), "роут open_fan не заведён"
    assert hasattr(rs, "OpenFanRequest"), "нет модели запроса OpenFanRequest"

    res = asyncio.run(rs.open_fan(rs.OpenFanRequest(
        fan_id="F231", parent_name="parent", scope="/repo", children=["c1", "c2"],
    )))
    assert res.get("ok") is True, f"роут не принял объявление веера: {res}"
    assert fb.should_buffer("c1") and fb.should_buffer("c2"), "вход не сработал"
    assert not fb.should_buffer("посторонний"), "барьер накрыл чужого агента"


def test_t1_caller_deadline_is_actually_used(db):
    """Реализация, игнорирующая аргумент и всегда берущая 1800, обязана падать.

    Наблюдаем не «веер создан», а СРОК: веер с нулевым дедлайном обязан попасть в
    `release_expired()` немедленно, а веер с дефолтным — не попасть.
    """
    import app.fan_barrier as fb
    from app.routes import sessions as rs

    asyncio.run(rs.open_fan(rs.OpenFanRequest(
        fan_id="F-now", parent_name="parent", scope="/repo",
        children=["x1"], deadline_seconds=0.0,
    )))
    asyncio.run(rs.open_fan(rs.OpenFanRequest(
        fan_id="F-default", parent_name="parent", scope="/repo", children=["x2"],
    )))

    expired = fb.release_expired()
    assert "F-now" in expired, (
        "веер с deadline_seconds=0.0 не истёк — аргумент вызывающего проигнорирован"
    )
    assert "F-default" not in expired, (
        "веер с дефолтным дедлайном истёк сразу — дефолт не 1800 секунд"
    )


# --- T6: веер через редьюсера ----------------------------------------------

def test_t6_children_release_to_reducer_not_parent(db, spy):
    """Дети отчитываются редьюсеру; родителя релиз барьера НЕ будит."""
    from app.routes import sessions as rs

    asyncio.run(rs.open_fan(rs.OpenFanRequest(
        fan_id="FR", parent_name="parent", scope="/repo",
        children=["c1", "c2"], reducer="R",
    )))
    _report("c1", "нашёл A")
    _report("c2", "нашёл B")

    assert len(spy.sent) == 1, (
        f"пробуждений при релизе {len(spy.sent)}, ожидалось ровно одно"
    )
    (sid, _text), = spy.sent
    assert sid == "sid-R", (
        f"релиз разбудил {sid}, а должен был разбудить редьюсера sid-R — "
        "иначе дорогой участник платит за сборку"
    )


def test_t6_parent_payload_survives_a_silent_reducer(db, spy):
    """Полнота сводки обеспечивается КОДОМ, а не послушанием редьюсера.

    Ревью плана (blocking 8) справедливо разнесло исходный довод «оба направления
    отказа доброкачественны»: редьюсер, забывший правило «не выбирай», именно что
    сокращает — то есть теряет отчёты детей. Поэтому манифест приклеивается кодом,
    и проверяется случай, когда собственный текст редьюсера ПУСТ.
    """
    from app.routes import sessions as rs
    from app.routes.sessions import SendRequest, send_message

    asyncio.run(rs.open_fan(rs.OpenFanRequest(
        fan_id="FR2", parent_name="parent", scope="/repo",
        children=["c1", "c2"], reducer="R",
    )))
    _report("c1", "нашёл A")
    _report("c2", "нашёл B")
    spy.sent.clear()

    asyncio.run(send_message("parent", SendRequest(
        message="", scope="/repo", sender="R",
    )))

    assert len(spy.sent) == 1, f"родитель разбужен {len(spy.sent)} раз, ожидался один"
    (sid, text), = spy.sent
    assert sid == "sid-parent", (
        f"полная сводка ушла в {sid}, а не родителю — доставка не туда"
    )
    for marker in ("c1=done", "c2=done"):
        assert marker in text, (
            f"в сводке нет `{marker}` при молчащем редьюсере — "
            "полнота держится на промпте, а он не принуждается"
        )


def test_t6_explicit_report_with_pending_mailbox_does_not_release(db, spy):
    """Контракт T3↔T1 на ВТОРОМ терминальном пути (находка раунда 2, blocking 3).

    Порядок «разгрузка ящика до `fire_auto_report`» закрывает только молчаливый путь.
    Ребёнок может отчитаться ЯВНЫМ `send_message`, имея невыданный вход в ящике, —
    и тогда терминальное состояние фиксируется по недоработавшему ребёнку.
    Веер здесь из ОДНОГО ребёнка: один отчёт обязан был бы его отпустить.
    """
    import app.fan_barrier as fb
    from app.routes import sessions as rs

    mb = __import__("importlib").import_module("app.mailbox")
    asyncio.run(rs.open_fan(rs.OpenFanRequest(
        fan_id="F-solo", parent_name="parent", scope="/repo",
        children=["c1"], reducer="R",
    )))
    mb.enqueue(recipient="c1", scope="/repo", sender="peer", body="ещё не прочитано")

    _report("c1", "готово")

    assert not fb.is_released("F-solo"), (
        "веер отпущен, хотя у ребёнка остался невыданный вход — "
        "сводка собрана по недоработавшему ребёнку"
    )
    assert spy.sent == [], f"кого-то разбудили раньше времени: {spy.sent}"


def test_t6_manifest_is_glued_exactly_once(db, spy):
    """Найдено пре-мортемом, а не оракулом: признак «веер отпущен» истинен навсегда,
    поэтому наивная склейка приклеивала бы манифест к КАЖДОМУ последующему сообщению
    редьюсера. Сводка отдаётся ровно один раз."""
    from app.routes import sessions as rs
    from app.routes.sessions import SendRequest, send_message

    asyncio.run(rs.open_fan(rs.OpenFanRequest(
        fan_id="FR3", parent_name="parent", scope="/repo",
        children=["c1"], reducer="R",
    )))
    _report("c1", "нашёл A")
    spy.sent.clear()

    asyncio.run(send_message("parent", SendRequest(message="сводка", scope="/repo", sender="R")))
    asyncio.run(send_message("parent", SendRequest(message="а теперь про другое", scope="/repo", sender="R")))

    first, second = spy.sent
    assert "c1=done" in first[1], "первое сообщение редьюсера пришло без манифеста"
    assert "c1=done" not in second[1], (
        "манифест приклеен ко ВТОРОМУ сообщению — он будет ездить в контекст родителя вечно"
    )


# --- Молчаливый путь: находки 4 и 5 ревью реализации ------------------------

class _SilentChild:
    """Двойник ребёнка, закончившего ход МОЛЧА (`send_message` не звал)."""
    is_orchestrator = False
    _did_report = False
    _manually_interrupted = False
    _pending_messages = False
    _compacting = False
    _last_turn_ok = True
    _turn_logs = ["did work"]
    _last_stop_reason = "end_turn"
    _auto_report_task = None
    parent_name = "parent"
    last_task_sender = "parent"

    def __init__(self, name, scope="/repo", logs=None, turn_ok=True):
        self.name = name
        self.scope = scope
        self._turn_logs = ["did work"] if logs is None else logs
        self._last_turn_ok = turn_ok
        self._last_text_output = self._turn_logs[-1] if self._turn_logs else None

    async def on_idle(self, *a):
        return None


def test_impl4_silent_child_with_pending_mailbox_does_not_release(db):
    """blocking 4: явный путь проверял осушение, молчаливый — нет, и веер отпускался
    по ребёнку, не видевшему своего входа."""
    import app.fan_barrier as fb
    from app.routes import sessions as rs
    from app.session_turns import TurnManager

    mb = __import__("importlib").import_module("app.mailbox")
    asyncio.run(rs.open_fan(rs.OpenFanRequest(
        fan_id="F-silent", parent_name="parent", scope="/repo",
        children=["c9"], reducer="R",
    )))
    mb.enqueue(recipient="c9", scope="/repo", sender="peer", body="не прочитано")

    TurnManager(_SilentChild("c9")).fire_auto_report()
    assert not fb.is_released("F-silent"), (
        "молчаливое завершение отпустило веер при невыданном входе"
    )


def test_impl5_silent_completion_wakes_reducer_not_parent(db, monkeypatch):
    """blocking 5: адресат релиза зависел от того, отчитался ребёнок явно или молча."""
    from app.routes import sessions as rs
    from app.session_turns import TurnManager

    asyncio.run(rs.open_fan(rs.OpenFanRequest(
        fan_id="F-silent2", parent_name="parent", scope="/repo",
        children=["c8"], reducer="R",
    )))
    m = _SpyManager()
    monkeypatch.setattr("app.deps.manager", m)

    child = _SilentChild("c8")

    async def _go():
        # `fire_auto_report` создаёт задачу — значит должен идти внутри живого цикла
        TurnManager(child).fire_auto_report()
        if child._auto_report_task is not None:
            await child._auto_report_task

    asyncio.run(_go())

    assert m.sent, "релиз не доставлен никому"
    (sid, _), = m.sent
    assert sid == "sid-R", (
        f"молчаливый ребёнок разбудил {sid} вместо редьюсера — дорогой участник "
        "платит за сборку в зависимости от того, как ребёнок закончил ход"
    )


def test_impl5_exact_silent_marker_completes_fan_without_manifest_noise(db, monkeypatch):
    import app.fan_barrier as fb
    from app.routes import sessions as rs
    from app.session_turns import TurnManager

    asyncio.run(rs.open_fan(rs.OpenFanRequest(
        fan_id="F-silent-marker", parent_name="parent", scope="/repo",
        children=["c-marker"], reducer="R",
    )))
    m = _SpyManager()
    monkeypatch.setattr("app.deps.manager", m)
    child = _SilentChild("c-marker", logs=["[[ORCHESTRA:SILENT_TURN]]"])

    async def _go():
        TurnManager(child).fire_auto_report()
        if child._auto_report_task is not None:
            await child._auto_report_task

    asyncio.run(_go())

    manifest = fb.manifest("F-silent-marker")
    assert manifest["complete"] is True
    assert manifest["members"][0]["state"] == "done"
    assert len(m.sent) == 1 and m.sent[0][0] == "sid-R"
    assert "ORCHESTRA:SILENT_TURN" not in m.sent[0][1]


def test_impl6_manifest_survives_a_failed_delivery(db, monkeypatch):
    """blocking 6: пометка «сводка отдана» ставилась ДО доставки, и любой сбой
    уничтожал манифест навсегда. Это та же грабля #158, что и в ящике."""
    import app.fan_barrier as fb
    from app.routes import sessions as rs
    from app.routes.sessions import SendRequest, send_message

    asyncio.run(rs.open_fan(rs.OpenFanRequest(
        fan_id="F-lost", parent_name="parent", scope="/repo",
        children=["c7"], reducer="R",
    )))

    class _FailingManager(_SpyManager):
        async def send(self, session_id, msg):
            raise RuntimeError("доставка упала")

    monkeypatch.setattr("app.routes.sessions.manager", _SpyManager())
    _report("c7", "готово")
    monkeypatch.setattr("app.routes.sessions.manager", _FailingManager())
    try:
        asyncio.run(send_message("parent", SendRequest(
            message="сводка", scope="/repo", sender="R")))
    except Exception:
        pass

    assert fb.peek_summary("R", "/repo") == "F-lost", (
        "сводка помечена отданной, хотя доставка упала — манифест потерян навсегда"
    )
