"""Wave 11 regressions: Antigravity TG stream de-spam, MCP CLI scope binding, Kesha handoff."""
import asyncio
import json
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from app import acp_tg_delivery, db
from app.backend_antigravity import AntigravityBackend


class _FakeConn:
    def close(self):
        pass


@pytest.mark.asyncio
async def test_antigravity_stream_logs_uses_turnstate_and_drops_spam(monkeypatch, tmp_path):
    from app import tg_bridge as tb

    stream_spy = AsyncMock(side_effect=AssertionError("acp_tg_delivery.stream must not hijack stream_logs"))
    monkeypatch.setattr(acp_tg_delivery, "stream", stream_spy)

    sent_messages = []
    sent_files = []
    acp_once_calls = []

    async def tg_send_safe(chat_id, text, thread_id=None, entities=None, important=False, **kw):
        sent_messages.append({"chat_id": chat_id, "text": text, "thread_id": thread_id, "important": important})

    async def tg_send_file_safe(chat_id, path, caption, thread_id=None, **kw):
        sent_files.append({"path": path, "caption": caption, "thread_id": thread_id})

    async def acp_send_once(chat_id, text, *, message_thread_id, entities, reply_markup):
        acp_once_calls.append({"text": text, "thread_id": message_thread_id, "reply_markup": reply_markup})
        return SimpleNamespace(message_id=999)

    async def mirror_send(*args, **kwargs):
        return None

    async def edit_progress(turn, thread_id, orch_name, force=False):
        return None

    img = tmp_path / "shot.png"
    img.write_bytes(b"PNGDATA")

    logs = [
        {"id": 1, "type": "user_message", "content": "Сводка почты",
         "origin": "user", "origin_detail": {"senders": ["kesha"], "subtype": "kesha_handoff"}},
        {"id": 2, "type": "thinking", "content": "Let me inspect the repository carefully in English..."},
        {"id": 3, "type": "tool", "tool_name": "run_command", "tool_use_id": "t1",
         "content": 'run_command: {"CommandLine": "git status"}'},
        {"id": 4, "type": "tool_update", "tool_name": "run_command", "tool_use_id": "t1",
         "content": 'run_command: {"CommandLine": "git status -s"}'},
        {"id": 5, "type": "tool_result", "tool_name": "run_command", "tool_use_id": "t1",
         "content": '{"exit_code": 0, "output": "clean tree"}'},
        {"id": 6, "type": "tool", "tool_name": "read_file", "tool_use_id": "t2",
         "content": json.dumps({"Path": str(img)})},
        {"id": 7, "type": "tool_result", "tool_name": "read_file", "tool_use_id": "t2",
         "content": "{'type': 'image', 'data': 'abc'}"},
        {"id": 8, "type": "tool", "tool_name": "mcp_orchestra_0eaef74b_send_message", "tool_use_id": "t3",
         "content": json.dumps({"to": "codex-worker", "message": "Проверь билд"})},
        {"id": 9, "type": "tool_result", "tool_name": "mcp_orchestra_0eaef74b_send_message", "tool_use_id": "t3",
         "content": "Run mcp_orchestra_0eaef74b_send_message"},
        {"id": 10, "type": "tool", "tool_name": "mcp_mailru_mail_folders", "tool_use_id": "t4",
         "content": "{}"},
        {"id": 11, "type": "native_request", "content": json.dumps({
            "id": "req-1", "kind": "question", "title": "Выбери вариант",
            "options": [{"optionId": "o1", "name": "Да"}],
        })},
        {"id": 12, "type": "text", "content": "Готово, сводка обработана."},
        {"id": 13, "type": "status", "content": "turn ended (end_turn, 1 turn, $0.00 turn)"},
    ]

    calls = 0
    log_reads = 0

    def get_logs(session_id, after_id=0, conn=None):
        nonlocal log_reads
        log_reads += 1
        if log_reads == 1:
            return []
        return [x for x in logs if x["id"] > after_id]

    async def sleep_once(_sec):
        nonlocal calls
        calls += 1
        if calls >= 1:
            raise asyncio.CancelledError

    updates = []

    async def fake_update_progress(turn, thread_id, orch_name, force=False):
        if turn.block:
            updates.append((force, tb._progress_text(turn.lines(), len(turn.actions), 1.0)))

    monkeypatch.setattr(tb, "config", {"group_id": -100, "topics": {"seedon": 55}})
    monkeypatch.setattr(tb, "TG_USER_MENTION", "")
    monkeypatch.setattr("app.db.get_all_sessions", lambda: [
        {"name": "seedon", "scope": "/home/kesha/projects/seedon", "role": "orchestrator"},
    ])
    monkeypatch.setattr("app.db.get_session_by_name", lambda name, scope: {
        "id": "sid-agy", "name": "seedon", "scope": scope,
        "backend_type": "antigravity", "model": "antigravity/gemini-4-hydrogen",
    })
    monkeypatch.setattr("app.db.get_logs", get_logs)
    monkeypatch.setattr("app.db._conn", _FakeConn)
    monkeypatch.setattr(tb, "_schedule_topic_status", lambda *a: None)
    monkeypatch.setattr(tb, "_any_running_in_scope", lambda scope: False)
    monkeypatch.setattr(tb, "_tg_send_safe", tg_send_safe)
    monkeypatch.setattr(tb, "_tg_send_file_safe", tg_send_file_safe)
    monkeypatch.setattr(tb, "_acp_send_once", acp_send_once)
    monkeypatch.setattr(tb, "_mirror_send", mirror_send)
    monkeypatch.setattr(tb, "_update_progress", fake_update_progress)
    monkeypatch.setattr(tb.asyncio, "sleep", sleep_once)

    with pytest.raises(asyncio.CancelledError):
        await tb.stream_logs("seedon", 55)

    stream_spy.assert_not_awaited()
    joined = "\n".join(m["text"] for m in sent_messages)
    assert "🦜 kesha → seedon" in joined
    assert "Сводка почты" in joined
    assert "✉️ → codex-worker" in joined
    assert "💬\nГотово, сводка обработана." in joined
    # Zero spam:
    assert "Let me inspect the repository carefully" not in joined
    assert "Аргументы:" not in joined
    assert "Результат:" not in joined
    assert '"exit_code"' not in joined
    assert "Run mcp_orchestra_0eaef74b_send_message" not in joined
    # Progress block shows clean icons and updated command:
    prog_all = "\n".join(txt for _, txt in updates)
    assert "🖥 git status -s" in prog_all
    assert "📖 " in prog_all and "shot.png" in prog_all
    assert "📧 mail_folders" in prog_all
    # Photo preview sent for read_file image:
    assert len(sent_files) == 1 and sent_files[0]["path"] == str(img)
    # Native request rendered with acpn: buttons:
    assert len(acp_once_calls) == 1
    assert "Вопрос агента" in acp_once_calls[0]["text"]
    cb = acp_once_calls[0]["reply_markup"].inline_keyboard[0][0].callback_data
    assert cb.startswith("acpn:req-1:")


def test_tg_tool_helpers_for_acp_and_mcp_names():
    from app import tg_bridge as tb

    assert tb._tg_tool_icon("run_command") == "🖥"
    assert tb._tg_tool_icon("read_file") == "📖"
    assert tb._tg_tool_icon("view_file") == "📖"
    assert tb._tg_tool_icon("edit_file") == "✏️"
    assert tb._tg_tool_icon("write_file") == "✏️"
    assert tb._tg_tool_icon("grep_search") == "🔎"
    assert tb._tg_tool_icon("find_by_name") == "🔎"
    assert tb._tg_tool_icon("mcp_orchestra_0eaef74b_send_message") == "🎼"
    assert tb._tg_tool_icon("mcp_mailru_mail_folders") == "📧"
    assert tb._tg_tool_icon("mcp_gmail_send_gmail_message") == "📧"
    assert tb._tg_tool_icon("mcp_ozon_search") == "🛒"
    assert tb._tg_tool_icon("mcp_gpb_limits") == "🏦"
    assert tb._tg_tool_icon("mcp_hub-images_gen") == "🖼"
    assert tb._tg_tool_short("mcp_orchestra_0eaef74b_send_message") == "send_message"
    assert tb._tg_tool_short("mcp_mailru_mail_folders") == "mail_folders"
    assert tb._tool_target("read_file", '{"Path": "/home/kesha/seedon/STATE.md"}') == "/home/kesha/seedon/STATE.md"
    assert tb._tool_target("run_command", '{"CommandLine": "pytest -q"}') == "pytest -q"


def test_acp_tg_delivery_format_log_suppresses_thinking_update_result(monkeypatch):
    from app import tg_bridge as tb
    for kind in ("thinking", "tool_update", "tool_result"):
        assert acp_tg_delivery.format_log({"type": kind, "content": "noisy dump"}, tb) == []


def test_parallel_acp_sessions_register_distinct_orchestra_mcp_names(tmp_path):
    from app.acp_tools import canonical_name

    def server_for(session_id, project, agent, *, resume_session_id=None):
        backend = AntigravityBackend(SimpleNamespace(
            model="antigravity/gemini-4-neon-medium",
            cwd=str(tmp_path / project),
            system_prompt="",
            context_limit=100000,
            resume_session_id=resume_session_id,
            profile="",
            mcp_servers={"orchestra": {
                "command": "python3",
                "args": ["-m", "app.mcp_stdio"],
                "env": {
                    "ORCHESTRA_SESSION_ID": session_id,
                    "ORCHESTRA_SCOPE": str(tmp_path / project),
                    "WORKER_NAME": agent,
                },
            }},
        ))
        backend.app_session_id = session_id
        return backend._acp_mcp_servers()[0]

    first = server_for("first-app-session", "first-project", "first-agent")
    second = server_for("second-app-session", "second-project", "second-agent")
    resumed = server_for("first-app-session", "first-project", "first-agent", resume_session_id="native-id")

    assert first["name"] != second["name"]
    assert resumed == first
    for server, session_id in ((first, "first-app-session"), (second, "second-app-session")):
        assert server["args"][-2:] == ["--session-id", session_id]
        assert canonical_name({"rawInput": {"ServerName": server["name"], "ToolName": "send_files"}}) == (
            "mcp__orchestra__send_files"
        )


def test_acp_mcp_servers_injects_cli_flags_and_mcp_stdio_parses_them(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "be.db")
    db.init_db()
    backend = AntigravityBackend(SimpleNamespace(
        model="antigravity/gemini-4-neon-high",
        cwd=str(tmp_path),
        system_prompt="",
        context_limit=100000,
        resume_session_id="",
        profile="personal",
        mcp_servers={
            "orchestra": {
                "command": "python3",
                "args": ["-m", "app.mcp_stdio"],
                "env": {
                    "ORCHESTRA_SCOPE": "/home/kesha/projects/seedon",
                    "WORKER_NAME": "seedon-orchestrator",
                    "ORCHESTRA_SESSION_ID": "sid-123",
                },
            },
            "mailru": {
                "command": "python3",
                "args": ["-m", "mailru"],
                "env": {},
            },
        },
    ))
    servers = {s["name"]: s for s in backend._acp_mcp_servers()}
    orch_args = servers["orchestra"]["args"]
    assert "--scope" in orch_args and "/home/kesha/projects/seedon" in orch_args
    assert "--sender" in orch_args and "seedon-orchestrator" in orch_args
    assert "--session-id" in orch_args and "sid-123" in orch_args
    assert "--scope" not in servers["mailru"]["args"]

    # When env has no ORCHESTRA_* keys, args must remain untouched (preflight test compatibility)
    plain = AntigravityBackend(SimpleNamespace(
        model="antigravity/gemini-4-neon-high",
        cwd=str(tmp_path),
        system_prompt="",
        context_limit=100000,
        resume_session_id="",
        profile="personal",
        mcp_servers={"orchestra": {"command": "python3", "args": ["-m", "app.mcp_stdio"], "env": {}}},
    ))
    plain_args = plain._acp_mcp_servers()[0]["args"]
    assert plain_args[-2:] == ["-m", "app.mcp_stdio"]

    # Reload app.mcp_stdio in-process to verify CLI flags override env vars
    import importlib
    import os
    import app.mcp_stdio as mcp_stdio_mod

    orig_argv = list(sys.argv)
    orig_env = dict(os.environ)
    try:
        sys.argv = [
            "app.mcp_stdio",
            "--scope", "/cli/scope",
            "--sender", "cli-orch",
            "--session-id", "cli-sid-9",
        ]
        os.environ["ORCHESTRA_SCOPE"] = "/env/scope"
        os.environ["WORKER_NAME"] = "env-worker"
        importlib.reload(mcp_stdio_mod)
        assert mcp_stdio_mod.SCOPE == "/cli/scope"
        assert mcp_stdio_mod.WORKER_NAME == "cli-orch"
        assert mcp_stdio_mod.SESSION_ID == "cli-sid-9"
    finally:
        sys.argv = orig_argv
        os.environ.clear()
        os.environ.update(orig_env)
        importlib.reload(mcp_stdio_mod)


@pytest.mark.asyncio
async def test_kesha_handoff_admission_and_cron_still_blocked(monkeypatch, tmp_path):
    from app import deps
    from app.routes import sessions
    from app.session import AgentSession

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "wave11.db")
    db.init_db()
    monkeypatch.setenv("INTERNAL_TOKEN", "test-internal-secret")
    monkeypatch.setattr("app.auth.validate_session", lambda _v: False)

    received = []

    class FakeManager:
        def __init__(self):
            self.sessions = {}
            self.locks = {}

        def get_by_name(self, name, scope):
            return self.sessions.get((name, scope))

        def get_session_lock(self, sid):
            return self.locks.setdefault(sid, asyncio.Lock())

        async def ensure_loaded(self, name, scope):
            return self.sessions.get((name, scope))

        async def ensure_loaded_any(self, name):
            for s in self.sessions.values():
                if s.name == name:
                    return s
            return None

        async def send(self, session_id, message, provenance=None, **_kw):
            sess = next((s for s in self.sessions.values() if s.id == session_id), None)
            received.append((sess.name if sess else session_id, message, provenance))

    orch = AgentSession(
        id="orch-agy-1", name="seedon-orchestrator", scope=str(tmp_path), cwd=str(tmp_path),
        model="antigravity/gemini-4-neon-high", backend_type="antigravity", is_orchestrator=True, mcp_servers={},
    )
    wrk = AgentSession(
        id="wrk-agy-1", name="worker-1", scope=str(tmp_path), cwd=str(tmp_path),
        model="antigravity/gemini-4-neon-high", backend_type="antigravity", is_orchestrator=False, mcp_servers={},
    )
    orch._persist()
    wrk._persist()

    mgr = FakeManager()
    mgr.sessions[(orch.name, orch.scope)] = orch
    mgr.sessions[(wrk.name, wrk.scope)] = wrk
    monkeypatch.setattr(deps, "manager", mgr)
    monkeypatch.setattr(sessions, "manager", mgr)

    @asynccontextmanager
    async def lifespan(_app):
        yield

    app = FastAPI(lifespan=lifespan)
    app.include_router(sessions.router)

    headers_ok = {"Authorization": "Bearer test-internal-secret"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 51234)),
        base_url="http://127.0.0.1",
        trust_env=False,
    ) as client:
        # 1. Valid Kesha handoff via channel="kesha" -> 200 & provenance kesha_handoff
        r1 = await client.post(
            "/api/sessions/seedon-orchestrator/send",
            headers=headers_ok,
            json={"scope": str(tmp_path), "message": "Утренняя почта", "channel": "kesha"},
        )
        assert r1.status_code == 200, r1.text
        assert r1.json()["ok"] is True
        assert received[-1][0] == "seedon-orchestrator"
        assert received[-1][2].origin == "user"
        assert received[-1][2].senders == ("kesha",)
        assert received[-1][2].subtype == "kesha_handoff"

        # 2. Valid via X-Orchestra-Kesha-Handoff header or [от Кеши] prefix -> 200
        r2 = await client.post(
            "/api/sessions/seedon-orchestrator/send",
            headers={**headers_ok, "X-Orchestra-Kesha-Handoff": "1"},
            json={"scope": str(tmp_path), "message": "Дайджест 2"},
        )
        assert r2.status_code == 200
        r3 = await client.post(
            "/api/sessions/seedon-orchestrator/send",
            headers=headers_ok,
            json={"scope": str(tmp_path), "message": "[от Кеши] Дайджест 3"},
        )
        assert r3.status_code == 200

        # 3. Ordinary cron/script with INTERNAL_TOKEN WITHOUT kesha signal -> STILL 403!
        r_cron = await client.post(
            "/api/sessions/seedon-orchestrator/send",
            headers=headers_ok,
            json={"scope": str(tmp_path), "message": "cron ping"},
        )
        assert r_cron.status_code == 403

        # 4. Spoofed proxy header (non-loopback) -> 403
        r_fwd = await client.post(
            "/api/sessions/seedon-orchestrator/send",
            headers={**headers_ok, "X-Forwarded-For": "203.0.113.5"},
            json={"scope": str(tmp_path), "message": "spoof", "channel": "kesha"},
        )
        assert r_fwd.status_code == 403

        # 5. Wrong INTERNAL_TOKEN -> 403
        r_bad = await client.post(
            "/api/sessions/seedon-orchestrator/send",
            headers={"Authorization": "Bearer wrong-token"},
            json={"scope": str(tmp_path), "message": "spoof", "channel": "kesha"},
        )
        assert r_bad.status_code == 403

        # 6. Targeting a regular worker instead of orchestrator -> 403
        r_wrk = await client.post(
            "/api/sessions/worker-1/send",
            headers=headers_ok,
            json={"scope": str(tmp_path), "message": "direct worker", "channel": "kesha"},
        )
        assert r_wrk.status_code == 403
