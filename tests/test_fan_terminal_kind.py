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
