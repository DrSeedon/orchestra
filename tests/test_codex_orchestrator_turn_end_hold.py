"""02.11 «Codex stable and sharp like Claude»: a Codex orchestrator's running turn.

1: background / cron input waits for turn end across age/count escapes; worker
   reports retain their escalation/age/count escapes. Owner input still steers.
2: a delivered batch puts the owner's messages first, the rest in arrival order.
3: the idle precompact timer is cancelled only by a turn that really starts.
No provider CLI, no live DB: every database is a tmp file.
"""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app import db, mailbox, message_deliveries as deliveries
from app.events import MessageProvenance
from app.session import AgentSession, AgentStatus
from app.session_turns import TURN_END_HOLD_MAX_TURN_SECONDS, TURN_END_HOLD_MAX_WAITING

USER = MessageProvenance(origin="user", senders=("user",), subtype="telegram")
WORKER = MessageProvenance(origin="agent", senders=("worker-a",), subtype="http_send")
BG = MessageProvenance(origin="background_task", senders=("job-1",), subtype="done", ref="job-1")
IDS = [f"00000000-0000-4000-8000-0000000002{n:02d}" for n in range(20)]


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "turn-end-hold.db")
    db.init_db()
    monkeypatch.setattr(deliveries, "ensure_target_runner", lambda _target: None)
    monkeypatch.setattr(deliveries, "notify_message_delivery_failure", AsyncMock())
    yield
    for session in _SESSIONS:
        _close(session)
    _SESSIONS.clear()


_SESSIONS = []


def _session(backend_type="codex", *, role="orchestrator"):
    session = AgentSession(
        id=f"hold-{backend_type}-{role}", name=f"hold-{backend_type}-{role}",
        scope="/repo", cwd="/repo", role=role, backend_type=backend_type,
        model="gpt-6.1-sol" if backend_type == "codex" else "claude-sonnet-5-5[1m]",
        created_at=datetime.now(timezone.utc),
    )
    db.save_session({
        "id": session.id, "name": session.name, "scope": session.scope,
        "cwd": session.cwd, "model": session.model, "system_prompt": "",
        "status": "running", "session_id": None, "cost_usd": 0.0,
        "worktree_path": "", "branch": "", "is_orchestrator": role == "orchestrator",
        "color": "", "created_at": session.created_at.isoformat(), "finished_at": None,
    })
    session._log = MagicMock()
    session._persist = MagicMock()
    backend = MagicMock(send=AsyncMock(), active_turn_id="turn-running")
    backend.deferred_interrupt_pending = False
    session._backend = backend
    session._ensure_backend = AsyncMock(return_value=backend)
    session._attach_pending_facts = lambda message: (message, [])
    session._ack_pending_facts = MagicMock()
    session._last_context = {"known": True, "total_tokens": 1000, "max_tokens": 872_000,
                             "percentage": 1}
    session.status = AgentStatus.RUNNING
    session._turn_start = asyncio.get_event_loop().time()
    spawned = []
    session._spawn_bg = lambda coroutine: spawned.append(coroutine) or MagicMock()
    session.spawned = spawned
    _SESSIONS.append(session)
    return session


def _close(session):
    for coroutine in session.spawned:
        coroutine.close()
    session.spawned.clear()


def _statuses(session):
    return [c.args[1] for c in session._log.call_args_list if c.args[0] == "status"]


def _steered(session):
    return [c.args[0] for c in session._backend.send.await_args_list]


class _Manager:
    def __init__(self, session):
        self.session = session

    async def send_message_delivery(self, session_id, message, *, delivery,
                                    target_generation, provenance):
        await self.session.send(message, delivery=delivery, provenance=provenance)


async def _deliver(session, delivery_id, text, *, kind=None, origin="agent"):
    provenance = MessageProvenance(
        origin=origin, senders=("worker-a",), subtype="direct_message", ref=delivery_id,
    ) if origin != "user" else MessageProvenance(
        origin="user", senders=("user",), subtype="direct_message", ref=delivery_id,
    )
    await deliveries.accept_message_delivery(
        delivery_id=delivery_id, source_name="worker-a", source_scope=session.scope,
        target_session_id=session.id, target_name=session.name, target_scope=session.scope,
        target_generation="generation", message=text, rendered_message=f"[from:worker-a] {text}",
        message_kind=kind, provenance=provenance,
    )
    await deliveries.run_target_message_deliveries(session.id, manager=_Manager(session))


async def _parked_listener():
    await asyncio.Event().wait()


async def _end_turn(session, *, stopped=False):
    """The turn ends; run the turn-end drain it schedules (if any)."""
    session.status = AgentStatus.IDLE
    session._turn_start = 0
    session._manually_interrupted = stopped
    session._notify_scope_idle = MagicMock(side_effect=lambda: asyncio.sleep(0))
    session._hibernate.schedule = MagicMock()
    session._turns.fire_auto_report = MagicMock()
    session._backend.send.reset_mock()
    session._backend.active_turn_id = "turn-next"
    session._turn_event_loop = _parked_listener
    session._notify_scope_running = AsyncMock()
    session._turns.after_turn_idle_actions(1, allow_precompact=False)
    drains = [c for c in session.spawned if c.__qualname__ == "TurnManager._deliver_mailbox"]
    session.spawned[:] = [c for c in session.spawned if c not in drains]
    for drain in drains:
        await drain
    if session._listen_task is not None:
        session._listen_task.cancel()
    _close(session)
    return len(drains)


# ── 1: held for the turn end ──

@pytest.mark.asyncio
async def test_worker_messages_wait_for_the_turn_end_and_go_out_once_together(tmp_db):
    session = _session()

    await _deliver(session, IDS[0], "first report")
    await _deliver(session, IDS[1], "second report")

    session._backend.send.assert_not_awaited()
    # Held rows do not block the target queue: the second one was processed too.
    assert [deliveries._row(i)["state"] for i in IDS[:2]] == ["WAITING_NEXT_TURN"] * 2
    receipt = deliveries._resource(deliveries._row(IDS[0]))
    assert receipt["next_action"]["code"] == "WAITING_NEXT_TURN"
    assert receipt["provider_ref"] is None
    assert any(s.startswith("message held for the turn end (agent; 2 waiting)")
               for s in _statuses(session))

    assert await _end_turn(session) == 1
    sent = _steered(session)
    assert len(sent) == 1
    assert sent[0].index("first report") < sent[0].index("second report")
    assert [deliveries._row(i)["state"] for i in IDS[:2]] == ["SUBMITTED"] * 2
    assert {deliveries._row(i)["provider_ref"] for i in IDS[:2]} == {"turn-next"}
    assert mailbox.pending(session.name, session.scope) == []
    # The chat showed both at arrival; the drain does not repeat them.
    with db._conn() as connection:
        logs = [r[0] for r in connection.execute(
            "SELECT content FROM logs WHERE type='user_message' ORDER BY id")]
    assert logs == ["[from:worker-a] first report", "[from:worker-a] second report"]
    assert not any(c.args[0] == "user_message" for c in session._log.call_args_list)

    # Exactly once: the next turn end has nothing to deliver.
    session.status = AgentStatus.RUNNING
    assert await _end_turn(session) == 0


@pytest.mark.asyncio
async def test_background_result_is_held_durably_and_delivered_at_the_turn_end(tmp_db):
    session = _session()

    assert await session.send("[Background job done] tests passed", provenance=BG) is None

    session._backend.send.assert_not_awaited()
    rows = mailbox.pending(session.name, session.scope)
    assert [(r["body"], r["provenance"].subtype, r["provenance"].ref) for r in rows] == [
        ("[Background job done] tests passed", "codex_turn_end_hold", "done"),
    ]
    assert await _end_turn(session) == 1
    assert _steered(session) == ["[from:job-1] [Background job done] tests passed"]
    assert mailbox.pending(session.name, session.scope) == []


@pytest.mark.asyncio
async def test_agent_plain_message_keeps_its_time_but_not_a_second_sender_prefix(tmp_db):
    session = _session()
    await session.send("[12:30] [from:worker-a] blocked on review", provenance=WORKER)
    assert [r["body"] for r in mailbox.pending(session.name, session.scope)] == [
        "[12:30] blocked on review",
    ]


@pytest.mark.asyncio
async def test_owner_message_still_steers_immediately(tmp_db):
    session = _session()
    await _deliver(session, IDS[0], "worker report")

    route = await session.send("owner: stop the merge", provenance=USER)

    assert route == ("steer", "turn-running", True)
    assert _steered(session) == ["owner: stop the merge"]
    assert any("steered into active Codex turn" in s for s in _statuses(session))


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["blocked", "out_of_scope", "false_premise"])
async def test_worker_escalation_steers_after_the_held_block(tmp_db, kind):
    session = _session()
    await _deliver(session, IDS[0], "earlier report")

    await _deliver(session, IDS[1], "I am blocked: need a decision", kind=kind)

    assert len(_steered(session)) == 2
    assert "earlier report" in _steered(session)[0]
    assert _steered(session)[1] == "[from:worker-a] I am blocked: need a decision"
    assert deliveries._row(IDS[1])["state"] == "SUBMITTED"
    # The held receipt now names the turn that carries it, so its failure requeues it.
    assert deliveries._row(IDS[0])["provider_ref"] == "steered:turn-running"
    assert mailbox.pending(session.name, session.scope) == []


@pytest.mark.asyncio
async def test_an_ordinary_kind_is_held(tmp_db):
    session = _session()
    await session.send("progress", provenance=WORKER, message_kind="progress")
    session._backend.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_old_turn_steers_worker_but_retains_background_until_turn_end(tmp_db):
    session = _session()
    await session.send("bg one", provenance=BG)
    session._turn_start -= TURN_END_HOLD_MAX_TURN_SECONDS + 1
    await session.send("[from:worker-a] late report", provenance=WORKER)
    assert _steered(session) == ["[from:worker-a] late report"]
    rows = mailbox.pending(session.name, session.scope)
    assert [(r["body"], r["provenance"].subtype) for r in rows] == [
        ("bg one", "codex_turn_end_hold"),
        ("late report", "codex_steer_backup"),
    ]
    await session.send("owner correction", provenance=USER)
    assert _steered(session)[-1] == "owner correction"
    mailbox.complete_codex_steers(session.name, session.scope, "turn-running")
    assert await _end_turn(session) == 1
    assert _steered(session) == ["[from:job-1] bg one"]
    assert mailbox.pending(session.name, session.scope) == []

@pytest.mark.asyncio
async def test_more_than_eight_background_messages_wait_for_turn_end(tmp_db):
    session = _session()
    for n in range(TURN_END_HOLD_MAX_WAITING):
        await session.send(f"bg {n}", provenance=BG)
    await session.send("bg last", provenance=BG)
    session._backend.send.assert_not_awaited()
    rows = mailbox.pending(session.name, session.scope)
    assert len(rows) == TURN_END_HOLD_MAX_WAITING + 1
    assert all(r["provenance"].subtype == "codex_turn_end_hold" for r in rows)
    assert await _end_turn(session) == 1
    assert len(_steered(session)) == 1
    assert all(f"bg {n}" in _steered(session)[0] for n in range(TURN_END_HOLD_MAX_WAITING))
    assert "bg last" in _steered(session)[0]
    assert mailbox.pending(session.name, session.scope) == []

@pytest.mark.asyncio
async def test_age_timer_keeps_background_rows_until_turn_end(tmp_db):
    session = _session()
    await session.send("bg one", provenance=BG)
    timers = [c for c in session.spawned
              if c.__qualname__ == "TurnManager._steer_turn_end_holds_when_turn_ages"]
    assert len(timers) == 1
    await session.send("bg two", provenance=BG)
    # One timer per turn.
    assert len([c for c in session.spawned if c.__qualname__.endswith("when_turn_ages")]) == 1
    session.spawned.remove(timers[0])
    timers[0].close()
    session._turn_start -= TURN_END_HOLD_MAX_TURN_SECONDS

    await session._turns._steer_turn_end_holds_when_turn_ages(session._turn_gen)

    session._backend.send.assert_not_awaited()
    assert len(mailbox.pending(session.name, session.scope)) == 2
    mailbox.complete_codex_steers(session.name, session.scope, "turn-running")
    assert len(mailbox.pending(session.name, session.scope)) == 2
    assert await _end_turn(session) == 1
    assert _steered(session) == ["[from:job-1] bg one\n\n[from:job-1] bg two"]
    assert mailbox.pending(session.name, session.scope) == []
    _close(session)

@pytest.mark.asyncio
async def test_age_timer_of_a_finished_turn_does_nothing(tmp_db):
    session = _session()
    await session.send("bg one", provenance=BG)
    _close(session)
    gen = session._turn_gen
    session._turn_gen += 1
    session._turn_start -= TURN_END_HOLD_MAX_TURN_SECONDS

    await session._turns._steer_turn_end_holds_when_turn_ages(gen)

    session._backend.send.assert_not_awaited()
    assert len(mailbox.pending(session.name, session.scope)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("backend_type,role", [("codex", "worker"), ("claude", "orchestrator")])
async def test_workers_and_claude_keep_steering(tmp_db, backend_type, role):
    session = _session(backend_type, role=role)

    await _deliver(session, IDS[0], "report")
    await session.send("bg result", provenance=BG)

    assert len(_steered(session)) == 2
    assert deliveries._row(IDS[0])["state"] == "SUBMITTED"
    assert not any(r["provenance"].subtype in {"codex_turn_end_hold", "direct_message_recovery"}
                   for r in mailbox.pending(session.name, session.scope))


@pytest.mark.asyncio
async def test_cron_is_held_with_its_rendered_body(tmp_db):
    session = _session()
    provenance = MessageProvenance(
        origin="background_task", senders=("job-c",), subtype="cron", ref="job-c",
    )
    await deliveries.accept_message_delivery(
        delivery_id=IDS[5], source_principal="background_job:job-c", source_name="job-c",
        source_scope=session.scope, target_session_id=session.id, target_name=session.name,
        target_scope=session.scope, target_generation="generation",
        message="raw command output", rendered_message="[Cron command matched] check",
        message_kind="background_task", provenance=provenance,
    )
    await deliveries.run_target_message_deliveries(session.id, manager=_Manager(session))

    session._backend.send.assert_not_awaited()
    assert [r["body"] for r in mailbox.pending(session.name, session.scope)] == [
        "[Cron command matched] check",
    ]
    assert await _end_turn(session) == 1
    assert deliveries._row(IDS[5])["state"] == "SUBMITTED"


@pytest.mark.asyncio
async def test_failed_turn_after_flush_requeues_the_held_receipt(tmp_db):
    session = _session()
    await _deliver(session, IDS[0], "report")
    session._turn_start -= TURN_END_HOLD_MAX_TURN_SECONDS + 1
    await _deliver(session, IDS[1], "second")

    assert deliveries.requeue_failed_turn(session.id, "turn-running") == 2
    assert [deliveries._row(i)["state"] for i in IDS[:2]] == ["WAITING_NEXT_TURN"] * 2
    assert len(mailbox.pending(session.name, session.scope)) == 2


@pytest.mark.asyncio
async def test_stop_keeps_held_rows_for_the_next_owner_turn_owner_first(tmp_db):
    session = _session()
    await _deliver(session, IDS[0], "worker report")

    assert await _end_turn(session, stopped=True) == 0
    assert session._mailbox_held_after_stop is True
    assert deliveries._row(IDS[0])["state"] == "WAITING_NEXT_TURN"

    session._manually_interrupted = False
    await session.send("owner after stop", provenance=USER)
    session._listen_task.cancel()

    sent = _steered(session)[0].split("<current-user-message>")[-1]
    assert sent.index("owner after stop") < sent.index("worker report")
    assert deliveries._row(IDS[0])["state"] == "SUBMITTED"
    assert mailbox.pending(session.name, session.scope) == []


@pytest.mark.asyncio
async def test_compaction_queue_comes_before_the_hold(tmp_db):
    session = _session()
    session._compacting = True

    await session.send("bg during compaction", provenance=BG)

    assert session._pending_messages == ["bg during compaction"]
    assert mailbox.pending(session.name, session.scope) == []


# ── 2: owner first ──

def _row(body, provenance):
    return mailbox.enqueue("hold-codex-orchestrator", "/repo", provenance.senders[0], body,
                           provenance=provenance)


@pytest.mark.asyncio
async def test_turn_end_batch_puts_the_owner_first(tmp_db):
    session = _session()
    _row("agent early", WORKER)
    _row("owner later", MessageProvenance(origin="unknown", senders=("dashboard",),
                                          subtype="dashboard"))
    _row("bg latest", BG)

    assert await _end_turn(session) == 1

    sent = _steered(session)[0]
    assert sent.index("owner later") < sent.index("agent early") < sent.index("bg latest")
    logged = [c.args for c in session._log.call_args_list if c.args[0] == "user_message"]
    assert logged[0][1].index("owner later") < logged[0][1].index("agent early")


@pytest.mark.asyncio
async def test_queued_flush_puts_the_owner_first(tmp_db):
    session = _session()
    session._compacting = True
    await session.send("agent text", provenance=WORKER)
    await session.send("owner text", provenance=USER)
    await session.send("bg text", provenance=BG)
    session._compacting = False
    session.status = AgentStatus.IDLE
    session._turn_event_loop = _parked_listener

    await session._flush_pending()
    session._listen_task.cancel()

    sent = _steered(session)[0]
    assert sent.index("owner text") < sent.index("agent text") < sent.index("bg text")
    assert session._pending_owner_texts == []


@pytest.mark.asyncio
async def test_held_after_stop_prefix_puts_the_owner_first(tmp_db):
    session = _session()
    held = [
        {"id": 1, "sender": "worker-a", "body": "agent", "provenance": WORKER},
        {"id": 2, "sender": "user", "body": "owner held", "provenance": USER},
    ]
    turns = session._turns

    from_agent = turns.mailbox_turn_text(held, "[from:job-1] new bg")
    from_owner = turns.mailbox_turn_text(held, "owner new", message_is_owner=True)

    assert from_agent.split("\n\n") == [
        "[from:user] owner held", "[from:worker-a] agent", "[from:job-1] new bg",
    ]
    assert from_owner.split("\n\n") == [
        "[from:user] owner held", "owner new", "[from:worker-a] agent",
    ]


# ── 3: the idle precompact timer ──

@pytest.mark.asyncio
async def test_queued_send_keeps_the_precompact_timer_and_a_real_turn_cancels_it(tmp_db):
    session = _session()
    session.status = AgentStatus.IDLE
    timer = {"scheduled_at": datetime.now(timezone.utc).isoformat()}
    session._precompact_timer = dict(timer)
    session._compacting = True

    await session.send("queued while compacting", provenance=WORKER)

    assert session._precompact_timer == timer
    session._compacting = False
    session._pending_messages.clear()
    session._turn_event_loop = _parked_listener
    session._notify_scope_running = AsyncMock()

    await session.send("starts a turn", provenance=USER)
    session._listen_task.cancel()

    assert session._precompact_timer is None
    assert any("precompact timer cancelled" in s and "activity_before_fire" in s
               for s in _statuses(session))


@pytest.mark.asyncio
async def test_held_send_keeps_the_precompact_timer(tmp_db):
    session = _session()
    session._precompact_timer = {"scheduled_at": datetime.now(timezone.utc).isoformat()}

    await session.send("bg", provenance=BG)

    assert session._precompact_timer is not None
    _close(session)


# ── review round: the escape a real worker can reach, the batch race, the cut turn ──

@pytest.mark.asyncio
async def test_turn_end_batch_that_meets_a_running_turn_still_steers(tmp_db):
    """`require_submit` is the turn-end drain: holding it again would loop it forever."""
    session = _session()

    route = await session.send("[from:worker-a] batch", provenance=WORKER, require_submit=True)

    assert route[:2] == ("steer", "turn-running")
    assert _steered(session) == ["[from:worker-a] batch"]
    assert not any(r["provenance"].subtype == "codex_turn_end_hold"
                   for r in mailbox.pending(session.name, session.scope))


@pytest.mark.asyncio
async def test_mcp_send_message_carries_an_escalation_kind(monkeypatch):
    import app.mcp_stdio as m

    payloads = []

    async def fake_api(method, path, **kwargs):
        payloads.append(kwargs["json"])
        return {"ok": True}

    monkeypatch.setattr(m, "SCOPE", "/repo")
    monkeypatch.setattr(m, "WORKER_NAME", "worker-a")
    monkeypatch.setattr(m, "_api", fake_api)

    await m.send_message("orch", "need a decision", kind="Blocked")
    await m.send_message("orch", "done")
    with pytest.raises(m.ApiToolError) as refused:
        await m.send_message("orch", "x", kind="done")

    assert payloads[0]["message_kind"] == "blocked"
    assert "message_kind" not in payloads[1]
    assert refused.value.details == {"field": "kind"} and len(payloads) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,accepted", [("blocked", True), ("done", False)])
async def test_keyed_ingress_takes_only_an_escalation_kind(tmp_db, monkeypatch, kind, accepted):
    from types import SimpleNamespace
    from app.routes import sessions as routes

    session = _session()
    monkeypatch.setattr("app.auth.validate_session", lambda _cookie: True)
    monkeypatch.setattr(routes, "_preflight_or_quota_wait", AsyncMock(return_value=None))
    monkeypatch.setattr(routes.manager, "get_by_name", lambda _name, _scope: session)
    run = AsyncMock()
    monkeypatch.setattr(deliveries, "run_target_message_deliveries", run)

    response = await routes.send_message(
        session.name,
        routes.SendRequest(delivery_id=IDS[9], message="need a decision", scope=session.scope,
                           message_kind=kind),
        request=SimpleNamespace(headers={}, cookies={"session": "operator"}),
    )

    if accepted:
        assert response.status_code < 300
        assert deliveries._row(IDS[9])["message_kind"] == "blocked"
    else:
        assert response.status_code == 400
        assert deliveries._row(IDS[9]) is None


class _SweepManager:
    def __init__(self, session):
        self.sessions = {session.id: session}

    def get_by_name(self, name, scope):
        return next((s for s in self.sessions.values()
                     if s.name == name and s.scope == scope), None)

    async def ensure_loaded_by_id(self, session_id):
        return self.sessions.get(session_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,age,woken", [
    (AgentStatus.IDLE, deliveries.STUCK_WAKE_AFTER_SECONDS + 1, 1),
    (AgentStatus.IDLE, 1, 0),
    (AgentStatus.RUNNING, deliveries.STUCK_WAKE_AFTER_SECONDS + 1, 0),
])
async def test_sweep_delivers_plain_held_rows_of_a_cut_turn(tmp_db, status, age, woken):
    """A turn cut without its end (CLI or service restart) must not strand held rows."""
    session = _session()
    await session.send("[Background job done] tests passed", provenance=BG)
    with db._conn() as connection:
        connection.execute("UPDATE mailbox SET created_at = created_at - ?", (age,))
    session.status = status
    _close(session)

    assert await deliveries._wake_idle_waiting_targets(_SweepManager(session)) == woken
    drains = [c for c in session.spawned if c.__qualname__ == "TurnManager._deliver_mailbox"]
    assert len(drains) == woken
    _close(session)


@pytest.mark.asyncio
async def test_combined_report_keeps_every_sender(tmp_db):
    session = _session()
    both = MessageProvenance(origin="agent", senders=("w1", "w2"), subtype="auto_report")

    await session.send("two reports", provenance=both)

    assert [r["sender"] for r in mailbox.pending(session.name, session.scope)] == ["w1, w2"]


@pytest.mark.asyncio
async def test_held_receipt_says_it_waits_for_the_running_turn(tmp_db):
    session = _session()
    await _deliver(session, IDS[0], "report")

    action = deliveries._resource(deliveries._row(IDS[0]))["next_action"]

    assert action["code"] == "WAITING_NEXT_TURN" and action["retryable"] is False
    assert "running turn takes this message when it ends" in action["message"]
