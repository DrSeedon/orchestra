"""V-1160: steers of an interrupted Codex turn are re-sent once, never re-shown.

Synthetic replay of the reported shape: owner and agent steers accepted into a
running native turn, an Orchestra deferred interrupt, WAITING on a background
job, and the after-turn mailbox continuation. No provider, no live database.
Native rollout records are never delivery evidence: no installed Codex version
has a verified turn identity in its rollout, so every steer is redelivered.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import bg_jobs, db, mailbox, message_deliveries
from app.events import MessageProvenance
from app.session_state import AgentStatus

NAME = "orch-1160"
SCOPE = "/scope-1160"
THREAD = "thread-1160"
TURN = "turn-1160"
OWNER = MessageProvenance(origin="user", senders=("user",), subtype="dashboard")
AGENT = MessageProvenance(origin="agent", senders=("worker-1160",), subtype="direct_message")
DEFERRED = {
    "kind": "deferred_job", "origin": "orchestra.bg_jobs", "job_id": "bg-1160",
    "event_id": "bgjob:v1:bg-1160:completed", "turn_control": "interrupt",
}


def _user_item(text: str) -> str:
    return json.dumps({
        "type": "response_item",
        "payload": {
            "type": "message", "role": "user",
            "content": [{"type": "input_text", "text": text}],
        },
    }, ensure_ascii=False) + "\n"


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "v1160.db")
    db.init_db()
    logs: list[tuple[str, str]] = []

    def add_log(_session_id, _ts, kind, content, *args, **kwargs):
        logs.append((kind, content))
        return len(logs)

    monkeypatch.setattr("app.session.add_log", add_log)
    monkeypatch.setattr("app.session.save_session", lambda *_a, **_k: None)
    monkeypatch.setattr(
        bg_jobs, "bg_manager",
        SimpleNamespace(has_active_jobs=lambda session_id: session_id == NAME),
    )
    from app.backend_codex import CodexBackend
    from app.session import AgentSession

    session = AgentSession(
        id=NAME, name=NAME, scope=SCOPE, cwd=str(tmp_path), model="gpt-6-luna",
        system_prompt="prompt", created_at=datetime.now(timezone.utc),
    )
    session.is_orchestrator = True
    session.backend_type = "codex"
    session.session_id = THREAD
    session._prompt_injected = True
    session._persist = lambda: None
    session._hibernate.schedule = lambda: None

    rollout = tmp_path / "codex-home" / "sessions" / "2026" / f"rollout-{THREAD}.jsonl"
    rollout.parent.mkdir(parents=True)
    rollout.write_text(_user_item("older turn input"), encoding="utf-8")
    backend = CodexBackend(model="gpt-6-luna", cwd=str(tmp_path))
    backend._codex_home = tmp_path / "codex-home"
    backend._proc = SimpleNamespace(returncode=None)
    backend._thread_id = THREAD
    requests: list[tuple[str, dict]] = []
    turns = iter([TURN, *(f"turn-1160-{n}" for n in range(2, 40))])

    async def request(method, params):
        requests.append((method, params))
        if method == "turn/start":
            return {"turn": {"id": next(turns)}}
        return {}

    backend._request = request
    session._backend = backend
    return SimpleNamespace(
        session=session, backend=backend, rollout=rollout, logs=logs, requests=requests,
    )


def _insert_steered_delivery(
    delivery_id: str, rendered: str, seq: int, provenance: MessageProvenance = AGENT,
) -> None:
    origin, detail = provenance.to_storage()
    now = datetime.now(timezone.utc).isoformat()
    with db._conn() as connection:
        connection.execute(
            """INSERT INTO message_deliveries (
                   accept_seq, delivery_id, schema_version, source_session_id,
                   source_principal, source_name, source_scope, source_task_id,
                   target_session_id, target_name, target_scope, target_task_id,
                   target_generation, message, rendered_message, message_kind, wake,
                   origin, origin_detail, payload_hash, state, created_at, updated_at,
                   provider_ref
               ) VALUES (?, ?, 2, 'worker-1160', 'mcp:worker-1160', 'worker-1160',
                   ?, '', ?, ?, ?, '', '', ?, ?, 'direct_message', 1,
                   ?, ?, ?, 'SUBMITTED', ?, ?, ?)""",
            (seq, delivery_id, SCOPE, NAME, NAME, SCOPE, rendered.split("] ", 1)[1],
             rendered, origin, detail, f"hash-{seq}", now, now, f"steered:{TURN}"),
        )


async def _start_turn(h) -> None:
    await h.session.send("start the work", provenance=OWNER)
    assert h.backend.active_turn_id == TURN
    assert h.session.status == AgentStatus.RUNNING


async def _deferred_interrupt(h, *, expect_redelivery: bool = True) -> None:
    listener = h.session._listen_task
    await h.backend._notifications.put({"method": "item/completed", "params": {
        "threadId": THREAD, "turnId": TURN,
        "item": {"id": "review-1160", "type": "mcpToolCall", "server": "orchestra",
                 "tool": "codex_review", "arguments": {},
                 "result": {"content": [], "isError": False,
                            "structuredContent": {"result": DEFERRED, "error": None}}}}})
    await h.backend._notifications.put({"method": "turn/completed", "params": {
        "threadId": THREAD, "turn": {"id": TURN, "status": "interrupted", "items": []}}})
    await asyncio.wait_for(listener, timeout=10)
    # Bounded polls end on success; the budget only matters on a loaded host.
    for _ in range(200 if expect_redelivery else 10):
        if sum(method == "turn/start" for method, _ in h.requests) >= 2:
            break
        await asyncio.sleep(0.05)


def _turn_inputs(h) -> list[str]:
    return [params["input"][0]["text"] for method, params in h.requests if method == "turn/start"]


def _user_logs(h) -> list[str]:
    return [content for kind, content in h.logs if kind == "user_message"]




async def _end_turn(h, turn_id: str, status: str) -> None:
    listener = h.session._listen_task
    await h.backend._notifications.put({"method": "turn/completed", "params": {
        "threadId": THREAD, "turn": {"id": turn_id, "status": status}}})
    await asyncio.wait_for(listener, timeout=10)  # the terminal is handled in the listener


@pytest.mark.asyncio
async def test_every_steer_is_redelivered_once_and_not_reshown(harness):
    h = harness
    await _start_turn(h)
    await h.session.send("owner steer one", provenance=OWNER)
    await h.session.send("owner steer two", provenance=OWNER)
    _insert_steered_delivery("d-one", "[from:worker-1160] agent steer one", 1)
    _insert_steered_delivery("d-two", "[from:worker-1160] agent steer two", 2)
    with h.rollout.open("a", encoding="utf-8") as fh:  # what a rollout may contain
        fh.write(_user_item("start the work"))
        fh.write(_user_item("owner steer one"))
        fh.write(_user_item("[from:worker-1160] agent steer one"))

    await _deferred_interrupt(h)

    assert _turn_inputs(h)[1] == (
        "[from:user] owner steer one\n\n[from:user] owner steer two\n\n"
        "[from:worker-1160] agent steer one\n\n[from:worker-1160] agent steer two"
    )
    assert _user_logs(h) == ["start the work", "owner steer one", "owner steer two"]
    statuses = [content for kind, content in h.logs if kind == "status"]
    assert "steered messages waiting for next turn: 2" in statuses
    assert mailbox.pending(NAME, SCOPE) == []
    assert {message_deliveries._row(d)["state"] for d in ("d-one", "d-two")} == {"SUBMITTED"}


@pytest.mark.asyncio
async def test_fresh_after_turn_input_is_still_shown_beside_a_redelivery(harness):
    h = harness
    await _start_turn(h)
    await h.session.send("owner steer", provenance=OWNER)
    mailbox.enqueue(NAME, SCOPE, "", "queued after the turn", provenance=OWNER)

    await _deferred_interrupt(h)

    assert _turn_inputs(h)[1] == (
        "[from:user] owner steer\n\n[from:user] queued after the turn"
    )
    assert _user_logs(h) == [
        "start the work", "owner steer", "[from:user] queued after the turn",
    ]


@pytest.mark.parametrize("earlier_turns", [1, 6])
@pytest.mark.asyncio
async def test_late_record_and_turn_metadata_never_confirm_a_steer_on_a_new_backend(
    harness, monkeypatch, earlier_turns,
):
    """QA 0c907: replaced backend, history beyond any horizon, rows claiming the turn."""
    h = harness
    monkeypatch.setattr(bg_jobs, "bg_manager", SimpleNamespace(has_active_jobs=lambda _sid: False))
    await _start_turn(h)
    for _ in range(earlier_turns - 1):
        await _end_turn(h, h.backend.active_turn_id, "completed")
        await h.session.send("start the work", provenance=OWNER)
    await _end_turn(h, h.backend.active_turn_id, "completed")
    from app.backend_codex import CodexBackend

    replacement = CodexBackend(model="gpt-6-luna", cwd=h.backend.cwd)  # e.g. restart-cli
    replacement._codex_home = h.backend._codex_home
    replacement._proc = SimpleNamespace(returncode=None)
    replacement._thread_id = THREAD
    replacement._request = h.backend._request
    h.session._backend = h.backend = replacement
    await h.session.send("start the work", provenance=OWNER)  # same text, new turn
    current = replacement.active_turn_id
    await h.session.send("start the work", provenance=OWNER)  # a steer, never recorded
    with h.rollout.open("a", encoding="utf-8") as fh:
        fh.write(_user_item("start the work"))  # late flush of an older turn
        fh.write(json.dumps({"type": "turn_context", "payload": {"turn_id": current}}) + "\n")
        fh.write(_user_item("start the work"))  # this turn's own initial input

    await _end_turn(h, current, "interrupted")
    for _ in range(200):
        if _turn_inputs(h)[-1] == "[from:user] start the work" and len(_turn_inputs(h)) > earlier_turns + 1:
            break
        await asyncio.sleep(0.05)
    assert _turn_inputs(h)[-1] == "[from:user] start the work"
    assert mailbox.pending(NAME, SCOPE) == []


async def _interrupt_running_turn(h) -> str:
    turn = h.backend.active_turn_id
    await _end_turn(h, turn, "interrupted")
    return turn


async def _wait_for(predicate) -> None:
    for _ in range(200):
        if predicate():
            return
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_redelivered_initial_input_is_tracked_by_its_new_turn(harness, monkeypatch):
    """QA 62e32c: the receipt names turn 2 instead of the finished turn 1."""
    h = harness
    monkeypatch.setattr(bg_jobs, "bg_manager", SimpleNamespace(has_active_jobs=lambda _sid: False))
    await _start_turn(h)
    _insert_steered_delivery("d-life", "[from:worker-1160] keep me", 1)
    await _interrupt_running_turn(h)  # turn 1 → requeue → turn 2 starts with it
    await _wait_for(lambda: len(_turn_inputs(h)) == 2)
    assert _turn_inputs(h)[1] == "[from:worker-1160] keep me"
    second = h.backend.active_turn_id
    row = message_deliveries._row("d-life")
    assert (row["state"], row["provider_ref"]) == ("SUBMITTED", second)

    await _interrupt_running_turn(h)  # turn 2: its accepted initial input is not a steer
    assert message_deliveries._row("d-life")["provider_ref"] == second
    assert mailbox.pending(NAME, SCOPE) == []
    assert message_deliveries.requeue_failed_turn(NAME, TURN) == 0  # stale turn 1: nothing


@pytest.mark.parametrize("origin", ["agent", "system"])
@pytest.mark.asyncio
async def test_a_steered_redelivery_survives_repeated_interruptions(harness, monkeypatch, origin):
    """Two and three interruptions: an agent batch is owned by its backup row, a
    system batch (no backup) by its receipt; either way it reaches every next turn."""
    h = harness
    monkeypatch.setattr(bg_jobs, "bg_manager", SimpleNamespace(has_active_jobs=lambda _sid: False))
    provenance = AGENT if origin == "agent" else MessageProvenance(
        origin="system", senders=("system",), subtype="direct_message")
    await _start_turn(h)
    _insert_steered_delivery("d-loop", "[from:worker-1160] survive", 1, provenance)
    real_claim = mailbox.claim
    first_turn = None
    for interruption in range(3):
        monkeypatch.setattr(mailbox, "claim", lambda *_a, **_k: [])
        await _interrupt_running_turn(h)
        monkeypatch.setattr(mailbox, "claim", real_claim)
        await h.session.send(f"owner turn {interruption}", provenance=OWNER)
        turn = h.backend.active_turn_id
        queued = mailbox.claim(NAME, SCOPE)
        assert len(queued) == 1, interruption
        await h.session._turns._deliver_mailbox(queued)  # steered into the running turn
        steers = [p["input"][0]["text"] for m, p in h.requests
                  if m == "turn/steer" and p["expectedTurnId"] == turn]
        assert len(steers) == 1 and "survive" in steers[0], interruption
        first_turn = first_turn or turn
        row = message_deliveries._row("d-loop")
        # A backup copy owns later recoveries; without one the receipt follows the turn.
        expected = first_turn if origin == "agent" else f"steered:{turn}"
        assert (row["state"], row["provider_ref"]) == ("SUBMITTED", expected)
    monkeypatch.setattr(mailbox, "claim", lambda *_a, **_k: [])
    await _interrupt_running_turn(h)
    assert len(mailbox.pending(NAME, SCOPE)) == 1  # the fourth turn still owes it


@pytest.mark.asyncio
async def test_successful_turn_completes_a_steered_redelivery(harness, monkeypatch):
    h = harness
    monkeypatch.setattr(bg_jobs, "bg_manager", SimpleNamespace(has_active_jobs=lambda _sid: False))
    await _start_turn(h)
    _insert_steered_delivery("d-ok", "[from:worker-1160] done", 1)
    with monkeypatch.context() as patch:
        patch.setattr(mailbox, "claim", lambda *_a, **_k: [])
        await _interrupt_running_turn(h)
    await h.session.send("owner turn", provenance=OWNER)
    turn = h.backend.active_turn_id
    await h.session._turns._deliver_mailbox(mailbox.claim(NAME, SCOPE))
    await _end_turn(h, turn, "completed")

    assert mailbox.pending(NAME, SCOPE) == []  # the backup completed with the turn
    assert message_deliveries.requeue_failed_turn(NAME, turn) == 0
    assert message_deliveries._row("d-ok")["state"] == "SUBMITTED"


def test_unknown_redelivery_route_stores_no_finished_turn(tmp_path, monkeypatch):
    _recovery_db(tmp_path, monkeypatch)
    _insert_steered_delivery("d-route", "[from:worker-1160] x", 1)
    assert message_deliveries.requeue_failed_turn(NAME, TURN) == 1
    queued = mailbox.claim(NAME, SCOPE)
    message_deliveries.complete_recovered_mailbox_delivery(
        [m["id"] for m in queued], ["d-route"], route=None,  # queued, not submitted yet
    )
    row = message_deliveries._row("d-route")
    assert (row["state"], row["provider_ref"]) == ("SUBMITTED", None)
    message_deliveries.complete_recovered_mailbox_delivery(
        [m["id"] for m in queued], ["d-route"], route=("steer", "t9", False),
    )  # repeat: the receipt is no longer waiting, nothing changes
    assert message_deliveries._row("d-route")["provider_ref"] is None


def _occurrences(h, text: str) -> int:
    sent = [p["input"][0]["text"] for m, p in h.requests if m in ("turn/start", "turn/steer")]
    return sum(item.count(text) for item in sent)


@pytest.mark.asyncio
async def test_mailbox_batch_is_not_parked_in_memory_during_a_deferred_interrupt(harness):
    """QA be000c6 (1): the batch stays durable in the mailbox, then arrives exactly once."""
    h = harness
    await _start_turn(h)
    mailbox.enqueue(NAME, SCOPE, "worker-1160", "after-turn report", provenance=AGENT)
    listener = h.session._listen_task
    await h.backend._notifications.put({"method": "item/completed", "params": {
        "threadId": THREAD, "turnId": TURN,
        "item": {"id": "review-1160", "type": "mcpToolCall", "server": "orchestra",
                 "tool": "codex_review", "arguments": {},
                 "result": {"content": [], "isError": False,
                            "structuredContent": {"result": DEFERRED, "error": None}}}}})
    await _wait_for(lambda: h.backend.deferred_interrupt_pending)
    assert h.backend.deferred_interrupt_pending

    await h.session._turns._deliver_mailbox(mailbox.claim(NAME, SCOPE))

    assert h.session._pending_messages == []  # nothing that dies with the process
    rows = mailbox.pending(NAME, SCOPE)
    assert [(m["body"], m["claimed_at"]) for m in rows] == [("after-turn report", None)]
    assert _occurrences(h, "after-turn report") == 0
    assert "[from:worker-1160] after-turn report" not in _user_logs(h)

    await h.backend._notifications.put({"method": "turn/completed", "params": {
        "threadId": THREAD, "turn": {"id": TURN, "status": "interrupted", "items": []}}})
    await asyncio.wait_for(listener, timeout=10)
    await _wait_for(lambda: len(_turn_inputs(h)) == 2)
    await asyncio.sleep(1.5)  # the deferral waiter finds the rows already taken

    assert _turn_inputs(h)[1] == "[from:worker-1160] after-turn report"
    assert _occurrences(h, "after-turn report") == 1
    assert mailbox.pending(NAME, SCOPE) == []


@pytest.mark.asyncio
async def test_mailbox_batch_waits_out_a_compaction_without_a_memory_copy(harness, monkeypatch):
    h = harness
    monkeypatch.setattr(bg_jobs, "bg_manager", SimpleNamespace(has_active_jobs=lambda _sid: False))
    await _start_turn(h)
    await _end_turn(h, TURN, "completed")
    mailbox.enqueue(NAME, SCOPE, "worker-1160", "during compact", provenance=AGENT)
    h.session._compacting = True

    await h.session._turns._deliver_mailbox(mailbox.claim(NAME, SCOPE))

    assert h.session._pending_messages == []
    assert [m["claimed_at"] for m in mailbox.pending(NAME, SCOPE)] == [None]
    h.session._compacting = False
    await _wait_for(lambda: len(_turn_inputs(h)) == 2)
    assert _turn_inputs(h)[1] == "[from:worker-1160] during compact"
    assert _occurrences(h, "during compact") == 1
    assert mailbox.pending(NAME, SCOPE) == []


def _log_turn_end(when: datetime) -> None:
    db.add_log(NAME, when, "status", "turn ended (end_turn, 1 turns)")


def _steered_at(delivery_id: str, turn: str, when: datetime) -> None:
    with db._conn() as connection:
        connection.execute(
            "UPDATE message_deliveries SET provider_ref=?, updated_at=? WHERE delivery_id=?",
            (f"steered:{turn}", when.isoformat(), delivery_id),
        )


def test_startup_requeues_only_the_cut_turns_steers(tmp_path, monkeypatch):
    """QA be000c6 (2): death before the recovery intent; old successful turns stay."""
    _recovery_db(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    _insert_steered_delivery("d-old", "[from:worker-1160] old success", 1)
    _steered_at("d-old", "turn-old", now - timedelta(minutes=30))
    _log_turn_end(now - timedelta(minutes=20))
    _insert_steered_delivery("d-cut", "[from:worker-1160] cut by death", 2)
    _steered_at("d-cut", "turn-cut", now - timedelta(minutes=5))
    _insert_steered_delivery("d-done", "[from:worker-1160] recovered before", 3)
    _steered_at("d-done", "turn-done", now - timedelta(minutes=4))
    with db._conn() as connection:  # this turn's recovery committed before the death
        connection.execute(
            "INSERT INTO kv(key, value) VALUES (?, 'x')", (f"steer_recovery:{NAME}:turn-done",),
        )

    assert message_deliveries.requeue_cut_turn_steers(NAME) == 1
    assert message_deliveries._row("d-cut")["state"] == "WAITING_NEXT_TURN"
    assert message_deliveries._row("d-old")["state"] == "SUBMITTED"
    assert message_deliveries._row("d-done")["state"] == "SUBMITTED"
    assert [m["body"] for m in mailbox.pending(NAME, SCOPE)] == ["cut by death"]
    assert message_deliveries.requeue_cut_turn_steers(NAME) == 0  # a second boot


def test_startup_bound_uses_event_time_not_log_write_order(tmp_path, monkeypatch):
    """QA 09f496: the newer turn's end log was written first, the older one last."""
    _recovery_db(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    _insert_steered_delivery("d-success", "[from:worker-1160] steered in a finished turn", 1)
    _steered_at("d-success", "turn-finished", now - timedelta(minutes=10))
    _log_turn_end(now - timedelta(minutes=8))   # the finished turn, written first
    _log_turn_end(now - timedelta(minutes=20))  # an older turn, written later (higher id)
    _insert_steered_delivery("d-cut", "[from:worker-1160] cut", 2)
    _steered_at("d-cut", "turn-cut", now - timedelta(minutes=2))

    assert message_deliveries.requeue_cut_turn_steers(NAME) == 1
    assert message_deliveries._row("d-success")["state"] == "SUBMITTED"
    assert message_deliveries._row("d-cut")["state"] == "WAITING_NEXT_TURN"


@pytest.mark.asyncio
async def test_boot_runs_cut_turn_recovery_only_for_sessions_found_mid_turn(tmp_path, monkeypatch):
    from app import manager as manager_module

    _recovery_db(tmp_path, monkeypatch)
    _insert_steered_delivery("d-boot", "[from:worker-1160] boot", 1)
    with db._conn() as connection:
        connection.execute("UPDATE sessions SET status='running', cwd=?", (str(tmp_path),))
    seen = []
    monkeypatch.setattr(message_deliveries, "requeue_cut_turn_steers", lambda sid: seen.append(sid) or 0)
    monkeypatch.setattr(manager_module.SessionManager, "reconcile_live_colors", lambda self: None)
    monkeypatch.setattr(manager_module, "list_latest_runtime_handoffs", lambda: [])
    monkeypatch.setattr(manager_module, "spawn_supervised", lambda coro, _label: coro.close())
    manager = manager_module.SessionManager()

    async def load(row, *, recovery_handoff=None):
        session = SimpleNamespace(id=row["id"], name=row["name"], status=AgentStatus.IDLE,
                                  _persist=lambda: None, _restart_cut_pending=False)
        manager.sessions[row["id"]] = session
        return session

    manager._load_from_db = load
    await manager.auto_resume_all()
    assert seen == [NAME]

    seen.clear()
    manager.sessions.clear()
    with db._conn() as connection:
        connection.execute("DELETE FROM restart_cut_turns")
        connection.execute("UPDATE sessions SET status='idle'")
    await manager.auto_resume_all()
    assert seen == []  # an idle session's steers are never touched at boot


def _recovery_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "recover-1160.db")
    db.init_db()
    db.save_session({
        "id": NAME, "name": NAME, "scope": SCOPE, "cwd": "/tmp", "model": "gpt-6-luna",
        "system_prompt": "", "status": "idle", "session_id": None, "cost_usd": 0.0,
        "worktree_path": "/tmp", "branch": "main", "base_branch": "main",
        "needs_switch": 0, "task_id": "", "role": "orchestrator", "is_orchestrator": True,
        "color": "", "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None, "parent_name": "",
    })


def _sweeper_manager():
    class Manager:
        sessions = {}

        async def ensure_loaded_by_id(self, _sid):
            return None

    return Manager()


@pytest.mark.asyncio
async def test_failed_recovery_transaction_is_finished_by_the_sweeper(tmp_path, monkeypatch):
    _recovery_db(tmp_path, monkeypatch)
    _insert_steered_delivery("d-retry", "[from:worker-1160] retry me", 1)
    real = message_deliveries._requeue_failed_turn

    def crash(*_args, **_kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(message_deliveries, "_requeue_failed_turn", crash)
    with pytest.raises(RuntimeError):
        message_deliveries.requeue_failed_turn(NAME, TURN)
    assert message_deliveries._row("d-retry")["state"] == "SUBMITTED"  # rolled back
    assert mailbox.pending(NAME, SCOPE) == []

    result = await message_deliveries.sweep_stuck_deliveries(_sweeper_manager())
    assert result["recovered"] == 0  # still failing: kept pending, not dropped
    monkeypatch.setattr(message_deliveries, "_requeue_failed_turn", real)

    result = await message_deliveries.sweep_stuck_deliveries(_sweeper_manager())
    assert result["recovered"] == 1
    assert message_deliveries._row("d-retry")["state"] == "WAITING_NEXT_TURN"
    assert [m["body"] for m in mailbox.pending(NAME, SCOPE)] == ["retry me"]

    result = await message_deliveries.sweep_stuck_deliveries(_sweeper_manager())
    assert result["recovered"] == 0
    assert message_deliveries.requeue_failed_turn(NAME, TURN) == 0
    assert len(mailbox.pending(NAME, SCOPE)) == 1


def test_a_redelivered_receipt_is_not_requeued_by_a_repeat_terminal(tmp_path, monkeypatch):
    _recovery_db(tmp_path, monkeypatch)
    _insert_steered_delivery("d-once", "[from:worker-1160] once", 1)
    assert message_deliveries.requeue_failed_turn(NAME, TURN) == 1
    queued = mailbox.claim(NAME, SCOPE)
    message_deliveries.complete_recovered_mailbox_delivery(
        [m["id"] for m in queued], ["d-once"], route=("steer", TURN, False),
    )  # worst case: the receipt names the same turn again
    row = message_deliveries._row("d-once")
    assert (row["state"], row["provider_ref"]) == ("SUBMITTED", f"steered:{TURN}")

    assert message_deliveries.requeue_failed_turn(NAME, TURN) == 0  # e.g. restart-cli after the listener
    assert mailbox.pending(NAME, SCOPE) == []


@pytest.mark.asyncio
async def test_unavailable_database_at_turn_end_is_retried_in_process(harness, monkeypatch):
    h = harness
    await _start_turn(h)
    _insert_steered_delivery("d-later", "[from:worker-1160] later", 1)
    real = message_deliveries.requeue_failed_turn
    calls = []

    def flaky(session_id, turn_id):
        calls.append(turn_id)
        if len(calls) == 1:
            raise RuntimeError("database is locked")  # before the intent is durable
        return real(session_id, turn_id)

    monkeypatch.setattr(message_deliveries, "requeue_failed_turn", flaky)
    monkeypatch.setattr("app.session_turns.STEER_RECOVERY_RETRY_DELAYS", (0.0,))
    await _deferred_interrupt(h, expect_redelivery=False)
    for _ in range(200):
        if message_deliveries._row("d-later")["state"] != "SUBMITTED":
            break
        await asyncio.sleep(0.05)

    assert calls == [TURN, TURN]
    assert message_deliveries._row("d-later")["state"] == "WAITING_NEXT_TURN"
    assert [m["body"] for m in mailbox.pending(NAME, SCOPE)] == ["later"]


@pytest.mark.asyncio
async def test_rollout_lookup_failure_never_blocks_the_turn(harness, monkeypatch):
    h = harness

    def broken(_path, _pattern, *args, **kwargs):
        raise PermissionError("sessions directory unreadable")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "glob", broken)
        await _start_turn(h)
    h.backend._rollout_path = None
    real_stat = Path.stat
    with monkeypatch.context() as patch:
        patch.setattr(
            Path, "stat",
            lambda path, *a, **k: (_ for _ in ()).throw(FileNotFoundError(path))
            if path.name.startswith("rollout-") else real_stat(path, *a, **k),
        )
        assert h.backend._runtime_totals() is None  # the usage baseline before turn/start
    await h.session.send("owner steer", provenance=OWNER)
    await _deferred_interrupt(h)
    assert _turn_inputs(h)[1] == "[from:user] owner steer"


async def _restart_cli(h, monkeypatch):
    from app.routes import sessions as routes

    h.backend._disconnect_direct = lambda _proc: asyncio.sleep(0)
    monkeypatch.setattr(routes, "manager", SimpleNamespace(
        ensure_loaded=lambda *_a: asyncio.sleep(0, h.session),
        get_session_lock=lambda _sid: asyncio.Lock(),
    ))
    monkeypatch.setattr(message_deliveries, "_target_delivery_locks", {})
    return await routes.restart_cli(NAME, routes.ScopeRequest(scope=SCOPE))


@pytest.mark.asyncio
async def test_restart_cli_requeues_the_steers_of_the_cut_turn(harness, monkeypatch):
    h = harness
    await _start_turn(h)
    _insert_steered_delivery("d-a", "[from:worker-1160] before restart", 1)
    _insert_steered_delivery("d-b", "[from:worker-1160] dropped by the killed CLI", 2)
    with h.rollout.open("a", encoding="utf-8") as fh:
        fh.write(_user_item("start the work"))
        fh.write(_user_item("[from:worker-1160] before restart"))

    response = await _restart_cli(h, monkeypatch)

    assert response["ok"] is True
    assert h.session.status == AgentStatus.IDLE
    assert {message_deliveries._row(d)["state"] for d in ("d-a", "d-b")} == {"WAITING_NEXT_TURN"}
    assert [m["body"] for m in mailbox.pending(NAME, SCOPE)] == [
        "before restart", "dropped by the killed CLI",
    ]
    assert [method for method, _ in h.requests].count("turn/start") == 1  # no auto-turn

    h.session._backend = h.backend  # a second restart of the same cut turn
    h.backend._proc = SimpleNamespace(returncode=None)
    h.backend._active_turn_id = TURN
    await _restart_cli(h, monkeypatch)
    assert len(mailbox.pending(NAME, SCOPE)) == 2


@pytest.mark.asyncio
async def test_restart_cli_of_an_idle_session_requeues_nothing(harness, monkeypatch):
    h = harness
    _insert_steered_delivery("d-done", "[from:worker-1160] finished turn", 1)

    response = await _restart_cli(h, monkeypatch)

    assert response["ok"] is True
    assert message_deliveries._row("d-done")["state"] == "SUBMITTED"
    assert mailbox.pending(NAME, SCOPE) == []


@pytest.mark.asyncio
async def test_restart_cli_racing_the_native_terminal_requeues_once(harness, monkeypatch):
    h = harness
    await _start_turn(h)
    _insert_steered_delivery("d-race", "[from:worker-1160] cut by the restart", 1)
    await h.session.send("owner steer", provenance=OWNER)
    plain = h.backend._request

    async def request(method, params):
        if method == "turn/interrupt":  # the CLI answers the restart's interrupt
            h.backend._route_notification({"method": "turn/completed", "params": {
                "threadId": THREAD, "turn": {"id": TURN, "status": "interrupted"}}})
            await asyncio.sleep(0)
        return await plain(method, params)

    h.backend._request = request
    response = await _restart_cli(h, monkeypatch)
    for _ in range(20):
        await asyncio.sleep(0.05)

    assert response["ok"] is True
    rows = [m["body"] for m in mailbox.pending(NAME, SCOPE)]
    delivered = "\n\n".join(_turn_inputs(h)[1:])
    # Each steer is pending or redelivered exactly once, whichever path won the race.
    assert rows.count("cut by the restart") + delivered.count("cut by the restart") == 1
    assert rows.count("owner steer") + delivered.count("owner steer") == 1


@pytest.mark.asyncio
async def test_manual_stop_keeps_blocking_generation_bound_continuations(harness, monkeypatch):
    h = harness
    monkeypatch.setattr(bg_jobs, "bg_manager", SimpleNamespace(has_active_jobs=lambda _sid: False))
    await _start_turn(h)
    plain = h.backend._request

    async def request(method, params):
        if method == "turn/interrupt":
            h.backend._route_notification({"method": "turn/completed", "params": {
                "threadId": THREAD, "turn": {"id": TURN, "status": "interrupted"}}})
        return await plain(method, params)

    h.backend._request = request
    await h.session.interrupt()

    assert h.session._manually_interrupted is True
    assert h.session.status == AgentStatus.IDLE
    # A retry scheduled for the stopped turn carries the generation it ended with.
    generation = (h.session._turn_gen, h.session._turn_start_cancel_gen)
    starts = len(_turn_inputs(h))
    await h.session.send(
        "retry", provenance=MessageProvenance(
            origin="system", senders=("system",), subtype="server_error_retry"),
        retry_generation=generation,
    )
    assert len(_turn_inputs(h)) == starts  # the stop still wins over the retry


@pytest.mark.parametrize(("status", "compacting", "woken"), [
    (AgentStatus.WAITING, False, 1),
    (AgentStatus.IDLE, False, 1),
    (AgentStatus.WAITING, True, 0),  # V-1150 compact owns the session
    (AgentStatus.RUNNING, False, 0),
])
@pytest.mark.asyncio
async def test_sweeper_delivers_recovered_steers_to_a_waiting_session(
    tmp_path, monkeypatch, status, compacting, woken,
):
    _recovery_db(tmp_path, monkeypatch)
    old = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
    _insert_steered_delivery("d-waiting", "[from:worker-1160] body", 1)
    assert message_deliveries.requeue_failed_turn(NAME, TURN) == 1
    with db._conn() as connection:
        connection.execute("UPDATE message_deliveries SET updated_at=?", (old,))
    sent = []

    class Session:
        id = NAME
        name = NAME
        scope = SCOPE

        def __init__(self):
            from app.session_turns import TurnManager

            self.status = status
            self._compacting = compacting
            self._turns = TurnManager(self)

        def _log(self, *_args, **_kwargs):
            pass

        def _spawn_bg(self, coro):
            return asyncio.ensure_future(coro)

        async def send(self, text, *, provenance, chat_text=None, **_options):
            sent.append((text, chat_text))

    class Manager:
        sessions = {NAME: Session()}

    result = await message_deliveries.sweep_stuck_deliveries(Manager())
    await asyncio.sleep(0.05)

    assert result["woken"] == woken
    if woken:
        assert sent == [("[from:worker-1160] body", "")]
        assert message_deliveries._row("d-waiting")["state"] == "SUBMITTED"
    else:
        assert sent == []
        assert message_deliveries._row("d-waiting")["state"] == "WAITING_NEXT_TURN"
        assert len(mailbox.pending(NAME, SCOPE)) == 1
