import asyncio
import logging

import pytest


@pytest.fixture
def ready_service(monkeypatch):
    from app import rag_service

    monkeypatch.setattr(rag_service, "_RAG_ENABLED", True)
    monkeypatch.setattr(rag_service, "_initialized", True)
    monkeypatch.setattr(rag_service, "_backfill_tasks", {})
    monkeypatch.setattr(rag_service, "_backfill_dirty", set())
    return rag_service


@pytest.mark.parametrize(
    ("enabled", "initialized", "expected"),
    [
        (False, False, False),
        (True, False, False),
        (True, True, True),
    ],
)
def test_is_ready_requires_enabled_successful_initialization(
    monkeypatch,
    enabled,
    initialized,
    expected,
):
    from app import rag_service

    monkeypatch.setattr(rag_service, "_RAG_ENABLED", enabled)
    monkeypatch.setattr(rag_service, "_initialized", initialized)

    assert rag_service.is_ready() is expected


def test_schedule_backfill_returns_not_ready_without_live_service(monkeypatch, caplog):
    from app import rag_service

    monkeypatch.setattr(rag_service, "_RAG_ENABLED", True)
    monkeypatch.setattr(rag_service, "_initialized", False)
    monkeypatch.setattr(rag_service, "_backfill_tasks", {})
    monkeypatch.setattr(rag_service, "_backfill_dirty", set())

    with caplog.at_level(logging.WARNING):
        status = rag_service.schedule_backfill("/scope")

    assert status == "not_ready"
    assert not rag_service._backfill_tasks
    assert "not ready" in caplog.text.lower()


@pytest.mark.asyncio
async def test_schedule_backfill_retains_and_coalesces_one_followup(ready_service, monkeypatch):
    calls = []
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    async def fake_backfill(scope, session_name=None):
        calls.append(scope)
        if len(calls) == 1:
            first_started.set()
            await release_first.wait()
        return {"files": len(calls), "logs": 0}

    monkeypatch.setattr(ready_service, "backfill_scope", fake_backfill)

    assert ready_service.schedule_backfill("/scope/") == "accepted"
    task = ready_service._backfill_tasks["/scope"]
    await first_started.wait()

    assert ready_service.schedule_backfill("/scope") == "coalesced"
    assert ready_service.schedule_backfill("/scope//") == "coalesced"
    assert ready_service._backfill_tasks["/scope"] is task

    release_first.set()
    await task

    assert calls == ["/scope", "/scope"]
    assert ready_service._backfill_tasks == {}
    assert ready_service._backfill_dirty == set()


@pytest.mark.asyncio
async def test_coalesced_followup_runs_after_current_scan_fails(ready_service, monkeypatch):
    attempts = 0
    first_started = asyncio.Event()
    fail_first = asyncio.Event()

    async def fake_backfill(_scope, session_name=None):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            first_started.set()
            await fail_first.wait()
            raise RuntimeError("first scan failed")
        return {"files": 1, "logs": 0}

    monkeypatch.setattr(ready_service, "backfill_scope", fake_backfill)

    assert ready_service.schedule_backfill("/scope") == "accepted"
    task = ready_service._backfill_tasks["/scope"]
    await first_started.wait()
    assert ready_service.schedule_backfill("/scope") == "coalesced"

    fail_first.set()
    await task

    assert attempts == 2
    assert ready_service._backfill_tasks == {}


@pytest.mark.asyncio
async def test_schedule_backfill_keeps_scopes_independent(ready_service, monkeypatch):
    calls = []
    both_started = asyncio.Event()
    release = asyncio.Event()

    async def fake_backfill(scope, session_name=None):
        calls.append(scope)
        if len(calls) == 2:
            both_started.set()
        await release.wait()
        return {"files": 0, "logs": 0}

    monkeypatch.setattr(ready_service, "backfill_scope", fake_backfill)

    assert ready_service.schedule_backfill("/scope") == "accepted"
    assert ready_service.schedule_backfill("/scope-link") == "accepted"
    tasks = tuple(ready_service._backfill_tasks.values())
    await both_started.wait()

    assert len(tasks) == 2
    assert ready_service.schedule_backfill("/scope/") == "coalesced"
    assert "/scope-link" not in ready_service._backfill_dirty

    release.set()
    await asyncio.gather(*tasks)

    assert calls.count("/scope") == 2
    assert calls.count("/scope-link") == 1


@pytest.mark.asyncio
async def test_failed_backfill_is_logged_removed_and_can_be_rescheduled(
    ready_service,
    monkeypatch,
    caplog,
):
    attempts = 0

    async def fake_backfill(_scope, session_name=None):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("embedder failed")
        return {"files": 1, "logs": 0}

    monkeypatch.setattr(ready_service, "backfill_scope", fake_backfill)

    with caplog.at_level(logging.ERROR):
        assert ready_service.schedule_backfill("/scope") == "accepted"
        first = ready_service._backfill_tasks["/scope"]
        await first

    assert "embedder failed" in caplog.text
    assert ready_service._backfill_tasks == {}

    assert ready_service.schedule_backfill("/scope") == "accepted"
    second = ready_service._backfill_tasks["/scope"]
    await second

    assert attempts == 2
    assert ready_service._backfill_tasks == {}


@pytest.mark.asyncio
async def test_shutdown_cancels_retained_wrappers_and_clears_state(ready_service, monkeypatch):
    started = asyncio.Event()
    never = asyncio.Event()

    async def fake_backfill(_scope, session_name=None):
        started.set()
        await never.wait()

    monkeypatch.setattr(ready_service, "backfill_scope", fake_backfill)

    assert ready_service.schedule_backfill("/scope") == "accepted"
    task = ready_service._backfill_tasks["/scope"]
    await started.wait()

    ready_service.shutdown()
    await asyncio.sleep(0)

    assert task.cancelled()
    assert ready_service._backfill_tasks == {}
    assert ready_service._backfill_dirty == set()
    assert ready_service.is_ready() is False


def test_orchestra_logger_has_its_own_info_handler():
    """Весь жизненный цикл бэкфилла пишется на INFO. Uvicorn настраивает только свои логгеры,
    рутовый остаётся без хендлера → INFO съедает lastResort (WARNING) и в journald не видно
    ни старта, ни длительности, ни обрыва. Проверяем СВОЙ логгер, а не рутовый: рутовому
    хендлер добавляет сам pytest, и проверка по нему зеленела бы всегда."""
    import app.main  # noqa: F401 — импорт настраивает логирование процесса

    orchestra = logging.getLogger("orchestra")
    assert orchestra.handlers, "у 'orchestra' нет хендлера → INFO не долетит до journald"
    assert orchestra.level == logging.INFO
    assert logging.getLogger("orchestra.rag_service").isEnabledFor(logging.INFO)


def _fake_rag_run(monkeypatch, files_left: int, logs_left: int, seen: list):
    """Подменяет app.rag.run: отдаёт работу срезами, как настоящие backfill_*."""
    from app import rag

    state = {"files": files_left, "logs": logs_left}

    async def fake_run(_loop, method, *args):
        seen.append(method)
        if method == "backfill_files":
            take = min(state["files"], args[2])
            state["files"] -= take
            return take
        if method == "backfill_logs":
            take = min(state["logs"], args[2])
            state["logs"] -= take
            return take
        if method == "pending_files":
            return state["files"]
        raise AssertionError(f"unexpected method {method}")

    monkeypatch.setattr(rag, "run", fake_run)
    return state


@pytest.mark.asyncio
async def test_backfill_scope_drains_both_layers_in_slices(ready_service, monkeypatch):
    seen: list[str] = []
    _fake_rag_run(monkeypatch, files_left=5, logs_left=3, seen=seen)
    monkeypatch.setattr(ready_service, "_FILE_SLICE", 2)
    monkeypatch.setattr(ready_service, "_LOG_SLICE", 2)

    result = await ready_service.backfill_scope("/scope")

    assert result == {"files": 5, "logs": 3, "pending_files": 0}
    assert seen.count("backfill_files") > 1, "работа обязана нарезаться на срезы"
    # слои чередуются: логи не ждут, пока досчитается весь файловый корпус
    assert seen[:4] == ["backfill_files", "backfill_logs"] * 2


@pytest.mark.asyncio
async def test_backfill_scope_stops_on_budget_and_leaves_the_rest_to_the_next_trigger(
    ready_service, monkeypatch,
):
    seen: list[str] = []
    state = _fake_rag_run(monkeypatch, files_left=100, logs_left=0, seen=seen)
    monkeypatch.setattr(ready_service, "_FILE_SLICE", 2)
    monkeypatch.setattr(ready_service, "_PASS_BUDGET_SECONDS", 0.0)

    result = await ready_service.backfill_scope("/scope")

    assert result["files"] == 2, "бюджет обязан оборвать прогон на первом срезе"
    assert state["files"] == 98, "остаток остаётся следующему триггеру, а не теряется"


@pytest.mark.asyncio
async def test_index_status_stays_silent_until_a_pass_actually_ran(ready_service, monkeypatch):
    """Пустой статус честнее нуля: ноль читается как «индекс догнан»."""
    monkeypatch.setattr(ready_service, "_last_pending", {})
    assert ready_service.index_status("/scope") == {}

    seen: list[str] = []
    _fake_rag_run(monkeypatch, files_left=3, logs_left=0, seen=seen)
    monkeypatch.setattr(ready_service, "_FILE_SLICE", 1)
    monkeypatch.setattr(ready_service, "_PASS_BUDGET_SECONDS", 0.0)

    await ready_service.backfill_scope("/scope")

    assert ready_service.index_status("/scope") == {"pending_files": 2, "indexing": False}


@pytest.mark.asyncio
async def test_session_reindex_is_scheduled_separately_from_the_scope_pass(ready_service, monkeypatch):
    """Ручной пересессионный reindex не должен схлопываться в фоновый скан всего scope:
    его заказали явно, и «коалесцировано» означало бы «сделаем когда-нибудь другое»."""
    seen: list[tuple] = []
    release = asyncio.Event()

    async def fake_backfill(scope, session_name=None):
        seen.append((scope, session_name))
        await release.wait()
        return {"files": 0, "logs": 0}

    monkeypatch.setattr(ready_service, "backfill_scope", fake_backfill)

    assert ready_service.schedule_backfill("/scope") == "accepted"
    assert ready_service.schedule_backfill("/scope", session_name="w1") == "accepted"
    assert ready_service.schedule_backfill("/scope", session_name="w1") == "coalesced"
    tasks = tuple(ready_service._backfill_tasks.values())
    await asyncio.sleep(0)

    assert len(tasks) == 2
    assert set(ready_service._backfill_tasks) == {"/scope", "/scope::w1"}
    # `indexing` обязан видеть и сессионный прогон: ключ у него составной
    monkeypatch.setitem(ready_service._last_pending, "/scope", 5)
    assert ready_service.index_status("/scope") == {"pending_files": 5, "indexing": True}

    release.set()
    await asyncio.gather(*tasks)
    assert ("/scope", None) in seen and ("/scope", "w1") in seen


@pytest.mark.asyncio
async def test_session_pass_slices_logs_and_skips_files(ready_service, monkeypatch):
    """Сессионный прогон шёл одним неограниченным запросом: 500 логов × 1.3-2.9 с — больше
    6.5 минут. Теперь он идёт теми же срезами, что и общий, и файлы не трогает."""
    seen: list[str] = []
    state = _fake_rag_run(monkeypatch, files_left=99, logs_left=3, seen=seen)
    monkeypatch.setattr(ready_service, "_LOG_SLICE", 2)

    result = await ready_service.backfill_scope("/scope", session_name="w1")

    assert result == {"files": 0, "logs": 3}
    assert "backfill_files" not in seen, "логи сессии не привязаны к файлам scope"
    assert "pending_files" not in seen, "долг по файлам к сессионному прогону не относится"
    assert state["files"] == 99
    assert seen.count("backfill_logs") > 1, "работа обязана нарезаться на срезы"


@pytest.mark.asyncio
async def test_reindex_endpoint_returns_control_immediately(monkeypatch):
    """Эндпоинт держал HTTP-запрос до конца прогона и назывался при этом «fast»."""
    from app.routes import memory as memory_route

    calls: list[tuple] = []
    monkeypatch.setattr(memory_route.rag_service, "is_enabled", lambda: True)
    monkeypatch.setattr(memory_route.rag_service, "index_status", lambda scope: {"pending_files": 7})
    monkeypatch.setattr(
        memory_route.rag_service, "schedule_backfill",
        lambda scope, session_name="": (calls.append((scope, session_name)), "accepted")[1])

    async def never_awaited(*a, **k):
        raise AssertionError("роут не имеет права ждать прогон")

    monkeypatch.setattr(memory_route.rag_service, "backfill_scope", never_awaited)

    out = await memory_route.memory_reindex(
        memory_route.MemoryReindexRequest(scope="/scope/", session_name="w1"))

    assert out == {"ok": True, "status": "accepted", "index": {"pending_files": 7}}
    assert calls == [("/scope", "w1")]
