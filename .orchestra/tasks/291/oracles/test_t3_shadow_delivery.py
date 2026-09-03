from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request


def _controller():
    import importlib
    import importlib.util

    spec = importlib.util.find_spec("app.quota_controller")
    assert spec is not None, "app.quota_controller is not implemented"
    return importlib.import_module("app.quota_controller")


def _static_decision(*, valid_until=None):
    from app.quota_gate import QuotaDecision

    return QuotaDecision(
        state="available",
        model="gpt-5.6-sol",
        provider="codex",
        provider_label="Codex",
        weekly_utilization=20,
        observed_at=1,
        valid_until=valid_until,
        reset_at=None,
        alternatives=(),
        reason="fixture",
    )


class _Backend:
    def __init__(self, events):
        self.events = events
        self.messages = []

    async def send(self, message):
        self.events.append("backend_send")
        self.messages.append(message)


def _session_harness(monkeypatch, *, role="worker", admission=None, observer=None):
    import app.session as session_module
    from app.session import AgentSession
    from app.session_state import AgentStatus

    events = []
    logs = []
    backend = _Backend(events)
    session = AgentSession(
        id=f"s-{role}",
        name=f"n-{role}",
        scope="/scope",
        cwd="/scope",
        model="gpt-5.6-sol",
        backend_type="codex",
        role=role,
        status=AgentStatus.IDLE,
    )
    session._is_orchestrator = role == "orchestrator"
    session._quota_shadow_controller = observer
    session._admission_service = admission

    async def noop(*_args, **_kwargs):
        return None

    async def ensure_backend(*_args, **_kwargs):
        return backend

    session._ensure_backend = ensure_backend
    session._apply_pending_identity_restart = noop
    session._apply_manifest_effort = noop
    session._refresh_stale_backend = noop
    session._notify_scope_running = noop
    session._persist = lambda: None
    session._log = lambda kind, content, **_kw: logs.append((kind, content))
    session._attach_pending_facts = lambda message: (message, [])
    session._ack_pending_facts = lambda _keys: None
    monkeypatch.setattr(
        session_module,
        "get_runtime",
        lambda _runtime: SimpleNamespace(
            capabilities=SimpleNamespace(mid_turn_inject=True, event_stream="none")
        ),
    )
    return session, backend, events, logs


@pytest.mark.asyncio
async def test_t3_actual_send_reserves_before_exactly_one_backend_submit(monkeypatch):
    static = _static_decision()

    class Observer:
        async def reserve_before_submit(self, context, static_decision):
            events.append("shadow_reserve")
            assert context.intent_kind == "idle_send"
            assert static_decision is static
            return SimpleNamespace(decision_id="d-1")

        async def mark_submitted(self, reservation):
            events.append("shadow_submitted")
            assert reservation.decision_id == "d-1"

    async def admission(_model):
        return static

    observer = Observer()
    session, backend, events, _logs = _session_harness(
        monkeypatch, admission=admission, observer=observer,
    )
    await session.send("hello")

    assert events == ["shadow_reserve", "backend_send", "shadow_submitted"]
    assert backend.messages == ["hello"]


@pytest.mark.asyncio
async def test_t3_observer_exception_is_visible_and_cannot_block_or_duplicate(monkeypatch):
    static = _static_decision()

    class BrokenObserver:
        async def reserve_before_submit(self, _context, static_decision):
            assert static_decision is static
            raise RuntimeError("shadow storage broken")

    async def admission(_model):
        return static

    session, backend, events, logs = _session_harness(
        monkeypatch, admission=admission, observer=BrokenObserver(),
    )
    await session.send("still delivered")

    assert events == ["backend_send"]
    assert backend.messages == ["still delivered"]
    assert any(
        kind == "error" and "quota_shadow_error" in content and "RuntimeError" in content
        for kind, content in logs
    )


@pytest.mark.asyncio
async def test_t3_orchestrator_new_turn_is_observed_but_mid_turn_injection_is_not(monkeypatch):
    calls = []

    class Observer:
        async def reserve_before_submit(self, context, static_decision):
            calls.append((context.intent_kind, static_decision))
            return SimpleNamespace(decision_id="d-orch")

        async def mark_submitted(self, _reservation):
            return None

    async def admission_must_not_run(_model):
        raise AssertionError("orchestrator must not use worker admission")

    session, backend, _events, _logs = _session_harness(
        monkeypatch,
        role="orchestrator",
        admission=admission_must_not_run,
        observer=Observer(),
    )
    await session.send("new turn")
    await session.send("steer active turn")

    assert calls == [("idle_send", None)]
    assert backend.messages == ["new turn", "steer active turn"]


@pytest.mark.asyncio
async def test_t3_admission_refresh_still_creates_one_shadow_decision(monkeypatch):
    decisions = [_static_decision(valid_until=0), _static_decision()]
    reservations = []

    class Observer:
        async def reserve_before_submit(self, context, static_decision):
            reservations.append((context.turn_gen, static_decision))
            return SimpleNamespace(decision_id="one")

        async def mark_submitted(self, _reservation):
            return None

    async def admission(_model):
        return decisions.pop(0)

    session, backend, _events, _logs = _session_harness(
        monkeypatch, admission=admission, observer=Observer(),
    )
    await session.send("refresh")

    assert len(reservations) == 1
    assert backend.messages == ["refresh"]


def test_t3_actual_turn_manager_settlement_is_idempotent_and_keeps_intervals(
    tmp_path, monkeypatch,
):
    from app.events import AgentEvent
    import app.session_turns as turns_module

    controller = _controller()
    store = controller.SQLiteControllerStore(tmp_path / "controller.db")
    reservations = []
    for decision_id, session_id, started_at in (
        ("d-1", "s-1", "2030-01-01T00:00:00Z"),
        ("d-2", "s-2", "2030-01-01T00:00:01Z"),
    ):
        reservations.append(store.reserve_shadow_dispatch(
            decision_id=decision_id,
            constraints=[{
                "bucket": "codex:primary",
                "utilization": 20,
                "inflight_reserved_pp": 0,
                "q95_next_turn_pp": 1,
                "guard_pp": 0.5,
                "reserve_pp": 0,
                "reset_at": "2030-01-07T00:00:00Z",
                "observed_at": started_at,
                "regime_key": "r1",
                "confidence": "operational",
            }],
            target_pct=99,
            context={
                "session_id": session_id,
                "turn_gen": 1,
                "started_at": started_at,
            },
        ))

    def settle(reservation, event_id, ended_at):
        session, _backend, _events, _logs = _session_harness(
            monkeypatch, admission=None, observer=store,
        )
        session.id = reservation.context["session_id"]
        session._active_shadow_reservation = reservation

        class Cost:
            @staticmethod
            def apply_turn_result(_meta, _usage):
                return True, "end_turn", 1

            @staticmethod
            def update_context_from_turn(_meta, _usage):
                return True, None

        session._cost = Cost()
        session._submit_db_write = lambda *_args, **_kwargs: None
        session._refresh_context_from_api = lambda **_kw: _closed_coro()
        session._spawn_bg = lambda coro: coro.close()
        session._turns.finish_turn_status = lambda: None
        session._turns.after_turn_idle_actions = lambda *_args, **_kwargs: None
        event = AgentEvent(
            "turn_end",
            metadata={"event_id": event_id, "ended_at": ended_at},
        )
        session._turns.handle_turn_end(event)
        session._turns.handle_turn_end(event)

    async def _closed_coro():
        return None

    monkeypatch.setattr(
        turns_module,
        "_cached_quota_snapshot",
        lambda *_args, **_kwargs: {
            "state": {
                "quota_five_hour_pct": None,
                "quota_seven_day_pct": None,
                "quota_primary_pct": None,
                "quota_sampled_at": None,
            },
            "display": (),
        },
    )
    settle(reservations[0], "e-1", "2030-01-01T00:00:03Z")
    settle(reservations[1], "e-2", "2030-01-01T00:00:02Z")

    assert store.outcome_count("e-1") == 1
    assert store.outcome_count("e-2") == 1
    annotated = controller.annotate_concurrent_intervals(store.list_outcomes())
    assert [item["concurrent_consumers"] for item in annotated] == [True, True]


def _request(*, cookie="", bearer=""):
    headers = []
    if cookie:
        headers.append((b"cookie", f"session={cookie}".encode()))
    if bearer:
        headers.append((b"authorization", f"Bearer {bearer}".encode()))
    return Request({"type": "http", "method": "POST", "path": "/", "headers": headers})


@pytest.mark.asyncio
async def test_t3_reserve_api_is_owner_cookie_only(monkeypatch):
    from app import auth
    from app.routes import system

    monkeypatch.setenv("DASHBOARD_USER", "owner")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "secret")
    monkeypatch.setenv("INTERNAL_TOKEN", "agent-token")

    class Service:
        def __init__(self):
            self.calls = 0

        async def create_reserve_intent(self, payload):
            self.calls += 1
            return {"intent_id": "i-1", **payload}

    service = Service()
    monkeypatch.setattr(system, "get_quota_controller", lambda: service)
    payload = {
        "task_id": "291",
        "logical_work_id": "critical-fix-1",
        "lane": "codex",
        "task_class": "worker",
        "model": "gpt-5.6-sol",
        "turn_count": 2,
        "deadline_at": "2030-01-06T23:00:00Z",
        "reason": "critical fix",
    }

    with pytest.raises(HTTPException) as denied:
        await system.create_quota_reserve_intent(
            _request(bearer="agent-token"), payload,
        )
    assert denied.value.status_code == 403

    result = await system.create_quota_reserve_intent(
        _request(cookie=auth.create_session("owner")), payload,
    )
    assert result["intent_id"] == "i-1"
    assert service.calls == 1


def test_t3_status_schema_is_explicitly_shadow_only():
    controller = _controller()
    status = controller.empty_status()

    assert status["mode"] == "shadow"
    assert status["enforcement_active"] is False
    assert set(status["static_comparison_counts"]) == {
        "agree",
        "adaptive_would_allow",
        "adaptive_would_hold",
        "adaptive_indeterminate",
    }
