"""Live drain rollback wakes safe receipts without startup/orphan recovery."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app import db, message_deliveries as deliveries
from app.manager import SessionManager
from tests.test_cron_drain_delivery_v1074 import cron, fire, receipt


REAL_ENSURE_RUNNER = deliveries.ensure_target_runner


async def finish_runner(target):
    task = deliveries._target_runner_tasks.get(target)
    if task is None:
        return True
    observed = asyncio.Event()
    task.add_done_callback(lambda _task: observed.set())
    result = await task
    await observed.wait()
    return result


def forbid_orphan_recovery(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("live drain abort must not orphan provider work")

    monkeypatch.setattr(deliveries, "_recover_message_deliveries", forbidden)
    monkeypatch.setattr(deliveries, "recover_message_deliveries", forbidden)


@pytest.mark.asyncio
@pytest.mark.parametrize("runner_still_exiting", [False, True])
async def test_actual_abort_resumes_cron_once_after_nonmatch_without_command_replay(
    cron, monkeypatch, runner_still_exiting,
):
    from app import main as app_main
    from app.routes import system

    monkeypatch.setattr(system, "manager", cron.manager)
    monkeypatch.setattr(system, "_last_restart_abort", None)
    monkeypatch.setattr(app_main, "_restart_failure", "")
    monkeypatch.setattr(app_main, "_mutating_admission_open", True)
    monkeypatch.setattr(app_main, "schedule_restart_inbox_drain", MagicMock())
    guard = AsyncMock()
    monkeypatch.setattr(system.restart_guard, "abort_guard", guard)
    monkeypatch.setattr(deliveries, "_target_runner_tasks", {})
    monkeypatch.setattr(deliveries, "ensure_target_runner", REAL_ENSURE_RUNNER)
    forbid_orphan_recovery(monkeypatch)
    refused, exit_allowed, submitted = asyncio.Event(), asyncio.Event(), asyncio.Event()
    run = deliveries.run_target_message_deliveries
    provider = cron.session.send.side_effect

    async def hold_refused_exit(target, manager=None):
        result = await run(target, manager=manager)
        if not result:
            refused.set()
            await exit_allowed.wait()
        return result

    if runner_still_exiting:
        monkeypatch.setattr(deliveries, "run_target_message_deliveries", hold_refused_exit)

    async def notify_submit(*args, **kwargs):
        await provider(*args, **kwargs)
        submitted.set()

    cron.session.send.side_effect = notify_submit
    app_main.close_mutating_admission()
    cron.manager.begin_drain()
    delivery_id = await fire(cron)
    original = receipt(delivery_id)
    first_runner = deliveries._target_runner_tasks[cron.session.id]
    if runner_still_exiting:
        await asyncio.wait_for(refused.wait(), timeout=2)
    else:
        assert not await finish_runner(cron.session.id)
        assert cron.session.id not in deliveries._target_runner_tasks
    assert receipt(delivery_id)["state"] == "QUEUED"
    cron.session.send.assert_not_awaited()
    # A later, legitimate schedule tick finds nothing; its output cannot be the
    # recovery source, and reopening admission must not execute either command.
    cron.communicate.return_value = (b"nothing pending", b"")
    await fire(cron, slot=cron.slot + timedelta(minutes=1))
    assert cron.spawn.await_count == 2
    assert db.bg_get_job("fixture-cron")["last_output"] == "nothing pending"
    await system._abort_restart("fixture failed restart without process replacement")
    assert not cron.manager.draining and app_main.mutating_admission_open()
    guard.assert_awaited_once_with("fixture failed restart without process replacement")
    app_main.schedule_restart_inbox_drain.assert_called_once()
    if runner_still_exiting:
        assert deliveries._target_runner_tasks[cron.session.id] is first_runner
        exit_allowed.set()
        assert not await first_runner
    await asyncio.wait_for(submitted.wait(), timeout=2)
    await finish_runner(cron.session.id)
    cron.manager.end_drain()  # No duplicate wake on an already-open manager.
    final = receipt(delivery_id)
    assert final["state"] == "SUBMITTED"
    assert len(cron.started) == 1 and cron.spawn.await_count == 2
    for key in ("message", "rendered_message", "target_generation", "origin_detail"):
        assert final[key] == original[key]


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["DISPATCHING", "DELIVERY_UNKNOWN"])
async def test_abort_keeps_ambiguous_head_and_its_queued_follower_unchanged(cron, monkeypatch, state):
    monkeypatch.setattr(deliveries, "_target_runner_tasks", {})
    first = await fire(cron)
    deliveries.prepare_message_delivery(first)
    deliveries.mark_message_delivery_dispatching(first)
    if state == "DELIVERY_UNKNOWN":
        deliveries.mark_message_delivery_unknown(first, RuntimeError("fixture ambiguous provider ack"))
    second = await fire(cron, slot=cron.slot + timedelta(minutes=1))
    before = receipt(first), receipt(second)
    forbid_orphan_recovery(monkeypatch)
    monkeypatch.setattr(deliveries, "ensure_target_runner", REAL_ENSURE_RUNNER)
    cron.manager.begin_drain()
    cron.manager.end_drain()
    assert (receipt(first), receipt(second)) == before
    assert not deliveries._target_runner_tasks
    cron.session.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_abort_does_not_orphan_or_duplicate_a_live_provider_dispatch(cron, monkeypatch):
    monkeypatch.setattr(deliveries, "_target_runner_tasks", {})
    monkeypatch.setattr(deliveries, "ensure_target_runner", REAL_ENSURE_RUNNER)
    forbid_orphan_recovery(monkeypatch)
    started, finish = asyncio.Event(), asyncio.Event()

    async def live_provider(message, *, delivery, provenance):
        await delivery.before_submit()
        cron.started.append((message, delivery.delivery_id))
        if len(cron.started) == 1:
            started.set()
            await finish.wait()
        await delivery.mark_submitted("fixture-live-turn")

    cron.session.send.side_effect = live_provider
    first = await fire(cron)
    await asyncio.wait_for(started.wait(), timeout=2)
    cron.manager.begin_drain()
    second = await fire(cron, slot=cron.slot + timedelta(minutes=1))
    before = receipt(first), receipt(second)
    assert before[0]["state"] == "DISPATCHING"
    cron.manager.end_drain()
    assert (receipt(first), receipt(second)) == before
    assert len(cron.started) == 1
    finish.set()
    await finish_runner(cron.session.id)
    assert receipt(first)["state"] == receipt(second)["state"] == "SUBMITTED"
    assert [item[1] for item in cron.started] == [first, second]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["metadata", "wake"])
async def test_optional_abort_wake_failure_does_not_close_admission(cron, monkeypatch, caplog, failure):
    delivery_id = await fire(cron)
    original = receipt(delivery_id)

    def unavailable(*args, **kwargs):
        raise RuntimeError("fixture queue metadata unavailable")

    cron.manager.begin_drain()
    with monkeypatch.context() as patch:
        if failure == "metadata":
            patch.setattr(db, "_conn", unavailable)
        else:
            patch.setattr(deliveries, "ensure_target_runner", unavailable)
        cron.manager.end_drain()
        assert not cron.manager.draining
    assert receipt(delivery_id) == original
    assert "fixture queue metadata unavailable" in caplog.text
    cron.session.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_canonical_direct_preflight_switches_before_generation_capture_and_dispatches(
    cron, tmp_path, monkeypatch,
):
    from app import manager as manager_module
    from app.mcp_proof import issue_mcp_proof
    from app.routes import sessions as routes
    from tests.test_quota_wait_queue import _decision

    row = db.get_session(cron.session.id)
    row.update(task_id="", needs_switch=1, branch="fixture-merged", worktree_path=str(tmp_path))
    db.save_session(row)
    session = SessionManager._hydrate_row(row)
    session.send = AsyncMock(side_effect=cron.session.send.side_effect)
    session._admission_service = AsyncMock(return_value=_decision(-10))
    cron.manager.sessions[session.id] = session
    cron.manager._auto_switch_before_delivery = SessionManager._auto_switch_before_delivery.__get__(cron.manager)
    monkeypatch.setattr(routes, "manager", cron.manager)
    monkeypatch.setattr(manager_module, "resolve_git_base_branch", lambda *args: "main")
    switch = MagicMock()  # Only Git/process boundaries are fake; lifecycle publication is real.

    def switch_git(*args, **kwargs):
        switch(*args, **kwargs)
        return {"ok": True, "branch": "fixture-adhoc/worker"}

    monkeypatch.setattr("app.workspace.switch_worktree_branch", switch_git)
    monkeypatch.setattr(manager_module, "_release_hub_workspaces", AsyncMock())
    request = SimpleNamespace(headers={
        "x-orchestra-session-id": session.id,
        "x-orchestra-mcp-proof": issue_mcp_proof(session.id),
    }, cookies={})
    delivery_id = "00000000-0000-4000-8000-000000001074"
    response = await routes.send_message(session.name, routes.SendRequest(
        delivery_id=delivery_id, message="legitimate prepared fixture message",
        sender=session.name, scope=session.scope,
    ), request=request)
    assert response.status_code == 202
    accepted = receipt(delivery_id)
    assert accepted["target_generation"] == (
        f"session={session.id}|task=|branch=fixture-adhoc/worker|needs_switch=0"
    )
    assert session.branch == "fixture-adhoc/worker" and not session.needs_switch
    session._admission_service.assert_awaited_once()
    assert switch.call_count == 1
    assert await deliveries.run_target_message_deliveries(session.id, manager=cron.manager)
    assert receipt(delivery_id)["state"] == "SUBMITTED"
    assert len(cron.started) == 1 and switch.call_count == 1
    assert cron.started[0][0] == "[from:fixture-worker] legitimate prepared fixture message"
