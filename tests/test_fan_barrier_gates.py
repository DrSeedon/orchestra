"""#219 T1b — проводка барьера в рантайм: ДВА гейта и девять неприкосновенных путей.

Красные по замыслу до реализации. Оракул принадлежит дорогой стороне (#210).

Почему гейта именно два, а не один: `grep -rn "manager.send(" app/` даёт 11 вызовов
(грабля #154 — там же было 11). Сообщением РЕБЁНКА родителя будят только два:
`routes/sessions.py` (явный `send_message`) и `session_turns.fire_auto_report`
(молчаливое завершение хода, `send_message` не проходит вовсе).
Остальные девять гейтить ЗАПРЕЩЕНО: среди них доставка `[Background job FAILED]`
и живой ввод человека из Telegram.
"""
import asyncio
import pytest


@pytest.fixture
def fanned(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.DB_PATH", tmp_path / "gates.db")
    import app.db as _db
    _db.init_db()
    import app.fan_barrier as fb
    fb.open_fan(fan_id="F", parent_name="parent", scope="/repo",
                children=["c1", "c2"], deadline_seconds=3600)
    return fb


class _FakeSession:
    loaded = False
    worktree_path = None

    def __init__(self, name, sid="sid-parent"):
        self.id = sid
        self.name = name
        self.scope = "/repo"
        self.parent_name = "parent"
        self.last_task_sender = None


class _SpyManager:
    """Считает пробуждения. Ровно то, за что платят $0.87 (#219) и
    $0.900241/$0.756113 (#223, независимая репликация)."""
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


def _send(sender, message="report", kind=None):
    from app.routes.sessions import send_message, SendRequest
    payload = {"message": message, "scope": "/repo", "sender": sender}
    if kind is not None:
        payload["message_kind"] = kind
    return asyncio.run(send_message("parent", SendRequest(**payload)))


# --- Гейт 1: явный send_message -------------------------------------------

def test_child_report_does_not_wake_parent_while_barrier_closed(fanned, spy):
    _send("c1")
    assert spy.sent == [], "родитель разбужен первым же ребёнком — барьера нет"


def test_parent_woken_exactly_once_when_last_child_reports(fanned, spy):
    _send("c1")
    _send("c2")
    assert len(spy.sent) == 1, f"пробуждений {len(spy.sent)}, ожидалось ровно одно"


def test_release_wake_carries_manifest_not_report_bodies(fanned, spy):
    body = "y" * 4000
    _send("c1", message=body)
    _send("c2", message=body)
    (_sid, text), = spy.sent
    assert body not in text, "тело детского отчёта уехало в контекст родителя"
    assert "c1" in text and "c2" in text


@pytest.mark.parametrize("kind", ["out_of_scope", "false_premise", "blocked"])
def test_exception_classes_wake_parent_immediately(fanned, spy, kind):
    _send("c1", kind=kind)
    assert len(spy.sent) == 1, f"класс {kind} обязан пройти мимо барьера"


def test_send_payload_without_message_kind_still_works(fanned, spy):
    """AC-10, обратная совместимость MCP: старые процессы `mcp_stdio.py` живут
    до реконнекта и нового поля не пошлют. Новый ОБЯЗАТЕЛЬНЫЙ аргумент сломал бы
    всех подключённых агентов (грабля #215/#217)."""
    res = _send("c1")
    assert res.get("ok") is True


# --- Гейт 2: молчаливое завершение хода ------------------------------------

def test_silent_child_turn_does_not_wake_parent_while_barrier_closed(fanned):
    """`fire_auto_report` — ОТДЕЛЬНЫЙ путь, через `send_message` он не идёт.
    Без гейта здесь молчаливо закончивший ребёнок будит родителя мимо барьера,
    а это типичный случай, а не редкий."""
    from app.session_turns import TurnManager
    calls = []

    class _S:
        is_orchestrator = False
        _did_report = False
        _manually_interrupted = False
        _pending_messages = False
        _compacting = False
        _last_turn_ok = True
        _turn_logs = ["did work"]
        _last_stop_reason = "end_turn"
        _auto_report_task = None
        name = "c1"
        scope = "/repo"
        parent_name = "parent"
        last_task_sender = "parent"

        async def on_idle(self, *a):
            calls.append(a)

    s = _S()
    TurnManager(s).fire_auto_report()
    assert s._auto_report_task is None, "авто-отчёт запущен при закрытом барьере"
    assert calls == []


# --- AC-2: производитель токена `killed` -----------------------------------

def test_kill_path_produces_killed_token(fanned, monkeypatch):
    """AC-2 проверяется через РЕАЛЬНЫЙ путь удаления, а не вызовом примитива.

    Первая редакция этого теста звала `fb.on_child_killed` напрямую и была
    зелёной, ничего не доказывая: она проверяла примитив, а не проводку.
    Гейт на `fire_auto_report` породить `killed` не может — тот выходит раньше
    `on_idle` для `_manually_interrupted` (`session_turns.py:266`).
    """
    import app.fan_barrier as fb
    from app.manager import SessionManager

    fb.record_terminal("c1", "done")

    mgr = SessionManager.__new__(SessionManager)
    mgr.sessions = {"sid-c2": _FakeSession("c2", "sid-c2")}

    class _NoJobs:
        async def cancel_by_session(self, _sid):
            return None

    monkeypatch.setattr("app.bg_jobs.bg_manager", _NoJobs(), raising=False)
    monkeypatch.setattr("app.manager.archive_session", lambda _sid: None)
    asyncio.run(SessionManager.remove(mgr, "sid-c2"))

    m = fb.manifest("F")
    assert {x["child"]: x["state"] for x in m["members"]}["c2"] == "killed", (
        "реальный путь удаления не породил терминальный токен"
    )
    assert m["complete"] is True


# --- AC-9: девять путей, которые барьер трогать НЕ ДОЛЖЕН ------------------

def test_message_without_sender_is_never_buffered(fanned, spy):
    """Вход без отправителя-ребёнка — это человек из Telegram, `limit_wake`,
    `notify`, CI. Барьер, повешенный на общий лист `manager.send`, съел бы их."""
    _send(None)
    assert len(spy.sent) == 1, "сообщение без ребёнка-отправителя попало под барьер"


def test_background_job_failure_reaches_a_buffered_child(fanned):
    """`bg_jobs` доставляет `[Background job FAILED]` САМОМУ ребёнку, а не
    родителю, и обязан доходить при закрытом барьере."""
    import app.fan_barrier as fb
    assert fb.should_buffer("c1") is True
    assert fb.should_buffer("c1", message_kind="blocked") is False
    # доставка ребёнку идёт мимо should_buffer вообще: барьер судит только
    # сообщения, адресованные РОДИТЕЛЮ от его ребёнка
    assert fb.should_buffer("parent") is False
