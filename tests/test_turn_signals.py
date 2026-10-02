"""V-680 — the parent is woken exactly once when a worker turn ends without a report.

Real SQLite, real AgentSession turn-end paths, real manager callback; only the parent's
inbox (`manager.send`) is a recording fake.
"""
import asyncio
import uuid
from datetime import datetime, timezone

import pytest

from app import turn_signals
from app.events import MessageProvenance
from app.session import AgentSession, AgentStatus

SCOPE = "/proj"


def _row(sid, name, *, parent_id="", parent_name="", orch=False, status="idle"):
    return {
        "id": sid, "name": name, "scope": SCOPE, "cwd": SCOPE, "model": "claude-sonnet-5-5",
        "system_prompt": "", "status": status, "session_id": None, "cost_usd": 0.0,
        "worktree_path": "", "branch": "", "base_branch": "main", "is_orchestrator": orch,
        "color": "", "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None, "task_id": "", "needs_switch": 0,
        "parent_id": parent_id, "parent_name": parent_name,
        "role": "orchestrator" if orch else "worker",
    }


class FakeManager:
    """Parent inbox + the three lookups `turn_signals` uses."""

    def __init__(self):
        self.sessions = {}
        self.sent = []
        self.fail_with = None

    async def send(self, session_id, message, *, provenance):
        if self.fail_with is not None:
            raise self.fail_with
        self.sent.append((session_id, message, provenance))

    async def ensure_loaded_by_id(self, session_id):
        from app import db
        row = db.get_session(session_id)
        return type("S", (), {"id": row["id"], "name": row["name"]})() if row else None

    async def ensure_loaded(self, name, scope):
        from app import db
        row = db.get_session_by_name(name, scope)
        return type("S", (), {"id": row["id"], "name": row["name"]})() if row else None

    def _context_warning(self, _name):
        return ""

    def _find_orchestrator_name(self, _scope):
        return None


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.DB_PATH", tmp_path / "t.db")
    from app import db
    db.init_db()
    turn_signals._inflight.clear()
    parent_id = str(uuid.uuid4())
    db.save_session(_row(parent_id, "boss", orch=True))
    w = {"parent_id": parent_id, "manager": FakeManager(), "workers": {}}

    def add_worker(name):
        sid = str(uuid.uuid4())
        db.save_session(_row(sid, name, parent_id=parent_id, parent_name="boss"))
        w["workers"][name] = sid
        return sid

    w["add_worker"] = add_worker
    w["worker_id"] = add_worker("w1")
    return w


def _session(world, name="w1"):
    """A real AgentSession whose end-of-turn callback is the real manager callback."""
    from app.manager import SessionManager

    s = AgentSession(id=world["workers"][name], name=name, scope=SCOPE, cwd=SCOPE)
    s.parent_name = "boss"
    s.parent_id = world["parent_id"]
    s.status = AgentStatus.RUNNING
    s._last_turn_ok = True
    s._turn_logs = ["some work"]
    s._persist = lambda *a, **k: None
    s._log = lambda *a, **k: None
    s._hibernate.schedule = lambda *a, **k: None
    s._turn_gen = 7
    s.on_idle = SessionManager._make_idle_callback(world["manager"], SCOPE)
    world["manager"].sessions[s.id] = s
    return s


async def _settle(session):
    if session._auto_report_task is not None:
        await session._auto_report_task


@pytest.mark.asyncio
async def test_unreported_clean_end_wakes_parent_once_even_if_noticed_twice(world):
    s = _session(world)
    s._turns.fire_auto_report()
    await _settle(s)
    s._turns.fire_auto_report()  # a second code path noticing the same turn
    await _settle(s)

    sent = world["manager"].sent
    assert [m[0] for m in sent] == [world["parent_id"]]
    assert "[from:w1]" in sent[0][1]


@pytest.mark.asyncio
async def test_explicit_done_gives_no_extra_wake(world):
    s = _session(world)
    s._did_report = True
    s._turns.fire_auto_report()
    await _settle(s)

    assert world["manager"].sent == []


@pytest.mark.asyncio
@pytest.mark.parametrize("ending", ["listener_died", "continuation_failed", "failed_turn_end"])
async def test_every_abnormal_ending_wakes_parent_exactly_once(world, ending):
    s = _session(world)
    if ending == "listener_died":
        s._finish_failed_running_turn("listen task exception: boom")
    elif ending == "continuation_failed":
        s._turn_start_cancel_gen = 0
        assert s._finish_failed_continuation((s._turn_gen, s._turn_start_cancel_gen))
    else:
        s._last_turn_ok = False
        s._turns.fire_auto_report()
    await _settle(s)

    sent = world["manager"].sent
    assert len(sent) == 1 and sent[0][0] == world["parent_id"]
    assert "Turn failed before an explicit report" in sent[0][1]


@pytest.mark.asyncio
async def test_new_turn_starting_does_not_swallow_previous_turns_signal(world):
    s = _session(world)
    s._turns.fire_auto_report()
    s._turns.bump_turn_gen()  # next turn begins before the report task got to run
    await asyncio.sleep(0.05)

    assert len(world["manager"].sent) == 1


@pytest.mark.asyncio
async def test_failed_delivery_is_retried_until_accepted_then_never_repeated(world):
    s = _session(world)
    world["manager"].fail_with = RuntimeError("parent draining")
    s._turns.fire_auto_report()
    await _settle(s)
    assert world["manager"].sent == []

    from app import db
    with db._conn() as c:
        row = c.execute("SELECT state, attempts, next_attempt_at FROM turn_signals").fetchone()
        assert (row["state"], row["attempts"]) == ("pending", 1)
        assert row["next_attempt_at"] > 0
        c.execute("UPDATE turn_signals SET next_attempt_at=0")

    world["manager"].fail_with = None
    assert await turn_signals.deliver_due(world["manager"]) == 1
    assert await turn_signals.deliver_due(world["manager"]) == 0
    assert len(world["manager"].sent) == 1


@pytest.mark.asyncio
async def test_pending_signal_survives_restart_and_is_delivered_once(world):
    s = _session(world)
    world["manager"].fail_with = RuntimeError("Orchestra restarting")
    s._turns.fire_auto_report()
    await _settle(s)

    # "restart": a fresh process has an empty in-memory state and a new manager
    turn_signals._inflight.clear()
    from app import db
    with db._conn() as c:
        c.execute("UPDATE turn_signals SET next_attempt_at=0")
    after = FakeManager()
    assert await turn_signals.deliver_due(after) == 1
    assert await turn_signals.deliver_due(after) == 0
    assert len(after.sent) == 1


@pytest.mark.asyncio
async def test_crash_after_parent_accepted_does_not_resend(world):
    from app import db

    sid = world["worker_id"]
    signal_id = turn_signals.record(
        key="k1", worker_session_id=sid, worker_name="w1", scope=SCOPE,
        turn_ok=True, stop_reason="", summary="x",
    )
    # the parent's log already holds the message: process died before the row was marked
    db.add_log(
        world["parent_id"], datetime.now(timezone.utc), "user_message", "[from:w1] ...",
        provenance=MessageProvenance(
            origin="agent", senders=("w1",), subtype="auto_report",
            ref=turn_signals._ref([signal_id]),
        ),
    )
    assert await turn_signals.deliver_due(world["manager"]) == 0
    assert world["manager"].sent == []
    with db._conn() as c:
        assert c.execute("SELECT state FROM turn_signals").fetchone()["state"] == "delivered"


@pytest.mark.asyncio
async def test_restart_interrupted_turns_wake_each_parent_once_with_one_message(world):
    from app import db

    w2 = world["add_worker"]("w2")
    w3 = world["add_worker"]("w3-reported")
    # w3 had already told the parent during its interrupted turn
    t0 = datetime.now(timezone.utc)
    db.add_log(w3, t0, "user_message", "task", provenance=MessageProvenance(
        origin="agent", senders=("boss",), subtype="direct_message"))
    db.add_log(world["parent_id"], datetime.now(timezone.utc), "user_message", "DONE",
               provenance=MessageProvenance(
                   origin="agent", senders=("w3-reported",), subtype="direct_message"))
    rows = [db.get_session(i) for i in (world["worker_id"], w2, w3)]
    rows.append(db.get_session(world["parent_id"]))  # orchestrator: never signalled

    assert turn_signals.record_interrupted_by_restart(rows) == 2
    assert turn_signals.record_interrupted_by_restart(rows) == 0  # same boot, same turns

    assert await turn_signals.deliver_due(world["manager"]) == 2
    sent = world["manager"].sent
    assert len(sent) == 1, "two interrupted workers of one parent must be one wake-up"
    assert "[from:w1]" in sent[0][1] and "[from:w2]" in sent[0][1]
    assert "w3-reported" not in sent[0][1]


@pytest.mark.asyncio
async def test_signal_without_any_parent_is_dropped_not_retried_forever(world):
    from app import db

    sid = str(uuid.uuid4())
    db.save_session(_row(sid, "orphan"))
    turn_signals.record(
        key="k2", worker_session_id=sid, worker_name="orphan", scope=SCOPE,
        turn_ok=True, stop_reason="", summary="x",
    )
    assert await turn_signals.deliver_due(world["manager"]) == 0
    with db._conn() as c:
        assert c.execute("SELECT state FROM turn_signals").fetchone()["state"] == "dropped"
