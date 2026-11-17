"""Independent behavior regressions; only the kernel-isolated fake runner."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app import backend_antigravity as agy
from app.events import InjectedMessage, MessageProvenance
from tests.test_antigravity_acp import stand, turn, end, USER
REAL_CLI_ENVIRONMENT = agy.cli_environment


@pytest.mark.asyncio
async def test_operator_compact_failure_has_one_prompt_and_no_retry(stand, monkeypatch):
    from app.session import AgentSession, AgentStatus
    from app import bg_jobs
    monkeypatch.setattr(bg_jobs, "bg_manager", None)
    monkeypatch.setenv("AGY_MOCK_MODE", "all-error")
    s = AgentSession(id="failed-compact", name="failed-compact", scope=str(stand.home),
        cwd=str(stand.home), model="antigravity/gemini-4-carbon-medium",
        backend_type="antigravity", is_orchestrator=True)
    s.status = AgentStatus.IDLE
    s.session_id = "original-conversation"
    s._log = MagicMock(); s._persist = MagicMock(); s._drain_persist = AsyncMock()
    s._wake_durable_message_deliveries = MagicMock()
    s._make_backend = stand.backend
    result = await asyncio.wait_for(s.compact(provenance=USER), 3)
    assert not result["ok"] and s.session_id == "original-conversation"
    assert sum(r["method"] == "session/prompt" for r in stand.trace()) == 1
    assert not s._compacting


@pytest.mark.asyncio
@pytest.mark.parametrize("operator", [None, (False, "agent-id"), (True, "")])
async def test_compact_route_requires_operator_for_consumer(stand, monkeypatch, operator):
    from app.routes import sessions
    compact = AsyncMock(return_value={"ok": True})
    s = SimpleNamespace(backend_type="antigravity", status=SimpleNamespace(value="idle"), compact=compact)
    monkeypatch.setattr(sessions, "manager", SimpleNamespace(ensure_loaded=AsyncMock(return_value=s)))
    monkeypatch.setattr(sessions, "_delivery_caller", lambda request: operator)
    result = await sessions.compact_session("offline", sessions.ScopeRequest(scope="/synthetic"))
    if operator is None or not operator[0]:
        assert result.status_code == 403
        compact.assert_not_awaited()
    else:
        assert result == {"ok": True}
        assert compact.await_args.kwargs["provenance"].origin == "user"


@pytest.mark.asyncio
async def test_failed_tool_update_is_a_visible_error_even_if_terminal_succeeds(stand):
    events = await turn(stand.backend(), "RECOVERED")
    errors = [e for e in events if e.type == "tool_result" and e.metadata.get("is_error")]
    assert len(errors) == 1 and errors[0].metadata["status"] == "failed"
    assert "synthetic failure details" in errors[0].content and '"exitCode": 1' in errors[0].content
    assert end(events).metadata["ok"]


def test_cli_environment_blocks_browser_login_and_uses_canonical_store(stand, monkeypatch):
    from app import provider_safety
    monkeypatch.setattr(provider_safety, "build_provider_env", lambda provider: {"BROWSER": "/untrusted/browser"})
    env = REAL_CLI_ENVIRONMENT(stand.home)
    assert env["BROWSER"] == "/usr/bin/true"
    assert env["GEMINI_HOME"] == str(stand.home / ".gemini")
    assert env["AGY_ACP_FORCE_FILE_STORAGE"] == "1"


# Reuse frozen legacy assertions with a synthetic canonical profile instead of the
# retired token-copy fixture. The original files and assertions stay untouched.
from tests import test_antigravity_turn_health as legacy
from app.usage_contract import UnknownContext


def test_legacy_readonly_wal_assertions_on_canonical_profile(stand, monkeypatch):
    legacy.test_metadata_reader_uses_read_only_uri_and_observes_wal(stand.backend, monkeypatch)


@pytest.mark.parametrize("used,maximum", [(0, 256000), (256000, 256000), (150000, 200000)])
def test_legacy_context_boundaries_on_canonical_profile(stand, used, maximum):
    legacy.test_context_boundaries_use_cli_maximum(stand.backend, used, maximum)


@pytest.mark.parametrize("payload", [
    b"", b"\x80", b"\x0a\x05x", b"\x00", b"\x0b", b"\x09xx", b"\x0dxx",
    b"\xff" * 11, legacy.field(1, 7), legacy.field(1, legacy.field(9, legacy.field(10, 3))),
    legacy.metadata(None, 256000), legacy.metadata(183159, None), legacy.metadata(1, 0),
    legacy.metadata(256001, 256000), b"x" * 1048577,
], ids=["empty", "varint", "truncated", "zero-tag", "wire3", "wire1", "wire5", "overflow",
        "wrong-envelope", "wrong-window", "missing-used", "missing-max", "zero-max", "over-max", "oversize"])
def test_legacy_corrupt_context_assertions_on_canonical_profile(stand, payload):
    legacy.test_corrupt_or_invalid_latest_metadata_is_unknown(stand.backend, payload)


@pytest.mark.parametrize("conversation", [None, "../outside", "/absolute", "bad?mode=rw"])
def test_legacy_invalid_conversation_assertions_on_canonical_profile(stand, monkeypatch, conversation):
    legacy.test_invalid_conversation_never_opens_a_database(stand.backend, monkeypatch, conversation)


@pytest.mark.parametrize("case", ["missing", "empty", "missing-table", "corrupt-db", "text-blob"])
def test_unreadable_legacy_context_is_unknown_without_creating_files(stand, case):
    b = stand.backend()
    if case != "missing":
        connection, database = legacy.write_metadata(b, [])
        if case == "missing-table": connection.execute("DROP TABLE gen_metadata")
        if case == "text-blob": connection.execute("INSERT INTO gen_metadata VALUES (1, 'not bytes', 9)")
        connection.commit(); connection.close()
        if case == "corrupt-db": database.write_bytes(b"invalid sqlite")
    assert isinstance(agy._conversation_context(b.home, "conversation-a", 1000000), UnknownContext)
    if case == "missing": assert not (b.home / ".gemini/antigravity-cli/conversations").exists()


@pytest.mark.asyncio
async def test_cancelled_turn_accounts_latest_cost_once(stand):
    b = stand.backend()
    await b.send(InjectedMessage("COST_BLOCK", USER, "cost-cancel"))
    async with asyncio.timeout(3):
        while b._cost_total is None: await asyncio.sleep(.01)
    assert await b.interrupt()
    cancelled = end([e async for e in b.events()])
    assert not cancelled.metadata["ok"] and cancelled.metadata["cost_usd"] == pytest.approx(.01)
    following = end(await turn(b, "COST"))
    assert following.metadata["cost_usd"] == pytest.approx(.01)
    assert sum(r["method"] == "spawn" for r in stand.trace()) == 1


@pytest.mark.asyncio
async def test_new_session_collision_refuses_to_share_another_conversation(stand, monkeypatch):
    monkeypatch.setenv("AGY_MOCK_MODE", "collision")
    a, b = stand.backend(), stand.backend()
    assert end(await turn(a, "first conversation")).metadata["ok"]
    assert not end(await turn(b, "different conversation")).metadata["ok"]
    assert sum(r["method"] == "session/prompt" for r in stand.trace()) == 1
    assert a._owner.failure


@pytest.mark.asyncio
async def test_immediate_cancel_without_sleep_always_settles_once(stand):
    b = stand.backend()
    await b.send(InjectedMessage("cancel before _run", USER, "immediate"))
    assert await b.interrupt()
    async with asyncio.timeout(1):
        events = [e async for e in b.events()]
    assert len([e for e in events if e.type == "turn_end"]) == 1
    assert not end(events).metadata["ok"] and b._task.done()
    assert not stand.trace()  # not even initialize or prompt


@pytest.mark.asyncio
@pytest.mark.parametrize("refusal", ["model", "resume"])
async def test_local_refusal_keeps_sibling_session_on_same_process(stand, monkeypatch, refusal):
    if refusal == "resume": monkeypatch.setenv("AGY_MOCK_MODE", "no-resume")
    a = stand.backend()
    assert end(await turn(a, "before local refusal")).metadata["ok"]
    b = stand.backend(model="not-advertised") if refusal == "model" else stand.backend(resume="unloadable")
    assert not end(await turn(b, "must not be submitted")).metadata["ok"]
    assert a.is_alive and not a._owner.failure
    assert end(await turn(a, "after local refusal")).metadata["ok"]
    assert sum(r["method"] == "spawn" for r in stand.trace()) == 1
    assert sum(r["method"] == "session/prompt" for r in stand.trace()) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("payload,banned", [("BAN", True), ("ERROR", False)])
async def test_definite_ban_persists_only_safe_reason_in_isolated_state(stand, monkeypatch, tmp_path, payload, banned):
    from app import db
    db.init_db()
    state = tmp_path / "isolated-disabled.json"
    monkeypatch.setenv("ORCHESTRA_DISABLED_PROVIDERS_FILE", str(state))
    monkeypatch.setenv("ORCHESTRA_DISABLED_PROVIDERS", "")
    events = await turn(stand.backend(), payload)
    assert not end(events).metadata["ok"]
    assert "synthetic-secret" not in str(events)
    if banned:
        assert "antigravity" in json.loads(state.read_text())["disabled_providers"]
        incident = db.kv_get("provider_ban_incidents", "[]")
        assert "synthetic-secret" not in incident
        assert "ACP confirmed account-disabled" in incident
    else:
        assert not state.exists()


@pytest.mark.asyncio
async def test_multi_chunk_reply_has_one_history_message_and_complete_last_output(stand, monkeypatch):
    from app.session import AgentSession
    b = stand.backend(); events = await turn(b, "MULTI")
    s = AgentSession(id="chunks", name="chunks", scope=str(stand.home), cwd=str(stand.home),
        model="antigravity/gemini-4-carbon-medium", backend_type="antigravity", is_orchestrator=True)
    logs = []
    monkeypatch.setattr(s, "_log", lambda kind, content, **kwargs: logs.append((kind, content)))
    for event in events:
        if event.type in {"stream", "text"}: s._handle_event(event)
    assert [e.content for e in events if e.type == "stream"] == ["hello ", "complete ", "reply"]
    assert [x for x in logs if x[0] == "text"] == [("text", "hello complete reply")]
    assert s._last_text_output == "hello complete reply"


@pytest.mark.asyncio
async def test_tool_progress_is_not_premature_terminal_result(stand):
    events = await turn(stand.backend(), "tools")
    uses = [e for e in events if e.type == "tool_use"]
    results = [e for e in events if e.type == "tool_result"]
    assert len(uses) == len(results) == 1
    assert results[0].metadata["tool_name"] == uses[0].metadata["tool_name"] == "mock-tool"
    assert results[0].metadata["tool_use_id"] == uses[0].metadata["tool_use_id"]
    assert any(e.type == "tool_stream" and "tool progress" in e.content for e in events)


@pytest.mark.parametrize("uri", [False, True, "pathlike"])
def test_native_sqlite_open_is_denied_before_touching_production(uri):
    import sqlite3
    address = "file:/home/kesha/orchestra/data/do-not-open-review.db?mode=ro" if uri else "/home/kesha/orchestra/data/do-not-open-review.db"
    if uri == "pathlike":
        from pathlib import Path
        address, uri = Path("/home/kesha/orchestra/data/do-not-open-review.db"), False
    with pytest.raises(PermissionError, match="production repository"):
        sqlite3.connect(address, uri=uri)


def test_legacy_login_refuses_before_launch_or_auth_file_reads(stand, monkeypatch):
    import sys, subprocess
    from app import antigravity_auth
    launch = MagicMock(side_effect=AssertionError("login executable must never start"))
    monkeypatch.setattr(subprocess, "run", launch)
    monkeypatch.setattr(sys, "argv", ["legacy-login"])
    assert antigravity_auth.main() == 1
    launch.assert_not_called()


@pytest.mark.asyncio
async def test_permission_request_is_cancelled_without_closing_sibling_profile(stand, monkeypatch):
    monkeypatch.setenv("ANTIGRAVITY_AUTO_APPROVE", "0")
    b = stand.backend()
    events = await turn(b, "PERMISSION")
    assert not end(events).metadata["ok"] and end(events).metadata["stop_reason"] == "cancelled"
    assert sum(r["method"] == "permission_denied" for r in stand.trace()) == 1
    assert b.is_alive and end(await turn(b, "still usable")).metadata["ok"]
    assert sum(r["method"] == "spawn" for r in stand.trace()) == 1


@pytest.mark.asyncio
async def test_updated_model_metadata_is_used_on_the_next_turn(stand):
    b = stand.backend()
    assert end(await turn(b, "CONFIG")).metadata["ok"]
    assert b._owner.model_states[b.session_id]["current"] == "gemini-4-argon-medium"
    assert end(await turn(b, "must select Carbon again")).metadata["ok"]
    entries = [r for r in stand.trace() if r["method"] == "session/set_config_option"]
    assert len(entries) == 1 and entries[0]["params"]["value"] == "gemini-4-carbon-medium"
