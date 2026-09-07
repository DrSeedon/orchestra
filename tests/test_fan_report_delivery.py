"""#275 — веер обязан сохранить ТЕКСТ отчёта ребёнка, не только токен done.

Приёмка #231 («N детей → 1 пробуждение») зелёная и при доставленном тексте, и при
потерянном: она не смотрит, куда делся `req.message`. Этот оракул краснеет на
сегодняшнем коде именно из-за потери текста и идёт через прод-пути, не через
`record_terminal(..., report_path=...)` напрямую.
"""
import asyncio
from pathlib import Path

import pytest


EXPLICIT_MARKER = "ORACLE275-EXPLICIT-UNIQUE"
SILENT_MARKER = "ORACLE275-SILENT-TURN-LOG"
LONG_BODY = EXPLICIT_MARKER + ("Q" * 4000)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.DB_PATH", tmp_path / "fan-report.db")
    import app.db as _db
    _db.init_db()
    return _db


class _FakeSession:
    loaded = False
    worktree_path = None

    def __init__(self, name, sid=None):
        self.id = sid or f"sid-{name}"
        self.name = name
        self.scope = "/repo"
        self.parent_name = "parent"
        self.last_task_sender = None


class _SpyManager:
    def __init__(self):
        self.sent = []
        self.provenances = []

    async def ensure_loaded(self, name, scope=None):
        return _FakeSession(name)

    async def ensure_loaded_any(self, name):
        return _FakeSession(name)

    async def send(self, session_id, msg, *, provenance=None, **kwargs):
        # `provenance` — обязательный параметр боевого `manager.send` (#433). Двойник
        # без него ронял доставку уже ПОСЛЕ барьера: `send_message failed for parent:
        # _SpyManager.send() got an unexpected keyword argument 'provenance'`.
        self.sent.append((session_id, msg))
        self.provenances.append(provenance)

    def _context_warning(self, sender):
        return ""


@pytest.fixture
def spy(monkeypatch, db):
    m = _SpyManager()
    monkeypatch.setattr("app.routes.sessions.manager", m)
    monkeypatch.setattr("app.deps.manager", m)
    # Роут `send_message` при непустом `sender` требует ДОЛГОВЕЧНОЙ привязки сессии
    # (`app/routes/sessions.py:969-971`) и иначе отвечает
    # `409 {"error":"durable session binding is required"}`. Двойник сессии строки в БД
    # не создаёт, поэтому оба теста файла падали ещё до барьера: пробуждений 0,
    # `report_path` пустой. Гейт не обходим — создаём настоящие строки, как в проде.
    import app.db as db_module
    from datetime import datetime, timezone
    for name in ("parent", "c1", "c2"):
        db_module.save_session({
            "id": f"sid-{name}", "name": name, "scope": "/repo", "cwd": "/tmp",
            "model": "claude-sonnet-5[1m]", "system_prompt": "test", "status": "idle",
            "session_id": None, "cost_usd": 0.0, "worktree_path": "/tmp",
            "branch": "b", "is_orchestrator": False, "color": "#818cf8",
            "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
            "parent_name": "" if name == "parent" else "parent",
            # У получателя обязан быть `task_id`: сообщение С ОТПРАВИТЕЛЕМ безадресному
            # агенту роут считает НАЗНАЧЕНИЕМ задачи и пускает только его родителя
            # (`app/routes/sessions.py:972-976`, `403 only the durable parent may assign
            # a task`). Родитель веера в проде ведёт свою задачу, поэтому это не обход
            # гейта, а недостающая часть настоящего состояния.
            "task_id": "275",
        })
    return m


def _open_fan(children):
    import app.fan_barrier as fb
    fb.open_fan(
        fan_id="F275",
        parent_name="parent",
        scope="/repo",
        children=list(children),
        deadline_seconds=3600,
    )
    return fb


def _send(sender, message):
    from app.routes.sessions import SendRequest, send_message
    return asyncio.run(send_message("parent", SendRequest(
        message=message, scope="/repo", sender=sender, message_kind="done",
    )))


class _SilentChild:
    is_orchestrator = False
    _did_report = False
    _manually_interrupted = False
    _pending_messages = False
    _compacting = False
    _last_turn_ok = True
    _last_stop_reason = "end_turn"
    _auto_report_task = None
    parent_name = "parent"
    last_task_sender = "parent"

    def __init__(self, name, turn_logs):
        self.name = name
        self.scope = "/repo"
        self._turn_logs = list(turn_logs)
        # Молчаливый путь берёт текст ИМЕННО отсюда (`app/session_turns.py:277`,
        # `final_text = getattr(s, "_last_text_output", None)`), а не из `_turn_logs`.
        # Двойник, задававший только `_turn_logs`, оставлял `summary=None`, и манифест
        # получался «ОТЧЁТА НЕТ» — то есть тест мерил собственную неполноту.
        self._last_text_output = turn_logs[-1] if turn_logs else None

    async def on_idle(self, *a):
        return None


def _silent(name, turn_logs):
    from app.session_turns import TurnManager
    child = _SilentChild(name, turn_logs)

    async def _go():
        TurnManager(child).fire_auto_report()
        if child._auto_report_task is not None:
            await child._auto_report_task

    asyncio.run(_go())
    return child


def _member(fb, child):
    return next(m for m in fb.manifest("F275")["members"] if m["child"] == child)


def test_explicit_send_message_keeps_child_text_reachable_via_manifest(db, spy):
    """Прод-роут send_message. Текст, который ребёнок передал, обязан быть
    доступен родителю по пути из манифеста. Не вклейкой в пробуждение."""
    fb = _open_fan(["c1", "c2"])
    _send("c1", LONG_BODY)
    _send("c2", "ok")

    assert len(spy.sent) == 1, f"пробуждений {len(spy.sent)}, ждали одно"
    (_sid, wake), = spy.sent
    assert LONG_BODY not in wake, "длинный отчёт вклеен в пробуждение родителя"

    path = _member(fb, "c1")["report_path"]
    assert path, (
        "явный send_message не записал report_path — родитель видит path=- "
        "и текст потерян (дыра #275)"
    )
    stored = Path(path).read_text(encoding="utf-8")
    assert EXPLICIT_MARKER in stored, (
        f"файл манифеста не содержит текст ребёнка: path={path!r}"
    )
    assert LONG_BODY in stored


def test_silent_turn_manifest_is_as_rich_as_explicit_and_keeps_text(db, spy):
    """Молчаливый путь не беднее и не богаче явного: те же поля, свой файл."""
    fb = _open_fan(["c1", "c2"])
    _send("c1", EXPLICIT_MARKER)
    _silent("c2", [SILENT_MARKER])

    explicit = _member(fb, "c1")
    silent = _member(fb, "c2")
    assert set(explicit) == set(silent), (
        f"разный набор полей манифеста: explicit={sorted(explicit)} "
        f"silent={sorted(silent)}"
    )
    assert explicit["report_path"], "явный путь оставил report_path пустым"
    assert silent["report_path"], (
        "молчаливый путь оставил report_path пустым — манифест беднее явного"
    )
    assert explicit["report_path"] != silent["report_path"]
    assert EXPLICIT_MARKER in Path(explicit["report_path"]).read_text(encoding="utf-8")
    assert SILENT_MARKER in Path(silent["report_path"]).read_text(encoding="utf-8")
    assert len(spy.sent) == 1
    (_sid, wake), = spy.sent
    assert "path=-" not in wake
