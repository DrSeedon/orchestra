"""V-643: агентный аудит сводки компакта.

Настоящий CLI провайдера не запускается: вместо `claude` в PATH кладётся sh-заглушка,
поэтому проверяется весь путь процесса — запуск, JSON-ответ, таймаут, убийство группы,
удаление песочницы. Схема hybrid: свежий черновик отдельным проходом без инструментов,
затем AUDIT и FINAL. Главное свойство: любой сбой оставляет сводку из контекста.
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app import agentic_compact, db

DRAFT = "TASK STATE\n- исходная сводка сессии"
STUB = """#!/bin/sh
PROMPT=$(cat)
echo "$PWD" >> "$STUB_LOG"
case "$PROMPT" in
  *"=== TRANSCRIPT ==="*)
    [ "$STUB_MODE" = draftfail ] && { echo 'draft boom' >&2; exit 1; }
    echo '{"type":"result","is_error":false,"total_cost_usd":0.25,"result":"FRESH DRAFT"}'
    exit 0 ;;
esac
case "$STUB_MODE" in
  ok) { printf 'AUDITED SUMMARY\n'; cat summary.md; } > s.tmp && mv s.tmp summary.md
      echo '{"type":"result","is_error":false,"total_cost_usd":0.25,"result":"done"}' ;;
  fail) echo 'boom from cli' >&2; exit 1 ;;
  sleep) sleep 30 ;;
  empty) : > summary.md
      echo '{"type":"result","is_error":false,"total_cost_usd":0.1,"result":"done"}' ;;
  long) head -c 30000 /dev/zero | tr '\\0' 'a' > summary.md
      echo '{"type":"result","is_error":false,"total_cost_usd":0.1,"result":"done"}' ;;
esac
"""


@pytest.fixture
def stub_cli(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "claude"
    stub.write_text(STUB)
    stub.chmod(0o755)
    log = tmp_path / "stub.log"
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    monkeypatch.setenv("STUB_LOG", str(log))
    monkeypatch.setenv("AGENTIC_COMPACT_ENABLED", "1")
    monkeypatch.delenv("ORCHESTRA_AGENT_UID", raising=False)
    return log


@pytest.fixture
def journal():
    """Сессия с прежней преамбулой компакта и работой после неё."""
    db.init_db()
    db.save_session({
        "id": "s-643", "name": "w643", "scope": "/t", "cwd": "/t", "model": "m",
        "system_prompt": "", "status": "idle", "session_id": None, "cost_usd": 0.0,
        "worktree_path": "", "branch": "", "base_branch": "main", "needs_switch": 0,
        "is_orchestrator": False, "color": "", "role": "worker", "parent_id": "",
        "parent_name": "", "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    })
    from app.events import MessageProvenance

    now = datetime.now(timezone.utc)
    user = MessageProvenance(origin="user", senders=("owner",))
    db.add_log("s-643", now, "user_message", "старое задание до прежнего компакта", provenance=user)
    db.add_log("s-643", now, "user_message", "[PREVIOUS CONTEXT SUMMARY — context was compacted]\n\nold",
               provenance=MessageProvenance(origin="platform", senders=("Orchestra",), subtype="compact"))
    db.add_log("s-643", now, "user_message", "владелец: коммит abc123, не пушить", provenance=user)
    db.add_log("s-643", now, "tool", "{\"cmd\": \"ls\"}", tool_name="Bash")
    db.add_log("s-643", now, "tool_result", "x" * 10_000)
    db.add_log("s-643", now, "text", "сделал, жду решения")
    return "s-643"


def _audit(monkeypatch, mode, **env):
    monkeypatch.setenv("STUB_MODE", mode)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return asyncio.run(agentic_compact.audit_summary(
        session_id="s-643", model="m", draft=DRAFT, draft_prompt="COMPACT PROMPT"))


def _sandboxes():
    root = agentic_compact.sandbox_root()
    return list(root.iterdir()) if root.exists() else []


def test_success_audits_fresh_draft_and_removes_sandbox(stub_cli, journal, monkeypatch):
    result = _audit(monkeypatch, "ok")
    assert result.applied is True
    # аудит работал по свежему черновику, а не по сводке из контекста
    assert result.summary.startswith("AUDITED SUMMARY") and "FRESH DRAFT" in result.summary
    assert DRAFT not in result.summary
    assert result.cost == pytest.approx(0.75)  # черновик + AUDIT + FINAL по 0.25
    assert len(stub_cli.read_text().splitlines()) == 3
    assert _sandboxes() == []


def test_segment_starts_at_last_compact_preamble(journal):
    rows = db.get_compact_segment(journal)
    assert rows[0]["content"].startswith("[PREVIOUS CONTEXT SUMMARY")
    assert all("старое задание" not in r["content"] for r in rows)
    assert len(next(r for r in rows if r["type"] == "tool_result")["content"]) == 4000


@pytest.mark.parametrize("mode,env,reason", [
    ("draftfail", {}, "draft boom"),
    ("fail", {}, "boom from cli"),
    ("sleep", {"AGENTIC_COMPACT_TIMEOUT": "2"}, "timeout"),
    ("empty", {}, "empty summary"),
    ("long", {}, "too long"),
])
def test_failure_keeps_original_summary(stub_cli, journal, monkeypatch, mode, env, reason):
    result = _audit(monkeypatch, mode, **env)
    assert result.applied is False
    assert result.summary == DRAFT
    assert reason in result.reason
    assert _sandboxes() == []


def test_disabled_never_starts_cli(stub_cli, journal, monkeypatch):
    result = _audit(monkeypatch, "ok", AGENTIC_COMPACT_ENABLED="0")
    assert result.applied is False and result.summary == DRAFT
    assert not stub_cli.exists()


# ---- compact(): сводка в преамбуле, строка в журнале, цена в cost сессии ----

class _Backend:
    def __init__(self):
        self.sent = []
        self._turns = 0

    async def connect(self): pass
    async def disconnect(self): pass
    async def interrupt(self): pass

    async def send(self, msg):
        self.sent.append(msg)

    async def events(self):
        from app.events import AgentEvent
        self._turns += 1
        if self._turns == 1:
            yield AgentEvent(type="text", content=DRAFT)
        yield AgentEvent(type="turn_end", metadata={
            "ok": True, "stop_reason": "end_turn", "num_turns": 1, "session_id": "fresh",
        })


def _compact(tmp_path, monkeypatch, mode):
    from app.session import AgentSession

    monkeypatch.setenv("STUB_MODE", mode)
    monkeypatch.setattr("app.session.save_session", MagicMock())
    monkeypatch.setattr("app.session.add_log", MagicMock(return_value=1))
    monkeypatch.setattr("app.session.get_logs", lambda *a, **k: [])
    monkeypatch.setattr("app.bg_jobs.bg_manager", None)
    monkeypatch.setattr("app.session._claude_subscription_limit_active", lambda: False)
    session = AgentSession(
        id="s-643", name="w643", scope="/t", cwd=str(tmp_path), model="claude-opus-5[1m]",
        system_prompt="t", created_at=datetime.now(timezone.utc),
    )
    backend = _Backend()
    logged = []
    session._log = lambda t, c, **kw: logged.append((t, c))

    async def fake_ensure_backend(force_fresh=False):
        session._backend = backend
        if session._compact_ack_event:
            event = session._compact_ack_event
            asyncio.get_running_loop().call_later(0.02, event.set)
        return backend

    async def run():
        with patch.object(session, "_make_backend", return_value=backend), \
             patch.object(session, "_ensure_backend", side_effect=fake_ensure_backend):
            return await session.compact()

    result = asyncio.run(run())
    preamble = next(m for m in backend.sent if "Acknowledge briefly." in m)
    return session, result, preamble, logged


def test_compact_uses_audited_summary_and_counts_cost(stub_cli, journal, tmp_path, monkeypatch):
    session, result, preamble, logged = _compact(tmp_path, monkeypatch, "ok")
    assert result["ok"] is True
    assert "AUDITED SUMMARY" in preamble and "FRESH DRAFT" in preamble
    assert "исходная сводка" not in preamble
    assert session.cost_usd == pytest.approx(0.75)
    assert any(t == "status" and c.startswith("agentic compact audit:") for t, c in logged)
    replaced = [c for t, c in logged if c.startswith("agentic compact context summary")]
    assert replaced and DRAFT in replaced[0]


def test_compact_falls_back_to_original_summary_on_audit_error(stub_cli, journal, tmp_path, monkeypatch):
    session, result, preamble, logged = _compact(tmp_path, monkeypatch, "fail")
    assert result["ok"] is True
    assert DRAFT in preamble
    skipped = [c for t, c in logged if c.startswith("agentic compact audit skipped")]
    assert skipped and "boom from cli" in skipped[0]
