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

    async def fake_backfill(scope):
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

    async def fake_backfill(_scope):
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

    async def fake_backfill(scope):
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

    async def fake_backfill(_scope):
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

    async def fake_backfill(_scope):
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
