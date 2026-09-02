"""#276 — барьер снимается по завершению работы, не по факту send_message.

Проверка «веер закрылся» оракулом не является: при двух детях один вопрос
сегодня оставляет веер открытым (второй ещё pending) — зелёная в обе стороны.
Смотрим СОСТОЯНИЕ ребёнка и пару нетерминальных сообщений, которые сегодня
ложно закрывают веер целиком.
"""
import asyncio

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.DB_PATH", tmp_path / "fan-term.db")
    import app.db as _db
    _db.init_db()
    from tests.test_message_delivery_receipts_380 import _session_record
    _db.save_session(_session_record(
        session_id="sid-parent", name="parent", scope="/repo",
        task_id="fan-terminal", branch="task-fan/parent",
    ))
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

    async def send(self, session_id, msg, *, provenance):
        assert provenance.senders
        self.sent.append((session_id, msg))

    def _context_warning(self, sender):
        return ""


@pytest.fixture
def spy(monkeypatch):
    m = _SpyManager()
    monkeypatch.setattr("app.routes.sessions.manager", m)
    monkeypatch.setattr("app.deps.manager", m)
    return m


def _open(children=("c1", "c2")):
    import app.fan_barrier as fb
    fb.open_fan(
        fan_id="F276",
        parent_name="parent",
        scope="/repo",
        children=list(children),
        deadline_seconds=3600,
    )
    return fb


def _send(sender, message, kind=None):
    from app.routes.sessions import SendRequest, send_message
    payload = {"message": message, "scope": "/repo", "sender": sender}
    if kind is not None:
        payload["message_kind"] = kind
    return asyncio.run(send_message("parent", SendRequest(**payload)))


def _state(fb, child):
    return next(m["state"] for m in fb.manifest("F276")["members"] if m["child"] == child)


class _Child:
    is_orchestrator = False
    _manually_interrupted = False
    _pending_messages = False
    _compacting = False
    _last_turn_ok = True
    _last_stop_reason = "end_turn"
    _auto_report_task = None
    parent_name = "parent"
    last_task_sender = "parent"

    def __init__(self, name, *, did_report, turn_logs):
        self.name = name
        self.scope = "/repo"
        self._did_report = did_report
        self._turn_logs = list(turn_logs)

    async def on_idle(self, *a):
        return None


def _end_turn(name, *, did_report, turn_logs=("worked",)):
    from app.session_turns import TurnManager
    child = _Child(name, did_report=did_report, turn_logs=turn_logs)

    async def _go():
        TurnManager(child).fire_auto_report()
        if child._auto_report_task is not None:
            await child._auto_report_task

    asyncio.run(_go())
    return child


def test_question_does_not_mark_child_terminal(db, spy):
    """Ребёнок спросил и продолжает работать — сегодня его уже ставят done."""
    fb = _open()
    _send("c1", "Жду ок на хунк routes/sessions.py:749-751")
    assert _state(fb, "c1") is None, (
        "вопрос оркестратору пометил ребёнка done — барьер тратится на заблокированного"
    )
    assert fb.is_released("F276") is False


def test_two_nonterminal_sends_do_not_release_the_fan(db, spy):
    """Инцидент -8cee08b4: вопрос + SILENT_TURN закрыли веер на бегущих детях."""
    fb = _open()
    _send("c1", "Жду ок")
    _send("c2", "[[ORCHESTRA:SILENT_TURN]]")
    assert _state(fb, "c1") is None
    assert _state(fb, "c2") is None
    assert fb.is_released("F276") is False, (
        "два нетерминальных send_message сняли барьер — проверка «веер закрылся» "
        "сегодня зелёная как раз на этом дефекте"
    )


def test_done_word_in_body_is_not_a_terminal_signal(db, spy):
    """Признак — тип сообщения, не угадывание слова DONE в тексте."""
    fb = _open()
    _send("c1", "DONE #276: ещё работаю, это не завершение")
    assert _state(fb, "c1") is None, (
        "терминальность выведена из текста сообщения — вторая копия правды"
    )


def test_turn_end_after_a_question_is_still_terminal(db, spy):
    """Молчаливый конец хода — единственный сигнал, если send_message уже был."""
    fb = _open(("c1",))
    _send("c1", "покажи RED, дальше чиню")
    assert _state(fb, "c1") is None
    _end_turn("c1", did_report=True, turn_logs=["чиню дальше"])
    assert _state(fb, "c1") == "done"
    assert fb.is_released("F276") is True


def test_is_terminal_report_is_kind_only():
    import app.fan_barrier as fb
    assert fb.is_terminal_report("done") is True
    assert fb.is_terminal_report("failed") is True
    assert fb.is_terminal_report(None) is False
    assert fb.is_terminal_report("progress") is False
    assert fb.is_terminal_report("[[ORCHESTRA:SILENT_TURN]]") is False


def test_explicit_done_kind_still_releases(db, spy):
    fb = _open()
    _send("c1", "нашёл A", kind="done")
    assert _state(fb, "c1") == "done"
    assert fb.is_released("F276") is False
    _send("c2", "нашёл B", kind="done")
    assert fb.is_released("F276") is True
    assert len(spy.sent) == 1


def test_tool_report_then_turn_end_is_one_terminal_and_one_wake(db, spy, monkeypatch):
    """#276 доделка: тул + конец хода ≠ два терминала и два пробуждения.

    Сняли ранний return по `_did_report` внутри открытого веера. «Веер закрылся»
    зелёный и при одном, и при двух пробуждениях — смотрим счётчики.
    """
    import app.fan_barrier as fb_mod

    fb = _open(("c1",))
    accepted = []
    real = fb_mod.record_terminal

    def counted(*args, **kwargs):
        ok = real(*args, **kwargs)
        accepted.append(ok)
        return ok

    monkeypatch.setattr(fb_mod, "record_terminal", counted)

    _send("c1", "итоговый отчёт", kind="done")
    idle = []
    child = _Child("c1", did_report=True, turn_logs=["итог"])
    orig_idle = child.on_idle

    async def tracked_idle(*a):
        idle.append(a)
        return await orig_idle(*a)

    child.on_idle = tracked_idle

    async def _go():
        from app.session_turns import TurnManager
        TurnManager(child).fire_auto_report()
        if child._auto_report_task is not None:
            await child._auto_report_task

    asyncio.run(_go())

    assert accepted.count(True) == 1, (
        f"терминалов {accepted.count(True)} из {accepted!r}, ждали ровно один"
    )
    assert len(spy.sent) == 1, (
        f"пробуждений родителя {len(spy.sent)}, ждали одно"
    )
    assert idle == [], (
        f"после тула ещё и on_idle={idle!r} — второе пробуждение мимо барьера"
    )
