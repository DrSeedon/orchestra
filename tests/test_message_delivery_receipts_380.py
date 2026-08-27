"""Frozen fake-only RED oracles for #380 opt-in direct-message receipts."""

import asyncio
import importlib
import importlib.util
import inspect
import json
import sqlite3
import threading
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


DELIVERY_ID = "00000000-0000-4000-8000-000000000380"
DELIVERY_ID_2 = "00000000-0000-4000-8000-000000000382"
SOURCE_ID = "source-session-380"
SOURCE_NAME = "source-380"
SCOPE = "/scope-380"
TARGET_ID = "target-session-380"
TARGET_NAME = "target-380"
TARGET_TASK_ID = "380"
TARGET_BRANCH = "task-380/target-380"
TARGET_GENERATION = (
    f"session={TARGET_ID}|task={TARGET_TASK_ID}|branch={TARGET_BRANCH}|needs_switch=0"
)
MESSAGE = "Current #380: preserve this exact direct message"
RENDERED = f"[from:{SOURCE_NAME}] {MESSAGE}"


def _message_module():
    spec = importlib.util.find_spec("app.message_deliveries")
    assert spec is not None, (
        "#380 missing behavior: app.message_deliveries does not exist"
    )
    return importlib.import_module("app.message_deliveries")


def _required_callable(owner, name):
    value = getattr(owner, name, None)
    assert callable(value), f"#380 missing behavior: {owner!r}.{name} is not callable"
    return value


def _session_record(*, session_id, name, scope, task_id="", branch="", role="worker"):
    return {
        "id": session_id,
        "name": name,
        "scope": scope,
        "cwd": f"/tmp/{name}",
        "model": "gpt-5.6-sol",
        "system_prompt": "",
        "status": "idle",
        "session_id": None,
        "cost_usd": 0.0,
        "worktree_path": f"/tmp/{name}",
        "branch": branch,
        "base_branch": "main",
        "needs_switch": 0,
        "task_id": task_id,
        "role": role,
        "is_orchestrator": role in {"orchestrator", "sub-orchestrator"},
        "color": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
        "parent_name": "",
    }


@pytest.fixture
def message_db(tmp_path, monkeypatch):
    from app import db

    db_path = tmp_path / "message-delivery-380.db"
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.init_db()
    db.save_session(_session_record(
        session_id=SOURCE_ID,
        name=SOURCE_NAME,
        scope=SCOPE,
        task_id=TARGET_TASK_ID,
        branch="task-380/source-380",
        role="orchestrator",
    ))
    db.save_session(_session_record(
        session_id=TARGET_ID,
        name=TARGET_NAME,
        scope=SCOPE,
        task_id=TARGET_TASK_ID,
        branch=TARGET_BRANCH,
    ))
    return db


async def _accept(
    module,
    *,
    delivery_id=DELIVERY_ID,
    message=MESSAGE,
    rendered_message=RENDERED,
    target_id=TARGET_ID,
    target_name=TARGET_NAME,
    target_scope=SCOPE,
    target_task_id=TARGET_TASK_ID,
    target_generation=TARGET_GENERATION,
):
    accept = _required_callable(module, "accept_message_delivery")
    return await accept(
        delivery_id=delivery_id,
        source_session_id=SOURCE_ID,
        source_name=SOURCE_NAME,
        source_scope=SCOPE,
        source_task_id=TARGET_TASK_ID,
        target_session_id=target_id,
        target_name=target_name,
        target_scope=target_scope,
        target_task_id=target_task_id,
        target_generation=target_generation,
        message=message,
        rendered_message=rendered_message,
        message_kind=None,
        wake=True,
    )


def _delivery_row(db, delivery_id=DELIVERY_ID):
    with db._conn() as connection:
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "message_deliveries" in tables, (
            "#380 missing behavior: message_deliveries table was not created"
        )
        row = connection.execute(
            "SELECT * FROM message_deliveries WHERE delivery_id=?",
            (delivery_id,),
        ).fetchone()
        return dict(row) if row else None


def _user_messages(db):
    with db._conn() as connection:
        return [
            dict(row) for row in connection.execute(
                "SELECT * FROM logs WHERE session_id=? AND type='user_message' ORDER BY id",
                (TARGET_ID,),
            ).fetchall()
        ]


async def _spin_until(predicate, *, ticks=200):
    """Yield scheduler ticks without turning the correctness check into a timer."""
    for _ in range(ticks):
        if predicate():
            return True
        await asyncio.sleep(0)
    return predicate()


class _ImmediateManager:
    def __init__(self):
        self.calls = []
        self.provider_attempts = []

    async def send_message_delivery(
        self, session_id, message, *, delivery, target_generation,
    ):
        self.calls.append((session_id, message, target_generation))
        await delivery.before_submit()
        self.provider_attempts.append(message)
        await delivery.mark_submitted(provider_ref="native-turn-380")


@pytest.mark.asyncio
async def test_t380_r1_idle_accepts_before_blocked_manager_send_and_dedupes(
    message_db, monkeypatch,
):
    """An unbounded idle start is downstream of a committed 202 receipt."""
    module = _message_module()
    run_target = _required_callable(module, "run_target_message_deliveries")
    get_delivery = _required_callable(module, "get_message_delivery")
    entered = asyncio.Event()
    release = asyncio.Event()
    runner_tasks = []
    provider_attempts = []

    class BlockingIdleManager:
        async def send_message_delivery(
            self, session_id, message, *, delivery, target_generation,
        ):
            assert session_id == TARGET_ID
            assert target_generation == TARGET_GENERATION
            entered.set()
            await release.wait()  # deliberately unbounded: this represents >30 seconds
            await delivery.before_submit()
            provider_attempts.append(message)
            await delivery.mark_submitted(provider_ref="idle-turn-380")

    manager = BlockingIdleManager()

    def schedule(target_session_id):
        assert target_session_id == TARGET_ID
        committed = get_delivery(DELIVERY_ID, SOURCE_ID)
        assert committed["delivery_state"] == "QUEUED"
        runner_tasks.append(asyncio.create_task(
            run_target(TARGET_ID, manager=manager)
        ))

    monkeypatch.setattr(module, "ensure_target_runner", schedule)

    first, first_status = await _accept(module)
    assert await _spin_until(entered.is_set), "#380 runner never entered fake manager.send"
    assert first_status == 202
    assert first["acceptance"] == "ACCEPTED"
    assert first["delivery_state"] == "QUEUED"
    assert first["delivery_id"] == DELIVERY_ID
    assert first["accept_seq"] > 0
    assert len(runner_tasks) == 1 and not runner_tasks[0].done()

    repeated, repeated_status = await _accept(module)
    conflict, conflict_status = await _accept(
        module,
        message=MESSAGE + " changed",
        rendered_message=RENDERED + " changed",
    )
    generation_conflict, generation_conflict_status = await _accept(
        module,
        target_generation=(
            f"session={TARGET_ID}|task=381|branch=task-381/{TARGET_NAME}|needs_switch=0"
        ),
        target_task_id="381",
    )
    assert repeated_status == 202
    assert repeated["acceptance"] == "ALREADY_ACCEPTED"
    assert repeated["delivery_id"] == first["delivery_id"]
    assert repeated["accept_seq"] == first["accept_seq"]
    assert len(runner_tasks) == 1
    assert conflict_status == 409
    assert conflict["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert generation_conflict_status == 409
    assert generation_conflict["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    release.set()
    await runner_tasks[0]
    row = _delivery_row(message_db)
    assert row["state"] == "SUBMITTED"
    assert provider_attempts == [RENDERED]
    assert [row["content"] for row in _user_messages(message_db)] == [RENDERED]


@pytest.mark.asyncio
async def test_t380_r1_http_202_returns_while_manager_send_is_blocked(
    message_db, monkeypatch,
):
    """The public opt-in POST returns Orchestra ownership, not manager completion."""
    from app.mcp_proof import issue_mcp_proof
    from app.routes import sessions as routes

    assert "delivery_id" in routes.SendRequest.model_fields, (
        "#380 missing behavior: SendRequest has no opt-in delivery_id"
    )
    assert "request" in inspect.signature(routes.send_message).parameters, (
        "#380 missing behavior: keyed send route cannot authenticate the Request"
    )
    module = _message_module()
    run_target = _required_callable(module, "run_target_message_deliveries")
    from app import fan_barrier
    monkeypatch.setattr(
        fan_barrier,
        "peek_summary",
        MagicMock(side_effect=AssertionError("keyed direct send entered legacy fan path")),
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    runners = []

    class BlockingManager:
        async def send_message_delivery(
            self, session_id, message, *, delivery, target_generation,
        ):
            entered.set()
            await release.wait()
            await delivery.before_submit()
            await delivery.mark_submitted(provider_ref="http-turn-380")

    def schedule(target_session_id):
        runners.append(asyncio.create_task(
            run_target(target_session_id, manager=BlockingManager())
        ))

    monkeypatch.setattr(module, "ensure_target_runner", schedule)
    proof = issue_mcp_proof(SOURCE_ID)
    request = _request_with_proof(SOURCE_ID, proof)
    req = routes.SendRequest(
        delivery_id=DELIVERY_ID,
        message=MESSAGE,
        sender=SOURCE_NAME,
        scope=SCOPE,
    )

    response = await routes.send_message(TARGET_NAME, req, request=request)
    assert getattr(response, "status_code", None) == 202
    payload = _response_payload(response)
    assert payload["acceptance"] == "ACCEPTED"
    assert payload["delivery_id"] == DELIVERY_ID
    assert await _spin_until(entered.is_set), "#380 accepted HTTP runner never started"
    assert len(runners) == 1 and not runners[0].done()

    release.set()
    await runners[0]
    assert _delivery_row(message_db)["state"] == "SUBMITTED"


@pytest.mark.asyncio
async def test_t380_r1_post_commit_schedule_failure_still_returns_accepted(
    message_db, monkeypatch,
):
    """Runner wake is downstream bookkeeping and cannot rewrite a committed outcome."""
    module = _message_module()
    monkeypatch.setattr(
        module,
        "ensure_target_runner",
        MagicMock(side_effect=RuntimeError("synthetic scheduler unavailable")),
    )

    resource, status = await _accept(module)

    assert status == 202
    assert resource["acceptance"] == "ACCEPTED"
    assert resource["delivery_state"] == "QUEUED"
    assert _delivery_row(message_db)["delivery_id"] == DELIVERY_ID
    assert _user_messages(message_db) == []


@pytest.mark.asyncio
async def test_t380_r1_lost_commit_ack_reconciles_the_committed_receipt(
    message_db, monkeypatch,
):
    """A commit that lands and then raises is accepted, not a false 500/rollback."""
    module = _message_module()
    monkeypatch.setattr(module, "ensure_target_runner", lambda _target_id: None)
    real_conn = message_db._conn
    first_connection = True

    class CommitThenRaise:
        def __init__(self, inner):
            self.inner = inner

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def commit(self):
            self.inner.commit()
            raise sqlite3.OperationalError("synthetic lost commit acknowledgement")

        def rollback(self):
            self.inner.rollback()

        def close(self):
            self.inner.close()

        def __enter__(self):
            self.inner.__enter__()
            return self

        def __exit__(self, exc_type, exc, tb):
            return self.inner.__exit__(exc_type, exc, tb)

    def connection_factory():
        nonlocal first_connection
        connection = real_conn()
        if first_connection:
            first_connection = False
            return CommitThenRaise(connection)
        return connection

    monkeypatch.setattr(message_db, "_conn", connection_factory)
    resource, status = await _accept(module)

    assert status == 202
    assert resource["delivery_id"] == DELIVERY_ID
    assert resource["acceptance"] in {"ACCEPTED", "ALREADY_ACCEPTED"}
    assert _delivery_row(message_db)["state"] == "QUEUED"


@pytest.mark.asyncio
async def test_t380_r1_legacy_blank_key_and_unsupported_keyed_ingress_split_cleanly(
    message_db, monkeypatch,
):
    """Blank key keeps old synchronous behavior; keyed mailbox/fan shapes are rejected."""
    from app.routes import sessions as routes

    assert "delivery_id" in routes.SendRequest.model_fields, (
        "#380 missing behavior: SendRequest has no opt-in delivery_id"
    )
    assert "request" in inspect.signature(routes.send_message).parameters, (
        "#380 missing behavior: keyed send route cannot authenticate the Request"
    )
    target = SimpleNamespace(
        id=TARGET_ID,
        name=TARGET_NAME,
        scope=SCOPE,
        parent_name="",
        last_task_sender="",
    )
    monkeypatch.setattr(routes.manager, "ensure_loaded", AsyncMock(return_value=target))
    monkeypatch.setattr(routes.manager, "ensure_loaded_any", AsyncMock(return_value=None))
    legacy_send = AsyncMock()
    monkeypatch.setattr(routes.manager, "send", legacy_send)
    request = SimpleNamespace(headers={}, cookies={})

    legacy = await routes.send_message(
        TARGET_NAME,
        routes.SendRequest(message="legacy", scope=SCOPE),
        request=request,
    )
    assert legacy == {"ok": True, "parent_name": ""}
    legacy_send.assert_awaited_once()

    from app.mcp_proof import issue_mcp_proof
    proof_request = _request_with_proof(SOURCE_ID, issue_mcp_proof(SOURCE_ID))
    keyed_mailbox = await routes.send_message(
        TARGET_NAME,
        routes.SendRequest(
            delivery_id=DELIVERY_ID,
            message=MESSAGE,
            sender=SOURCE_NAME,
            scope=SCOPE,
            wake=False,
        ),
        request=proof_request,
    )
    keyed_fan = await routes.send_message(
        TARGET_NAME,
        routes.SendRequest(
            delivery_id=DELIVERY_ID_2,
            message=MESSAGE,
            sender=SOURCE_NAME,
            scope=SCOPE,
            message_kind="terminal_report",
        ),
        request=proof_request,
    )
    for response in (keyed_mailbox, keyed_fan):
        assert getattr(response, "status_code", None) == 400
        error = _response_payload(response)["error"]
        assert error["code"] == "UNSUPPORTED_KEYED_INGRESS"
        assert error["outcome_unknown"] is False


@pytest.mark.asyncio
async def test_t380_r2_running_receipt_steers_once_without_new_turn_or_second_log(
    message_db, monkeypatch,
):
    """The keyed direct context permits a real running steer and brackets its provider call."""
    module = _message_module()
    monkeypatch.setattr(module, "ensure_target_runner", lambda _target_id: None)
    await _accept(module)

    from app.manager import SessionManager
    from app.session import AgentSession, AgentStatus

    manager = SessionManager()
    send_delivery = _required_callable(manager, "send_message_delivery")
    entered = asyncio.Event()
    release = asyncio.Event()

    class Backend:
        active_turn_id = "running-turn-380"
        deferred_interrupt_pending = False

        async def send(self, message):
            assert message == RENDERED
            entered.set()
            await release.wait()

    backend = Backend()
    session = AgentSession(
        id=TARGET_ID,
        name=TARGET_NAME,
        scope=SCOPE,
        cwd=f"/tmp/{TARGET_NAME}",
        model="gpt-5.6-sol",
        system_prompt="",
        created_at=datetime.now(timezone.utc),
        task_id=TARGET_TASK_ID,
        branch=TARGET_BRANCH,
    )
    session.backend_type = "codex"
    session.status = AgentStatus.RUNNING
    session._backend = backend
    session._ensure_backend = AsyncMock(return_value=backend)
    session._admission_service = AsyncMock(side_effect=AssertionError("quota read"))
    session._note_next_precompact_activity = MagicMock()
    session._attach_pending_facts = lambda message: (message, [])
    session._ack_pending_facts = MagicMock()
    session._log = MagicMock()
    session._persist = MagicMock()
    manager.sessions[TARGET_ID] = session

    prepared = _required_callable(module, "prepare_message_delivery")(DELIVERY_ID)
    context_type = getattr(module, "MessageDeliveryContext", None)
    assert context_type is not None, "#380 missing behavior: MessageDeliveryContext"
    context = context_type(
        DELIVERY_ID,
        history_user_message=prepared["history_user_message"],
    )
    steer = asyncio.create_task(send_delivery(
        TARGET_ID,
        RENDERED,
        delivery=context,
        target_generation=TARGET_GENERATION,
    ))
    assert await _spin_until(entered.is_set), "#380 keyed running steer never reached backend"
    assert session.status == AgentStatus.RUNNING
    assert _delivery_row(message_db)["state"] == "DISPATCHING"

    repeated, _status = await _accept(module)
    assert repeated["acceptance"] == "ALREADY_ACCEPTED"
    release.set()
    await steer

    assert session.status == AgentStatus.RUNNING
    session._admission_service.assert_not_awaited()
    assert session._pending_messages == []
    assert [row["content"] for row in _user_messages(message_db)] == [RENDERED]
    assert not [
        call for call in session._log.call_args_list
        if call.args and call.args[0] == "user_message"
    ]
    assert _delivery_row(message_db)["state"] == "SUBMITTED"


@pytest.mark.asyncio
async def test_t380_r3_mcp_timeout_reconciles_same_key_or_returns_ambiguous_id(
    monkeypatch,
):
    """MCP never loses or replaces the pre-POST delivery id on transport timeout."""
    import app.mcp_stdio as mcp

    parameters = inspect.signature(mcp.send_message).parameters
    assert "delivery_id" in parameters, (
        "#380 missing behavior: send_message has no caller-stable delivery_id"
    )
    monkeypatch.setattr(mcp, "SCOPE", SCOPE)
    monkeypatch.setattr(mcp, "WORKER_NAME", SOURCE_NAME)
    receipt = {
        "ok": True,
        "acceptance": "ALREADY_ACCEPTED",
        "delivery_id": DELIVERY_ID,
        "delivery_state": "QUEUED",
        "payload_hash": "a" * 64,
        "accept_seq": 1,
        "status_url": f"/api/message-deliveries/{DELIVERY_ID}",
    }
    calls = []

    async def accepted_then_timeout(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "POST":
            assert kwargs["json"]["delivery_id"] == DELIVERY_ID
            raise mcp.ApiToolError(
                code="transport_timeout",
                message="ReadTimeout",
                outcome_unknown=True,
                details={"request_not_sent": False, "method": "POST", "path": path},
            )
        assert method == "GET"
        return receipt

    monkeypatch.setattr(mcp, "_api", accepted_then_timeout)
    output = await mcp.send_message(
        to=TARGET_NAME,
        message=MESSAGE,
        delivery_id=DELIVERY_ID,
    )
    assert DELIVERY_ID in output
    assert "accepted" in output.lower()
    assert [(method, path) for method, path, _kw in calls] == [
        ("POST", f"/api/sessions/{TARGET_NAME}/send"),
        ("GET", f"/api/message-deliveries/{DELIVERY_ID}"),
    ]

    calls.clear()

    async def unavailable_reconciliation(method, path, **kwargs):
        calls.append((method, path, kwargs))
        raise mcp.ApiToolError(
            code="transport_timeout" if method == "POST" else "connect_error",
            message="ReadTimeout" if method == "POST" else "connection refused",
            retryable=method == "GET",
            outcome_unknown=method == "POST",
            details={"request_not_sent": method == "GET", "method": method, "path": path},
        )

    monkeypatch.setattr(mcp, "_api", unavailable_reconciliation)
    with pytest.raises(mcp.ApiToolError) as caught:
        await mcp.send_message(
            to=TARGET_NAME,
            message=MESSAGE,
            delivery_id=DELIVERY_ID,
        )
    assert caught.value.outcome_unknown is True
    assert caught.value.result["delivery_id"] == DELIVERY_ID
    assert caught.value.result["acceptance"] == "AMBIGUOUS"
    warning = caught.value.result["next_action"]["message"].lower()
    assert "new" in warning and ("do not" in warning or "never" in warning)
    assert [method for method, _path, _kw in calls] == ["POST", "GET"]


@pytest.mark.asyncio
async def test_t380_r3_blank_key_generates_once_before_post_and_status_tool_reads_it(
    monkeypatch,
):
    """Default MCP invocation uses one pre-POST UUID through timeout reconciliation."""
    import app.mcp_stdio as mcp

    parameters = inspect.signature(mcp.send_message).parameters
    assert "delivery_id" in parameters, (
        "#380 missing behavior: send_message has no caller-stable delivery_id"
    )
    status_tool = _required_callable(mcp, "message_delivery_status")
    monkeypatch.setattr(mcp, "SCOPE", SCOPE)
    monkeypatch.setattr(mcp, "WORKER_NAME", SOURCE_NAME)
    generated = []

    class FixedUUID:
        def __str__(self):
            return DELIVERY_ID

    def uuid_once():
        generated.append(DELIVERY_ID)
        return FixedUUID()

    monkeypatch.setattr(mcp.uuid, "uuid4", uuid_once)
    calls = []
    receipt = {
        "ok": True,
        "acceptance": "ALREADY_ACCEPTED",
        "delivery_id": DELIVERY_ID,
        "delivery_state": "QUEUED",
        "payload_hash": "b" * 64,
        "accept_seq": 8,
        "status_url": f"/api/message-deliveries/{DELIVERY_ID}",
    }

    async def fake_api(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if method == "POST":
            assert kwargs["json"]["delivery_id"] == DELIVERY_ID
            raise mcp.ApiToolError(
                code="transport_timeout",
                message="ReadTimeout",
                outcome_unknown=True,
                details={"request_not_sent": False},
            )
        return receipt

    monkeypatch.setattr(mcp, "_api", fake_api)
    output = await mcp.send_message(to=TARGET_NAME, message=MESSAGE)
    assert generated == [DELIVERY_ID]
    assert DELIVERY_ID in output
    assert [(method, path) for method, path, _kwargs in calls] == [
        ("POST", f"/api/sessions/{TARGET_NAME}/send"),
        ("GET", f"/api/message-deliveries/{DELIVERY_ID}"),
    ]

    calls.clear()
    status = await status_tool(DELIVERY_ID)
    assert status == receipt
    assert [(method, path) for method, path, _kwargs in calls] == [
        ("GET", f"/api/message-deliveries/{DELIVERY_ID}"),
    ]


@pytest.mark.asyncio
async def test_t370_unknown_receipt_tells_caller_how_to_check_and_retry_safely(
    monkeypatch,
):
    import app.mcp_stdio as mcp

    monkeypatch.setattr(mcp, "SCOPE", SCOPE)
    monkeypatch.setattr(mcp, "WORKER_NAME", SOURCE_NAME)
    unknown = {
        "ok": True,
        "acceptance": "ALREADY_ACCEPTED",
        "delivery_id": DELIVERY_ID,
        "delivery_state": "DELIVERY_UNKNOWN",
        "error": {
            "code": "DELIVERY_OUTCOME_UNKNOWN",
            "message": "Provider acknowledgement was lost",
            "outcome_unknown": True,
        },
        "next_action": {
            "code": "CHECK_DELIVERY_STATUS",
            "tool": "message_delivery_status",
            "arguments": {"delivery_id": DELIVERY_ID},
        },
    }

    async def provider_failure_then_status(method, path, **kwargs):
        if method == "POST":
            raise mcp.ApiToolError(
                code="transport_timeout",
                message="CodexProtocolError",
                outcome_unknown=True,
                details={"method": "POST", "path": path},
            )
        assert method == "GET"
        return unknown

    monkeypatch.setattr(mcp, "_api", provider_failure_then_status)
    output = await mcp.send_message(
        to=TARGET_NAME,
        message=MESSAGE,
        delivery_id=DELIVERY_ID,
    )

    assert "DELIVERY_OUTCOME_UNKNOWN" in output
    assert DELIVERY_ID in output
    assert f"message_delivery_status(delivery_id=\"{DELIVERY_ID}\")" in output
    assert "same delivery_id" in output
    assert "new id" in output


@pytest.mark.asyncio
async def test_t370_same_id_unknown_receipt_is_never_replayed(message_db, monkeypatch):
    module = _message_module()
    monkeypatch.setattr(module, "ensure_target_runner", lambda _target_id: None)
    await _accept(module)
    prepare = _required_callable(module, "prepare_message_delivery")
    dispatching = _required_callable(module, "mark_message_delivery_dispatching")
    unknown = _required_callable(module, "mark_message_delivery_unknown")
    prepare(DELIVERY_ID)
    dispatching(DELIVERY_ID)
    unknown(DELIVERY_ID, RuntimeError("provider acknowledgement lost"))

    repeated, status = await _accept(module)
    assert status == 202
    assert repeated["acceptance"] == "ALREADY_ACCEPTED"
    assert repeated["delivery_state"] == "DELIVERY_UNKNOWN"
    assert repeated["next_action"]["tool"] == "message_delivery_status"

    manager = _ImmediateManager()
    await module.run_target_message_deliveries(TARGET_ID, manager=manager)
    assert manager.provider_attempts == []


@pytest.mark.asyncio
async def test_t380_r4_pre_dispatch_cancel_and_restart_recover_same_receipt_once(
    message_db, monkeypatch,
):
    """Known pre-submit cancellation is same-key retryable and restart-safe."""
    module = _message_module()
    monkeypatch.setattr(module, "ensure_target_runner", lambda _target_id: None)
    await _accept(module)
    entered = asyncio.Event()

    class CancelBeforeSubmit:
        async def send_message_delivery(
            self, session_id, message, *, delivery, target_generation,
        ):
            entered.set()
            await asyncio.Event().wait()

    run = _required_callable(module, "run_message_delivery")
    task = asyncio.create_task(run(DELIVERY_ID, manager=CancelBeforeSubmit()))
    assert await _spin_until(entered.is_set), "#380 pre-submit runner never entered"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    row = _delivery_row(message_db)
    assert row["state"] == "FAILED_BEFORE_SUBMIT"
    assert len(_user_messages(message_db)) == 1

    scheduled = []
    monkeypatch.setattr(
        module, "ensure_target_runner", lambda target_id: scheduled.append(target_id),
    )
    repeated, status = await _accept(module)
    assert status == 202
    assert repeated["acceptance"] == "ALREADY_ACCEPTED"
    assert repeated["delivery_state"] == "PREPARING"
    assert scheduled == [TARGET_ID]

    manager = _ImmediateManager()
    run_target = _required_callable(module, "run_target_message_deliveries")
    await run_target(TARGET_ID, manager=manager)
    assert _delivery_row(message_db)["state"] == "SUBMITTED"
    assert len(_user_messages(message_db)) == 1
    assert manager.provider_attempts == [RENDERED]

    # A second logical receipt loses every in-memory runner before a simulated restart.
    monkeypatch.setattr(module, "ensure_target_runner", lambda _target_id: None)
    await _accept(
        module,
        delivery_id=DELIVERY_ID_2,
        message=MESSAGE + " after restart",
        rendered_message=RENDERED + " after restart",
    )
    _required_callable(module, "prepare_message_delivery")(DELIVERY_ID_2)
    scheduled.clear()
    runner_registry = getattr(module, "_target_runner_tasks", None)
    if isinstance(runner_registry, dict):
        runner_registry.clear()
    monkeypatch.setattr(
        module, "ensure_target_runner", lambda target_id: scheduled.append(target_id),
    )
    recover = _required_callable(module, "recover_message_deliveries")
    await recover()
    assert scheduled == [TARGET_ID]

    restarted = _ImmediateManager()
    await run_target(TARGET_ID, manager=restarted)
    assert restarted.provider_attempts == [RENDERED + " after restart"]
    scheduled.clear()
    await recover()
    assert scheduled == []
    assert manager.provider_attempts == [RENDERED]
    assert len(_user_messages(message_db)) == 2


@pytest.mark.asyncio
async def test_t380_r4_prepare_log_and_state_rollback_atomically(
    message_db, monkeypatch,
):
    """Neither side of user-log plus PREPARING can commit without the other."""
    module = _message_module()
    monkeypatch.setattr(module, "ensure_target_runner", lambda _target_id: None)
    await _accept(module)
    prepare = _required_callable(module, "prepare_message_delivery")

    with message_db._conn() as connection:
        connection.execute(
            """CREATE TRIGGER fail_t380_user_log_insert
               BEFORE INSERT ON logs WHEN NEW.type='user_message'
               BEGIN SELECT RAISE(ABORT, 'forced user log rollback'); END"""
        )
    with pytest.raises(sqlite3.DatabaseError, match="forced user log rollback"):
        prepare(DELIVERY_ID)
    assert _delivery_row(message_db)["state"] == "QUEUED"
    assert _delivery_row(message_db)["user_log_id"] is None
    assert _user_messages(message_db) == []

    with message_db._conn() as connection:
        connection.execute("DROP TRIGGER fail_t380_user_log_insert")
        connection.execute(
            """CREATE TRIGGER fail_t380_preparing_update
               BEFORE UPDATE OF state ON message_deliveries
               WHEN OLD.delivery_id='00000000-0000-4000-8000-000000000380'
                    AND NEW.state='PREPARING'
               BEGIN SELECT RAISE(ABORT, 'forced preparing rollback'); END"""
        )
    with pytest.raises(sqlite3.DatabaseError, match="forced preparing rollback"):
        prepare(DELIVERY_ID)
    assert _delivery_row(message_db)["state"] == "QUEUED"
    assert _delivery_row(message_db)["user_log_id"] is None
    assert _user_messages(message_db) == []

    with message_db._conn() as connection:
        connection.execute("DROP TRIGGER fail_t380_preparing_update")
    prepared = prepare(DELIVERY_ID)
    assert prepared["delivery_state"] == "PREPARING"
    assert prepared["user_log_id"]
    assert [row["content"] for row in _user_messages(message_db)] == [RENDERED]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["cancel", "raise"])
async def test_t380_r5_post_dispatch_failure_is_unknown_and_never_replayed(
    message_db, monkeypatch, failure,
):
    """A provider attempt is the no-replay boundary for error and cancellation."""
    module = _message_module()
    monkeypatch.setattr(module, "ensure_target_runner", lambda _target_id: None)
    await _accept(module)
    external_attempts = []

    class AcceptedThenLost:
        async def send_message_delivery(
            self, session_id, message, *, delivery, target_generation,
        ):
            await delivery.before_submit()
            external_attempts.append(message)
            if failure == "cancel":
                raise asyncio.CancelledError()
            raise RuntimeError("provider acknowledgement lost")

    run = _required_callable(module, "run_message_delivery")
    if failure == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await run(DELIVERY_ID, manager=AcceptedThenLost())
    else:
        with pytest.raises(RuntimeError, match="acknowledgement lost"):
            await run(DELIVERY_ID, manager=AcceptedThenLost())

    original = _delivery_row(message_db)
    assert original["state"] == "DELIVERY_UNKNOWN"
    assert external_attempts == [RENDERED]
    assert len(_user_messages(message_db)) == 1

    scheduled = []
    monkeypatch.setattr(
        module, "ensure_target_runner", lambda target_id: scheduled.append(target_id),
    )
    recover = _required_callable(module, "recover_message_deliveries")
    await recover()
    await recover()
    await recover()
    repeated, status = await _accept(module)
    assert status == 202
    assert repeated["acceptance"] == "ALREADY_ACCEPTED"
    assert repeated["delivery_state"] == "DELIVERY_UNKNOWN"
    assert repeated["next_action"]["code"] == "CHECK_DELIVERY_STATUS"
    assert repeated["next_action"]["retryable"] is False
    assert scheduled == []
    assert external_attempts == [RENDERED]


@pytest.mark.asyncio
async def test_t380_r5_recovery_quarantines_orphan_dispatching_without_schedule(
    message_db, monkeypatch,
):
    """Startup sees DISPATCHING as ambiguous even if no in-memory runner survives."""
    module = _message_module()
    monkeypatch.setattr(module, "ensure_target_runner", lambda _target_id: None)
    await _accept(module)
    _required_callable(module, "prepare_message_delivery")(DELIVERY_ID)
    _required_callable(module, "mark_message_delivery_dispatching")(DELIVERY_ID)
    external_attempts = [RENDERED]  # provider may already have accepted before process loss
    scheduled = []
    monkeypatch.setattr(
        module, "ensure_target_runner", lambda target_id: scheduled.append(target_id),
    )

    recover = _required_callable(module, "recover_message_deliveries")
    await recover()
    row = _delivery_row(message_db)
    error = json.loads(row["error_json"])
    assert row["state"] == "DELIVERY_UNKNOWN"
    assert error["outcome_unknown"] is True
    assert error["details"]["phase"] == "PROVIDER_CALL_STARTED"
    assert scheduled == []
    assert external_attempts == [RENDERED]

    repeated, status = await _accept(module)
    assert status == 202
    assert repeated["delivery_state"] == "DELIVERY_UNKNOWN"
    assert repeated["next_action"]["retryable"] is False
    assert scheduled == []
    assert external_attempts == [RENDERED]


def _response_payload(response):
    if isinstance(response, dict):
        return response
    body = getattr(response, "body", b"")
    return json.loads(body.decode("utf-8")) if body else {}


def _request_with_proof(session_id, proof):
    return SimpleNamespace(
        headers={
            "x-orchestra-session-id": session_id,
            "x-orchestra-mcp-proof": proof,
        },
        cookies={},
    )


@pytest.mark.asyncio
async def test_t401_quota_refusal_is_returned_before_receipt_or_user_log(
    message_db, monkeypatch,
):
    """A known quota refusal is visible to the MCP caller, not an accepted queue row."""
    from app.quota_gate import evaluate_worker_admission
    from app.mcp_proof import issue_mcp_proof
    from app.routes import sessions as routes

    target = routes.manager.get_by_name(TARGET_NAME, SCOPE)
    assert target is not None
    target.model = "claude-sonnet-5[1m]"
    now = datetime.now(timezone.utc).timestamp()
    reset_at = datetime.fromtimestamp(
        now + 10080 * 60 / 2, timezone.utc,
    ).isoformat()
    blocked = evaluate_worker_admission(
        target.model,
        {"anthropic": {"label": "Claude", "windows": [{
            "id": "seven_day",
            "window_minutes": 10080,
            "utilization": 95,
            "resets_at": reset_at,
        }]}},
        {"anthropic": now},
        now=now,
    )
    target._admission_service = AsyncMock(return_value=blocked)
    monkeypatch.setitem(routes.manager.sessions, TARGET_ID, target)
    request = _request_with_proof(SOURCE_ID, issue_mcp_proof(SOURCE_ID))
    response = await routes.send_message(
        TARGET_NAME,
        routes.SendRequest(
            delivery_id=DELIVERY_ID,
            message=MESSAGE,
            sender=SOURCE_NAME,
            scope=SCOPE,
        ),
        request=request,
    )

    assert getattr(response, "status_code", None) == 429
    payload = _response_payload(response)
    error = payload["error"]
    assert error["code"] == "weekly_quota_blocked"
    assert "Claude" in error["message"]
    assert "95%" in error["message"]
    assert "line limit" in error["message"]
    assert "55.5" in error["message"]
    assert _delivery_row(message_db) is None
    assert _user_messages(message_db) == []


@pytest.mark.asyncio
async def test_t380_r6_http_auth_conflict_rollback_and_name_ambiguity_are_known(
    message_db, monkeypatch,
):
    """Keyed REST derives identity from MCP proof and rejects every pre-accept spoof."""
    from app import db
    from app.mcp_proof import issue_mcp_proof
    from app.routes import sessions as routes

    assert "delivery_id" in routes.SendRequest.model_fields, (
        "#380 missing behavior: SendRequest has no opt-in delivery_id"
    )
    assert "request" in inspect.signature(routes.send_message).parameters, (
        "#380 missing behavior: keyed send route cannot authenticate the Request"
    )
    module = _message_module()
    monkeypatch.setattr(module, "ensure_target_runner", lambda _target_id: None)
    proof = issue_mcp_proof(SOURCE_ID)
    request = _request_with_proof(SOURCE_ID, proof)

    async def post(*, delivery_id, message=MESSAGE, sender=SOURCE_NAME, scope=SCOPE, name=TARGET_NAME):
        req = routes.SendRequest(
            delivery_id=delivery_id,
            message=message,
            sender=sender,
            scope=scope,
        )
        return await routes.send_message(name, req, request=request)

    accepted = await post(delivery_id=DELIVERY_ID)
    assert getattr(accepted, "status_code", None) == 202
    accepted_payload = _response_payload(accepted)
    assert accepted_payload["acceptance"] == "ACCEPTED"
    assert accepted_payload["delivery_id"] == DELIVERY_ID
    accepted_row = _delivery_row(message_db)
    assert accepted_row["source_session_id"] == SOURCE_ID
    assert accepted_row["source_scope"] == SCOPE
    assert accepted_row["source_task_id"] == TARGET_TASK_ID
    assert accepted_row["target_session_id"] == TARGET_ID
    assert accepted_row["target_scope"] == SCOPE
    assert accepted_row["target_task_id"] == TARGET_TASK_ID

    status_route = next(
        (
            route for route in routes.router.routes
            if getattr(route, "path", "") == "/api/message-deliveries/{delivery_id}"
            and "GET" in getattr(route, "methods", set())
        ),
        None,
    )
    assert status_route is not None, (
        "#380 missing behavior: authenticated message-delivery status route"
    )
    owner_status = await status_route.endpoint(DELIVERY_ID, request=request)
    assert getattr(owner_status, "status_code", 200) == 200
    assert _response_payload(owner_status)["delivery_id"] == DELIVERY_ID

    other_source_id = "other-source-session-380"
    db.save_session(_session_record(
        session_id=other_source_id,
        name="other-source-380",
        scope="/other-source",
        task_id="999",
        branch="task-999/other-source-380",
        role="orchestrator",
    ))
    other_proof = issue_mcp_proof(other_source_id)
    denied_status = await status_route.endpoint(
        DELIVERY_ID,
        request=_request_with_proof(other_source_id, other_proof),
    )
    token_only_status = await status_route.endpoint(
        DELIVERY_ID,
        request=SimpleNamespace(
            headers={"authorization": "Bearer shared-internal-token"},
            cookies={},
        ),
    )
    for response in (denied_status, token_only_status):
        assert getattr(response, "status_code", None) == 403
        assert _response_payload(response)["error"]["outcome_unknown"] is False

    from app.auth import create_session
    monkeypatch.setenv("DASHBOARD_USER", "owner-380")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "secret-380")
    operator_request = SimpleNamespace(
        headers={},
        cookies={"session": create_session("owner-380")},
    )
    operator_status = await status_route.endpoint(
        DELIVERY_ID,
        request=operator_request,
    )
    assert getattr(operator_status, "status_code", 200) == 200
    operator_delivery_id = "00000000-0000-4000-8000-000000000385"
    operator_send = await routes.send_message(
        TARGET_NAME,
        routes.SendRequest(
            delivery_id=operator_delivery_id,
            message="operator direct message",
            scope=SCOPE,
        ),
        request=operator_request,
    )
    assert getattr(operator_send, "status_code", None) == 202
    operator_row = _delivery_row(message_db, operator_delivery_id)
    assert operator_row["source_session_id"] in {None, ""}
    assert operator_row["source_principal"].startswith("operator:")
    assert operator_row["source_scope"] == SCOPE

    conflict = await post(delivery_id=DELIVERY_ID, message=MESSAGE + " changed")
    assert getattr(conflict, "status_code", None) == 409
    assert _response_payload(conflict)["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    forged_sender = await post(
        delivery_id="00000000-0000-4000-8000-000000000386",
        sender="spoofed-source",
    )
    forged_scope = await post(
        delivery_id="00000000-0000-4000-8000-000000000387",
        scope="/spoofed-scope",
    )
    no_proof_req = routes.SendRequest(
        delivery_id="00000000-0000-4000-8000-000000000388",
        message=MESSAGE,
        sender=SOURCE_NAME,
        scope=SCOPE,
    )
    no_proof = await routes.send_message(
        TARGET_NAME,
        no_proof_req,
        request=_request_with_proof(SOURCE_ID, "wrong-proof"),
    )
    for response in (forged_sender, forged_scope, no_proof):
        assert getattr(response, "status_code", None) == 403
        assert _response_payload(response)["error"]["outcome_unknown"] is False

    for index, other_scope in enumerate(("/other-a", "/other-b"), start=1):
        db.save_session(_session_record(
            session_id=f"ambiguous-target-{index}",
            name="ambiguous-380",
            scope=other_scope,
            task_id="380",
            branch=f"task-380/ambiguous-{index}",
        ))
    ambiguous = await post(
        delivery_id="00000000-0000-4000-8000-000000000389",
        name="ambiguous-380",
    )
    assert getattr(ambiguous, "status_code", None) == 409
    assert _response_payload(ambiguous)["error"]["code"] == "TARGET_NAME_AMBIGUOUS"

    cross_target_id = "cross-target-session-380"
    db.save_session(_session_record(
        session_id=cross_target_id,
        name="unique-cross-target-380",
        scope="/cross-project-380",
        task_id="55",
        branch="task-55/unique-cross-target-380",
    ))
    cross_delivery_id = "00000000-0000-4000-8000-000000000393"
    cross_project = await post(
        delivery_id=cross_delivery_id,
        name="unique-cross-target-380",
    )
    assert getattr(cross_project, "status_code", None) == 202
    cross_row = _delivery_row(message_db, cross_delivery_id)
    assert cross_row["source_session_id"] == SOURCE_ID
    assert cross_row["target_session_id"] == cross_target_id
    assert cross_row["target_scope"] == "/cross-project-380"
    assert cross_row["target_task_id"] == "55"

    archived = _session_record(
        session_id="archived-target-session-380",
        name="archived-target-380",
        scope=SCOPE,
        task_id="56",
        branch="task-56/archived-target-380",
    )
    archived["status"] = "archived"
    archived["finished_at"] = datetime.now(timezone.utc).isoformat()
    db.save_session(archived)
    archived_response = await post(
        delivery_id="00000000-0000-4000-8000-000000000394",
        name="archived-target-380",
    )
    assert getattr(archived_response, "status_code", None) == 404
    assert _response_payload(archived_response)["error"]["outcome_unknown"] is False

    with message_db._conn() as connection:
        connection.execute(
            """CREATE TRIGGER fail_t380_message_accept
               BEFORE INSERT ON message_deliveries
               BEGIN SELECT RAISE(ABORT, 'forced direct receipt rollback'); END"""
        )
    rolled_back = await post(
        delivery_id="00000000-0000-4000-8000-000000000390",
    )
    assert getattr(rolled_back, "status_code", None) == 503
    error = _response_payload(rolled_back)["error"]
    assert error["code"] == "DELIVERY_ACCEPT_REJECTED"
    assert error["outcome_unknown"] is False
    assert error["details"]["commit_state"] == "NOT_COMMITTED"

    with message_db._conn() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM message_deliveries"
        ).fetchone()[0] == 3
    assert _user_messages(message_db) == []


@pytest.mark.asyncio
async def test_t380_r7_concurrent_accept_and_competing_runners_follow_accept_seq(
    message_db, monkeypatch,
):
    """BEGIN IMMEDIATE commit order is the sole FIFO order under concurrency."""
    module = _message_module()
    monkeypatch.setattr(module, "ensure_target_runner", lambda _target_id: None)
    barrier = threading.Barrier(3)
    results = []
    failures = []

    def accept_in_thread(delivery_id, suffix):
        try:
            barrier.wait()
            result = asyncio.run(_accept(
                module,
                delivery_id=delivery_id,
                message=MESSAGE + suffix,
                rendered_message=RENDERED + suffix,
            ))
            results.append((suffix, result))
        except BaseException as error:  # surfaced in the main test below
            failures.append(error)

    threads = [
        threading.Thread(
            target=accept_in_thread,
            args=(DELIVERY_ID, " concurrent-a"),
        ),
        threading.Thread(
            target=accept_in_thread,
            args=(DELIVERY_ID_2, " concurrent-b"),
        ),
    ]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        await asyncio.to_thread(thread.join)
    assert failures == []
    assert len(results) == 2

    ordered = sorted(
        (
            (resource["accept_seq"], RENDERED + suffix)
            for suffix, (resource, status) in results
            if status == 202
        ),
    )
    assert len(ordered) == 2
    manager = _ImmediateManager()
    run_target = _required_callable(module, "run_target_message_deliveries")
    await asyncio.gather(
        run_target(TARGET_ID, manager=manager),
        run_target(TARGET_ID, manager=manager),
    )
    assert manager.provider_attempts == [message for _seq, message in ordered]
    assert _delivery_row(message_db, DELIVERY_ID)["state"] == "SUBMITTED"
    assert _delivery_row(message_db, DELIVERY_ID_2)["state"] == "SUBMITTED"
    assert len(_user_messages(message_db)) == 2


@pytest.mark.asyncio
async def test_t380_r7_accept_while_runner_exits_cannot_lose_wake(
    message_db, monkeypatch,
):
    """A commit between empty-head read and task teardown is rechecked durably."""
    module = _message_module()
    real_ensure = _required_callable(module, "ensure_target_runner")
    monkeypatch.setattr(module, "ensure_target_runner", lambda _target_id: None)
    await _accept(module)
    monkeypatch.setattr(module, "ensure_target_runner", real_ensure)
    next_delivery = _required_callable(module, "_next_target_delivery")
    observe_runner = _required_callable(module, "_observe_target_runner")
    registry = getattr(module, "_target_runner_tasks", None)
    assert isinstance(registry, dict), "#380 missing behavior: per-target runner registry"
    empty_seen = threading.Event()
    allow_empty_return = threading.Event()
    inserted = []
    thread_failures = []
    gated_once = False

    def gated_next(target_session_id):
        nonlocal gated_once
        row = next_delivery(target_session_id)
        if row is None and not gated_once:
            gated_once = True
            empty_seen.set()
            assert allow_empty_return.wait(2), "#380 lost-wake insertion thread stalled"
        return row

    monkeypatch.setattr(module, "_next_target_delivery", gated_next)
    manager = _ImmediateManager()
    from app import deps
    monkeypatch.setattr(deps, "manager", manager)

    def insert_at_exit_boundary():
        try:
            assert empty_seen.wait(2), "#380 runner never reached empty-head boundary"
            inserted.append(asyncio.run(_accept(
                module,
                delivery_id=DELIVERY_ID_2,
                message=MESSAGE + " late",
                rendered_message=RENDERED + " late",
            )))
        except BaseException as error:
            thread_failures.append(error)
        finally:
            allow_empty_return.set()

    inserter = threading.Thread(target=insert_at_exit_boundary)
    inserter.start()
    real_ensure(TARGET_ID)
    first_runner = registry.get(TARGET_ID)
    assert isinstance(first_runner, asyncio.Task), (
        "#380 ensure_target_runner did not create/register the production runner"
    )
    callbacks = getattr(first_runner, "_callbacks", None) or []
    assert callbacks, "#380 ensure_target_runner registered no completion callback"
    await first_runner
    await asyncio.to_thread(inserter.join)
    assert thread_failures == []
    assert inserted and inserted[0][1] == 202
    assert await _spin_until(
        lambda: _delivery_row(message_db, DELIVERY_ID_2)["state"] == "SUBMITTED"
    ), "#380 committed receipt was stranded at runner teardown"
    assert manager.provider_attempts == [RENDERED, RENDERED + " late"]
    remaining = [task for task in registry.values() if not task.done()]
    if remaining:
        await asyncio.gather(*remaining)


@pytest.mark.asyncio
async def test_t380_r7_fifo_and_unknown_head_block_later_receipts(
    message_db, monkeypatch,
):
    """Commit sequence is FIFO, and ambiguity is a deliberate head-of-line barrier."""
    module = _message_module()
    monkeypatch.setattr(module, "ensure_target_runner", lambda _target_id: None)
    first, _ = await _accept(module)
    second, _ = await _accept(
        module,
        delivery_id=DELIVERY_ID_2,
        message=MESSAGE + " second",
        rendered_message=RENDERED + " second",
    )
    assert first["accept_seq"] < second["accept_seq"]

    manager = _ImmediateManager()
    run_target = _required_callable(module, "run_target_message_deliveries")
    await run_target(TARGET_ID, manager=manager)
    assert manager.provider_attempts == [RENDERED, RENDERED + " second"]

    blocked_id = "00000000-0000-4000-8000-000000000391"
    tail_id = "00000000-0000-4000-8000-000000000392"
    await _accept(
        module,
        delivery_id=blocked_id,
        message="ambiguous head",
        rendered_message="ambiguous head",
    )
    await _accept(
        module,
        delivery_id=tail_id,
        message="must not overtake",
        rendered_message="must not overtake",
    )
    _required_callable(module, "prepare_message_delivery")(blocked_id)
    _required_callable(module, "mark_message_delivery_dispatching")(blocked_id)
    _required_callable(module, "mark_message_delivery_unknown")(
        blocked_id,
        RuntimeError("provider outcome lost"),
    )
    manager.provider_attempts.clear()
    await run_target(TARGET_ID, manager=manager)
    assert manager.provider_attempts == []
    assert _delivery_row(message_db, blocked_id)["state"] == "DELIVERY_UNKNOWN"
    assert _delivery_row(message_db, tail_id)["state"] == "QUEUED"


@pytest.mark.asyncio
async def test_t380_r7_task_generation_change_fails_before_provider(
    message_db, monkeypatch,
):
    """A receipt cannot cross an ABA-sensitive target task/branch generation change."""
    module = _message_module()
    monkeypatch.setattr(module, "ensure_target_runner", lambda _target_id: None)
    await _accept(module)

    from app.manager import SessionManager
    from app.session import AgentStatus

    manager = SessionManager()
    _required_callable(manager, "send_message_delivery")
    session = SimpleNamespace(
        id=TARGET_ID,
        name=TARGET_NAME,
        scope=SCOPE,
        task_id="381",
        branch="task-381/target-380",
        needs_switch=False,
        status=AgentStatus.IDLE,
        send=AsyncMock(),
    )
    manager.sessions[TARGET_ID] = session
    run = _required_callable(module, "run_message_delivery")
    with pytest.raises(RuntimeError, match="task generation"):
        await run(DELIVERY_ID, manager=manager)

    session.send.assert_not_awaited()
    row = _delivery_row(message_db)
    assert row["state"] == "FAILED_BEFORE_SUBMIT"
    error = json.loads(row["error_json"])
    assert error["code"] == "TARGET_TASK_CHANGED"
    assert error["outcome_unknown"] is False
    assert _user_messages(message_db)[0]["content"] == RENDERED


@pytest.mark.asyncio
async def test_t380_r7_no_inject_turn_finalization_wakes_durable_receipt(
    message_db, monkeypatch,
):
    """A real no-inject turn finalizer wakes the SQLite receipt exactly once."""
    module = _message_module()
    real_ensure = _required_callable(module, "ensure_target_runner")
    monkeypatch.setattr(module, "ensure_target_runner", lambda _target_id: None)
    await _accept(module)

    from app.manager import SessionManager
    from app.session import AgentSession, AgentStatus

    manager = SessionManager()
    _required_callable(manager, "send_message_delivery")
    backend = SimpleNamespace(
        active_turn_id="running-turn-380",
        deferred_interrupt_pending=False,
        send=AsyncMock(),
    )

    async def empty_events():
        if False:
            yield None

    backend.events = empty_events
    session = AgentSession(
        id=TARGET_ID,
        name=TARGET_NAME,
        scope=SCOPE,
        cwd=f"/tmp/{TARGET_NAME}",
        model="gpt-5.6-sol",
        system_prompt="",
        created_at=datetime.now(timezone.utc),
        task_id=TARGET_TASK_ID,
        branch=TARGET_BRANCH,
    )
    session.backend_type = "grok"
    session.status = AgentStatus.RUNNING
    session._backend = backend
    session._ensure_backend = AsyncMock(return_value=backend)
    session._note_next_precompact_activity = MagicMock()
    session._log = MagicMock()
    session._persist = MagicMock()
    session._hibernate.schedule = MagicMock()
    manager.sessions[TARGET_ID] = session

    run = _required_callable(module, "run_message_delivery")
    await run(DELIVERY_ID, manager=manager)
    assert _delivery_row(message_db)["state"] == "PREPARING"
    assert len(_user_messages(message_db)) == 1
    assert session._pending_messages == []
    backend.send.assert_not_awaited()

    from app import deps
    resumed = _ImmediateManager()
    monkeypatch.setattr(deps, "manager", resumed)
    monkeypatch.setattr(module, "ensure_target_runner", real_ensure)
    await session._turn_event_loop()
    registry = getattr(module, "_target_runner_tasks", {})
    pending = [task for task in registry.values() if not task.done()]
    if pending:
        await asyncio.gather(*pending)
    assert resumed.provider_attempts == [RENDERED]
    assert _delivery_row(message_db)["state"] == "SUBMITTED"
    assert len(_user_messages(message_db)) == 1


@pytest.mark.asyncio
async def test_t380_r7_native_compact_completion_wakes_durable_receipt(
    message_db, monkeypatch,
):
    """The actual Codex compact finally path drains the keyed durable receipt."""
    module = _message_module()
    real_ensure = _required_callable(module, "ensure_target_runner")
    monkeypatch.setattr(module, "ensure_target_runner", lambda _target_id: None)
    await _accept(module)

    from app.manager import SessionManager
    from app.session import AgentSession, AgentStatus

    compact_started = asyncio.Event()
    finish_compact = asyncio.Event()

    async def compact_context():
        compact_started.set()
        await finish_compact.wait()
        return {
            "ok": True,
            "thread_id": "compact-thread-380",
            "context_tokens": 30_000,
            "max_tokens": 258_400,
        }

    backend = SimpleNamespace(
        compact_context=AsyncMock(side_effect=compact_context),
        send=AsyncMock(),
    )
    session = AgentSession(
        id=TARGET_ID,
        name=TARGET_NAME,
        scope=SCOPE,
        cwd=f"/tmp/{TARGET_NAME}",
        model="gpt-5.6-sol",
        system_prompt="",
        created_at=datetime.now(timezone.utc),
        task_id=TARGET_TASK_ID,
        branch=TARGET_BRANCH,
        is_orchestrator=True,
    )
    session.backend_type = "codex"
    session.status = AgentStatus.IDLE
    session.session_id = "compact-thread-380"
    session._last_context = {
        "percentage": 88,
        "total_tokens": 227_000,
        "max_tokens": 258_400,
    }
    session._backend = backend
    session._ensure_backend = AsyncMock(return_value=backend)
    session._note_next_precompact_activity = MagicMock()
    session._log = MagicMock()
    session._persist = MagicMock()
    session._hibernate.schedule = MagicMock()
    manager = SessionManager()
    _required_callable(manager, "send_message_delivery")
    manager.sessions[TARGET_ID] = session

    compact_task = asyncio.create_task(session.compact())
    assert await _spin_until(compact_started.is_set), "#380 compact path never entered"
    assert session._compacting is True
    run = _required_callable(module, "run_message_delivery")
    await run(DELIVERY_ID, manager=manager)
    assert _delivery_row(message_db)["state"] == "PREPARING"
    assert session._pending_messages == []
    assert len(_user_messages(message_db)) == 1

    from app import deps
    resumed = _ImmediateManager()
    monkeypatch.setattr(deps, "manager", resumed)
    monkeypatch.setattr(module, "ensure_target_runner", real_ensure)
    finish_compact.set()
    compact_result = await compact_task
    assert compact_result["ok"] is True
    registry = getattr(module, "_target_runner_tasks", {})
    pending = [task for task in registry.values() if not task.done()]
    if pending:
        await asyncio.gather(*pending)
    assert resumed.provider_attempts == [RENDERED]
    assert _delivery_row(message_db)["state"] == "SUBMITTED"
    assert len(_user_messages(message_db)) == 1


@pytest.mark.asyncio
async def test_t380_r7_claude_compact_completion_wakes_durable_receipt(
    message_db, monkeypatch,
):
    """The actual summary+ack compact finally path also drains the durable receipt."""
    module = _message_module()
    real_ensure = _required_callable(module, "ensure_target_runner")
    monkeypatch.setattr(module, "ensure_target_runner", lambda _target_id: None)
    await _accept(module)

    from app.events import AgentEvent
    from app.manager import SessionManager
    from app.session import AgentSession, AgentStatus

    compact_started = asyncio.Event()
    finish_summary_send = asyncio.Event()

    class CompactBackend:
        session_id = None

        def __init__(self):
            self.send_count = 0

        async def connect(self):
            return None

        async def send(self, _message):
            self.send_count += 1
            if self.send_count == 1:
                compact_started.set()
                await finish_summary_send.wait()

        async def events(self):
            yield AgentEvent(
                type="text",
                content="TASK STATE: compacting #380. " + "x" * 250,
            )
            yield AgentEvent(
                type="turn_end",
                metadata={
                    "ok": True,
                    "stop_reason": "end_turn",
                    "num_turns": 1,
                    "session_id": "post-compact-380",
                },
            )

        async def disconnect(self):
            return None

    backend = CompactBackend()
    session = AgentSession(
        id=TARGET_ID,
        name=TARGET_NAME,
        scope=SCOPE,
        cwd=f"/tmp/{TARGET_NAME}",
        model="claude-sonnet-5[1m]",
        system_prompt="",
        created_at=datetime.now(timezone.utc),
        task_id=TARGET_TASK_ID,
        branch=TARGET_BRANCH,
        is_orchestrator=True,
    )
    session.backend_type = "claude"
    session.status = AgentStatus.IDLE
    session.session_id = "pre-compact-380"
    session._backend = None
    session._log = MagicMock()
    session._persist = MagicMock()
    session._hibernate.schedule = MagicMock()
    ack_scheduled = False

    async def ensure_backend(force_fresh=False, **_kwargs):
        nonlocal ack_scheduled
        session._backend = backend
        if force_fresh and not ack_scheduled and session._compact_ack_event:
            async def finish_ack():
                await asyncio.sleep(0)
                if session._compact_ack_event:
                    session._compact_ack_event.set()
            asyncio.create_task(finish_ack())
            ack_scheduled = True
        return backend

    session._make_backend = MagicMock(return_value=backend)
    session._ensure_backend = AsyncMock(side_effect=ensure_backend)
    monkeypatch.setattr("app.bg_jobs.bg_manager", None)
    monkeypatch.setattr(
        "app.session._claude_subscription_limit_active",
        lambda: False,
    )
    manager = SessionManager()
    _required_callable(manager, "send_message_delivery")
    manager.sessions[TARGET_ID] = session

    compact_task = asyncio.create_task(session.compact())
    assert await _spin_until(compact_started.is_set), "#380 Claude compact never entered"
    assert session._compacting is True
    run = _required_callable(module, "run_message_delivery")
    await run(DELIVERY_ID, manager=manager)
    assert _delivery_row(message_db)["state"] == "PREPARING"
    assert session._pending_messages == []
    assert len(_user_messages(message_db)) == 1

    from app import deps
    resumed = _ImmediateManager()
    monkeypatch.setattr(deps, "manager", resumed)
    monkeypatch.setattr(module, "ensure_target_runner", real_ensure)
    finish_summary_send.set()
    compact_result = await compact_task
    assert compact_result["ok"] is True
    registry = getattr(module, "_target_runner_tasks", {})
    pending = [task for task in registry.values() if not task.done()]
    if pending:
        await asyncio.gather(*pending)
    assert resumed.provider_attempts == [RENDERED]
    assert _delivery_row(message_db)["state"] == "SUBMITTED"
    assert len(_user_messages(message_db)) == 1


@pytest.mark.asyncio
async def test_t380_r7_deferred_interrupt_stays_durable_not_volatile(
    message_db, monkeypatch,
):
    """#385 control keeps a keyed wake in SQLite until the native terminal boundary."""
    module = _message_module()
    real_ensure = _required_callable(module, "ensure_target_runner")
    monkeypatch.setattr(module, "ensure_target_runner", lambda _target_id: None)
    await _accept(module)

    from app.manager import SessionManager
    from app.session import AgentSession, AgentStatus

    manager = SessionManager()
    _required_callable(manager, "send_message_delivery")
    backend = SimpleNamespace(
        active_turn_id="dying-turn-385",
        deferred_interrupt_pending=True,
        send=AsyncMock(),
    )

    async def empty_events():
        if False:
            yield None

    backend.events = empty_events
    session = AgentSession(
        id=TARGET_ID,
        name=TARGET_NAME,
        scope=SCOPE,
        cwd=f"/tmp/{TARGET_NAME}",
        model="gpt-5.6-sol",
        system_prompt="",
        created_at=datetime.now(timezone.utc),
        task_id=TARGET_TASK_ID,
        branch=TARGET_BRANCH,
    )
    session.backend_type = "codex"
    session.status = AgentStatus.RUNNING
    session._backend = backend
    session._ensure_backend = AsyncMock(return_value=backend)
    session._note_next_precompact_activity = MagicMock()
    session._log = MagicMock()
    session._persist = MagicMock()
    session._hibernate.schedule = MagicMock()
    manager.sessions[TARGET_ID] = session

    run = _required_callable(module, "run_message_delivery")
    await run(DELIVERY_ID, manager=manager)
    assert _delivery_row(message_db)["state"] == "PREPARING"
    assert len(_user_messages(message_db)) == 1
    assert session._pending_messages == []
    backend.send.assert_not_awaited()

    backend.deferred_interrupt_pending = False
    resumed = _ImmediateManager()
    from app import deps
    monkeypatch.setattr(deps, "manager", resumed)
    monkeypatch.setattr(module, "ensure_target_runner", real_ensure)
    await session._turn_event_loop()
    registry = getattr(module, "_target_runner_tasks", {})
    pending = [task for task in registry.values() if not task.done()]
    if pending:
        await asyncio.gather(*pending)
    assert resumed.provider_attempts == [RENDERED]
    assert _delivery_row(message_db)["state"] == "SUBMITTED"
    assert len(_user_messages(message_db)) == 1
