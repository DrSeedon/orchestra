"""Model-free cron receipts: real drain/generation gates, isolated SQLite, fake provider."""

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import bg_jobs, db, message_deliveries as deliveries
from app.bg_jobs import BgJobManager
from app.events import MessageProvenance
from app.manager import SessionManager
from app.session import DrainingRefused


@pytest.fixture
def cron(tmp_path, monkeypatch):
    from app import deps, report_holds

    db.init_db()
    now = datetime.now(timezone.utc)
    session = SimpleNamespace(
        id="fixture-recipient", name="fixture-worker", scope=str(tmp_path),
        task_id="fixture-task", branch="task-fixture/worker", needs_switch=False,
        parent_name="", last_task_sender="", send=AsyncMock(),
    )
    db.save_session(dict(
        id=session.id, name=session.name, scope=session.scope, cwd=str(tmp_path),
        model="claude-opus-5-5[1m]", system_prompt="", status="idle", session_id=None,
        cost_usd=0, worktree_path=str(tmp_path), branch=session.branch,
        base_branch="main", needs_switch=0, task_id=session.task_id, role="worker",
        is_orchestrator=False, color="", created_at=now.isoformat(), finished_at=None,
        parent_name="",
    ))
    manager = SessionManager()
    manager.sessions[session.id] = session
    manager._auto_switch_before_delivery = AsyncMock()
    manager.ensure_loaded_by_id = AsyncMock(return_value=session)
    monkeypatch.setattr(deps, "manager", manager)
    # Explicit event-driven scheduling makes assertions independent of task timing.
    monkeypatch.setattr(deliveries, "ensure_target_runner", lambda target: None)
    monkeypatch.setattr(deliveries, "_target_delivery_locks", {})
    monkeypatch.setattr(report_holds, "ensure_runner", lambda *args: None)
    bg = BgJobManager()
    bg.set_session_manager(manager)
    started = []

    async def provider(message, *, delivery, provenance):
        await delivery.before_submit()
        started.append((message, provenance, delivery.delivery_id))
        await delivery.mark_submitted("fixture-turn")

    session.send.side_effect = provider
    process = SimpleNamespace(pid=12345, returncode=0)
    spawn = AsyncMock(return_value=process)
    communicate = AsyncMock(return_value=(b"MATCH fixture result\n", b""))
    monkeypatch.setattr(bg, "_spawn_managed_process", spawn)
    monkeypatch.setattr(bg_jobs, "_communicate_cron_command", communicate)
    monkeypatch.setattr(bg_jobs, "_kill_proc", AsyncMock())
    db.bg_save_job(dict(
        id="fixture-cron", type="cron_command",
        config=json.dumps(dict(cron_expr="* * * * *", command="fixture command", pattern="MATCH")),
        message="inspect fixture result", target_session_id=session.id,
        target_name=session.name, target_scope=session.scope, created_by_name="fixture-owner",
        status="active", expires_at=(now + timedelta(hours=1)).isoformat(),
        created_at=now.isoformat(), trigger_at=None, last_output="",
    ))
    return SimpleNamespace(bg=bg, manager=manager, session=session, started=started,
                           spawn=spawn, communicate=communicate, slot=now.replace(second=0, microsecond=0))


async def fire(cron, kind="cron_command", slot=None):
    when = slot or cron.slot
    if kind == "cron":
        with db._conn() as connection:
            connection.execute("UPDATE bg_jobs SET type='cron' WHERE id='fixture-cron'")
        await cron.bg._fire_cron("fixture-cron", "inspect fixture result", "fixture-worker",
                                 cron.session.scope, fire_at=when)
    else:
        await cron.bg._fire_cron_command(
            "fixture-cron", "fixture command", "MATCH", "inspect fixture result",
            "fixture-worker", cron.session.scope, fire_at=when,
        )
    return cron.bg._cron_delivery_id("fixture-cron", when)


def receipt(delivery_id):
    row = deliveries._row(delivery_id)
    return dict(row) if row is not None else None


async def dispatch(cron):
    return await deliveries.run_target_message_deliveries(cron.session.id, manager=cron.manager)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["cron", "cron_command"])
async def test_actual_drain_keeps_accepted_fire_through_cancel_restore_restart(cron, monkeypatch, kind):
    cron.manager.begin_drain()
    delivery_id = await fire(cron, kind)
    accepted = receipt(delivery_id)
    config = json.loads(db.bg_get_job("fixture-cron")["config"])
    assert config["fire_count"] == 1
    assert config["last_delivery_id"] == delivery_id
    assert config["last_fired_at"]
    assert accepted["state"] == "QUEUED"
    # Exercise the actual exception and manager gate, not a lookalike RuntimeError.
    with pytest.raises(DrainingRefused):
        await cron.manager.send_message_delivery(
            cron.session.id, accepted["rendered_message"], delivery=None,
            target_generation=accepted["target_generation"],
            provenance=MessageProvenance.from_storage(accepted["origin"], accepted["origin_detail"]),
        )
    assert not await dispatch(cron)
    assert receipt(delivery_id)["state"] == "QUEUED"
    cron.session.send.assert_not_awaited()
    cron.manager._auto_switch_before_delivery.assert_not_awaited()
    with db._conn() as connection:
        assert connection.execute("SELECT count(*) FROM logs WHERE type='user_message'").fetchone()[0] == 0
    # Cancelling the schedule after acceptance cannot cancel a completed result.
    db.bg_cancel_job("fixture-cron")
    recovered = BgJobManager()
    recovered.set_session_manager(cron.manager)
    monkeypatch.setattr(recovered, "_start_task", lambda *args, **kwargs: pytest.fail("cancelled schedule restarted"))
    await recovered.restore_from_db()
    cron.manager.end_drain()
    # Fresh manager models runtime replacement while SQLite is retained.
    replacement = SessionManager()
    replacement.sessions[cron.session.id] = cron.session
    replacement._auto_switch_before_delivery = AsyncMock()
    monkeypatch.setattr("app.deps.manager", replacement)
    cron.manager = replacement
    await deliveries.recover_message_deliveries()
    await asyncio.gather(dispatch(cron), dispatch(cron))
    await deliveries.recover_message_deliveries()
    await dispatch(cron)
    final = receipt(delivery_id)
    assert final["state"] == "SUBMITTED"
    for key in ("delivery_id", "message", "rendered_message", "origin", "origin_detail",
                "target_session_id", "target_scope", "target_task_id", "target_generation"):
        assert final[key] == accepted[key]
    assert len(cron.started) == 1
    assert cron.started[0][1] == MessageProvenance(
        origin="background_task", senders=("fixture-cron",), subtype=kind, ref="fixture-cron",
    )
    assert cron.spawn.await_count == (1 if kind == "cron_command" else 0)


@pytest.mark.asyncio
async def test_nonmatch_cannot_overwrite_full_accepted_source_or_display(cron):
    raw = "  MATCH\n" + "x" * 4100 + "\nfixture tail\n  "
    cron.communicate.return_value = (raw.encode(), b"fixture stderr\n")
    delivery_id = await fire(cron)
    accepted = receipt(delivery_id)
    assert accepted["message"] == raw + "fixture stderr\n"
    output = accepted["message"].strip()
    assert accepted["rendered_message"].endswith(output[-3000:])
    assert db.bg_get_job("fixture-cron")["last_output"] == output[-3000:]
    cron.communicate.return_value = (b"nothing pending", b"")
    await fire(cron, slot=cron.slot + timedelta(minutes=1))
    assert db.bg_get_job("fixture-cron")["last_output"] == "nothing pending"
    assert receipt(delivery_id) == accepted
    await dispatch(cron)
    assert cron.started[0][0] == accepted["rendered_message"]
    assert len(cron.started[0][0]) < 3200


@pytest.mark.asyncio
async def test_double_observer_reuses_fire_but_next_occurrence_is_new(cron):
    first, second = await asyncio.gather(fire(cron), fire(cron))
    assert first == second
    await asyncio.gather(dispatch(cron), dispatch(cron))
    await fire(cron)  # The completed command is not rerun on re-observation.
    assert cron.spawn.await_count == 1
    await fire(cron, slot=cron.slot + timedelta(minutes=1))
    await dispatch(cron)
    assert len(cron.started) == 2
    assert json.loads(db.bg_get_job("fixture-cron")["config"])["fire_count"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["task", "branch", "needs_switch", "missing"])
async def test_changed_recipient_fails_visibly_without_executing_stale_body(cron, change):
    delivery_id = await fire(cron)
    if change == "missing":
        cron.manager.sessions.clear()
        cron.manager.ensure_loaded_by_id.return_value = None
    elif change == "task":
        cron.session.task_id = "other-fixture-task"
    elif change == "branch":
        cron.session.branch = "other-fixture-branch"
    else:
        cron.session.needs_switch = True
    await dispatch(cron)
    row = receipt(delivery_id)
    assert row["state"] == "FAILED_BEFORE_SUBMIT"
    assert row["user_log_id"] is None
    assert json.loads(row["error_json"])["code"] == (
        "DELIVERY_NOT_SUBMITTED" if change == "missing" else "TARGET_TASK_CHANGED"
    )
    cron.session.send.assert_not_awaited()
    await deliveries.recover_message_deliveries()
    await fire(cron)
    assert receipt(delivery_id)["state"] == "FAILED_BEFORE_SUBMIT"
    assert cron.spawn.await_count == 1
    with db._conn() as connection:
        warnings = connection.execute("SELECT content FROM logs WHERE type='warning'").fetchall()
        assert connection.execute("SELECT count(*) FROM logs WHERE type='user_message'").fetchone()[0] == 0
    assert len(warnings) == 1
    assert delivery_id in warnings[0]["content"]


@pytest.mark.asyncio
async def test_rename_cannot_redirect_receipt_by_name(cron):
    delivery_id = await fire(cron)
    cron.session.name = "renamed-fixture-worker"
    cron.manager.sessions["unrelated-fixture"] = SimpleNamespace(send=AsyncMock())
    await dispatch(cron)
    assert receipt(delivery_id)["target_session_id"] == cron.session.id
    assert len(cron.started) == 1
    cron.manager.sessions["unrelated-fixture"].send.assert_not_awaited()


@pytest.mark.asyncio
async def test_lifecycle_switch_during_delivery_cannot_execute_old_instruction(cron):
    delivery_id = await fire(cron)

    async def switch(session):
        session.task_id = "other-fixture-task"

    cron.manager._auto_switch_before_delivery.side_effect = switch
    await dispatch(cron)
    row = receipt(delivery_id)
    assert row["state"] == "FAILED_BEFORE_SUBMIT"
    assert json.loads(row["error_json"])["code"] == "TARGET_TASK_CHANGED"
    cron.session.send.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [PermissionError, RuntimeError])
async def test_other_admission_errors_remain_visible_terminal_failures(cron, error_type):
    delivery_id = await fire(cron)
    cron.manager._auto_switch_before_delivery.side_effect = error_type("fixture authority refused")
    await dispatch(cron)
    row = receipt(delivery_id)
    assert row["state"] == "FAILED_BEFORE_SUBMIT"
    resource = deliveries._resource(row)
    assert resource["error"]["code"] == "DELIVERY_NOT_SUBMITTED"
    assert "fixture authority refused" in resource["error"]["message"]
    cron.session.send.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("acknowledged", [False, True])
async def test_ambiguous_provider_ack_is_never_automatically_replayed(cron, acknowledged):
    delivery_id = await fire(cron)

    async def lose_ack(message, *, delivery, provenance):
        await delivery.before_submit()
        cron.started.append(message)
        if acknowledged:
            await delivery.mark_submitted("fixture-turn")
        raise RuntimeError("fixture lost acknowledgement")

    cron.session.send.side_effect = lose_ack
    if acknowledged:
        await dispatch(cron)
    else:
        with pytest.raises(RuntimeError, match="lost acknowledgement"):
            await dispatch(cron)
    await deliveries.recover_message_deliveries()
    await dispatch(cron)
    await fire(cron)
    assert len(cron.started) == 1
    assert cron.spawn.await_count == 1
    assert receipt(delivery_id)["state"] == ("SUBMITTED" if acknowledged else "DELIVERY_UNKNOWN_ORPHANED")


@pytest.mark.asyncio
async def test_quota_hold_uses_existing_queue_and_release(cron, monkeypatch):
    from app import quota_queue, initial_delivery_events
    from app.quota_gate import QuotaGateError
    from tests.test_quota_wait_queue import _decision

    delivery_id = await fire(cron)
    provider = cron.session.send.side_effect
    cron.session.send.side_effect = QuotaGateError(_decision(20))
    assert not await dispatch(cron)
    row = receipt(delivery_id)
    assert row["state"] == "WAITING_QUOTA"
    assert row["user_log_id"] is None
    await deliveries.recover_message_deliveries()
    assert not await dispatch(cron)
    cron.session.send.side_effect = provider
    monkeypatch.setattr(quota_queue, "_admission_allows", AsyncMock(return_value=(True, None)))
    monkeypatch.setattr(initial_delivery_events, "ensure_runner", lambda *args: None)
    assert await quota_queue.release_waiting() == 1
    await dispatch(cron)
    assert receipt(delivery_id)["state"] == "SUBMITTED"
    assert len(cron.started) == 1
    assert cron.spawn.await_count == 1


@pytest.mark.asyncio
async def test_cancel_during_command_prevents_acceptance(cron):
    async def cancel_on_finish(proc):
        db.bg_cancel_job("fixture-cron")
        return b"MATCH", b""

    cron.communicate.side_effect = cancel_on_finish
    delivery_id = await fire(cron)
    assert receipt(delivery_id) is None
    assert "fire_count" not in json.loads(db.bg_get_job("fixture-cron")["config"])


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["cancel", "expire", "retarget"])
async def test_eligibility_is_rechecked_atomically_after_target_loading(cron, change):
    async def load(session_id):
        with db._conn() as connection:
            if change == "cancel":
                connection.execute("UPDATE bg_jobs SET status='cancelled' WHERE id='fixture-cron'")
            elif change == "expire":
                expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
                connection.execute("UPDATE bg_jobs SET expires_at=? WHERE id='fixture-cron'", (expired,))
            else:
                connection.execute("UPDATE bg_jobs SET target_session_id='other-fixture' WHERE id='fixture-cron'")
        return cron.session

    cron.manager.ensure_loaded_by_id.side_effect = load
    delivery_id = await fire(cron)
    assert receipt(delivery_id) is None
    assert "fire_count" not in json.loads(db.bg_get_job("fixture-cron")["config"])
    cron.session.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_acceptance_failure_rolls_back_fire_marker(cron):
    with db._conn() as connection:
        connection.execute("""CREATE TRIGGER fixture_refuse_acceptance BEFORE INSERT ON message_deliveries
                              BEGIN SELECT RAISE(ABORT, 'fixture transaction failure'); END""")
    delivery_id = await fire(cron)
    assert receipt(delivery_id) is None
    assert "fire_count" not in json.loads(db.bg_get_job("fixture-cron")["config"])
    cron.session.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_lost_commit_ack_keeps_one_atomic_fire(cron, monkeypatch):
    connect = db._conn

    class LostAck:
        def __init__(self):
            self.inner = connect()

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def commit(self):
            self.inner.commit()
            raise sqlite3.OperationalError("fixture lost acceptance acknowledgement")

    # Wrap only the connection used by acceptance, leaving all normal reads intact.
    accept = deliveries.accept_message_delivery

    async def lose_acceptance_ack(**kwargs):
        first = True

        def connection():
            nonlocal first
            if first:
                first = False
                return LostAck()
            return connect()

        with monkeypatch.context() as patch:
            patch.setattr(db, "_conn", connection)
            return await accept(**kwargs)

    monkeypatch.setattr(deliveries, "accept_message_delivery", lose_acceptance_ack)
    delivery_id = await fire(cron)
    assert receipt(delivery_id)["state"] == "QUEUED"
    await fire(cron)
    await dispatch(cron)
    assert len(cron.started) == 1
    assert cron.spawn.await_count == 1
    assert json.loads(db.bg_get_job("fixture-cron")["config"])["fire_count"] == 1


@pytest.mark.asyncio
async def test_runner_cancel_before_submit_retains_accepted_cron(cron):
    delivery_id = await fire(cron)
    provider = cron.session.send.side_effect
    cron.session.send.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await dispatch(cron)
    assert receipt(delivery_id)["state"] == "QUEUED"
    assert receipt(delivery_id)["user_log_id"] is None
    cron.session.send.side_effect = provider
    await deliveries.recover_message_deliveries()
    await dispatch(cron)
    assert len(cron.started) == 1
    assert cron.spawn.await_count == 1


@pytest.mark.asyncio
async def test_restore_active_schedule_does_not_rerun_accepted_command(cron, monkeypatch):
    delivery_id = await fire(cron)
    restored = []
    replacement = BgJobManager()
    replacement.set_session_manager(cron.manager)
    monkeypatch.setattr(replacement, "_start_task", lambda *args, **kwargs: restored.append(args))
    await replacement.restore_from_db()
    assert len(restored) == 1
    assert restored[0][1] == "cron_command"
    assert restored[0][2]["cron_expr"] == "* * * * *"
    assert receipt(delivery_id)["state"] == "QUEUED"
    await deliveries.recover_message_deliveries()
    await dispatch(cron)
    assert cron.spawn.await_count == 1
    assert len(cron.started) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_task", [False, True])
async def test_failed_steer_recovery_keeps_body_and_generation_in_durable_owner(cron, changed_task):
    delivery_id = await fire(cron)
    accepted = receipt(delivery_id)
    provider = cron.session.send.side_effect

    async def steer(message, *, delivery, provenance):
        delivery.mark_running_steer()
        await provider(message, delivery=delivery, provenance=provenance)

    cron.session.send.side_effect = steer
    await dispatch(cron)
    assert deliveries.requeue_failed_turn(cron.session.id, "fixture-turn") == 1
    assert deliveries.requeue_failed_turn(cron.session.id, "fixture-turn") == 0
    with db._conn() as connection:
        assert connection.execute("SELECT count(*) FROM mailbox").fetchone()[0] == 0
    cron.session.send.side_effect = provider
    if changed_task:
        cron.session.task_id = "other-fixture-task"
    await deliveries.recover_message_deliveries()
    await dispatch(cron)
    if changed_task:
        assert receipt(delivery_id)["state"] == "FAILED_BEFORE_SUBMIT"
        assert len(cron.started) == 1
    else:
        assert receipt(delivery_id)["state"] == "SUBMITTED"
        assert len(cron.started) == 2
        assert cron.started[1][0] == accepted["rendered_message"]
    for key in ("message", "rendered_message", "target_generation", "origin_detail"):
        assert receipt(delivery_id)[key] == accepted[key]
    assert cron.spawn.await_count == 1


@pytest.mark.asyncio
async def test_recovered_pending_text_does_not_attach_referenced_private_file(cron, tmp_path, monkeypatch):
    from app import hub_workspace as hw
    from app.backend_hub import HubBackend
    from tests.test_hub_workspace import FakeSsh

    private = tmp_path / "COMPANY-DATA.md"
    marker = "synthetic local record must never be attached"
    private.write_text(marker)
    cron.communicate.return_value = (f"MATCH\nfile_path={private}\n".encode(), b"")
    monkeypatch.setattr(hw, "STATE_DIR", tmp_path / "fixture-hub-state")
    monkeypatch.setattr(hw, "known_secret_values", lambda extra=None: [])
    remote = tmp_path / hw.WorkspaceState.new_id()
    remote.mkdir()
    state = hw.WorkspaceState(remote.name, str(tmp_path), str(remote), thread_id="fixture-thread")
    state.save()
    backend = HubBackend("hub-gpt-6.1-sol", str(tmp_path))
    ssh = FakeSsh(tmp_path)
    ssh.put = AsyncMock(side_effect=AssertionError("text recovery must not upload files"))
    backend._ssh, backend._state, backend._run_id = ssh, state, "fixture-run"
    backend._turn_active = True
    client = SimpleNamespace(tool_call=AsyncMock(return_value={"runId": "fixture-run"}))
    monkeypatch.setattr(backend, "_client", AsyncMock(return_value=client))

    async def submit(message, *, delivery, provenance):
        await delivery.before_submit()
        await backend.send(message)
        await delivery.mark_submitted("fixture-run")

    cron.session.send.side_effect = submit
    cron.manager.begin_drain()
    delivery_id = await fire(cron)
    assert not await dispatch(cron)
    client.tool_call.assert_not_awaited()
    cron.manager.end_drain()
    await deliveries.recover_message_deliveries()
    await dispatch(cron)
    await dispatch(cron)
    assert receipt(delivery_id)["state"] == "SUBMITTED"
    client.tool_call.assert_awaited_once()
    name, args = client.tool_call.await_args.args
    assert name == "t3_thread_send" and args["mode"] == "steer"
    assert str(private) in args["message"] and marker not in args["message"]
    ssh.put.assert_not_awaited()
    assert private.read_text() == marker


@pytest.mark.asyncio
@pytest.mark.parametrize("stdout,stderr", [(b"", b""), (b"no work", b""), (b"\xff\x00", b"")])
async def test_nonmatching_or_empty_source_is_not_fabricated(cron, stdout, stderr):
    cron.communicate.return_value = stdout, stderr
    delivery_id = await fire(cron)
    assert receipt(delivery_id) is None
    assert "fire_count" not in json.loads(db.bg_get_job("fixture-cron")["config"])
