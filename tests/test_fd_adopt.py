"""Restart admission, HTTP draining and restoration from persisted sessions."""
import asyncio
import os
from datetime import datetime, timezone
from unittest.mock import patch

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    from app.db import init_db
    init_db()
    return db_path


@pytest.fixture
def mgr(db, tmp_path, monkeypatch):
    wt_root = tmp_path / "worktrees"
    wt_root.mkdir()
    monkeypatch.setattr("app.workspace.WORKTREE_ROOT", wt_root)
    from app.manager import SessionManager
    return SessionManager()








def _save_running_session(session_id="adopted-1", model="gpt-5.6-luna", thread="thread-abc"):
    from app.db import save_session
    save_session({
        "id": session_id, "name": session_id, "scope": "/tmp", "cwd": "/tmp",
        "model": model, "system_prompt": "", "status": "running",
        "session_id": thread, "cost_usd": 0.0, "worktree_path": None, "branch": None,
        "is_orchestrator": False, "role": "worker", "pipeline": "default", "color": "#818cf8",
        "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
    })


# ------------------------------------------------- T2: Codex adopts and reads the live stream


# ------------------------------------------------- T3: Claude transport over inherited pipes


@pytest.mark.asyncio
async def test_t3_write_before_connect_fails_loudly_not_with_nameerror():
    """Guard added after the freeze: the not-ready path raised NameError until the import
    was fixed, and the ticket oracle never walks it."""
    from claude_agent_sdk import CLIConnectionError

    from app.backend_claude import InheritedFdTransport

    r, w = os.pipe()
    try:
        transport = InheritedFdTransport(w, r)
        with pytest.raises(CLIConnectionError):
            await transport.write("{}\n")
    finally:
        os.close(r)
        os.close(w)


# --- post-freeze guards for the blocking findings of the implementation review ---


# ------------------------------------- T4: shutdown hands over instead of killing the backend


# ----------------------------------------------- T5: startup adopts the turn, does not reset it


@pytest.mark.asyncio
async def test_t5_session_without_inheritance_still_resets_to_idle(mgr, monkeypatch):
    """The negative case: no inheritance -> today's behaviour, reset to idle."""
    from app.session_state import AgentStatus
    from tests.conftest import make_backend_mock

    _save_running_session("orphaned-1")
    monkeypatch.setattr("app.fdstore.acquire_fds", lambda: {})

    with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
        await mgr.auto_resume_all()

    session = mgr.get("orphaned-1")
    assert session is not None
    assert session.status == AgentStatus.IDLE


# ---------------------------------- T6: the gate runs BEFORE systemd, classification fail-closed

@pytest.mark.asyncio
async def test_t6_drain_never_waits_for_a_mutating_call(monkeypatch):
    """Кнопка рестарта не ждёт мутаций (решение юзера 28.08.2026).

    Ловит возврат ожидания: если бюджет снова станет положительным, дефолтный вызов
    провисит те самые секунды, ради отсутствия которых правка и делалась.
    """
    from app import main as app_main

    assert app_main.MUTATING_DRAIN_BUDGET_S == 0.0

    monkeypatch.setattr(app_main, "inflight_mutating_count", lambda: 1, raising=False)

    loop = asyncio.get_running_loop()
    t0 = loop.time()
    await app_main.drain_mutating_requests()
    waited = loop.time() - t0
    assert waited < 0.05, f"restart must not wait for in-flight mutating calls, waited {waited}"


@pytest.mark.asyncio
async def test_t6_budget_exhausted_refuses_the_restart(monkeypatch):
    """An accepted mutating call cannot be retroactively called 'never started'."""
    from app import main as app_main

    monkeypatch.setattr(app_main, "inflight_mutating_count", lambda: 2, raising=False)
    loop = asyncio.get_running_loop()
    t0 = loop.time()
    # the outer boundary is what makes this FAIL instead of reporting 120s later, if the
    # implementation reads the module constant instead of the budget it was handed
    result = await asyncio.wait_for(app_main.drain_mutating_requests(budget_s=0.3), timeout=5)
    assert result is False
    assert loop.time() - t0 < 1.5, "drain must not outlive its budget"


def test_t6_classification_comes_from_the_route_table_and_fails_closed():
    """Not from the HTTP verb: a GET route may mutate, and guessing would drop such a call.

    Table-driven over the app's REAL routes, plus a path the table does not know.
    """
    from app import main as app_main

    routes = [r for r in app_main.app.routes if getattr(r, "path", "").startswith("/api/")]
    assert routes, "no /api routes found — the census would classify nothing"

    for route in routes:
        for method in sorted(getattr(route, "methods", set()) or set()):
            if method in ("HEAD", "OPTIONS"):
                continue
            verdict = app_main.is_mutating_path(method, route.path)
            assert isinstance(verdict, bool), f"{method} {route.path} -> {verdict!r}"

    # expected classifications for REAL routes: `lambda *_: True` would be fail-safe for
    # integrity and still defeat the point, blocking restarts on read-only traffic
    assert app_main.is_mutating_path("POST", "/api/sessions/{name}/send") is True
    assert app_main.is_mutating_path("POST", "/api/sessions") is True
    assert app_main.is_mutating_path("GET", "/api/sessions") is False
    assert app_main.is_mutating_path("GET", "/api/sessions/{name}/stream") is False

    # the restart endpoint must not be counted as mutating traffic: its own preflight would
    # otherwise wait for the request that asked for the restart — a self-deadlock
    assert app_main.is_mutating_path("POST", "/api/restart") is False

    # an unknown path must count as mutating: unknown means "I do not know", not "safe"
    assert app_main.is_mutating_path("POST", "/api/this-route-does-not-exist") is True
    assert app_main.is_mutating_path("GET", "/api/this-route-does-not-exist") is True


@pytest.mark.asyncio
async def test_t6_real_middleware_counts_mutating_but_not_streams():
    """The census must be moved by an ACTUAL request through the middleware, not by a stub."""
    from starlette.applications import Starlette
    from starlette.responses import StreamingResponse, JSONResponse
    from starlette.routing import Route
    import httpx

    from app import main as app_main

    seen = {}

    async def mutate(request):
        seen["mutating_during"] = app_main.inflight_mutating_count()
        return JSONResponse({"ok": True})

    async def stream(request):
        async def body():
            seen["streams_during"] = app_main.inflight_stream_count()
            seen["mutating_during_stream"] = app_main.inflight_mutating_count()
            yield b"data: x\n\n"

        return StreamingResponse(body(), media_type="text/event-stream")

    probe = Starlette(routes=[
        Route("/api/sessions/x/send", mutate, methods=["POST"]),
        Route("/api/events", stream, methods=["GET"]),
    ])
    probe.add_middleware(app_main.RequestCensusMiddleware)

    transport = httpx.ASGITransport(app=probe)
    async with httpx.AsyncClient(transport=transport, base_url="http://probe") as client:
        await client.post("/api/sessions/x/send", json={})
        async with client.stream("GET", "/api/events") as response:
            async for _chunk in response.aiter_bytes():
                break

    assert seen["mutating_during"] == 1, "a mutating request must be counted while it runs"
    assert seen["mutating_during_stream"] == 0, "an SSE stream is not a mutating request"
    assert seen["streams_during"] == 1, "streams are counted separately, and never drained"
    assert app_main.inflight_mutating_count() == 0, "the census must fall back to zero"


def test_t6_admission_gate_rejects_new_mutating_calls_as_retryable():
    """A call refused BEFORE its side effect is honestly retryable — that is the whole point."""
    from app import main as app_main

    # control arm FIRST: with the gate open, a mutating call must be ALLOWED. Without this
    # assert, a constant `{allowed: False, retryable: True}` passes — which in production is
    # "the gate closed before a restart and never reopened", i.e. every mutating tool call
    # answered "retry later" forever, with a green oracle.
    app_main.open_mutating_admission()
    assert app_main.mutating_admission_verdict("POST", "/api/sessions/x/send")["allowed"] is True

    app_main.close_mutating_admission()
    try:
        verdict = app_main.mutating_admission_verdict("POST", "/api/sessions/x/send")
        assert verdict["allowed"] is False
        assert verdict["retryable"] is True
        assert verdict["outcome_unknown"] is False
        # a read-only call is never gated: the gate protects side effects, not traffic
        assert app_main.mutating_admission_verdict("GET", "/api/sessions")["allowed"] is True
    finally:
        app_main.open_mutating_admission()
    assert app_main.mutating_admission_verdict("POST", "/api/sessions/x/send")["allowed"] is True, (
        "the gate must REOPEN; a stuck-closed gate starves every mutating tool call")


@pytest.mark.asyncio
async def test_t6_restart_endpoint_refuses_before_touching_systemd(monkeypatch):
    """A gate inside the lifespan is too late: systemctl restart is already committed by then."""
    from app.routes import system as system_routes

    invoked = []
    monkeypatch.setattr(system_routes, "_restart_service_after_response",
                        lambda *a, **kw: invoked.append(True), raising=False)

    async def refuse():
        return {"ok": False, "reason": "2 mutating tool calls still in flight"}

    monkeypatch.setattr(system_routes, "restart_preflight", refuse, raising=False)

    with pytest.raises(Exception) as excinfo:
        await system_routes.restart_server()

    assert getattr(excinfo.value, "status_code", None) == 409
    assert invoked == [], "systemd must NOT be invoked when the preflight refuses"


@pytest.mark.asyncio
async def test_t6_successful_preflight_reaches_systemd_without_waiting_on_itself(monkeypatch):
    """The restart request is itself an HTTP request: if the census counts it, the drain waits
    for the very call that asked for the restart and never finishes."""
    import httpx
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    from app import main as app_main
    from app.routes import system as system_routes

    scheduled = []
    monkeypatch.setattr(system_routes, "_restart_service_after_response",
                        lambda *a, **kw: scheduled.append(True), raising=False)

    async def restart(request):
        result = await system_routes.restart_preflight()
        if not result["ok"]:
            return JSONResponse({"error": result["reason"]}, status_code=409)
        system_routes._restart_service_after_response()
        return JSONResponse({"ok": True})

    probe = Starlette(routes=[Route("/api/restart", restart, methods=["POST"])])
    probe.add_middleware(app_main.RequestCensusMiddleware)

    transport = httpx.ASGITransport(app=probe)
    async with httpx.AsyncClient(transport=transport, base_url="http://probe") as client:
        response = await asyncio.wait_for(client.post("/api/restart", json={}), timeout=10)

    assert response.status_code == 200, response.text
    assert scheduled == [True], "a successful preflight must reach the systemd seam"
    # the real preflight deliberately leaves admission CLOSED (a restart follows); in a test
    # nothing follows, so restore it — otherwise every later mutating request gets 503
    app_main.open_mutating_admission()
    assert app_main.mutating_admission_verdict("POST", "/api/sessions/x/send")["allowed"] is True


@pytest.mark.asyncio
async def test_t6_admission_reopens_if_the_restart_never_happens(monkeypatch):
    """Post-freeze regression guard, not a ticket oracle.

    The full suite found this: a SUCCESSFUL preflight leaves admission closed (a restart is
    supposed to follow and kill the process). When the restart does not happen, the gate stayed
    shut and every mutating tool call got 503 — the exact "closed and never reopened" state the
    independent review warned about, here in production rather than in the oracle.
    """
    from app import main as app_main
    from app.routes import system as system_routes

    monkeypatch.setattr(system_routes, "_watchdog_budget_s", lambda: 0.1, raising=False)
    monkeypatch.setattr(app_main, "inflight_mutating_count", lambda: 0, raising=False)
    scheduled = []

    async def fake_restart(*a, **kw):
        # async, because the caller hands this to asyncio.create_task — a sync double raises
        # "a coroutine was expected, got None" (my third sync-double-for-async-contract slip)
        scheduled.append(True)
        return {"ok": True}

    monkeypatch.setattr(system_routes, "_restart_service_after_response", fake_restart,
                        raising=False)
    try:
        result = await system_routes.restart_server()
        assert result["ok"] is True
        assert app_main.mutating_admission_verdict("POST", "/api/sessions/x/send")["allowed"] \
            is False, "right after a successful preflight the gate must be CLOSED"

        await asyncio.sleep(0.4)
        assert app_main.mutating_admission_verdict("POST", "/api/sessions/x/send")["allowed"] \
            is True, "a restart that never happened must not starve every mutating call"
    finally:
        app_main.open_mutating_admission()


def test_t6_concrete_paths_resolve_to_their_route_template():
    """Post-freeze regression guard, not a ticket oracle. Found by the pre-mortem.

    The middleware sees CONCRETE paths; the route table holds templates. Comparing them
    directly made every parameterised route "unknown" -> mutating, so ordinary dashboard GETs
    would have held the restart drain and been refused by the admission gate.
    """
    from app import main as app_main

    # concrete GET on a parameterised route: read-only, must NOT be counted as mutating
    assert app_main.is_mutating_path("GET", "/api/sessions/some-worker/context") is False
    # concrete POST on a parameterised route: mutating
    assert app_main.is_mutating_path("POST", "/api/sessions/some-worker/send") is True
    # still fail-closed for a path that matches nothing
    assert app_main.is_mutating_path("GET", "/api/nope/nope/nope") is True


@pytest.mark.asyncio
async def test_269_restart_header_states_both_values_on_ordinary_responses():
    """#269: the pause must be readable in BOTH directions, on a response nobody was refused.

    Only the closed arm ("1") is not enough: a restart that never happens reopens admission
    silently (`restart_preflight` with an undrained tail), and a page loaded mid-restart sent
    nothing, so it never saw a 503. This is the send_wrapper point — a read-only request is
    never refused, so it cannot reach the refusal branch.
    """
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    import httpx

    from app import main as app_main

    async def read(request):
        return JSONResponse({"ok": True})

    probe = Starlette(routes=[Route("/api/sessions", read, methods=["GET"])])
    probe.add_middleware(app_main.RequestCensusMiddleware)

    transport = httpx.ASGITransport(app=probe)
    async with httpx.AsyncClient(transport=transport, base_url="http://probe") as client:
        app_main.open_mutating_admission()
        opened = await client.get("/api/sessions")
        app_main.close_mutating_admission()
        try:
            closed = await client.get("/api/sessions")
        finally:
            app_main.open_mutating_admission()
        reopened = await client.get("/api/sessions")

    assert opened.headers.get("X-Orchestra-Restarting") == "0"
    assert closed.headers.get("X-Orchestra-Restarting") == "1", (
        "a read-only response must still carry the pause: the dashboard's heartbeat is a GET")
    assert reopened.headers.get("X-Orchestra-Restarting") == "0", (
        "a header stuck at 1 leaves the client paused until its own 120s ceiling")
    generations = {
        opened.headers.get("X-Orchestra-Generation"),
        closed.headers.get("X-Orchestra-Generation"),
        reopened.headers.get("X-Orchestra-Generation"),
    }
    assert len(generations) == 1 and None not in generations
    started = {
        opened.headers.get("X-Orchestra-Started-At"),
        closed.headers.get("X-Orchestra-Started-At"),
        reopened.headers.get("X-Orchestra-Started-At"),
    }
    assert len(started) == 1 and None not in started


@pytest.mark.asyncio
async def test_269_restart_header_is_on_the_refusal_itself():
    """#269: the 503 answers WITHOUT reaching send_wrapper, so it needs its own header.

    Covered separately on purpose: a test that only checks ordinary responses is green while
    the refused call — the one the client is looking at — carries no state at all.
    """
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    import httpx

    from app import main as app_main

    reached = []

    async def mutate(request):
        reached.append(True)
        return JSONResponse({"ok": True})

    probe = Starlette(routes=[Route("/api/sessions/x/send", mutate, methods=["POST"])])
    probe.add_middleware(app_main.RequestCensusMiddleware)

    transport = httpx.ASGITransport(app=probe)
    async with httpx.AsyncClient(transport=transport, base_url="http://probe") as client:
        app_main.close_mutating_admission()
        try:
            refused = await client.post("/api/sessions/x/send", json={})
        finally:
            app_main.open_mutating_admission()

    assert refused.status_code == 503
    assert refused.json()["error"]["code"] == "restart_pending"
    assert not reached, "the refusal must happen before the handler, i.e. before send_wrapper"
    assert refused.headers.get("X-Orchestra-Restarting") == "1"
    assert refused.headers.get("X-Orchestra-Generation")
    assert refused.headers.get("X-Orchestra-Started-At")


# ------------------------------------------------------------- T7: fail-closed orphan sweep


# ------------------------------------- T9: new tools and prompt land on the NEXT turn
