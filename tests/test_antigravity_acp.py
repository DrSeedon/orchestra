"""Persistent ACP behavior over real stdio, with credential-free fake and no egress.

Run via scripts/run_antigravity_offline.sh: a kernel namespace cuts all external
routes; the runner also forbids real provider binaries and production file reads.
"""
import asyncio
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio

from app import antigravity_acp as acp
from app import backend_antigravity as agy
from app.events import InjectedMessage, MessageProvenance
from app.runtime_registry import RuntimeReadinessContext

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / ".orchestra/tasks/agy-acp-safe-20261116"
FAKE = ROOT / "tests/acp_mock/fake_agy_acp.py"
USER = MessageProvenance("user", ("owner",))


def owner_message(text):
    return InjectedMessage(text, USER, "synthetic-event")


@pytest_asyncio.fixture
async def stand(tmp_path, monkeypatch, request):
    assert os.environ.get("ORCHESTRA_ACP_OFFLINE") == "1", "use the isolated runner"
    home = tmp_path / "profile"
    for path, content in {
        ".gemini/antigravity-cli/settings.json": {"useG1Credits": False},
        ".gemini/antigravity-acp/settings.json": {"useG1Credits": False},
        ".gemini/config/config.json": {"userSettings": {"useAiCredits": False}},
    }.items():
        f = home / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(content))
    trace_file = tmp_path / "trace.jsonl"
    monkeypatch.setattr(agy, "ANTIGRAVITY_BIN", str(FAKE))
    monkeypatch.setattr(agy, "ANTIGRAVITY_AUTH_HOME", home)
    monkeypatch.setattr(agy, "_has_cached_credentials", lambda path: path == home.resolve())
    # Exact synthetic CLI environment: no real account, .env, proxies or MCP token.
    monkeypatch.setattr(agy, "cli_environment", lambda path: {
        "HOME": str(path), "PATH": "/usr/bin:/bin", "AGY_MOCK_TRACE": str(trace_file),
        "AGY_MOCK_MODE": os.environ.get("AGY_MOCK_MODE", "normal"),
        "AGY_MOCK_MAX_ACTIVE": os.environ.get("ANTIGRAVITY_MAX_CONCURRENT_TURNS", "3"),
    })
    from app import provider_safety, models
    egress = AsyncMock()
    monkeypatch.setattr(provider_safety, "verify_provider_egress", egress)
    monkeypatch.setattr(provider_safety, "record_provider_activity", lambda _: None)
    monkeypatch.setattr(models, "is_provider_disabled", lambda _: False)

    def backend(*, model="gemini-4-carbon-medium", resume=None, role="synthetic role"):
        return agy.AntigravityBackend(SimpleNamespace(
            model="antigravity/" + model, cwd=str(tmp_path), system_prompt=role,
            mcp_servers={"orchestra": {"command": "/bin/false", "args": [], "env": {}}},
            context_limit=1000, resume_session_id=resume, profile=""))

    def trace():
        return [json.loads(row) for row in trace_file.read_text().splitlines()] if trace_file.exists() else []

    yield SimpleNamespace(home=home, trace=trace, backend=backend, egress=egress)
    await acp.shutdown_profiles()
    assert not list(home.rglob("*token*")), "no token copies may be created"
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    with (EVIDENCE / "mock-counters.jsonl").open("a") as f:
        f.write(json.dumps({"test": request.node.name, "methods": dict(Counter(r["method"] for r in trace())),
                           "pids": sorted({r["pid"] for r in trace()}), "token_files": 0}) + "\n")


async def turn(backend, text):
    await backend.send(owner_message(text))
    events = [event async for event in backend.events()]
    await backend._task
    assert sum(e.type == "turn_end" for e in events) == 1
    return events


def end(events):
    return next(e for e in events if e.type == "turn_end")


async def wait_prompt(stand, number=1):
    async with asyncio.timeout(3):
        while sum(r["method"] == "prompt_start" for r in stand.trace()) < number:
            await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_one_daemon_multiple_turns_and_instances(stand):
    a, b = stand.backend(role="role-a"), stand.backend(role="role-b")
    await a.connect()
    await b.connect()
    assert not stand.trace()  # lazy connect is passive
    assert not a.is_alive
    first = await turn(a, "one")
    second = await turn(a, "two")
    third = await turn(b, "three")
    assert all(end(e).metadata["ok"] for e in (first, second, third))
    assert a.session_id != b.session_id
    methods = Counter(r["method"] for r in stand.trace())
    assert methods["spawn"] == methods["initialize"] == methods["authenticate"] == 1
    assert methods["session/new"] == 2 and methods["session/prompt"] == 3
    assert first[-1].usage.current.tokens == 200
    assert first[-1].metadata["cost_unaccounted"] is True
    assert all("WRONG" not in e.content for events in (first, second, third) for e in events)
    prompts = [r for r in stand.trace() if r["method"] == "prompt_start"]
    assert [r["role"] for r in prompts] == ["[Orchestra role instructions]\nrole-a", "", "[Orchestra role instructions]\nrole-b"]
    await a.disconnect()
    assert b.is_alive  # disconnecting a session does not kill the app-owned daemon
    assert end(await turn(b, "four")).metadata["ok"]


@pytest.mark.asyncio
async def test_profile_concurrency_and_event_isolation(stand, monkeypatch, tmp_path):
    # 1) Same (cwd, mcpServers) reuses one transport and runs concurrently with isolated event streams:
    a, b = stand.backend(), stand.backend(model="gemini-4-argon-medium")
    ea, eb = await asyncio.gather(turn(a, "a"), turn(b, "b"))
    assert [e.content for e in ea if e.type == "text"] == [a.session_id + ":a"]
    assert [e.content for e in eb if e.type == "text"] == [b.session_id + ":b"]
    assert all("WRONG" not in e.content for evs in (ea, eb) for e in evs)
    assert sum(r["method"] == "spawn" for r in stand.trace()) == 1
    assert max(r["active_count"] for r in stand.trace() if r["method"] == "prompt_start") == 2

    # 2) Distinct project (cwd, mcpServers) sessions get isolated transports under one AcpProfile,
    #    bounded across the entire profile by Semaphore(3):
    await acp.shutdown_profiles()
    before_multi = len(stand.trace())
    sessions = []
    for idx, model in enumerate(("gemini-4-carbon-medium", "gemini-4-argon-medium", "gemini-4-carbon-medium", "gemini-4-argon-medium")):
        cwd_i = tmp_path / f"proj-{idx}"; cwd_i.mkdir()
        inst = agy.AntigravityBackend(SimpleNamespace(
            model="antigravity/" + model, cwd=str(cwd_i), system_prompt=f"role-{idx}",
            mcp_servers={"orchestra": {"command": "/bin/false", "args": [], "env": {"ORCHESTRA_SESSION_ID": f"sess-{idx}"}}},
            context_limit=1000, resume_session_id=None, profile=""))
        sessions.append(inst)
    results = await asyncio.gather(*(turn(s, f"msg-{i}") for i, s in enumerate(sessions)))
    for i, (s, evs) in enumerate(zip(sessions, results)):
        assert [e.content for e in evs if e.type == "text"] == [f"{s.session_id}:msg-{i}"]
        assert all("WRONG" not in e.content for e in evs)
    multi_trace = stand.trace()[before_multi:]
    assert len({r["pid"] for r in multi_trace if r["method"] == "spawn"}) == 4
    before_warm = len(stand.trace())
    warm_results = await asyncio.gather(*(turn(s, f"warm-{i}") for i, s in enumerate(sessions)))
    assert all(end(evs).metadata["ok"] for evs in warm_results)
    warm_trace = stand.trace()[before_warm:]
    assert not any(r["method"] == "spawn" for r in warm_trace)
    cur = peak = 0
    for r in warm_trace:
        if r["method"] == "prompt_start":
            cur += 1; peak = max(peak, cur)
        elif r["method"] == "prompt_end":
            cur -= 1
    assert 2 <= peak <= 3

    # 3) Same native session resumed concurrently is strictly serialized by session_lock:
    same_a = agy.AntigravityBackend(SimpleNamespace(
        model="antigravity/gemini-4-carbon-medium", cwd=str(tmp_path / "proj-0"), system_prompt="role-0",
        mcp_servers={"orchestra": {"command": "/bin/false", "args": [], "env": {"ORCHESTRA_SESSION_ID": "sess-0"}}},
        context_limit=1000, resume_session_id=sessions[0].session_id, profile=""))
    same_b = agy.AntigravityBackend(SimpleNamespace(
        model="antigravity/gemini-4-carbon-medium", cwd=str(tmp_path / "proj-0"), system_prompt="role-0",
        mcp_servers={"orchestra": {"command": "/bin/false", "args": [], "env": {"ORCHESTRA_SESSION_ID": "sess-0"}}},
        context_limit=1000, resume_session_id=sessions[0].session_id, profile=""))
    ra, rb = await asyncio.gather(turn(same_a, "seq-1"), turn(same_b, "seq-2"))
    assert end(ra).metadata["ok"] and end(rb).metadata["ok"]

    # 4) Explicit ANTIGRAVITY_MAX_CONCURRENT_TURNS=1 enforces strict 1-at-a-time order:
    await acp.shutdown_profiles()
    monkeypatch.setenv("ANTIGRAVITY_MAX_CONCURRENT_TURNS", "1")
    x, y = stand.backend(), stand.backend(model="gemini-4-argon-medium")
    before_idx = len(stand.trace())
    await asyncio.gather(turn(x, "x"), turn(y, "y"))
    order = [r["method"] for r in stand.trace()[before_idx:] if r["method"] in {"prompt_start", "prompt_end"}]
    assert order == ["prompt_start", "prompt_end"] * 2


@pytest.mark.asyncio
async def test_resume_capability_no_history_replay(stand):
    b = stand.backend(resume="existing-session")
    assert end(await turn(b, "resume")).metadata["ok"]
    methods = Counter(r["method"] for r in stand.trace())
    assert methods["session/resume"] == 1 and methods["session/new"] == 0


@pytest.mark.asyncio
async def test_unsupported_resume_never_silently_creates_new(stand, monkeypatch):
    monkeypatch.setenv("AGY_MOCK_MODE", "no-resume")
    assert not end(await turn(stand.backend(resume="retained-session"), "no")).metadata["ok"]
    assert not any(r["method"] in {"session/new", "session/prompt", "session/resume"} for r in stand.trace())


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["init-death", "auth-error"])
async def test_start_failure_latches_without_login_or_spawn_loop(stand, monkeypatch, mode):
    monkeypatch.setenv("AGY_MOCK_MODE", mode)
    for _ in range(3):
        assert not end(await turn(stand.backend(), "no replay")).metadata["ok"]
    methods = Counter(r["method"] for r in stand.trace())
    assert methods["spawn"] == 1 and methods["session/prompt"] == 0
    assert methods["authenticate"] <= 1


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["DIE", "MALFORMED", "ERROR"])
async def test_turn_failure_no_automatic_prompt_replay_or_restart(stand, message):
    b = stand.backend()
    events = await turn(b, message)
    assert not end(events).metadata["ok"]
    assert "synthetic-secret" not in str(events)
    for _ in range(3):
        assert not end(await turn(stand.backend(), "later user action")).metadata["ok"]
    methods = Counter(r["method"] for r in stand.trace())
    assert methods["spawn"] == 1 and methods["session/prompt"] == 1


@pytest.mark.asyncio
async def test_cancellation_is_session_scoped_and_daemon_reused(stand):
    a, b = stand.backend(), stand.backend()
    await a.send(owner_message("BLOCK"))
    await wait_prompt(stand)
    queued = asyncio.create_task(turn(b, "next"))
    assert await a.interrupt() is True
    assert not end([e async for e in a.events()]).metadata["ok"]
    assert end(await queued).metadata["ok"]
    assert sum(r["method"] == "spawn" for r in stand.trace()) == 1
    assert sum(r["method"] == "session/cancel" for r in stand.trace()) == 1


@pytest.mark.asyncio
async def test_cancel_queued_turn_does_not_cancel_other_session(stand, monkeypatch):
    monkeypatch.setenv("ANTIGRAVITY_MAX_CONCURRENT_TURNS", "1")
    a, b = stand.backend(), stand.backend()
    await a.send(owner_message("BLOCK"))
    await wait_prompt(stand)
    await b.send(owner_message("queued"))
    await asyncio.sleep(0.01)
    await b.interrupt()
    assert not end([e async for e in b.events()]).metadata["ok"]
    assert a.is_alive and not any(r["method"] == "session/cancel" for r in stand.trace())
    await a.interrupt()
    assert sum(r["method"] == "session/prompt" for r in stand.trace()) == 1


@pytest.mark.asyncio
async def test_prompt_timeout_latches_and_shutdown_cleans_owned_pid(stand):
    b = stand.backend()
    await b.connect()
    b._owner.prompt_timeout = 0.10
    assert not end(await turn(b, "BLOCK")).metadata["ok"]
    pid = b._owner.process.pid
    assert b._owner.process.returncode is not None
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)
    assert not end(await turn(stand.backend(), "no restart")).metadata["ok"]
    assert sum(r["method"] == "spawn" for r in stand.trace()) == 1


@pytest.mark.asyncio
async def test_unacknowledged_cancel_closes_profile(stand):
    b = stand.backend()
    await b.send(owner_message("IGNORE_CANCEL"))
    await wait_prompt(stand)
    await b.interrupt()
    assert b._owner.failure and b._owner.process.returncode is not None
    assert not end(await turn(stand.backend(), "no restart")).metadata["ok"]
    assert sum(r["method"] == "spawn" for r in stand.trace()) == 1


@pytest.mark.asyncio
async def test_passive_status_and_quota_never_probe_or_verify_egress(stand, monkeypatch):
    from app.routes import system
    monkeypatch.setattr(system, "_antigravity_usage_cache", {"data": None, "ts": 0.0})
    for _ in range(20):
        r = await agy.antigravity_readiness(RuntimeReadinessContext("antigravity/gemini-4-carbon-medium"))
        assert not r.catalog_ready
        assert await agy.fetch_antigravity_usage() == dict.fromkeys(agy.QUOTA_KEYS)
        await system._refresh_antigravity_usage(force_refresh=True)
        await system.current_quota_observation(required_provider="antigravity_gemini", max_age=0)
    assert not stand.trace()
    stand.egress.assert_not_awaited()
    assert system._antigravity_usage_cache["ts"] == 0.0


@pytest.mark.asyncio
async def test_cached_observation_does_not_become_fresh_by_polling(stand, monkeypatch):
    from app.routes import system
    cache = {"data": {"gemini-weekly": {"utilization": 42}}, "ts": 12.0}
    monkeypatch.setattr(system, "_antigravity_usage_cache", cache)
    for _ in range(4):
        await system._refresh_antigravity_usage(force_refresh=True, max_age=0)
        assert await agy.fetch_antigravity_usage() == cache["data"]
    assert cache["ts"] == 12.0 and not stand.trace()
    stand.egress.assert_not_awaited()


@pytest.mark.asyncio
async def test_readiness_uses_only_catalog_from_explicit_session(stand):
    b = stand.backend()
    await turn(b, "catalog")
    before = len(stand.trace())
    stand.egress.reset_mock()
    for _ in range(10):
        r = await agy.antigravity_readiness(RuntimeReadinessContext("antigravity/gemini-4-carbon-medium"))
        assert r.credentials_ready and r.catalog_ready
    assert len(stand.trace()) == before
    stand.egress.assert_not_awaited()


@pytest.mark.asyncio
async def test_disabled_and_egress_guards_preserved(stand, monkeypatch):
    from app import models
    monkeypatch.setattr(models, "is_provider_disabled", lambda _: True)
    r = await agy.antigravity_readiness(RuntimeReadinessContext("antigravity/gemini-4-carbon-medium"))
    assert not r.credentials_ready
    stand.egress.side_effect = RuntimeError("synthetic guard refusal")
    assert not end(await turn(stand.backend(), "blocked")).metadata["ok"]
    assert not stand.trace()


@pytest.mark.asyncio
async def test_credit_settings_fail_closed_without_rewriting(stand):
    settings = stand.home / ".gemini/config/config.json"
    settings.write_text('{"userSettings":{"useAiCredits":true}}')
    before = settings.read_bytes()
    assert not end(await turn(stand.backend(), "blocked")).metadata["ok"]
    assert settings.read_bytes() == before and not stand.trace()


@pytest.mark.asyncio
async def test_cross_process_profile_lock_refuses_second_owner(stand):
    # Distinct owner simulates a second app; flock applies across FDs/processes.
    first = stand.backend()
    await turn(first, "first")
    other = acp.AcpProfile(stand.home.resolve())
    with pytest.raises(acp.AcpError):
        await other.start()
    assert sum(r["method"] == "spawn" for r in stand.trace()) == 1
    assert first.is_alive


@pytest.mark.asyncio
@pytest.mark.parametrize("origin,subtype", [("background_task", "cron"), ("background_task", "timer"),
    ("system", "dreaming"), ("system", "turn_limit_continue"), ("agent", "direct_message"), ("unknown", "")])
async def test_automated_inputs_denied_at_session_and_backend(stand, origin, subtype):
    from app.session import AgentSession
    provenance = MessageProvenance(origin, ("automation",), subtype)
    s = AgentSession(id="synthetic", name="offline", scope=str(stand.home), cwd=str(stand.home),
                     model="antigravity/gemini-4-carbon-medium")
    with pytest.raises(ValueError, match="interactive_only"):
        await s.send("automated", provenance=provenance)
    with pytest.raises(ValueError, match="interactive_only"):
        await stand.backend().send(InjectedMessage("automated", provenance, "fake-event"))
    assert not stand.trace()


@pytest.mark.asyncio
async def test_plain_backend_calls_cannot_bypass_user_provenance(stand):
    with pytest.raises(ValueError, match="interactive_only"):
        await stand.backend().send("unattributed automatic compact/retry")
    acp.ensure_interactive_input("hub-gpt-6.1-sol", MessageProvenance("agent", ("native",)))
    assert not stand.trace()


@pytest.mark.asyncio
async def test_native_timer_keeps_mailbox_durable_without_loading_consumer(stand):
    from app import db, mailbox, timers
    from app.session_state import AgentStatus
    db.init_db()
    session = SimpleNamespace(id="offline", model="antigravity/gemini-4-carbon-medium", status=AgentStatus.IDLE)
    manager = SimpleNamespace(get_by_name=lambda *args: session, ensure_loaded_by_id=AsyncMock())
    timers.set_timer("offline", "/scope", "alarm", due_at=1)
    assert await timers.tick_timers(manager, now=2) == 1
    assert len(mailbox.pending("offline", "/scope")) == 1
    manager.ensure_loaded_by_id.assert_not_awaited()
    assert not stand.trace()


def test_harness_enforces_external_network_and_real_executable_denial():
    import subprocess
    assert socket.if_nameindex() == [(1, "lo")]
    with socket.socket() as s, pytest.raises(PermissionError, match="external network denied"):
        s.connect(("192.0.2.1", 9))
    with pytest.raises(PermissionError, match="external DNS denied"):
        socket.getaddrinfo("example.invalid", 443)
    with pytest.raises(PermissionError, match="only fake_agy"):
        subprocess.run(["/bin/true"], check=True)
    with pytest.raises(PermissionError, match="production repository"):
        Path("/home/kesha/orchestra/data/never-read").read_text()


@pytest.mark.asyncio
async def test_loopback_http_and_real_orchestra_sse_smoke(stand, monkeypatch):
    """Production usage and chat SSE routers, separate SQLite, no main lifespan."""
    from fastapi import FastAPI
    import uvicorn
    from app import db
    from app.routes import sessions, system
    from app.session import AgentSession
    from app.session_state import AgentStatus
    db.init_db()
    s = AgentSession(id="offline-http", name="offline-http", scope=str(stand.home), cwd=str(stand.home),
                     model="antigravity/gemini-4-carbon-medium", backend_type="antigravity", is_orchestrator=True)
    s._persist()
    async def send_owner(session_id, message, *, provenance, **kwargs):
        assert session_id == s.id
        await s.send(message, provenance=provenance)
        await s._listen_task
    monkeypatch.setattr(sessions, "manager", SimpleNamespace(
        get_session_id=lambda *a: s.id, get=lambda _: s,
        ensure_loaded=AsyncMock(return_value=s), send=send_owner))
    monkeypatch.setattr("app.auth.validate_session", lambda cookie: cookie == "offline-operator")
    monkeypatch.setattr(system, "is_provider_disabled", lambda p: p != "antigravity")
    monkeypatch.setattr(system, "_antigravity_usage_cache", {"data": None, "ts": 0.0})
    backend = stand.backend()
    async def ensure_stand_backend(**kwargs):
        s._backend = backend
        return backend
    monkeypatch.setattr(s, "_ensure_backend", ensure_stand_backend)
    monkeypatch.setattr(s, "_start_checklist_reminder", lambda: None)
    @asynccontextmanager
    async def lifespan(app):
        yield
        await backend.disconnect()
        await acp.shutdown_profiles()
    app = FastAPI(lifespan=lifespan)
    app.include_router(system.router)
    app.include_router(sessions.router)
    # The actual operator send route and AgentSession dispatch are exercised below;
    # only production bootstrap/lifespan and auth credentials are replaced.
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=18889, log_level="critical"))
    running = asyncio.create_task(server.serve())
    try:
        async with asyncio.timeout(3):
            while not server.started:
                if running.done():
                    await running
                await asyncio.sleep(0.01)
        frames = []
        async with httpx.AsyncClient(base_url="http://127.0.0.1:18889", timeout=5, trust_env=False,
                cookies={"session":"offline-operator"}) as client:
            for _ in range(5):
                assert (await client.get("/api/usage")).status_code == 200
                assert (await client.get("/api/usage/readiness", params={"model": s.model})).status_code == 200
            assert not stand.trace()
            stand.egress.assert_not_awaited()
            client.cookies.clear()
            denied = await client.post("/api/sessions/offline-http/send",
                json={"message":"unattributed automation", "scope":s.scope})
            assert denied.status_code == 403 and not stand.trace()
            client.cookies.set("session", "offline-operator")
            async with client.stream("GET", "/api/sessions/offline-http/stream", params={"scope": s.scope}) as response:
                assert response.status_code == 200
                submitted = asyncio.create_task(client.post("/api/sessions/offline-http/send",
                    json={"message":"http-sse", "scope":s.scope}))
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        frame = json.loads(line[6:])
                        frames.append(frame)
                        # AgentSession publishes chat text/status, not raw backend turn_end.
                        if "http-sse" in frame.get("content", ""):
                            break
                assert (await submitted).status_code == 200
            assert (await client.post("/api/sessions/offline-http/send",
                json={"message":"second-http-turn", "scope":s.scope})).status_code == 200
            assert s.status == AgentStatus.IDLE
            before = len(stand.trace())
            for _ in range(5):
                assert (await client.get("/api/usage")).status_code == 200
            assert len(stand.trace()) == before
        assert any("http-sse" in f.get("content", "") for f in frames)
        assert Counter(r["method"] for r in stand.trace())["spawn"] == 1
        (EVIDENCE / "http-sse-smoke.json").write_text(json.dumps({
            "url": "http://127.0.0.1:18889", "database": str(db.DB_PATH),
            "imported_app": str(__import__("app").__path__[0]),
            "passive_http_polls": 15, "spawn_before_prompt": 0,
            "methods": dict(Counter(r["method"] for r in stand.trace())),
            "sse_frames": frames, "telegram": "not started", "cron": "not started",
            "main_lifespan": "deliberately replaced by mock-only stand lifespan",
        }, indent=2))
    finally:
        server.should_exit = True
        await asyncio.wait_for(running, 3)
    assert backend._owner.process.returncode is not None


@pytest.mark.asyncio
async def test_config_options_catalog_and_same_session_model_switch(stand, monkeypatch):
    monkeypatch.setenv("AGY_MOCK_MODE", "config-options")
    a = stand.backend(model="gemini-4-argon-medium")
    assert end(await turn(a, "argon")).metadata["ok"]
    b = stand.backend(resume=a.session_id)
    assert end(await turn(b, "carbon")).metadata["ok"]
    methods = Counter(r["method"] for r in stand.trace())
    assert methods["session/set_config_option"] == 2
    assert methods["session/set_model"] == 0
    assert methods["session/new"] == methods["spawn"] == 1


@pytest.mark.asyncio
async def test_absent_model_fails_without_substitution(stand):
    assert not end(await turn(stand.backend(model="gemini-not-advertised"), "no fallback")).metadata["ok"]
    assert not any(r["method"] == "session/prompt" for r in stand.trace())


@pytest.mark.asyncio
async def test_shutdown_during_prompt_settles_events_and_releases_profile(stand):
    b = stand.backend()
    await b.send(owner_message("BLOCK"))
    await wait_prompt(stand)
    pid = b._owner.process.pid
    await acp.shutdown_profiles()
    events = [e async for e in b.events()]
    assert not end(events).metadata["ok"]
    assert b._owner._lock_fd is None
    assert not acp.cached_profile(stand.home)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


@pytest.mark.asyncio
async def test_settings_and_credential_status_do_not_read_oauth_snapshot(stand, monkeypatch):
    from app import antigravity_auth
    monkeypatch.setattr(antigravity_auth, "read_auth_snapshot", lambda *a: pytest.fail("token snapshot read"))
    monkeypatch.setattr(antigravity_auth, "sync_antigravity_home", lambda *a: pytest.fail("token copy attempted"))
    b = stand.backend()
    assert end(await turn(b, "no application credential reads")).metadata["ok"]
    assert not list(stand.home.rglob("*token*"))


@pytest.mark.asyncio
async def test_canonical_profile_aliases_share_owner(stand, monkeypatch, tmp_path):
    from app import db
    alias = tmp_path / "same-profile"
    alias.symlink_to(stand.home, target_is_directory=True)
    monkeypatch.setattr(db, "get_profile", lambda name: {"config_dir": str(alias)})
    assert agy.canonical_profile("alias") == stand.home.resolve()
    assert acp.get_profile(alias) is acp.get_profile(stand.home)


@pytest.mark.asyncio
@pytest.mark.parametrize("message,ok", [("RECOVERED", True), ("PARTIAL_ERROR", False), ("PARTIAL_CANCEL", False)])
async def test_terminal_result_controls_success_after_partial_output(stand, message, ok):
    events = await turn(stand.backend(), message)
    assert any(e.type == "text" and e.content.startswith("partial-output") for e in events)
    assert end(events).metadata["ok"] is ok
    if message == "RECOVERED":
        assert any(e.type == "tool_result" and e.metadata["status"] == "failed" for e in events)
    assert sum(e.type == "turn_end" for e in events) == 1
    assert sum(r["method"] == "session/prompt" for r in stand.trace()) == 1


@pytest.mark.asyncio
async def test_cumulative_cost_delta_survives_backend_recreation(stand):
    b = stand.backend()
    first = end(await turn(b, "COST"))
    assert first.metadata["cost_usd"] == pytest.approx(0.01)
    assert first.metadata["cost_unaccounted"] is False
    resumed = stand.backend(resume=b.session_id)
    second = end(await turn(resumed, "COST"))
    assert second.metadata["cost_usd"] == pytest.approx(0.01)
    assert resumed._owner.cost_totals[b.session_id] == pytest.approx(0.02)
    # ACP's context usage is NOT billed aggregate input/output token counts.
    assert second.usage.aggregate.accuracy == "unknown"
    assert second.usage.aggregate.derived()["prompt_total"] is None


@pytest.mark.asyncio
async def test_failed_turn_cost_is_recorded_without_success_or_replay(stand):
    b = stand.backend()
    event = end(await turn(b, "COST_ERROR"))
    assert event.metadata["ok"] is False
    assert event.metadata["cost_usd"] == pytest.approx(0.01)
    assert b._owner.cost_totals[b.session_id] == pytest.approx(0.01)
    assert b._owner.failure
    assert sum(r["method"] == "session/prompt" for r in stand.trace()) == 1


@pytest.mark.asyncio
async def test_resumed_unknown_cost_baseline_never_double_counts_history(stand):
    b = stand.backend(resume="existing-cost-history")
    first = end(await turn(b, "COST"))
    assert first.metadata["cost_unaccounted"] is True
    second = end(await turn(b, "COST"))
    assert second.metadata["cost_usd"] == pytest.approx(0.01)


@pytest.mark.asyncio
async def test_credits_are_never_converted_to_usd(stand):
    event = end(await turn(stand.backend(), "COST_CREDITS"))
    assert event.metadata["cost_unaccounted"] is True
    assert event.metadata["cost_usd"] == 0


@pytest.mark.asyncio
async def test_invalid_context_is_unknown_without_breaking_terminal_success(stand):
    from app.usage_contract import UnknownContext
    event = end(await turn(stand.backend(), "INVALID_CONTEXT"))
    assert event.metadata["ok"] is True
    assert isinstance(event.usage.current, UnknownContext)


@pytest.mark.asyncio
async def test_auth_loss_after_success_latches_without_reauth(stand):
    b = stand.backend()
    assert end(await turn(b, "before auth loss")).metadata["ok"]
    assert not end(await turn(b, "ERROR")).metadata["ok"]
    assert not end(await turn(b, "never resubmitted")).metadata["ok"]
    methods = Counter(r["method"] for r in stand.trace())
    assert methods["spawn"] == methods["authenticate"] == 1
    assert methods["session/prompt"] == 2
    readiness = await agy.antigravity_readiness(RuntimeReadinessContext("antigravity/gemini-4-carbon-medium"))
    assert not readiness.credentials_ready and not readiness.catalog_ready


@pytest.mark.asyncio
async def test_owner_session_submission_delivers_trusted_backend_provenance(stand, monkeypatch):
    from app.session import AgentSession
    from app.session_state import AgentStatus
    b = stand.backend()
    s = AgentSession(id="owner-path", name="owner-path", scope=str(stand.home), cwd=str(stand.home),
        model="antigravity/gemini-4-carbon-medium", backend_type="antigravity", is_orchestrator=True)
    monkeypatch.setattr(s, "_ensure_backend", AsyncMock(return_value=b))
    monkeypatch.setattr(s, "_persist", lambda: None)
    monkeypatch.setattr(s, "_log", lambda *a, **kw: None)
    monkeypatch.setattr(s, "_start_checklist_reminder", lambda: None)
    events = []
    async def listen():
        events.extend([e async for e in b.events()])
        s.status = AgentStatus.IDLE
    monkeypatch.setattr(s, "_turn_event_loop", listen)
    await s.send("owner through AgentSession", provenance=USER)
    await s._listen_task
    assert end(events).metadata["ok"]
    assert sum(r["method"] == "session/prompt" for r in stand.trace()) == 1
