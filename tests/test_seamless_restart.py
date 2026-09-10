"""Restart cuts active turns, persists outcomes and reopens admission on failure."""

import asyncio
import os
import signal
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest





def _adoptable_backend():
    """Двойник бэкенда, УМЕЮЩЕГО передаваться (#230 T5).

    Рестарт спрашивает способность (`adopt`), а не имя рантайма, поэтому двойник, который
    изображает Codex, обязан её иметь: без неё он изображает рантайм, чей ход рестарт обязан
    ждать, и тест мерил бы не то, что называется в его имени.
    """
    async def _adopt(*a, **k):
        return None

    return SimpleNamespace(adopt=_adopt)








@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    db_path = tmp_path / "orchestra-237.db"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    from app.db import init_db
    init_db()
    return db_path


def _save_handover_row(
    cwd,
    *,
    session_id=None,
    row_id="23700000-0000-4000-8000-000000000001",
    name="codex-237",
):
    from app.db import save_session

    save_session({
        "id": row_id,
        "name": name,
        "scope": str(cwd),
        "cwd": str(cwd),
        "model": "gpt-5.6-luna",
        "backend_type": "codex",
        "system_prompt": "",
        "status": "running",
        "session_id": session_id,
        "cost_usd": 0.0,
        "worktree_path": None,
        "branch": None,
        "is_orchestrator": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "role": "worker",
        "pipeline": "default",
        "color": "#818cf8",
    })



@pytest.mark.asyncio
async def test_t3_auto_resume_wakes_a_gracefully_interrupted_worker(
    isolated_db, tmp_path, monkeypatch,
):
    from app.db import _conn
    from app.manager import SessionManager

    row_id = "41300000-0000-4000-8000-000000000001"
    _save_handover_row(
        tmp_path,
        session_id="thread-413",
        row_id=row_id,
        name="interrupted-413",
    )
    with _conn() as connection:
        connection.execute(
            "UPDATE sessions SET status='interrupted' WHERE id=?", (row_id,),
        )

    manager = SessionManager()
    loaded = []
    spawned = []

    async def load(row, *, recovery_handoff=None):
        session = SimpleNamespace(id=row["id"], name=row["name"])
        loaded.append((session, recovery_handoff))
        manager.sessions[session.id] = session
        return session

    notice = AsyncMock()
    monkeypatch.setattr(manager, "_load_from_db", load)
    monkeypatch.setattr(manager, "_inject_restart_notice", notice)
    monkeypatch.setattr(
        "app.manager.spawn_supervised",
        lambda awaitable, label: spawned.append((awaitable, label)),
    )

    await manager.auto_resume_all()

    assert [session.id for session, _handoff in loaded] == [row_id]
    assert len(spawned) == 1
    await spawned[0][0]
    notice.assert_awaited_once_with(loaded[0][0])


@pytest.fixture(autouse=True)
def _restore_restart_gates():
    yield
    from app import main as app_main
    from app.deps import manager
    app_main.open_mutating_admission()
    manager.end_drain()


@pytest.mark.asyncio
async def test_t3_restart_closes_both_admissions_before_its_first_wait(monkeypatch):
    from app import main as app_main
    from app.deps import manager
    from app.routes import system

    order = []
    real_begin = manager.begin_drain
    real_close = app_main.close_mutating_admission

    def begin():
        order.append("agent")
        real_begin()

    def close():
        order.append("http")
        real_close()

    async def first_wait():
        assert len(order) >= 2 and set(order[:2]) == {"agent", "http"}, (
            f"both gates must close atomically before yielding; got {order}")
        raise RuntimeError("stop after observing the first await")

    monkeypatch.setattr(manager, "begin_drain", begin)
    monkeypatch.setattr(app_main, "close_mutating_admission", close)
    monkeypatch.setattr(app_main, "drain_mutating_requests", first_wait)

    with pytest.raises(RuntimeError, match="stop after observing"):
        await system.restart_server()


@pytest.mark.asyncio
async def test_t3_inflight_mutating_http_never_blocks_the_signal(monkeypatch):
    """Живая мутация рестарт НЕ откладывает и НЕ отменяет (решение юзера 28.08.2026).

    Мутация не заканчивается за весь тест: раньше это держало сигнал до конца бюджета и
    затем отменяло рестарт целиком, то есть нажатие кнопки не делало ничего.
    """
    from app import main as app_main
    from app.deps import manager
    from app.routes import system

    kill = MagicMock()
    monkeypatch.setattr(system, "_drain_sessions", lambda: [])
    monkeypatch.setattr(system, "_RESPONSE_FLUSH_PAUSE_S", 0)
    monkeypatch.setattr(system.os, "kill", kill)
    monkeypatch.setattr(app_main, "inflight_mutating_count", lambda: 2)
    monkeypatch.setattr(
        manager,
        "prepare_restart_handover",
        AsyncMock(return_value={"ok": True, "handed_over": []}),
        raising=False,
    )

    await asyncio.wait_for(system._restart_service_after_response(), timeout=5)
    kill.assert_called_once_with(os.getpid(), system.signal.SIGINT)


@pytest.mark.asyncio
async def test_t3_abandoned_mutations_are_reported_not_hidden(monkeypatch):
    """Оборванные мутации теряют ответ — это обязано быть видно в выдаче рестарта."""
    from app import main as app_main
    from app.routes import system

    monkeypatch.setattr(system, "_drain_sessions", lambda: [])
    monkeypatch.setattr(app_main, "inflight_mutating_count", lambda: 3)
    monkeypatch.setattr(app_main, "drain_mutating_requests", AsyncMock(return_value=False))

    outcome = await system._do_restart_service()

    assert outcome["ok"] is True, "a live mutation must not cancel the restart"
    assert outcome["abandoned_mutations"] == 3, outcome


@pytest.mark.asyncio
async def test_t3_active_codex_is_cut_without_handover(monkeypatch):
    from app import main as app_main
    from app.deps import manager
    from app.routes import system

    active_codex = SimpleNamespace(
        id="codex-active", name="codex-active", backend_type="codex", is_busy=True,
        _backend=_adoptable_backend(),
    )
    order = []

    prepare = AsyncMock(return_value={"ok": True, "handed_over": ["codex-active"]})

    monkeypatch.setattr(system, "_drain_sessions", lambda: [active_codex])
    monkeypatch.setattr(system, "_RESPONSE_FLUSH_PAUSE_S", 0)
    monkeypatch.setattr(app_main, "drain_mutating_requests", AsyncMock(return_value=True))
    monkeypatch.setattr(app_main, "inflight_mutating_count", lambda: 0)
    monkeypatch.setattr(manager, "prepare_restart_handover", prepare, raising=False)
    monkeypatch.setattr(system.os, "kill", lambda *_args: order.append("signal"))

    outcome = await asyncio.wait_for(system._restart_service_after_response(), timeout=2)

    assert order == ["signal"]
    prepare.assert_not_awaited()
    assert outcome["ok"] is True and outcome["handed_over"] == []
    assert outcome["cut_ids"] == ["codex-active"]


@pytest.mark.asyncio
async def test_t3_restart_does_not_ask_a_live_backend_for_handover(monkeypatch):
    from app import main as app_main
    from app.deps import manager
    from app.routes import system

    stuck = SimpleNamespace(
        id="stuck", name="stuck", backend_type="codex", is_busy=True,
        _backend=_adoptable_backend(),
    )
    kill = MagicMock()
    monkeypatch.setattr(system, "_drain_sessions", lambda: [stuck])
    monkeypatch.setattr(system, "_RESPONSE_FLUSH_PAUSE_S", 0)
    monkeypatch.setattr(system.os, "kill", kill)
    monkeypatch.setattr(app_main, "drain_mutating_requests", AsyncMock(return_value=True))
    monkeypatch.setattr(app_main, "inflight_mutating_count", lambda: 0)
    prepare = AsyncMock(return_value={
            "ok": False,
            "reason": "pending request",
            "refused_ids": ["stuck"],
            "refused_names": ["stuck"],
        })
    monkeypatch.setattr(manager, "prepare_restart_handover", prepare, raising=False)

    outcome = await asyncio.wait_for(system._restart_service_after_response(), timeout=2)

    kill.assert_called_once_with(os.getpid(), signal.SIGINT)
    prepare.assert_not_awaited()
    assert outcome["ok"] is True and outcome["cut_ids"] == ["stuck"]
    assert outcome["restore_after_restart"] == ["stuck"]


@pytest.mark.asyncio
async def test_t3_restart_cuts_every_runtime_and_uses_graceful_stop(monkeypatch):
    from app import main as app_main
    from app.manager import SessionManager
    from app.routes import system

    local_manager = SessionManager()
    sessions = []
    for runtime, backend in (
        ("claude", None),
        ("codex", _adoptable_backend()),
        ("grok", SimpleNamespace()),
    ):
        sessions.append(SimpleNamespace(
            id=f"{runtime}-active",
            name=f"{runtime}-active",
            backend_type=runtime,
            is_busy=True,
            _backend=backend,
            stop=AsyncMock(),
        ))
    local_manager.sessions = {session.id: session for session in sessions}
    monkeypatch.setattr(system, "manager", local_manager)
    monkeypatch.setattr(system, "_drain_sessions", lambda: sessions)
    monkeypatch.setattr(app_main, "drain_mutating_requests", AsyncMock(return_value=True))
    monkeypatch.setattr(app_main, "inflight_mutating_count", lambda: 0)
    prepare = AsyncMock(return_value={"ok": True, "handed_over": []})
    monkeypatch.setattr(local_manager, "prepare_restart_handover", prepare, raising=False)
    hand_over = AsyncMock(return_value=True)
    monkeypatch.setattr(local_manager, "_hand_over_backend", hand_over, raising=False)

    # 5 с, как у соседних проверок этого файла, а не 0.5: внутри всё замокано
    # (`AsyncMock`), поэтому полсекунды здесь не проверяли ничего, кроме загрузки
    # машины. На раннере 05.09 это дало `TimeoutError` из `asyncio.wait_for` на
    # заведомо исправном коде. Бюджет остаётся защитой от ЗАВИСАНИЯ; перф-ассертом
    # он подрабатывать не должен — правило проекта, 21 такое место уже вычищено.
    outcome = await asyncio.wait_for(
        system._restart_service_after_response(signal=False), timeout=5,
    )
    await local_manager.shutdown_all()

    prepare.assert_not_awaited()
    hand_over.assert_not_awaited()
    for session in sessions:
        session.stop.assert_awaited_once_with()
    expected = ["claude-active", "codex-active", "grok-active"]
    assert outcome["ok"] is True and outcome["cut_ids"] == expected
    assert outcome["restore_after_restart"] == expected


@pytest.mark.asyncio
async def test_t3_signal_failure_clears_pending_interrupt_without_handover(monkeypatch):
    from app import main as app_main
    from app.manager import SessionManager
    from app.routes import system

    local_manager = SessionManager()
    removed = []
    backends = []
    sessions = []
    for suffix in ("one", "two"):
        # `adopt` — то, по чему рестарт решает, можно ли не ждать эту сессию (#230 T5)
        backend = SimpleNamespace(_handover_quiescing=False,
                                  adopt=_adoptable_backend().adopt)

        async def resume(backend=backend):
            backend._handover_quiescing = False

        backend.resume_after_aborted_handover = AsyncMock(side_effect=resume)
        session = SimpleNamespace(
            id=f"codex-{suffix}",
            name=f"codex-{suffix}",
            backend_type="codex",
            is_busy=True,
            _backend=backend,
        )
        backends.append(backend)
        sessions.append(session)

    local_manager._hand_over_backend = AsyncMock(return_value=True)
    monkeypatch.setattr(system, "manager", local_manager)
    monkeypatch.setattr(system, "_drain_sessions", lambda: sessions)
    monkeypatch.setattr(system, "_RESPONSE_FLUSH_PAUSE_S", 0)
    monkeypatch.setattr(app_main, "drain_mutating_requests", AsyncMock(return_value=True))
    monkeypatch.setattr(app_main, "inflight_mutating_count", lambda: 0)

    def fail_signal(*_args):
        raise OSError("synthetic signal failure")

    monkeypatch.setattr(system.os, "kill", fail_signal)

    with pytest.raises(OSError, match="synthetic signal failure"):
        await asyncio.wait_for(system._restart_service_after_response(), timeout=2)

    assert removed == []
    local_manager._hand_over_backend.assert_not_awaited()
    for backend in backends:
        backend.resume_after_aborted_handover.assert_not_awaited()
        assert backend._handover_quiescing is False
    assert getattr(local_manager, "_prepared_restart_sessions", set()) == set()
    assert local_manager.draining is False
    assert app_main.mutating_admission_verdict(
        "POST", "/api/sessions/worker/send"
    )["allowed"] is True


@pytest.mark.asyncio
async def test_t3_runtime_capability_does_not_change_cut_membership(monkeypatch):
    from app import main as app_main
    from app.deps import manager
    from app.routes import system

    codex = SimpleNamespace(
        id="codex-active", name="codex-active", backend_type="codex", is_busy=True,
        _backend=_adoptable_backend(),
    )
    claude = SimpleNamespace(
        id="claude-active", name="claude-active", backend_type="claude", is_busy=True
    )
    kill = MagicMock()
    prepare = AsyncMock(return_value={"ok": True, "handed_over": ["codex-active"]})

    monkeypatch.setattr(system, "_drain_sessions", lambda: [codex, claude])
    monkeypatch.setattr(system, "_RESPONSE_FLUSH_PAUSE_S", 0)
    monkeypatch.setattr(system.os, "kill", kill)
    monkeypatch.setattr(app_main, "drain_mutating_requests", AsyncMock(return_value=True))
    monkeypatch.setattr(app_main, "inflight_mutating_count", lambda: 0)
    monkeypatch.setattr(manager, "prepare_restart_handover", prepare, raising=False)

    outcome = await asyncio.wait_for(system._restart_service_after_response(), timeout=2)

    kill.assert_called_once_with(os.getpid(), signal.SIGINT)
    prepare.assert_not_awaited()
    assert outcome["ok"] is True
    assert outcome["cut_ids"] == ["codex-active", "claude-active"]
    assert outcome["restore_after_restart"] == ["codex-active", "claude-active"]
