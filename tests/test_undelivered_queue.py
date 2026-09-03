"""#50 — очередь фактов о недоставке доезжает в КОНТЕКСТ агента.

Приёмка жёсткая: проверяется payload, ушедший в `backend.send`, а не строка в БД.
Гашение только по факту доставки — первым идёт тест на управляемый отказ бэкенда.
"""
import uuid
from datetime import datetime, timezone
import pytest
import pytest_asyncio

from app.events import MessageProvenance


USER_PROVENANCE = MessageProvenance(origin="user", senders=("user",))


@pytest.fixture
def db(tmp_path, monkeypatch):
    import app.db as dbmod

    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "t.db")
    dbmod.init_db()
    return dbmod


@pytest.fixture
def session_id(db):
    sid = str(uuid.uuid4())
    db.save_session({
        "id": sid, "name": "worker", "scope": "/s", "cwd": "/s",
        "model": "claude-sonnet-5[1m]", "system_prompt": "", "status": "idle",
        "session_id": None, "cost_usd": 0.0, "worktree_path": "", "branch": "",
        "base_branch": "main", "is_orchestrator": False, "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
        "task_id": "", "needs_switch": 0,
    })
    return sid


class TestQueue:
    def test_same_event_twice_is_one_row(self, db, session_id):
        assert db.enqueue_fact(session_id, "bug:42", "текст") is True
        assert db.enqueue_fact(session_id, "bug:42", "текст ещё раз") is False
        assert len(db.peek_facts(session_id)["facts"]) == 1

    def test_overflow_is_collapsed_visibly_not_dropped(self, db, session_id):
        for i in range(25):
            db.enqueue_fact(session_id, f"k{i}", f"событие {i}")
        got = db.peek_facts(session_id)
        assert len(got["facts"]) == 20
        assert got["collapsed"] == 5
        # гасить надо ВСЕ, включая свёрнутые: их существование агенту сообщено
        assert len(got["keys"]) == 25

    def test_ack_removes_only_given_keys(self, db, session_id):
        db.enqueue_fact(session_id, "a", "раз")
        db.enqueue_fact(session_id, "b", "два")
        assert db.ack_facts(session_id, ["a"]) == 1
        left = db.peek_facts(session_id)
        assert [f["text"] for f in left["facts"]] == ["два"]

    def test_queue_survives_reopening_the_database(self, db, session_id, tmp_path):
        import sqlite3

        db.enqueue_fact(session_id, "durable", "переживи рестарт")
        # отдельное соединение = не память процесса
        raw = sqlite3.connect(tmp_path / "t.db")
        rows = raw.execute(
            "SELECT text FROM undelivered_facts WHERE session_id=?", (session_id,)
        ).fetchall()
        raw.close()
        assert rows == [("переживи рестарт",)]


@pytest_asyncio.fixture
async def agent(monkeypatch):
    """Сессия с подменённым бэкендом + гарантированная остановка её фоновых задач.

    Без остановки прогон висит на TEARDOWN: мок `events()` ждёт вечно, а слушающая
    задача сессии остаётся жить после теста. Сам тест при этом проходит — красное
    приходит из уборки, и это выглядит как «мои правки сломали всё».
    """
    from tests.conftest import make_backend_mock

    created = []

    async def _make(send_impl):
        backend = make_backend_mock()
        backend.send = send_impl
        # AsyncMock отвечает ЛЮБЫМ атрибутом, и `getattr(backend, "resume_failed", False)`
        # оказывается истинным — сессия уходит в ветку восстановления транскрипта и молча
        # затирает runtime_handoff. Ставим явно.
        backend.resume_failed = False
        monkeypatch.setattr("app.session.AgentSession._make_backend",
                            lambda _self, *a, **k: backend)
        from app.main import manager

        manager.sessions.clear()
        session = await manager.ensure_loaded_any("worker")
        created.append(session)
        return session

    yield _make

    import asyncio

    for session in created:
        try:
            await asyncio.wait_for(session.stop(), timeout=5)
        except Exception:
            pass
        tasks = [getattr(session, name, None)
                 for name in ("_listen_task", "_hibernate_task", "_auto_report_task")]
        tasks += list(getattr(session, "_background_tasks", ()) or ())
        for task in tasks:
            if task is not None and not task.done():
                task.cancel()
    await asyncio.sleep(0.05)
    from app.main import manager as _m

    _m.sessions.clear()


@pytest.mark.asyncio
async def test_failed_send_keeps_the_facts_in_the_queue(db, session_id, monkeypatch, agent):
    """Гашение строго по факту доставки: не дошло — факт остаётся."""
    db.enqueue_fact(session_id, "bug:1", "уведомление о баг-репорте не доставлено")

    async def boom(_msg):
        raise RuntimeError("CLI отвалился")

    session = await agent(send_impl=boom)
    with pytest.raises(RuntimeError):
        await session.send(
            "сообщение, которое не уедет", provenance=USER_PROVENANCE,
        )

    left = db.peek_facts(session_id)
    print("\nПОСЛЕ ОТКАЗА в очереди:", [f["text"] for f in left["facts"]])
    assert len(left["facts"]) == 1, "недоставленный факт не имеет права исчезнуть"


@pytest.mark.asyncio
async def test_agent_sees_the_fact_in_its_context(db, session_id, monkeypatch, agent):
    db.enqueue_fact(session_id, "autoreport:1",
                    "автоотчёт воркера «perf» не доставлен: RuntimeError: занято")
    seen = []

    async def capture(msg):
        seen.append(msg)

    session = await agent(send_impl=capture)
    await session.send("новая задача", provenance=USER_PROVENANCE)

    payload = seen[0]
    print("\nPAYLOAD В BACKEND.SEND:\n" + payload)
    assert "автоотчёт воркера «perf» не доставлен" in payload
    assert "исходные сообщения НЕ пересылались" in payload
    assert payload.rstrip().endswith("новая задача")
    assert db.peek_facts(session_id)["facts"] == [], "доставленный факт обязан погаснуть"

    seen.clear()
    await session.send("вторая задача", provenance=USER_PROVENANCE)
    assert "автоотчёт" not in seen[0], "второй раз тот же факт приписывать нельзя"


@pytest.mark.asyncio
async def test_overflow_line_is_visible_to_the_agent(db, session_id, monkeypatch, agent):
    for i in range(23):
        db.enqueue_fact(session_id, f"k{i}", f"событие {i}")
    seen = []

    async def capture(msg):
        seen.append(msg)

    session = await agent(send_impl=capture)
    await session.send("задача", provenance=USER_PROVENANCE)
    print("\nСТРОКА О СВЁРНУТЫХ:",
          [ln for ln in seen[0].splitlines() if "свёрнуто" in ln])
    assert "и ещё 3 событий, свёрнуто" in seen[0]
    assert db.peek_facts(session_id)["facts"] == []


@pytest.mark.asyncio
async def test_broken_queue_does_not_block_the_message(db, session_id, monkeypatch, agent):
    """Сообщение важнее факта: сбой очереди не должен мешать доставке."""
    import app.db as dbmod

    def boom(*_a, **_k):
        raise RuntimeError("БД недоступна")

    monkeypatch.setattr(dbmod, "peek_facts", boom)
    seen = []

    async def capture(msg):
        seen.append(msg)

    session = await agent(send_impl=capture)
    await session.send(
        "задача при сломанной очереди", provenance=USER_PROVENANCE,
    )
    assert seen == ["задача при сломанной очереди"]


@pytest.mark.asyncio
async def test_mid_turn_inject_also_carries_the_fact(db, session_id, monkeypatch, agent):
    """Путь RUNNING + рантайм с mid-turn inject (Claude)."""
    from app.session_state import AgentStatus

    db.enqueue_fact(session_id, "wake:7", "пробуждение не доставлено")
    seen = []

    async def capture(msg):
        seen.append(msg)

    session = await agent(send_impl=capture)
    session.status = AgentStatus.RUNNING
    await session.send(
        "сообщение в активный ход", provenance=USER_PROVENANCE,
    )

    print("\nMID-TURN PAYLOAD:\n" + seen[0])
    assert "пробуждение не доставлено" in seen[0]
    assert db.peek_facts(session_id)["facts"] == []


@pytest.mark.asyncio
async def test_flush_path_carries_the_fact(db, session_id, monkeypatch, agent):
    """Путь рантайма БЕЗ mid-turn inject (Codex): сообщение уходит через _flush_pending."""
    db.enqueue_fact(session_id, "bgjob:9", "результат фоновой задачи не доставлен")
    seen = []

    async def capture(msg):
        seen.append(msg)

    session = await agent(send_impl=capture)
    session._pending_messages.append("сообщение из очереди")
    await session._flush_pending()

    print("\nFLUSH PAYLOAD:\n" + seen[0])
    assert "результат фоновой задачи не доставлен" in seen[0]
    assert "сообщение из очереди" in seen[0]
    assert db.peek_facts(session_id)["facts"] == []


@pytest.mark.asyncio
async def test_fact_lands_inside_current_user_message_on_handoff(db, session_id, monkeypatch, agent):
    """При смене рантайма факт обязан быть ВНУТРИ <current-user-message>, а не над ним."""
    db.enqueue_fact(session_id, "bug:5", "уведомление о баг-репорте не доставлено")
    seen = []

    async def capture(msg):
        seen.append(msg)

    session = await agent(send_impl=capture)
    session.runtime_handoff = "прошлый диалог"
    await session.send(
        "сообщение после смены рантайма", provenance=USER_PROVENANCE,
    )

    payload = seen[0]
    inside = payload.split("<current-user-message>")[1]
    print("\nВНУТРИ ОБЁРТКИ:\n" + inside.strip()[:200])
    assert "уведомление о баг-репорте не доставлено" in inside
