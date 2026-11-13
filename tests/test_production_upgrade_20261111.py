"""Approved six-slice regression contracts. No live providers or production state."""
import asyncio
import io
import json
import subprocess
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from app import db, models, temp_rules, hub_workspace as hw, backend_hub as hub, runaway_guard
from app.events import AgentEvent, MessageProvenance
from app.hub_activity import HubActivityStream
from app.session import AgentSession, AgentStatus


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    return tmp_path


@pytest.mark.parametrize("scope", ["orchestra", "seedon", "katya-work", "University",
                                   "VPN-Service", "kesha-tg-bot", "comfy-image-pipeline",
                                   "cog-second-brain", "Claude-Code-Game-Master", "dnd-game-master",
                                   "not-multicast", "multicast-personal"])
@pytest.mark.parametrize("model", ["hubopus", "hubsonnet", "claude-opus-5-5", "agy-opus"])
def test_claude_project_gate(scope, model, monkeypatch):
    monkeypatch.delenv("ORCHESTRA_ALLOW_CLAUDE_ALL", raising=False)
    monkeypatch.delenv("ORCHESTRA_MULTICAST_PATH_TOKENS", raising=False)
    with pytest.raises(ValueError, match="claude_multicast_only"):
        models.ensure_project_model_allowed(model, "/home/kesha/" + scope)
    models.ensure_project_model_allowed("hubsol", "/home/kesha/" + scope)


@pytest.mark.parametrize("project", ["multicode", "multicast", "obelisk", "polus", "empire-front"])
def test_multicast_allowed(project, monkeypatch):
    monkeypatch.delenv("ORCHESTRA_ALLOW_CLAUDE_ALL", raising=False)
    models.ensure_project_model_allowed("hubopus", "/projects/" + project)


def test_gate_override_and_astra(monkeypatch):
    monkeypatch.setenv("ORCHESTRA_ALLOW_CLAUDE_ALL", "1")
    models.ensure_project_model_allowed("hubopus", "/projects/orchestra")
    monkeypatch.delenv("ORCHESTRA_ALLOW_CLAUDE_ALL")
    monkeypatch.setenv("ORCHESTRA_MULTICAST_PATH_TOKENS", "custom-company")
    models.ensure_project_model_allowed("hubsonnet", "/projects/custom-company")
    assert models.resolve_model("hubastra") == "hub-gpt-6-astra"
    models.ensure_hub_worker_allowed("hubastra", scope="/projects/orchestra")
    assert hub.HUB_MODELS["hub-gpt-6-astra"] == ("codex", "gpt-6-astra")


@pytest.mark.parametrize("bucket", ["infra", "tool_or_harness", "test_or_fixture", "unknown"])
def test_care_rejects_non_prompt_failure_before_write(bucket):
    with pytest.raises(temp_rules.RuleError):
        temp_rules.check_failure_bucket(bucket)


@pytest.mark.parametrize("bucket", ["model", "skill_or_rules"])
def test_care_preserves_bucket(bucket):
    assert temp_rules.check_failure_bucket(bucket) == bucket
    result = temp_rules._dump([{"id": "x", "failure_bucket": bucket}])
    assert f"failure_bucket: {bucket}" in result


@pytest.mark.asyncio
async def test_notice_backoff_and_quarantine_survive_sweeps(isolated_db, monkeypatch):
    clock = [datetime(2026, 11, 11, tzinfo=timezone.utc)]
    monkeypatch.setattr(temp_rules, "_now", lambda: clock[0])
    row = {"scope": "/repo", "id": "rule-1", "due_at": clock[0].isoformat(),
           "expires_at": clock[0].isoformat(), "project": "/repo",
           "targets": ["workers"], "text": "test", "author": "closed"}
    monkeypatch.setattr(temp_rules, "claim_due_notices", lambda: [row])
    monkeypatch.setattr(temp_rules, "_recipient", lambda _: ({"id": "dead"}, False))
    manager = SimpleNamespace(send=AsyncMock(side_effect=RuntimeError("session gone")))
    await temp_rules.notify_due(manager)
    for _ in range(20):
        await temp_rules.notify_due(manager)
    assert manager.send.await_count == 1
    clock[0] += timedelta(seconds=60)
    await temp_rules.notify_due(manager)
    assert manager.send.await_count == 2
    clock[0] += timedelta(seconds=299)
    await temp_rules.notify_due(manager)
    assert manager.send.await_count == 2
    clock[0] += timedelta(seconds=1)
    await temp_rules.notify_due(manager)
    assert manager.send.await_count == 3
    clock[0] += timedelta(days=100)
    await temp_rules.notify_due(manager)
    assert manager.send.await_count == 3
    with db._conn() as conn:
        assert tuple(conn.execute("SELECT attempts,quarantined FROM temp_rule_notice_retries").fetchone()) == (3, 1)


@pytest.mark.parametrize("kind,text", [("file_change", "file.py"), ("command_execution", "$ true")])
def test_successful_empty_tools_are_not_errors(kind, text):
    stream = HubActivityStream("r")
    events = stream.feed([{"itemId": "i", "runId": "r", "position": 1,
                           "type": kind, "text": text, "status": "completed"}])
    result = next(e for e in events if e.type == "tool_result")
    assert result.metadata["is_error"] is False


def test_artifact_classification_never_softens_security():
    assert hw.benign_artifact_rejection("huge.mp4", "exceeds per-file size limit")
    for why in ["contains a credential", "path escapes the workspace",
                "not a regular file (link or special)", "exceeds the size limit"]:
        assert not hw.benign_artifact_rejection("huge.mp4", why)


def test_media_import_checks_secrets_before_ignoring(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / ".gitignore").write_text("*.mp4\n")
    archive = tmp_path / "return.tar"
    with tarfile.open(archive, "w") as tar:
        tok = "synthetic-cred-" + ("9" * 24)
        for name, payload in [("ok.py", b"print(1)"), ("movie.mp4", b"media"),
                              ("secret.mp4", ("Bearer " + tok).encode())]:
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    result = hw.apply_changes(archive, root, {}, known=[tok])
    assert result.changed == ["ok.py"]
    assert ("movie.mp4", "gitignored media artifact") in result.rejected
    assert ("secret.mp4", "contains a credential") in result.rejected
    assert not (root / "movie.mp4").exists()


@pytest.mark.asyncio
async def test_archive_persists_metadata_before_delete_and_retries(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "STATE_DIR", tmp_path / "records")
    state = hw.WorkspaceState("hub-aaaaaaaaaaaaaaaa", "/repo", "/remote/hub-aaaaaaaaaaaaaaaa",
                              project_id="p", thread_id="t")
    state.save()
    ssh = SimpleNamespace(assert_file_policy=AsyncMock(), remove=AsyncMock(side_effect=[OSError("lost"), None]))
    calls = []
    async def call(name, args):
        calls.append(name)
        if name == "t3_thread_wait":
            return {"status": "idle", "timedOut": False}
        if name == "t3_project_delete":
            assert hw.WorkspaceState.load(state.ws_id).archived
            assert args == {"projectId": "p", "force": True}
        return {}
    mc = SimpleNamespace(tool_call=call)
    with pytest.raises(OSError):
        await hw.archive_workspace(state, ssh, mc)
    assert hw.WorkspaceState.load(state.ws_id).archived
    await hw.archive_workspace(state, ssh, mc)
    assert hw.WorkspaceState.load(state.ws_id).remote_released
    before = list(calls)
    await hw.archive_workspace(state, ssh, mc)
    assert calls == before
    assert state.path().exists()


@pytest.mark.asyncio
async def test_archive_never_deletes_pending_sync(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "STATE_DIR", tmp_path / "records")
    state = hw.WorkspaceState("hub-aaaaaaaaaaaaaaaa", "/repo", "/remote/hub-aaaaaaaaaaaaaaaa",
                              archived=True, pending_sync={"phase": "report"})
    state.save()
    mc = SimpleNamespace(tool_call=AsyncMock())
    with pytest.raises(hw.HubWorkspaceError, match="pending sync"):
        await hw.archive_workspace(state, SimpleNamespace(remove=AsyncMock()), mc)
    mc.tool_call.assert_not_awaited()


def test_turn_limits():
    assert runaway_guard.turn_limit_reason(80, 1, orchestrator=True) == ""
    assert runaway_guard.turn_limit_reason(249, 1, orchestrator=True) == ""
    assert runaway_guard.turn_limit_reason(250, 1, orchestrator=True) == "tool_limit"
    assert runaway_guard.turn_limit_reason(249, 1, orchestrator=False) == ""
    assert runaway_guard.turn_limit_reason(250, 1, orchestrator=False) == "tool_limit"
    assert runaway_guard.turn_limit_reason(0, 3600, orchestrator=False) == "wall_limit"


@pytest.mark.asyncio
async def test_cron_never_steers_overdue_orchestrator():
    session = AgentSession(id="x", name="x", scope="/repo", cwd="/repo", role="orchestrator",
                           model="gpt-6-luna", backend_type="codex", created_at=datetime.now(timezone.utc))
    session._turn_start = asyncio.get_running_loop().time() - 24000
    bg = MessageProvenance(origin="background_task", senders=("cron",), subtype="cron_command")
    owner = MessageProvenance(origin="user", senders=("user",), subtype="telegram")
    assert session._turns.turn_end_hold(bg) == ("hold", "")
    assert session._turns.turn_end_hold(owner) == (None, "")


@pytest.mark.asyncio
async def test_clean_handoff_excludes_failed_model_speech(isolated_db):
    session = AgentSession(id="clean", name="clean", scope=str(isolated_db), cwd=str(isolated_db),
                           model="gpt-6-luna", backend_type="codex", created_at=datetime.now(timezone.utc))
    from app.db import save_session, add_log
    save_session(session._to_db_dict())
    add_log(session.id, datetime.now(timezone.utc), "user_message", "Original task",
            provenance=MessageProvenance(origin="user", senders=("user",)))
    add_log(session.id, datetime.now(timezone.utc), "text", "failed model excuses and reasoning")
    add_log(session.id, datetime.now(timezone.utc), "tool_result", "pytest: 2 failed", tool_is_error=True)
    result = json.loads(await session._build_runtime_handoff(clean_handoff=True))
    assert result["original_task"] == "Original task"
    assert result["last_failure"] == "pytest: 2 failed"
    assert "excuses" not in json.dumps(result)
    assert set(result) == {"schema", "original_task", "last_failure", "branch", "status", "diff_stat"}


def test_swap_watch_cooldown_and_pressure():
    from scripts.swap_watch import check, GIB
    memory = {"SwapTotal": 16*GIB, "SwapFree": 4*GIB, "MemAvailable": 18*GIB}
    message, state = check(memory, {}, 100)
    assert message == ""
    memory["MemAvailable"] = 3*GIB
    message, state = check(memory, state, 101)
    assert "SWAPHIGH" in message
    assert check(memory, state, 102)[0] == ""
    assert "SWAPHIGH" in check(memory, state, 7302)[0]
    memory["MemAvailable"] = 18*GIB
    memory["SwapFree"] = GIB
    assert "SWAPHIGH" in check(memory, state, 7302)[0]


def test_error_watch_uses_day_index_and_ignores_noise(tmp_path):
    import sqlite3
    from app.error_watch import collect_db_events
    path = tmp_path / "events.db"
    with sqlite3.connect(path) as c:
        c.executescript("""
            CREATE TABLE sessions(id TEXT,scope TEXT,name TEXT);
            CREATE TABLE logs(ts TEXT,type TEXT,content TEXT,session_id TEXT,tool_name TEXT,tool_is_error INTEGER);
            CREATE INDEX idx_logs_day ON logs(date(ts));
            INSERT INTO sessions VALUES('s','/repo','worker');
        """)
        for content in ["applied", "(no output)", "real failure"]:
            c.execute("INSERT INTO logs VALUES(?,?,?,?,?,?)",
                      ("2026-11-11T12:00:00+00:00", "tool_result", content, "s", "Bash", 1))
        plan = c.execute("EXPLAIN QUERY PLAN SELECT * FROM logs l WHERE (l.tool_is_error=1 OR l.type='error') "
                         "AND l.ts>=? AND date(l.ts)>=substr(?,1,10)",
                         ("2026-11-11", "2026-11-11")).fetchall()
        assert any("USING INDEX idx_logs_day" in row[3] for row in plan)
    events = collect_db_events(path, datetime(2026,11,11,tzinfo=timezone.utc))
    assert [event["message"] for event in events] == ["real failure"]


@pytest.mark.asyncio
async def test_runaway_event_loop_enforces_worker_limit(monkeypatch, tmp_path):
    session = AgentSession(id="guard", name="guard", scope=str(tmp_path), cwd=str(tmp_path),
                           model="gpt-6-luna", backend_type="codex", created_at=datetime.now(timezone.utc))
    session.status = AgentStatus.RUNNING
    session._turn_start = asyncio.get_running_loop().time()
    session._persist = MagicMock()
    session._log = MagicMock()
    session._wake_durable_message_deliveries = MagicMock()
    session._handle_event = MagicMock()
    async def events():
        for _ in range(1000):
            yield AgentEvent("tool_use", "read")
    backend = SimpleNamespace(events=events)
    session._backend = backend
    async def checkpoint(*args, **kwargs):
        session.status = AgentStatus.IDLE
    session._checkpoint_runaway_turn = AsyncMock(side_effect=checkpoint)
    await session._turn_event_loop()
    assert session._handle_event.call_count == 250
    assert session._checkpoint_runaway_turn.await_args.args[1] == "tool_limit"


@pytest.mark.asyncio
async def test_runaway_interrupt_failure_disconnects_only_its_generation(tmp_path):
    session = AgentSession(id="guard", name="guard", scope=str(tmp_path), cwd=str(tmp_path),
                           model="gpt-6-luna", backend_type="codex", created_at=datetime.now(timezone.utc))
    session.status = AgentStatus.RUNNING
    backend = SimpleNamespace(interrupt=AsyncMock(return_value=False), disconnect=AsyncMock())
    session._backend = backend
    session._log = MagicMock()
    session._persist = MagicMock()
    session._spawn_bg = lambda coroutine: coroutine.close()
    session._finish_failed_running_turn = MagicMock()
    session._turns.cancel_auto_report = MagicMock()
    await session._checkpoint_runaway_turn(backend, "tool_limit", 250, 10, turn_gen=session._turn_gen - 1)
    backend.interrupt.assert_not_awaited()
    await session._checkpoint_runaway_turn(backend, "tool_limit", 250, 10, turn_gen=session._turn_gen)
    backend.interrupt.assert_awaited_once()
    backend.disconnect.assert_awaited_once()
    assert not session._manually_interrupted
    assert session._auto_continue_count == 1
    assert session._backend is None
    assert session.status == AgentStatus.IDLE
    session._finish_failed_running_turn.assert_not_called()


@pytest.mark.asyncio
async def test_codex_missing_rollout_starts_fresh_thread_with_handoff_flag(monkeypatch, tmp_path):
    from app import backend_codex as module
    from tests.test_backend_codex import _FakeProcess
    monkeypatch.delenv("ORCHESTRA_AGENT_CGROUP_REQUIRED", raising=False)
    monkeypatch.delenv("ORCHESTRA_AGENT_CGROUP", raising=False)
    monkeypatch.setattr(module, "_CODEX_HOME_ROOT", tmp_path / "codex")
    monkeypatch.setattr(module.RuntimeProcessGroup, "create", lambda **kwargs: (None, "unsupported"))
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", AsyncMock(return_value=_FakeProcess()))
    backend = module.CodexBackend(model="gpt-6-luna", cwd=str(tmp_path), resume_thread_id="thread-stale")
    backend._read_stdout = AsyncMock()
    backend._drain_stderr = AsyncMock()
    backend._notify = AsyncMock()
    backend._request = AsyncMock(side_effect=[{}, RuntimeError("no rollout found for thread id stale"),
                                              {"thread": {"id": "thread-fresh"}}])
    try:
        await backend.connect()
        assert backend.session_id == "thread-fresh"
        assert backend.resume_failed
        assert [c.args[0] for c in backend._request.await_args_list] == ["initialize", "thread/resume", "thread/start"]
        fresh_params = backend._request.await_args_list[-1].args[1]
        assert "threadId" not in fresh_params and "excludeTurns" not in fresh_params
    finally:
        await backend.disconnect()


def test_cleanup_plan_protects_live_and_real_projects():
    from scripts.cleanup_closed_hub_projects import plan_cleanup
    state = hw.WorkspaceState("hub-aaaaaaaaaaaaaaaa", "/repo", "/remote/hub-aaaaaaaaaaaaaaaa",
                              project_id="p", archived=True)
    project = {"id": "p", "title": state.ws_id, "workspaceRoot": state.remote_dir}
    live = {"id": "s", "name": "live", "status": "idle", "worktree_path": "/repo"}
    assert plan_cleanup([live], [state], [project], "/remote")[0]["reason"] == "live owner"
    assert plan_cleanup([], [state], [project], "/remote")[0]["action"] == "delete"
    assert plan_cleanup([], [state], [{**project, "title": "User real project"}], "/remote")[0]["action"] == "keep"
    assert plan_cleanup([], [state], [{**project, "workspaceRoot": "/elsewhere"}], "/remote")[0]["action"] == "keep"
    state.pending_sync = {"phase": "report"}
    assert plan_cleanup([], [state], [project], "/remote")[0]["reason"] == "pending sync"


def test_preflight_does_not_bulk_load_truncated_instructions(tmp_path):
    from app.prompting import codex_project_doc_preflight
    root = tmp_path / "repo"
    root.mkdir()
    (root / "AGENTS.md").write_text("instructions\n" * 10000)
    home = tmp_path / "codex"
    home.mkdir()
    (home / "config.toml").write_text("project_doc_max_bytes = 100\n")
    warning = codex_project_doc_preflight(str(root), codex_home=str(home))
    assert ".orchestra/kb/" in warning.instruction
    assert "through EOF once" not in warning.instruction
    assert len(warning.instruction) < 700


@pytest.mark.asyncio
async def test_clean_model_escalation_automatic_after_error(tmp_path):
    session = AgentSession(id="handoff", name="handoff", scope=str(tmp_path), cwd=str(tmp_path),
                           model="hub-gpt-6.1-sol", backend_type="hub", created_at=datetime.now(timezone.utc))
    session._last_turn_ok = False
    session._change_model_locked = AsyncMock(return_value={"ok": True})
    session._persist = MagicMock()
    result = await session.change_model("hub-gpt-6-astra")
    assert result["ok"]
    session._change_model_locked.assert_awaited_once_with("hub-gpt-6-astra", clean_handoff=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("security", [False, True])
async def test_sync_code_commit_artifact_warning_does_not_repeat(tmp_path, monkeypatch, caplog, security):
    import hashlib
    monkeypatch.setattr(hw, "STATE_DIR", tmp_path / "state")
    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text("print(1)")
    state = hw.WorkspaceState("hub-bbbbbbbbbbbbbbbb", str(root), "/remote/hub-bbbbbbbbbbbbbbbb",
                              manifest={"app.py": hashlib.sha256(b"print(1)").hexdigest()})
    backend = hub.HubBackend("hub-gpt-6.1-sol", str(root))
    backend._run_outbox = AsyncMock(return_value="")
    def git(root, *args):
        if args[0] == "rev-parse":
            return SimpleNamespace(returncode=0, stdout=b"abc123")
        return SimpleNamespace(returncode=1, stdout=b"")
    monkeypatch.setattr(hw, "_git_out", git)
    commit = MagicMock(return_value=("abc123", []))
    monkeypatch.setattr(hw, "commit_sync", commit)
    reason = "contains a credential" if security else "exceeds per-file size limit"
    pending = {"phase": "commit", "changed": ["app.py"], "deleted": [], "conflicts": [],
               "rejected": [("huge.mp4", reason)], "no_work": False, "provider_status": "completed",
               "entries": [], "done": [], "dropped": [], "has_outbox": False}
    for _ in range(2):
        state.pending_sync = dict(pending)
        await backend._finish_sync(SimpleNamespace(), state, root, tmp_path / "return.tar")
        assert bool(backend._sync_failure) == security
    assert commit.call_count == 2
    warnings = [record for record in caplog.records if "artifact excluded" in record.message]
    assert len(warnings) == (0 if security else 1)
    if not security:
        assert hw.WorkspaceState.load(state.ws_id).artifact_warnings == [["huge.mp4", reason]]


def test_hub_completion_reports_measured_characters_and_duration():
    import time
    backend = hub.HubBackend("hub-gpt-6.1-sol", "/repo")
    backend._turn_started = time.perf_counter() - 1
    backend._prompt_chars = 30
    backend._response_chars = 20
    backend._sync_changed_files = 2
    event = backend._turn_end(True, "end_turn", "")
    assert event.metadata["prompt_chars"] == 30
    assert event.metadata["response_chars"] == 20
    assert event.metadata["sync_changed_files"] == 2
    assert event.metadata["turn_duration_ms"] >= 1000
    assert event.usage.aggregate.accuracy == "unknown"
