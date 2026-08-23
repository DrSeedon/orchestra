"""Immutable RED oracles for #311 durable spawn initial-task delivery."""

import asyncio
import importlib
import importlib.util
import inspect
import json
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


DELIVERY_ID = "00000000-0000-4000-8000-000000000311"
SESSION_ID = "session-311"
SCOPE = "/scope-311"
WORKER = "worker-311"
SENDER = "orchestrator-311"
MESSAGE = "implement the durable initial task"


def _delivery_module():
    spec = importlib.util.find_spec("app.initial_deliveries")
    assert spec is not None, (
        "#311 missing behavior: app.initial_deliveries does not exist"
    )
    return importlib.import_module("app.initial_deliveries")


def _required_callable(owner, name):
    value = getattr(owner, name, None)
    assert callable(value), f"#311 missing behavior: {owner!r}.{name} is not callable"
    return value


@pytest.fixture
def delivery_db(tmp_path, monkeypatch):
    from app import db

    db_path = tmp_path / "delivery.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()
    db.save_session({
        "id": SESSION_ID,
        "name": WORKER,
        "scope": SCOPE,
        "cwd": "/tmp/worker-311",
        "model": "gpt-5.6-sol",
        "system_prompt": "",
        "status": "idle",
        "session_id": None,
        "cost_usd": 0.0,
        "worktree_path": "/tmp/worker-311",
        "branch": "task-311/worker-311",
        "is_orchestrator": False,
        "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "parent_name": SENDER,
    })
    return db


async def _accept(module, *, message=MESSAGE, delivery_id=DELIVERY_ID):
    accept = _required_callable(module, "accept_initial_delivery")
    return await accept(
        delivery_id=delivery_id,
        session_id=SESSION_ID,
        worker_name=WORKER,
        scope=SCOPE,
        sender=SENDER,
        message=message,
    )


def _delivery_row(db, delivery_id=DELIVERY_ID):
    with db._conn() as connection:
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "initial_deliveries" in tables, (
            "#311 missing behavior: initial_deliveries table was not created"
        )
        row = connection.execute(
            "SELECT * FROM initial_deliveries WHERE delivery_id=?",
            (delivery_id,),
        ).fetchone()
        return dict(row) if row else None


def _user_messages(db):
    with db._conn() as connection:
        return [
            dict(row) for row in connection.execute(
                "SELECT * FROM logs WHERE session_id=? AND type='user_message' "
                "ORDER BY id",
                (SESSION_ID,),
            ).fetchall()
        ]


@pytest.mark.asyncio
async def test_t1_accept_commits_before_blocked_cold_wake_and_returns_202(
    delivery_db, monkeypatch,
):
    """An indefinitely blocked cold start cannot hold the acceptance receipt open."""
    module = _delivery_module()
    get_delivery = _required_callable(module, "get_initial_delivery")
    cold_gate = asyncio.Event()
    cold_started = asyncio.Event()
    cold_tasks = []
    observed_states = []

    async def cold_runtime_start():
        cold_started.set()
        await cold_gate.wait()

    def fake_ensure(delivery_id):
        # A separate committed read must see QUEUED before any runtime wake begins.
        observed = get_delivery(delivery_id, SCOPE)
        observed_states.append(observed["delivery_state"])
        cold_tasks.append(asyncio.create_task(cold_runtime_start()))

    monkeypatch.setattr(module, "ensure_delivery_runner", fake_ensure)

    payload, status = await _accept(module)
    await asyncio.sleep(0)  # scheduler tick only; no wall-clock cold-start sleep

    assert status == 202
    assert payload["delivery_id"] == DELIVERY_ID
    assert payload["delivery_state"] == "QUEUED"
    assert payload["status_url"].endswith(f"/api/initial-deliveries/{DELIVERY_ID}")
    assert observed_states == ["QUEUED"]
    assert cold_started.is_set()
    assert len(cold_tasks) == 1 and not cold_tasks[0].done()

    cold_gate.set()
    await cold_tasks[0]


@pytest.mark.asyncio
async def test_t1_same_key_is_insert_or_read_and_different_payload_conflicts(
    delivery_db, monkeypatch,
):
    module = _delivery_module()
    wakes = []
    monkeypatch.setattr(
        module, "ensure_delivery_runner", lambda delivery_id: wakes.append(delivery_id),
    )

    first, first_status = await _accept(module)
    repeated, repeated_status = await _accept(module)
    conflict, conflict_status = await _accept(module, message=MESSAGE + " changed")

    assert first_status == repeated_status == 202
    assert first == repeated
    assert wakes == [DELIVERY_ID]
    assert conflict_status == 409
    assert conflict["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert conflict["delivery_id"] == DELIVERY_ID
    assert _delivery_row(delivery_db)["payload_hash"] == first["payload_hash"]


@pytest.mark.asyncio
async def test_t1_failed_accept_commit_has_no_row_wake_log_or_backend_call(
    delivery_db, monkeypatch,
):
    module = _delivery_module()
    wakes = []
    backend_calls = []
    monkeypatch.setattr(
        module, "ensure_delivery_runner", lambda delivery_id: wakes.append(delivery_id),
    )
    monkeypatch.setattr(module, "_test_backend_calls", backend_calls, raising=False)
    with delivery_db._conn() as connection:
        connection.execute(
            """CREATE TRIGGER fail_t1_initial_delivery_insert
               BEFORE INSERT ON initial_deliveries
               BEGIN SELECT RAISE(ABORT, 'forced accept commit failure'); END"""
        )

    with pytest.raises(sqlite3.DatabaseError, match="forced accept commit failure"):
        await _accept(module)

    assert _delivery_row(delivery_db) is None
    assert _user_messages(delivery_db) == []
    assert wakes == []
    assert backend_calls == []


@pytest.mark.asyncio
async def test_t1_http_failed_accept_is_explicitly_safe_to_retry_same_key(
    delivery_db, monkeypatch,
):
    module = _delivery_module()
    wakes = []
    monkeypatch.setattr(
        module, "ensure_delivery_runner", lambda delivery_id: wakes.append(delivery_id),
    )
    with delivery_db._conn() as connection:
        connection.execute(
            """CREATE TRIGGER fail_t1_http_delivery_insert
               BEFORE INSERT ON initial_deliveries
               BEGIN SELECT RAISE(ABORT, 'forced HTTP accept rollback'); END"""
        )

    from app.routes import sessions as session_routes

    request_type = getattr(session_routes, "InitialDeliveryRequest", None)
    assert request_type is not None, (
        "#311 missing behavior: InitialDeliveryRequest is not defined"
    )
    route = next(
        (
            route for route in session_routes.router.routes
            if getattr(route, "path", "")
            == "/api/sessions/{name}/initial-deliveries"
            and "POST" in getattr(route, "methods", set())
        ),
        None,
    )
    assert route is not None, (
        "#311 missing behavior: initial-delivery POST route is not registered"
    )
    assert route.status_code == 202
    endpoint = route.endpoint
    fake_session = SimpleNamespace(id=SESSION_ID, name=WORKER, scope=SCOPE)
    monkeypatch.setattr(
        session_routes.manager,
        "get_by_name",
        lambda name, scope: fake_session if (name, scope) == (WORKER, SCOPE) else None,
    )

    response = await endpoint(
        WORKER,
        request_type(
            delivery_id=DELIVERY_ID,
            message=MESSAGE,
            scope=SCOPE,
            sender=SENDER,
        ),
    )
    payload = json.loads(response.body)

    assert response.status_code == 503
    assert payload["error"]["code"] == "DELIVERY_ACCEPT_REJECTED"
    assert payload["error"]["outcome_unknown"] is False
    assert payload["error"]["retryable"] is True
    assert payload["error"]["details"]["commit_state"] == "NOT_COMMITTED"
    assert _delivery_row(delivery_db) is None
    assert _user_messages(delivery_db) == []
    assert wakes == []


@pytest.mark.asyncio
async def test_t1_http_status_lookup_returns_the_same_committed_resource(
    delivery_db, monkeypatch,
):
    module = _delivery_module()
    monkeypatch.setattr(module, "ensure_delivery_runner", lambda _delivery_id: None)
    accepted, status = await _accept(module)
    assert status == 202

    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get(
            f"/api/initial-deliveries/{DELIVERY_ID}",
            params={"scope": SCOPE},
        )

    assert response.status_code == 200
    assert response.json() == accepted


@pytest.mark.asyncio
async def test_t2_manager_entry_preserves_session_lock_and_auto_switch(
    delivery_db, monkeypatch,
):
    from app.manager import SessionManager

    manager = SessionManager()
    events = []
    delivery = object()

    class FakeSession:
        id = SESSION_ID

        async def send(self, message, *, delivery=None):
            assert manager.get_session_lock(self.id).locked()
            events.append(("send", message, delivery))

    session = FakeSession()
    manager.sessions = {SESSION_ID: session}

    async def auto_switch(target):
        assert manager.get_session_lock(SESSION_ID).locked()
        assert target is session
        events.append(("auto-switch",))

    monkeypatch.setattr(manager, "_auto_switch_before_delivery", auto_switch)
    send_initial = _required_callable(manager, "send_initial_delivery")

    await send_initial(SESSION_ID, MESSAGE, delivery=delivery)

    assert events == [
        ("auto-switch",),
        ("send", MESSAGE, delivery),
    ]


@pytest.mark.asyncio
async def test_t2_session_context_logs_no_duplicate_and_brackets_backend_send(
    delivery_db, monkeypatch,
):
    from app.session import AgentSession

    delivery_db.add_log(
        SESSION_ID,
        datetime.now(timezone.utc),
        "user_message",
        MESSAGE,
    )
    delivery_db.add_log(
        SESSION_ID,
        datetime.now(timezone.utc),
        "user_message",
        "older user context",
    )
    module = _delivery_module()
    monkeypatch.setattr(module, "ensure_delivery_runner", lambda _delivery_id: None)
    await _accept(module)
    prepare = _required_callable(module, "prepare_initial_delivery")
    prepared = prepare(DELIVERY_ID)
    assert prepared["user_log_id"]
    assert [entry["content"] for entry in _user_messages(delivery_db)] == [
        MESSAGE,
        "older user context",
        MESSAGE,
    ]

    parameters = inspect.signature(AgentSession.send).parameters
    assert "delivery" in parameters, (
        "#311 missing behavior: AgentSession.send has no durable delivery context"
    )

    events = []

    class FakeBackend:
        session_id = "native-session"
        active_turn_id = "native-turn-311"

        async def send(self, message):
            events.append(("backend", message))

    class DeliveryContext:
        async def before_submit(self):
            events.append(("before-submit",))

        async def mark_submitted(self, provider_ref=None):
            events.append(("submitted", provider_ref))

        async def mark_unknown(self, error):
            events.append(("unknown", type(error).__name__))

    session = AgentSession(
        id=SESSION_ID,
        name=WORKER,
        scope=SCOPE,
        cwd="/tmp/worker-311",
        model="claude-sonnet-5[1m]",
        system_prompt="",
        created_at=datetime.now(timezone.utc),
        is_orchestrator=True,
    )
    session._log = MagicMock()
    session._persist = MagicMock()
    reconstructed_histories = []

    async def ensure_backend(*, exclude_history_users=(), **_kwargs):
        assert exclude_history_users == (MESSAGE,)
        reconstructed_histories.append(
            await session._build_runtime_handoff(
                exclude_user_messages=exclude_history_users,
            )
        )
        return FakeBackend()

    session._ensure_backend = ensure_backend
    session._refresh_stale_backend = AsyncMock()
    session._apply_pending_identity_restart = AsyncMock()
    session._apply_manifest_effort = AsyncMock()
    session._shadow_reserve = AsyncMock(return_value=None)
    session._notify_scope_running = AsyncMock()

    await session.send(MESSAGE, delivery=DeliveryContext())
    await asyncio.sleep(0)

    user_log_calls = [
        call for call in session._log.call_args_list
        if call.args and call.args[0] == "user_message"
    ]
    assert user_log_calls == []
    assert len(reconstructed_histories) == 1
    assert "older user context" in reconstructed_histories[0]
    assert reconstructed_histories[0].count(MESSAGE) == 1
    assert events == [
        ("before-submit",),
        ("backend", MESSAGE),
        ("submitted", "native-turn-311"),
    ]


class _RecordingManager:
    def __init__(self):
        self.prompts = []
        self.backend_calls = []

    async def send_initial_delivery(self, session_id, message, *, delivery):
        assert session_id == SESSION_ID
        self.prompts.append(message)
        await delivery.before_submit()
        self.backend_calls.append(message)
        await delivery.mark_submitted(provider_ref="native-turn-311")


@pytest.mark.asyncio
@pytest.mark.parametrize("prepared_before_restart", [False, True])
async def test_t2_restart_recovers_queued_or_preparing_once(
    delivery_db, monkeypatch, prepared_before_restart,
):
    module = _delivery_module()
    monkeypatch.setattr(module, "ensure_delivery_runner", lambda _delivery_id: None)
    await _accept(module)

    if prepared_before_restart:
        prepare = _required_callable(module, "prepare_initial_delivery")
        prepared = prepare(DELIVERY_ID)
        assert prepared["delivery_state"] == "PREPARING"
        assert prepared["user_log_id"]
        assert len(_user_messages(delivery_db)) == 1

    scheduled = []
    monkeypatch.setattr(
        module, "ensure_delivery_runner", lambda delivery_id: scheduled.append(delivery_id),
    )
    recover = _required_callable(module, "recover_initial_deliveries")
    await recover()

    assert scheduled == [DELIVERY_ID]

    manager = _RecordingManager()
    run = _required_callable(module, "run_initial_delivery")
    await run(DELIVERY_ID, manager=manager)

    row = _delivery_row(delivery_db)
    assert row["state"] == "SUBMITTED"
    assert row["provider_ref"] == "native-turn-311"
    assert [entry["content"] for entry in _user_messages(delivery_db)] == [MESSAGE]
    assert manager.prompts == [MESSAGE]
    assert manager.backend_calls == [MESSAGE]


@pytest.mark.asyncio
async def test_t2_prepare_commit_is_atomic_with_the_single_user_log(
    delivery_db, monkeypatch,
):
    module = _delivery_module()
    monkeypatch.setattr(module, "ensure_delivery_runner", lambda _delivery_id: None)
    await _accept(module)
    prepare = _required_callable(module, "prepare_initial_delivery")
    with delivery_db._conn() as connection:
        connection.execute(
            """CREATE TRIGGER fail_t2_user_log_insert
               BEFORE INSERT ON logs WHEN NEW.type='user_message'
               BEGIN SELECT RAISE(ABORT, 'forced prepare commit failure'); END"""
        )

    with pytest.raises(sqlite3.DatabaseError, match="forced prepare commit failure"):
        prepare(DELIVERY_ID)

    row = _delivery_row(delivery_db)
    assert row["state"] == "QUEUED"
    assert row["user_log_id"] is None
    assert _user_messages(delivery_db) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_accepted", [False, True])
async def test_t2_restart_never_replays_dispatching_even_if_acceptance_is_unknown(
    delivery_db, monkeypatch, provider_accepted,
):
    module = _delivery_module()
    monkeypatch.setattr(module, "ensure_delivery_runner", lambda _delivery_id: None)
    await _accept(module)
    prepare = _required_callable(module, "prepare_initial_delivery")
    mark_dispatching = _required_callable(module, "mark_initial_delivery_dispatching")
    prepare(DELIVERY_ID)
    mark_dispatching(DELIVERY_ID)

    external_calls = [MESSAGE] if provider_accepted else []
    scheduled = []
    monkeypatch.setattr(
        module, "ensure_delivery_runner", lambda delivery_id: scheduled.append(delivery_id),
    )
    recover = _required_callable(module, "recover_initial_deliveries")
    await recover()

    row = _delivery_row(delivery_db)
    assert row["state"] == "DELIVERY_UNKNOWN"
    assert scheduled == []
    assert external_calls == ([MESSAGE] if provider_accepted else [])


@pytest.mark.asyncio
async def test_t2_restart_leaves_submitted_terminal_and_unscheduled(
    delivery_db, monkeypatch,
):
    module = _delivery_module()
    monkeypatch.setattr(module, "ensure_delivery_runner", lambda _delivery_id: None)
    await _accept(module)
    prepare = _required_callable(module, "prepare_initial_delivery")
    mark_dispatching = _required_callable(module, "mark_initial_delivery_dispatching")
    mark_submitted = _required_callable(module, "mark_initial_delivery_submitted")
    prepare(DELIVERY_ID)
    mark_dispatching(DELIVERY_ID)
    mark_submitted(DELIVERY_ID, provider_ref="native-turn-311")

    scheduled = []
    monkeypatch.setattr(
        module, "ensure_delivery_runner", lambda delivery_id: scheduled.append(delivery_id),
    )
    recover = _required_callable(module, "recover_initial_deliveries")
    await recover()

    row = _delivery_row(delivery_db)
    assert row["state"] == "SUBMITTED"
    assert row["provider_ref"] == "native-turn-311"
    assert scheduled == []


@pytest.mark.asyncio
async def test_t2_cancel_after_dispatching_marks_unknown_and_never_replays(
    delivery_db, monkeypatch,
):
    module = _delivery_module()
    monkeypatch.setattr(module, "ensure_delivery_runner", lambda _delivery_id: None)
    await _accept(module)

    class CancellingManager:
        async def send_initial_delivery(self, session_id, message, *, delivery):
            assert session_id == SESSION_ID
            assert message == MESSAGE
            await delivery.before_submit()
            raise asyncio.CancelledError

    run = _required_callable(module, "run_initial_delivery")
    with pytest.raises(asyncio.CancelledError):
        await run(DELIVERY_ID, manager=CancellingManager())

    row = _delivery_row(delivery_db)
    assert row["state"] == "DELIVERY_UNKNOWN"

    scheduled = []
    monkeypatch.setattr(
        module, "ensure_delivery_runner", lambda delivery_id: scheduled.append(delivery_id),
    )
    recover = _required_callable(module, "recover_initial_deliveries")
    await recover()

    assert _delivery_row(delivery_db)["state"] == "DELIVERY_UNKNOWN"
    assert scheduled == []


def test_t2_startup_orders_recovery_before_background_delivery_sources():
    from app import main

    source = inspect.getsource(main.lifespan)
    markers = [
        "await manager.auto_resume_all()",
        "await recover_initial_deliveries()",
        "await manager.sweep_orphan_fds()",
        "manager.start_background_tasks()",
        "schedule_restart_inbox_drain()",
    ]
    for marker in markers:
        assert marker in source, f"#311 missing startup delivery marker: {marker}"

    positions = [source.index(marker) for marker in markers]
    assert positions == sorted(positions), (
        "#311 delivery recovery must run after auto-resume and before background sources"
    )


T381_SHARED_ERROR_TEXT = "'NoneType' object has no attribute 'send'"


def _t381_session():
    from app.session import AgentSession

    session = AgentSession(
        id=SESSION_ID,
        name=WORKER,
        scope=SCOPE,
        cwd="/tmp/worker-381",
        model="claude-sonnet-5[1m]",
        system_prompt="",
        created_at=datetime.now(timezone.utc),
        is_orchestrator=True,
    )
    session._log = MagicMock()
    session._persist = MagicMock()
    session._note_next_precompact_activity = MagicMock()
    session._refresh_stale_backend = AsyncMock()
    session._apply_pending_identity_restart = AsyncMock()
    session._apply_manifest_effort = AsyncMock()
    session._notify_scope_running = AsyncMock()
    session._attach_pending_facts = lambda message: (message, [])
    session._ack_pending_facts = MagicMock()
    return session


class _T381SessionManager:
    def __init__(self, session):
        self.session = session

    async def send_initial_delivery(self, session_id, message, *, delivery):
        assert session_id == SESSION_ID
        await self.session.send(message, delivery=delivery)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_mode", ["backend-none", "raised-before-call"])
async def test_t381_backend_none_before_provider_is_known_retryable(
    delivery_db, monkeypatch, failure_mode,
):
    module = _delivery_module()
    monkeypatch.setattr(module, "ensure_delivery_runner", lambda _delivery_id: None)
    await _accept(module)
    session = _t381_session()
    if failure_mode == "backend-none":
        session._ensure_backend = AsyncMock(return_value=None)
    else:
        session._ensure_backend = AsyncMock(
            side_effect=AttributeError(T381_SHARED_ERROR_TEXT),
        )

    run = _required_callable(module, "run_initial_delivery")
    with pytest.raises(Exception):
        await run(DELIVERY_ID, manager=_T381SessionManager(session))
    await asyncio.sleep(0)

    row = _delivery_row(delivery_db)
    assert row["state"] == "FAILED_BEFORE_SUBMIT", (
        "#381 pre-provider failure must stay known and retryable"
    )
    error = json.loads(row["error_json"])
    assert error["code"] == "DELIVERY_NOT_SUBMITTED"
    assert error["outcome_unknown"] is False
    assert error["retryable"] is True
    assert error["details"]["phase"] == "PRE_PROVIDER"
    assert session._ensure_backend.await_count == 1
    assert len(_user_messages(delivery_db)) == 1


@pytest.mark.asyncio
async def test_t381_retry_after_backend_recovery_submits_once_without_duplicate_input(
    delivery_db, monkeypatch,
):
    import threading

    module = _delivery_module()
    monkeypatch.setattr(module, "ensure_delivery_runner", lambda _delivery_id: None)
    await _accept(module)
    failed_session = _t381_session()
    failed_session._ensure_backend = AsyncMock(
        side_effect=AttributeError(T381_SHARED_ERROR_TEXT),
    )
    with pytest.raises(AttributeError, match="NoneType"):
        await module.run_initial_delivery(
            DELIVERY_ID,
            manager=_T381SessionManager(failed_session),
        )
    await asyncio.sleep(0)
    failed = _delivery_row(delivery_db)
    assert failed["state"] == "FAILED_BEFORE_SUBMIT"
    original_user_log_id = failed["user_log_id"]
    assert original_user_log_id is not None
    assert len(_user_messages(delivery_db)) == 1

    conflict, conflict_status = await _accept(module, message=MESSAGE + " changed")
    assert conflict_status == 409
    assert conflict["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    wake_attempts = []

    def lose_first_wake(delivery_id):
        wake_attempts.append(delivery_id)
        raise RuntimeError("simulated crash between retry claim and runner wake")

    monkeypatch.setattr(module, "ensure_delivery_runner", lose_first_wake)
    barrier = threading.Barrier(2)

    def retry_same_delivery():
        barrier.wait()
        return asyncio.run(_accept(module))

    results = await asyncio.gather(
        asyncio.to_thread(retry_same_delivery),
        asyncio.to_thread(retry_same_delivery),
        return_exceptions=True,
    )
    failures = [result for result in results if isinstance(result, Exception)]
    receipts = [result for result in results if not isinstance(result, Exception)]
    assert len(failures) == 1
    assert "simulated crash" in str(failures[0])
    assert len(receipts) == 1 and receipts[0][1] == 202
    assert wake_attempts == [DELIVERY_ID]

    claimed = _delivery_row(delivery_db)
    assert claimed["state"] == "PREPARING"
    assert claimed["error_json"] is None
    assert claimed["user_log_id"] == original_user_log_id

    recovered = []
    monkeypatch.setattr(
        module,
        "ensure_delivery_runner",
        lambda delivery_id: recovered.append(delivery_id),
    )
    await module.recover_initial_deliveries()
    assert recovered == [DELIVERY_ID]

    provider_calls = []
    prompt_preparations = []

    class _T381RecoveredBackend:
        active_turn_id = "native-turn-381"

        async def send(self, message):
            provider_calls.append(message)

    recovered_session = _t381_session()
    recovered_session._ensure_backend = AsyncMock(return_value=_T381RecoveredBackend())

    def prepare_prompt(message):
        prompt_preparations.append(message)
        return message, []

    recovered_session._attach_pending_facts = prepare_prompt
    await module.run_initial_delivery(
        DELIVERY_ID,
        manager=_T381SessionManager(recovered_session),
    )
    await asyncio.sleep(0)
    row = _delivery_row(delivery_db)
    assert row["state"] == "SUBMITTED"
    assert row["user_log_id"] == original_user_log_id
    assert row["provider_ref"] == "native-turn-381"
    assert provider_calls == [MESSAGE]
    assert prompt_preparations == [MESSAGE]
    assert recovered_session._ensure_backend.await_args.kwargs == {
        "exclude_history_users": (MESSAGE,),
    }
    assert [entry["content"] for entry in _user_messages(delivery_db)] == [MESSAGE]


@pytest.mark.asyncio
async def test_t381_provider_accept_then_transport_loss_stays_unknown_quarantined(
    delivery_db, monkeypatch,
):
    module = _delivery_module()
    monkeypatch.setattr(module, "ensure_delivery_runner", lambda _delivery_id: None)
    await _accept(module)
    dispatching_id = "00000000-0000-4000-8000-000000000387"
    historical_unknown_id = "00000000-0000-4000-8000-000000000388"
    await _accept(module, delivery_id=dispatching_id)
    await _accept(module, delivery_id=historical_unknown_id)
    module.prepare_initial_delivery(dispatching_id)
    module.mark_initial_delivery_dispatching(dispatching_id)
    module.prepare_initial_delivery(historical_unknown_id)
    historical_error_json = json.dumps(
        {
            "code": "DELIVERY_OUTCOME_UNKNOWN",
            "message": "historical quarantine sentinel",
            "outcome_unknown": True,
            "retryable": False,
            "details": {"exception_type": "LegacyError"},
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    with delivery_db._conn() as connection:
        connection.execute(
            "UPDATE initial_deliveries SET state='DELIVERY_UNKNOWN', error_json=? "
            "WHERE delivery_id=?",
            (historical_error_json, historical_unknown_id),
        )

    dispatching_wakes = []
    monkeypatch.setattr(
        module,
        "ensure_delivery_runner",
        lambda delivery_id: dispatching_wakes.append(delivery_id),
    )
    dispatching_receipt, dispatching_status = await _accept(
        module,
        delivery_id=dispatching_id,
    )
    assert dispatching_status == 202
    assert dispatching_receipt["delivery_state"] == "DISPATCHING"
    assert dispatching_wakes == []
    external_acceptances = []

    class _T381AcceptedThenLostBackend:
        active_turn_id = None

        async def send(self, message):
            external_acceptances.append(message)
            raise AttributeError(T381_SHARED_ERROR_TEXT)

    session = _t381_session()
    session._ensure_backend = AsyncMock(return_value=_T381AcceptedThenLostBackend())
    run = _required_callable(module, "run_initial_delivery")
    with pytest.raises(AttributeError, match="NoneType"):
        await run(DELIVERY_ID, manager=_T381SessionManager(session))
    await asyncio.sleep(0)

    row = _delivery_row(delivery_db)
    error = json.loads(row["error_json"])
    fresh_unknown_error_json = row["error_json"]
    assert external_acceptances == [MESSAGE]
    assert row["state"] == "DELIVERY_UNKNOWN"
    assert error["outcome_unknown"] is True
    assert error["retryable"] is False

    scheduled = []
    monkeypatch.setattr(
        module,
        "ensure_delivery_runner",
        lambda delivery_id: scheduled.append(delivery_id),
    )
    await module.recover_initial_deliveries()
    repeated, repeated_status = await _accept(module)
    historical_repeated, historical_status = await _accept(
        module,
        delivery_id=historical_unknown_id,
    )
    assert repeated_status == 202
    assert repeated["delivery_state"] == "DELIVERY_UNKNOWN"
    assert historical_status == 202
    assert historical_repeated["delivery_state"] == "DELIVERY_UNKNOWN"
    assert _delivery_row(delivery_db, dispatching_id)["state"] == "DELIVERY_UNKNOWN"
    assert _delivery_row(delivery_db)["error_json"] == fresh_unknown_error_json
    assert (
        _delivery_row(delivery_db, historical_unknown_id)["error_json"]
        == historical_error_json
    )
    assert scheduled == []
    assert external_acceptances == [MESSAGE]
    assert error["details"].get("phase") == "PROVIDER_CALL_STARTED", (
        "#381 ambiguous outcome must be classified by provider-call phase"
    )


@pytest.mark.asyncio
async def test_t381_next_action_structurally_permits_only_known_safe_retry(
    delivery_db, monkeypatch,
):
    module = _delivery_module()
    monkeypatch.setattr(module, "ensure_delivery_runner", lambda _delivery_id: None)
    delivery_ids = {
        "QUEUED": "00000000-0000-4000-8000-000000000381",
        "PREPARING": "00000000-0000-4000-8000-000000000382",
        "FAILED_BEFORE_SUBMIT": "00000000-0000-4000-8000-000000000383",
        "DISPATCHING": "00000000-0000-4000-8000-000000000384",
        "DELIVERY_UNKNOWN": "00000000-0000-4000-8000-000000000385",
        "SUBMITTED": "00000000-0000-4000-8000-000000000386",
    }
    for delivery_id in delivery_ids.values():
        await _accept(module, delivery_id=delivery_id)

    for state in ("PREPARING", "FAILED_BEFORE_SUBMIT", "DISPATCHING",
                  "DELIVERY_UNKNOWN", "SUBMITTED"):
        module.prepare_initial_delivery(delivery_ids[state])
    module.mark_initial_delivery_dispatching(delivery_ids["DISPATCHING"])
    module.mark_initial_delivery_dispatching(delivery_ids["DELIVERY_UNKNOWN"])
    module.mark_initial_delivery_unknown(
        delivery_ids["DELIVERY_UNKNOWN"],
        AttributeError(T381_SHARED_ERROR_TEXT),
    )
    module.mark_initial_delivery_dispatching(delivery_ids["SUBMITTED"])
    module.mark_initial_delivery_submitted(
        delivery_ids["SUBMITTED"], provider_ref="native-turn-381",
    )
    known_error = json.dumps({
        "code": "DELIVERY_NOT_SUBMITTED",
        "message": "backend unavailable before provider call",
        "outcome_unknown": False,
        "retryable": True,
        "details": {"phase": "PRE_PROVIDER", "exception_type": "RuntimeError"},
    })
    with delivery_db._conn() as connection:
        connection.execute(
            "UPDATE initial_deliveries SET state='FAILED_BEFORE_SUBMIT', error_json=? "
            "WHERE delivery_id=?",
            (known_error, delivery_ids["FAILED_BEFORE_SUBMIT"]),
        )

    expected = {
        "QUEUED": ("WAIT_FOR_DELIVERY", "delivery_status", False),
        "PREPARING": ("WAIT_FOR_DELIVERY", "delivery_status", False),
        "FAILED_BEFORE_SUBMIT": (
            "RETRY_SAME_DELIVERY", "retry_initial_delivery", True,
        ),
        "DISPATCHING": ("CHECK_DELIVERY_STATUS", "delivery_status", False),
        "DELIVERY_UNKNOWN": (
            "CHECK_DELIVERY_STATUS", "delivery_status", False,
        ),
        "SUBMITTED": ("NONE", None, False),
    }
    for state, delivery_id in delivery_ids.items():
        resource = module.get_initial_delivery(delivery_id, SCOPE)
        action = resource["next_action"]
        code, tool, retryable = expected[state]
        arguments = (
            {"name": WORKER, "task": MESSAGE, "delivery_id": delivery_id}
            if state == "FAILED_BEFORE_SUBMIT"
            else ({"delivery_id": delivery_id} if tool else {})
        )
        assert isinstance(action, dict), f"#381 {state} must expose a next_action object"
        assert action.get("code") == code
        assert action.get("tool") == tool
        assert action.get("arguments") == arguments
        assert action.get("retryable") is retryable
        assert isinstance(action.get("message"), str) and action["message"]
        assert set(action) == {"code", "tool", "arguments", "retryable", "message"}
        error = resource["error"]
        if error is not None:
            assert error["retryable"] is action["retryable"]

    retry_actions = [
        state for state, delivery_id in delivery_ids.items()
        if module.get_initial_delivery(delivery_id, SCOPE)["next_action"]["tool"]
        == "retry_initial_delivery"
    ]
    assert retry_actions == ["FAILED_BEFORE_SUBMIT"]
