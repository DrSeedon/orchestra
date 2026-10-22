"""V-1028: quota holds stay gated, visible and recoverable, with one upstream notice."""

import asyncio
import uuid
from datetime import datetime, timezone

import pytest

from app import db, message_deliveries, report_holds, turn_signals
from app.events import InjectedMessage, MessageProvenance
from app.quota_gate import QuotaGateError
from tests.test_quota_wait_queue import _decision
from tests.test_turn_signals import FakeManager, _row, _session, _settle, world  # noqa: F401


class Manager(FakeManager):
    blocked = True
    notice_failure = ""

    async def send(self, session_id, message, *, provenance):
        from app.session import QUOTA_GATE_EXEMPT_ORIGINS

        if session_id == self.parent_id and self.blocked and provenance.origin not in QUOTA_GATE_EXEMPT_ORIGINS:
            raise QuotaGateError(_decision(20))
        if isinstance(message, InjectedMessage):
            if self.notice_failure == "before":
                raise RuntimeError("upstream offline")
            db.add_log(session_id, datetime.now(timezone.utc), "user_message", message.text,
                       event_id=message.event_id, provenance=provenance)
        self.sent.append((session_id, message, provenance))
        if isinstance(message, InjectedMessage) and self.notice_failure == "after":
            raise RuntimeError("crash after acceptance")

    async def send_message_delivery(self, session_id, message, *, delivery, **kwargs):
        if self.blocked:
            raise QuotaGateError(_decision(20))
        await delivery.before_submit()
        await delivery.mark_submitted(provider_ref="accepted")
        self.sent.append((session_id, message, kwargs["provenance"]))


@pytest.fixture
def tree(world, monkeypatch):
    from app import deps

    db.save_session(_row("top", "top", orch=True))
    db.save_session(_row(world["parent_id"], "boss", parent_id="top", parent_name="top"))
    manager = Manager()
    manager.parent_id = world["parent_id"]
    world["manager"] = manager
    monkeypatch.setattr(deps, "manager", manager)
    monkeypatch.setattr(report_holds, "_recovery_task", None)
    monkeypatch.setattr(report_holds, "_rescan_requested", False)
    report_holds._inflight.clear()
    return world


def _notice_rows():
    with db._conn() as connection:
        return [dict(r) for r in connection.execute("SELECT * FROM report_hold_notices")]


def _status_logs(worker_id):
    with db._conn() as connection:
        return connection.execute(
            "SELECT content FROM logs WHERE session_id=? AND event_id LIKE 'report-held:%'",
            (worker_id,),
        ).fetchall()


async def _signal(tree):
    session = _session(tree)
    session._turns.fire_auto_report()
    await _settle(session)
    await _settle_notices()
    return session


async def _settle_notices():
    task = report_holds._recovery_task
    if task is not None:
        await task
    followup = report_holds._recovery_task
    if followup is not None and followup is not task:
        await followup


def _retry_signals():
    with db._conn() as connection:
        connection.execute("UPDATE turn_signals SET next_attempt_at=0")


@pytest.mark.asyncio
async def test_signal_hold_visible_once_and_original_report_stays_gated(tree):
    await _signal(tree)
    manager = tree["manager"]
    with db._conn() as connection:
        row = connection.execute("SELECT * FROM turn_signals").fetchone()
    assert row["state"] == "pending" and row["attempts"] == 1
    assert row["last_error"].startswith("QuotaGateError:")
    assert [m[0] for m in manager.sent] == ["top"]
    text = str(manager.sent[0][1])
    assert "boss" in text and "hubsol" in text and "hubsonnet/hubopus" in text
    assert "model_reason" in text and "quota" in text
    assert "some work" not in text, "the diagnostic must not forward the held report"
    assert manager.sent[0][2].origin == "platform"
    assert len(_status_logs(tree["worker_id"])) == 1
    assert report_holds.status_map()[tree["worker_id"]]["count"] == 1

    for _ in range(2):
        _retry_signals()
        assert await turn_signals.deliver_due(manager) == 0
    await asyncio.gather(report_holds.recover(manager), report_holds.recover(manager))
    assert len(manager.sent) == 1
    assert len(_status_logs(tree["worker_id"])) == 1

    manager.blocked = False
    _retry_signals()
    assert await turn_signals.deliver_due(manager) == 1
    assert manager.sent[-1][0] == tree["parent_id"]
    assert manager.sent[-1][2].origin == "agent"
    assert report_holds.status_map() == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["before", "after"])
async def test_notice_recovery_and_crash_after_acceptance_do_not_lose_or_repeat_notice(
    tree, failure,
):
    manager = tree["manager"]
    manager.notice_failure = failure
    await _signal(tree)
    assert _notice_rows()[0]["notified_at"] is None
    manager.notice_failure = ""
    report_holds._inflight.clear()  # a fresh process
    # Signals are still in backoff: recovery must not wait for their due date.
    assert await turn_signals.deliver_due(manager, []) == 0
    await _settle_notices()
    assert _notice_rows()[0]["notified_at"]
    assert len(manager.sent) == 1
    assert len(_status_logs(tree["worker_id"])) == 1


async def _accept(tree, *, parked, target=None, settle=True):
    target = target or tree["parent_id"]
    receipt = await message_deliveries.accept_message_delivery(
        delivery_id=str(uuid.uuid4()), source_session_id=tree["worker_id"],
        source_name="w1", source_scope="/proj", target_session_id=target,
        target_name="boss" if target == tree["parent_id"] else "top",
        target_scope="/proj", target_generation="test-generation", message="private report body",
        rendered_message="[from:w1] private report body",
        provenance=MessageProvenance("agent", ("w1",), subtype="direct_message"),
        quota_wait=_decision(20) if parked else None,
    )
    if settle:
        await _settle_notices()
    return receipt


@pytest.mark.asyncio
async def test_explicit_report_parked_at_acceptance_is_visible_and_notified(tree):
    receipt, code = await _accept(tree, parked=True)
    assert code == 202 and receipt["delivery_state"] == "WAITING_QUOTA"
    assert [m[0] for m in tree["manager"].sent] == ["top"]
    assert report_holds.status_map()[tree["worker_id"]]["parent_name"] == "boss"
    assert len(_status_logs(tree["worker_id"])) == 1
    assert "private report body" not in str(tree["manager"].sent[0][1])
    await report_holds.recover(tree["manager"])
    assert len(tree["manager"].sent) == 1
    message_deliveries.cancel_message_delivery(receipt["delivery_id"], tree["worker_id"])
    assert report_holds.status_map() == {}


@pytest.mark.asyncio
async def test_gate_closes_after_acceptance_and_release_clears_hold(tree, monkeypatch):
    monkeypatch.setattr(message_deliveries, "ensure_target_runner", lambda *_: None)
    receipt, _ = await _accept(tree, parked=False)
    await message_deliveries.run_message_delivery(receipt["delivery_id"], tree["manager"])
    await _settle_notices()
    held = message_deliveries.get_message_delivery(receipt["delivery_id"], tree["worker_id"])
    assert held["delivery_state"] == "WAITING_QUOTA"
    assert len(tree["manager"].sent) == 1
    from app import quota_queue

    monkeypatch.setattr(quota_queue, "_admission_allows", lambda *_: _allowed())
    assert await quota_queue.release_waiting() == 1
    assert report_holds.status_map() == {}
    tree["manager"].blocked = False
    await message_deliveries.run_message_delivery(receipt["delivery_id"], tree["manager"])
    assert tree["manager"].sent[-1][0] == tree["parent_id"]
    assert len(tree["manager"].sent) == 2


async def _allowed():
    return True, None


@pytest.mark.asyncio
async def test_old_waiting_delivery_is_discovered_without_new_acceptance(tree, monkeypatch):
    # Reproduce a receipt parked before this code existed.
    original = report_holds.recover
    async def no_observation(*_):
        pass
    monkeypatch.setattr(report_holds, "recover", no_observation)
    await _accept(tree, parked=True)
    assert tree["manager"].sent == []
    monkeypatch.setattr(report_holds, "recover", original)
    await original(tree["manager"])
    assert len(tree["manager"].sent) == 1


@pytest.mark.asyncio
async def test_report_queued_behind_quota_wait_is_also_visible(tree, monkeypatch):
    monkeypatch.setattr(message_deliveries, "ensure_target_runner", lambda *_: None)
    first, _ = await _accept(tree, parked=True)
    second, _ = await _accept(tree, parked=False)
    assert second["delivery_state"] == "QUEUED"
    assert report_holds.status_map()[tree["worker_id"]]["count"] == 2
    assert len(tree["manager"].sent) == 2
    message_deliveries.cancel_message_delivery(first["delivery_id"], tree["worker_id"])
    assert report_holds.status_map() == {}


@pytest.mark.asyncio
async def test_name_only_parent_links_and_malformed_old_error_do_not_break_status(tree):
    worker = db.get_session(tree["worker_id"])
    worker["parent_id"] = ""
    db.save_session(worker)
    parent = db.get_session(tree["parent_id"])
    parent["parent_id"] = ""
    db.save_session(parent)
    receipt, _ = await _accept(tree, parked=True)
    with db._conn() as connection:
        connection.execute("UPDATE message_deliveries SET error_json='[' WHERE delivery_id=?",
                           (receipt["delivery_id"],))
    assert report_holds.status_map()[tree["worker_id"]]["parent_name"] == "boss"
    assert len(tree["manager"].sent) == 1


@pytest.mark.asyncio
async def test_slow_notice_cannot_delay_acceptance_or_quota_release(tree, monkeypatch):
    from app import quota_queue

    entered, release = asyncio.Event(), asyncio.Event()
    original = tree["manager"].send

    async def slow_notice(session_id, message, *, provenance):
        if session_id == "top":
            entered.set()
            await release.wait()
        await original(session_id, message, provenance=provenance)

    monkeypatch.setattr(tree["manager"], "send", slow_notice)
    monkeypatch.setattr(message_deliveries, "ensure_target_runner", lambda *_: None)
    try:
        receipt, _ = await asyncio.wait_for(_accept(tree, parked=True, settle=False), 1)
        assert receipt["delivery_state"] == "WAITING_QUOTA"
        await asyncio.wait_for(entered.wait(), 1)
        assert report_holds.status_map()[tree["worker_id"]]
        monkeypatch.setattr(quota_queue, "_admission_allows", lambda *_: _allowed())
        assert await asyncio.wait_for(quota_queue.release_waiting(), 1) == 1
    finally:
        release.set()
        await _settle_notices()
    assert len(tree["manager"].sent) == 1


@pytest.mark.asyncio
async def test_detached_upstream_is_loaded_and_unavailable_upstream_retries(tree, monkeypatch):
    original = tree["manager"].ensure_loaded_by_id
    attempts = []
    unavailable = True

    async def lookup(session_id):
        if session_id == "top":
            attempts.append(session_id)
            if unavailable:
                return None
        return await original(session_id)

    monkeypatch.setattr(tree["manager"], "ensure_loaded_by_id", lookup)
    await _accept(tree, parked=True)
    assert _notice_rows()[0]["notified_at"] is None
    assert tree["manager"].sent == []
    unavailable = False
    await report_holds.recover(tree["manager"])
    assert attempts == ["top", "top"]
    assert len(tree["manager"].sent) == 1


@pytest.mark.asyncio
async def test_nonparent_delivery_and_nonquota_signal_do_not_raise_false_alert(tree):
    await _accept(tree, parked=True, target="top")
    assert report_holds.status_map() == {}
    signal_id = turn_signals.record(
        key="non-quota", worker_session_id=tree["worker_id"], worker_name="w1", scope="/proj",
        turn_ok=False, stop_reason="error", summary="failed",
    )
    turn_signals._retry_later([signal_id], "RuntimeError: parent offline")
    await report_holds.recover(tree["manager"])
    assert tree["manager"].sent == []


@pytest.mark.asyncio
async def test_list_sessions_exposes_hold_for_detached_worker_and_clears_on_delivery(tree):
    from app.manager import SessionManager

    await _signal(tree)
    manager = SessionManager()
    manager.lifecycle_quarantine = lambda *_: None
    listed = {r["id"]: r for r in manager.list_sessions("/proj")}
    hold = listed[tree["worker_id"]].get("report_quota_hold")
    assert hold is not None
    assert hold["parent_name"] == "boss"
    assert "report_quota_hold" not in listed[tree["parent_id"]]
    with db._conn() as connection:
        connection.execute("UPDATE turn_signals SET state='delivered'")
    listed = {r["id"]: r for r in manager.list_sessions("/proj")}
    assert "report_quota_hold" not in listed[tree["worker_id"]]


@pytest.mark.asyncio
async def test_top_level_parent_has_no_upstream_but_worker_status_is_visible(world):
    manager = Manager()
    manager.parent_id = world["parent_id"]
    world["manager"] = manager
    await _signal(world)
    assert manager.sent == []
    assert len(_status_logs(world["worker_id"])) == 1
    assert report_holds.status_map()[world["worker_id"]]
