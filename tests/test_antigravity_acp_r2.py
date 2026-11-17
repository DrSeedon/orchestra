"""Astra R2 corrections: real lifecycle, mock stdio, no account/network access."""
import asyncio
from collections import Counter
from contextlib import asynccontextmanager
import json
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from tests.test_antigravity_acp import stand, turn, end, USER
from app.events import MessageProvenance
from app.session import AgentSession, AgentStatus

EVIDENCE = Path(__file__).resolve().parents[1] / ".orchestra/tasks/agy-acp-safe-20261116/r2"


@pytest_asyncio.fixture
async def real_session(stand, monkeypatch, tmp_path):
    from app import db, bg_jobs
    db.init_db()
    monkeypatch.setattr(bg_jobs, "bg_manager", None)
    s = AgentSession(id="real-acp-r2", name="real-acp-r2", scope=str(tmp_path), cwd=str(tmp_path),
        model="antigravity/gemini-4-carbon-medium", backend_type="antigravity",
        is_orchestrator=True, mcp_servers={}, system_prompt="Synthetic R2 role")
    s._persist()
    await s._drain_persist()  # Durable parent must exist before the first log/child write.
    # No _ensure_backend/_make_backend/event-loop replacement: actual lifecycle.
    try:
        yield s
    finally:
        await s.abort_unpublished()


async def send_and_finish(s, text):
    await s.send(text, provenance=USER)
    async with asyncio.timeout(4):
        await s._listen_task
    await s._drain_persist()
    assert s.status == AgentStatus.IDLE


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,ok,known", [("normal",True,True),("ack-unknown",True,False),("ack-error",False,True)])
async def test_real_compact_ack_lifecycle_context_receipt_and_rollback(stand, real_session, monkeypatch, mode, ok, known):
    from app import db
    monkeypatch.setenv("AGY_MOCK_MODE", mode)
    s = real_session
    await send_and_finish(s, "INITIAL_CONTEXT")
    old_id, old_context = s.session_id, dict(s._last_context)
    assert old_context["total_tokens"] == 700
    before = len(stand.trace())
    denied = await s.compact()
    assert not denied["ok"] and "interactive_only" in denied["error"]
    assert len(stand.trace()) == before
    async with asyncio.timeout(5):
        result = await s.compact(provenance=MessageProvenance("user", ("operator",), "manual_compact"))
    if s._listen_task is not None: await s._listen_task
    await s._drain_persist()
    assert result["ok"] is ok and not s._compacting
    assert s._last_context["known"] is known
    if ok:
        assert s.session_id != old_id and s._last_turn_ok
        assert s.session_id_history[-1]["session_id"] == old_id
        assert result["pre_tokens"] == 700
        assert result["post_tokens"] == (200 if known else None)
        assert result["after_pct"] == (20 if known else None)
        assert result["context_known"] is known
        assert result["dropped_tokens"] == (500 if known else None)
        assert s._last_context["total_tokens"] == (200 if known else 0)
    else:
        assert s.session_id == old_id and s._last_context == old_context
        assert not s._last_turn_ok and not s.session_id_history
    assert db.get_session(s.id)["session_id"] == s.session_id
    methods = Counter(r["method"] for r in stand.trace())
    assert methods["spawn"] == methods["initialize"] == methods["authenticate"] == 1
    assert methods["session/prompt"] == 3 and methods["session/new"] == 2
    assert sum(r["method"] == "prompt_end" for r in stand.trace()) == 3
    (EVIDENCE / ("real-compact-"+mode+".json")).write_text(json.dumps({
        "result":result, "context":s._last_context, "last_turn_ok":s._last_turn_ok,
        "methods":dict(methods), "listener_done":s._listen_task is None or s._listen_task.done(),
        "real_ensure_backend":True, "real_event_loop":True}, ensure_ascii=False, indent=2))


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,banned", [("BAN_ROOT",True),("BAN_NESTED",True),("BAN_LIST",True),
    ("BAN_CAUSE",True),("RPC_AUTH",False),("RPC_QUOTA",False),("RPC_MODEL",False),("RPC_INTERNAL",False)])
async def test_structured_ban_wrappers_and_ordinary_errors(stand, monkeypatch, tmp_path, payload, banned):
    from app import db, provider_safety
    db.init_db()
    # Dedup registry is process-local; each test simulates a fresh app state.
    monkeypatch.setattr(provider_safety, "_tripped_incidents_mem", set())
    state = tmp_path / "disabled-r2.json"
    monkeypatch.setenv("ORCHESTRA_DISABLED_PROVIDERS_FILE",str(state))
    monkeypatch.setenv("ORCHESTRA_DISABLED_PROVIDERS", "")
    events = await turn(stand.backend(), payload)
    assert not end(events).metadata["ok"]
    assert "synthetic-secret" not in str(events)
    assert state.exists() is banned
    if banned:
        assert "antigravity" in json.loads(state.read_text())["disabled_providers"]
        incidents = db.kv_get("provider_ban_incidents", "[]")
        assert "ACP confirmed account-disabled" in incidents and "synthetic-secret" not in incidents


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,confirmed", [("config-confirm",True),("config-mismatch",False),("config-unknown",False)])
async def test_selected_model_requires_actual_config_confirmation(stand, monkeypatch, mode, confirmed):
    monkeypatch.setenv("AGY_MOCK_MODE",mode)
    b = stand.backend(model="gemini-4-carbon-medium")
    events = await turn(b, "Carbon required")
    assert end(events).metadata["ok"] is confirmed
    methods = Counter(r["method"] for r in stand.trace())
    assert methods["session/prompt"] == int(confirmed)
    assert methods["session/set_config_option"] == 1
    if not confirmed:
        assert b.is_alive and not b._owner.failure
        sibling = stand.backend(model="gemini-4-argon-medium")
        assert end(await turn(sibling, "Argon actually advertised")).metadata["ok"]
        assert sum(r["method"] == "spawn" for r in stand.trace()) == 1


@pytest.mark.asyncio
async def test_real_http_receipts_interrupt_and_compact(stand, real_session, monkeypatch):
    from fastapi import FastAPI
    import uvicorn, uuid
    from app.manager import SessionManager
    from app.routes import sessions
    from app import deps, message_deliveries
    s = real_session
    manager = SessionManager()
    manager.sessions[s.id] = s
    monkeypatch.setattr(deps, "manager", manager)
    monkeypatch.setattr(sessions, "manager", manager)
    monkeypatch.setattr("app.auth.validate_session", lambda cookie: cookie == "synthetic-operator")
    @asynccontextmanager
    async def lifespan(app):
        yield
    app = FastAPI(lifespan=lifespan)
    app.include_router(sessions.router)
    server = uvicorn.Server(uvicorn.Config(app,host="127.0.0.1",port=18889,log_level="critical"))
    runner = asyncio.create_task(server.serve())
    try:
        async with asyncio.timeout(3):
            while not server.started: await asyncio.sleep(.01)
        async with httpx.AsyncClient(base_url="http://127.0.0.1:18889",trust_env=False,timeout=6,
            cookies={"session":"synthetic-operator"}) as client:
            delivery_id = str(uuid.uuid4())
            body = {"message":"receipt accepted once", "scope":s.scope,"delivery_id":delivery_id}
            response = await client.post("/api/sessions/"+s.name+"/send",json=body)
            assert response.status_code in (200,202), response.text
            async with asyncio.timeout(4):
                while message_deliveries._row(delivery_id)["state"] not in {"SUBMITTED","FAILED_BEFORE_SUBMIT","DELIVERY_UNKNOWN"}:
                    await asyncio.sleep(.01)
            row = message_deliveries._row(delivery_id)
            assert row["state"] == "SUBMITTED", row["error_json"]
            if s._listen_task: await s._listen_task
            assert s._last_turn_ok and s.status == AgentStatus.IDLE
            before = Counter(r["method"] for r in stand.trace())["session/prompt"]
            repeat = await client.post("/api/sessions/"+s.name+"/send",json=body)
            assert repeat.status_code in (200,202)
            await asyncio.sleep(.05)
            assert Counter(r["method"] for r in stand.trace())["session/prompt"] == before == 1
            status = await client.get("/api/message-deliveries/"+delivery_id)
            assert status.status_code == 200 and status.json()["delivery_state"] == "SUBMITTED"
            accepted = await client.post("/api/sessions/"+s.name+"/send",json={"message":"HTTP_BLOCK","scope":s.scope})
            assert accepted.status_code == 200, accepted.text
            async with asyncio.timeout(3):
                while sum(r["method"] == "prompt_start" for r in stand.trace()) < 2: await asyncio.sleep(.01)
            interrupted = await client.post("/api/sessions/"+s.name+"/interrupt",json={"scope":s.scope})
            assert interrupted.status_code == 200, interrupted.text
            if s._listen_task: await s._listen_task
            assert s.status == AgentStatus.IDLE and not s._last_turn_ok
            compact = await client.post("/api/sessions/"+s.name+"/compact",json={"scope":s.scope})
            assert compact.status_code == 200 and compact.json()["ok"], compact.text
            assert compact.json()["post_tokens"] == 200
            if s._listen_task: await s._listen_task
            methods = Counter(r["method"] for r in stand.trace())
            assert methods["spawn"] == 1 and methods["session/prompt"] == 4 and methods["session/cancel"] == 1
            (EVIDENCE/"http-receipts-interrupt-compact.json").write_text(json.dumps({
                "receipt":status.json(), "repeat_status":repeat.status_code, "interrupt":interrupted.json(),
                "compact":compact.json(), "methods":dict(methods), "actual_session_manager":True,
                "actual_ensure_backend":True, "actual_event_loop":True},ensure_ascii=False,indent=2))
    finally:
        server.should_exit = True
        await asyncio.wait_for(runner,3)


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["NULL","BOOL","NEGATIVE","TEXT"])
async def test_malformed_cost_does_not_erase_last_valid_baseline(stand, invalid):
    b = stand.backend()
    assert end(await turn(b,"COST")).metadata["cost_usd"] == pytest.approx(.01)
    event = end(await turn(b,"COST_INVALID_"+invalid))
    assert event.metadata["cost_unaccounted"] is True
    assert b._owner.cost_totals[b.session_id] == pytest.approx(.01)
    assert end(await turn(b,"COST")).metadata["cost_usd"] == pytest.approx(.01)


@pytest.mark.asyncio
async def test_cumulative_cost_reset_uses_the_new_reported_epoch(stand):
    b = stand.backend()
    assert end(await turn(b,"COST")).metadata["cost_usd"] == pytest.approx(.01)
    assert end(await turn(b,"COST_RESET")).metadata["cost_usd"] == pytest.approx(.005)
    assert end(await turn(b,"COST")).metadata["cost_usd"] == pytest.approx(.01)
    assert sum(r["method"] == "spawn" for r in stand.trace()) == 1
