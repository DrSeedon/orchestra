"""Core contract for in-session Claude compaction passes (V-650)."""

import asyncio
import json
import re
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app import agentic_compact

DRAFT = "TASK STATE\n- draft summary"
FINAL = "TASK STATE\n- FINAL summary"


def test_prepare_journal_writes_python_grep_source(tmp_path, monkeypatch):
    rows = [{
        "id": 7, "ts": "2026-09-28T10:00:00Z", "type": "user_message",
        "content": "do not push commit abc123", "tool_name": None, "tool_is_error": False,
    }]
    monkeypatch.setattr("app.agentic_compact.db.get_compact_segment", lambda session_id: rows)

    journal = asyncio.run(agentic_compact.prepare_journal("s-650", tmp_path / "audit"))

    assert (journal / "INDEX.md").is_file()
    assert "USER:" in (journal / "chunk_001.md").read_text()
    event = json.loads((journal / "journal.jsonl").read_text())
    assert event["content"] == rows[0]["content"] and event["id"] == 7


def test_sandbox_root_is_next_to_database(tmp_path, monkeypatch):
    monkeypatch.setattr(agentic_compact.db, "DB_PATH", tmp_path / "data" / "orchestra.db")

    assert agentic_compact.sandbox_root() == tmp_path / "data" / "compact-sandbox"


class _Backend:
    def __init__(self, root, *, mode="ok", on_audit_end=None):
        self.root = root
        self.mode = mode
        self.on_audit_end = on_audit_end
        self.sent = []
        self.event_streams = 0
        self.disconnected = False

    async def connect(self):
        pass

    async def disconnect(self):
        self.disconnected = True

    async def interrupt(self):
        pass

    async def send(self, message):
        self.sent.append(message)

    async def events(self):
        from app.events import AgentEvent

        self.event_streams += 1
        next_prompt = max(0, len(self.sent) - 1)
        while next_prompt < len(self.sent):
            prompt = self.sent[next_prompt]
            next_prompt += 1
            if "[SYSTEM: Context compaction requested" in prompt:
                yield AgentEvent(type="tool", content="Read: {\"path\":\"journal\"}", metadata={
                    "tool_use_id": "draft-read", "tool_name": "Read",
                })
                yield AgentEvent(type="tool_result", content="draft journal excerpt", metadata={
                    "tool_use_id": "draft-read", "tool_name": "Read",
                })
                yield AgentEvent(type="text", content=DRAFT)
                yield AgentEvent(type="turn_end", metadata={
                    "ok": True, "stop_reason": "end_turn", "num_turns": 1,
                    "session_id": "same-session", "cost_usd": 0.1,
                })
            elif "pass 1 — AUDIT" in prompt:
                if self.mode == "fail":
                    yield AgentEvent(type="error", content="audit exploded")
                    return
                if self.mode in ("limit_warning", "limit_rejected"):
                    status = "allowed_warning" if self.mode == "limit_warning" else "rejected"
                    yield AgentEvent(type="provider_limit", metadata={
                        "status": status, "rate_limit_type": "seven_day",
                    })
                if self.on_audit_end:
                    self.on_audit_end()
                yield AgentEvent(type="tool", content="Grep: {\"pattern\":\"omission\"}", metadata={
                    "tool_use_id": "audit-grep", "tool_name": "Grep",
                })
                yield AgentEvent(type="tool_result", content="audit findings", metadata={
                    "tool_use_id": "audit-grep", "tool_name": "Grep",
                })
                yield AgentEvent(type="text", content="AUDIT INTERNAL TEXT")
                yield AgentEvent(type="turn_end", metadata={
                    "ok": True, "stop_reason": "end_turn", "num_turns": 1,
                    "session_id": "same-session", "cost_usd": 0.3,
                })
            elif "last pass — FINALIZE" in prompt:
                match = re.search(r"journal is in (.+?): INDEX", prompt)
                assert match
                final = "" if self.mode == "empty" else "x" * 30 if self.mode == "long" else FINAL
                (self.root / match.group(1)).parent.joinpath("summary.md").write_text(final)
                yield AgentEvent(type="tool", content="Edit: summary.md", metadata={
                    "tool_use_id": "final-edit", "tool_name": "Edit",
                })
                yield AgentEvent(type="tool_result", content="summary written", metadata={
                    "tool_use_id": "final-edit", "tool_name": "Edit",
                })
                yield AgentEvent(type="text", content="FINAL INTERNAL TEXT")
                yield AgentEvent(type="turn_end", metadata={
                    "ok": True, "stop_reason": "end_turn", "num_turns": 1,
                    "session_id": "same-session", "cost_usd": 0.6,
                })
            else:
                raise AssertionError(f"unexpected backend prompt: {prompt[:100]}")


def _compact(tmp_path, monkeypatch, *, mode="ok", enabled="1", stop_between=False):
    from app.session import AgentSession

    monkeypatch.setenv("AGENTIC_COMPACT_ENABLED", enabled)
    monkeypatch.setenv("AGENTIC_COMPACT_TIMEOUT", "0" if mode == "timeout" else "5")
    monkeypatch.setenv("AGENTIC_COMPACT_MAX_CHARS", "10" if mode == "long" else "25000")
    monkeypatch.setattr("app.session.save_session", MagicMock())
    monkeypatch.setattr("app.session._claude_subscription_limit_active", lambda: False)
    monkeypatch.setattr("app.session._preserved_tail", lambda *a, **k: "")
    monkeypatch.setattr("app.session.add_log", MagicMock(return_value=1))
    monkeypatch.setattr("app.bg_jobs.bg_manager", None)
    audit_root = tmp_path / "data" / "compact-sandbox"
    monkeypatch.setattr(agentic_compact, "sandbox_root", lambda: audit_root)
    logs = []
    session = AgentSession(
        id="s-650", name="w650", scope=str(tmp_path), cwd=str(tmp_path),
        model="claude-opus-5[1m]", system_prompt="role",
        created_at=datetime.now(timezone.utc),
    )
    compact_events = []
    def capture_log(kind, content, **kwargs):
        logs.append((kind, content))
        if kind == "compact_event":
            compact_events.append({**json.loads(content), "event_id": kwargs.get("event_id"),
                                   "tool_use_id": kwargs.get("tool_use_id")})
    session._log = capture_log
    session._compact_log_events = compact_events
    session._persist = lambda: None
    session._drain_persist = lambda: asyncio.sleep(0)
    session._wake_durable_message_deliveries = lambda: None
    backend = _Backend(
        tmp_path, mode=mode,
        on_audit_end=(lambda: setattr(session, "_turn_start_cancel_gen", 1))
        if stop_between else None,
    )

    async def prepare_journal(session_id, directory):
        journal = directory / "journal"
        journal.mkdir()
        return journal

    monkeypatch.setattr(agentic_compact, "prepare_journal", prepare_journal)

    async def ensure_backend(force_fresh=False):
        session._backend = backend
        if session._compact_ack_event:
            asyncio.get_running_loop().call_soon(session._compact_ack_event.set)
        return backend

    async def run():
        with patch.object(session, "_make_backend", return_value=backend), \
             patch.object(session, "_ensure_backend", side_effect=ensure_backend):
            return await session.compact()

    result = asyncio.run(run())
    ack = next((prompt for prompt in backend.sent if "Acknowledge briefly." in prompt), "")
    return session, result, backend, logs, ack


def test_final_replaces_draft_in_ack_and_pass_cost_is_accounted(tmp_path, monkeypatch):
    session, result, backend, logs, ack = _compact(tmp_path, monkeypatch)

    assert result["ok"] is True
    assert len([p for p in backend.sent if "pass 1 — AUDIT" in p]) == 1
    assert len([p for p in backend.sent if "last pass — FINALIZE" in p]) == 1
    assert "FINAL summary" in ack and "draft summary" not in ack
    assert backend.event_streams == 2  # draft stream plus one stream shared by AUDIT and FINAL
    assert session.cost_usd == 0.6
    assert any(content.startswith("agentic compact context summary (replaced):") for _, content in logs)
    assert any(f"summary {len(DRAFT)} → {len(FINAL)} chars" in content for _, content in logs)
    assert not any(kind == "text" and "FINAL summary" in content for kind, content in logs)
    assert not any(kind == "text" and "INTERNAL TEXT" in content for kind, content in logs)
    assert not any(kind in {"tool", "tool_result"} for kind, _ in logs)
    compact_rows = session._compact_log_events
    assert {row.get("phase") for row in compact_rows if row.get("action") == "tool"} == {
        "draft", "audit", "final",
    }
    tool_rows = [row for row in compact_rows if row.get("action") == "tool"]
    assert len(tool_rows) == 6
    assert all(row["event_id"] == compact_rows[0]["event_id"] for row in compact_rows)
    assert {row["tool_use_id"] for row in tool_rows} == {
        "draft-read", "audit-grep", "final-edit",
    }
    assert next(row for row in compact_rows if row.get("action") == "finish")["status"] == "complete"
    audit_root = tmp_path / "data" / "compact-sandbox"
    assert str(audit_root) in next(p for p in backend.sent if "pass 1 — AUDIT" in p)
    assert list(audit_root.iterdir()) == []


def test_audit_failure_uses_draft_and_logs_reason(tmp_path, monkeypatch):
    session, result, backend, logs, ack = _compact(tmp_path, monkeypatch, mode="fail")

    assert result["ok"] is True
    assert "draft summary" in ack and "FINAL summary" not in ack
    assert not any("last pass — FINALIZE" in prompt for prompt in backend.sent)
    assert any("agentic compact audit skipped" in content and "audit exploded" in content
               for _, content in logs)
    assert list((tmp_path / "data" / "compact-sandbox").iterdir()) == []


def test_timeout_empty_and_oversized_final_fall_back_to_draft(tmp_path, monkeypatch):
    for mode, reason in (("timeout", "timeout"), ("empty", "empty summary"), ("long", "too long")):
        case_dir = tmp_path / mode
        case_dir.mkdir()
        _, result, _, logs, ack = _compact(case_dir, monkeypatch, mode=mode)
        assert result["ok"] is True
        assert "draft summary" in ack and "FINAL summary" not in ack
        assert any("agentic compact audit skipped" in content and reason in content
                   for _, content in logs)


def test_stop_after_audit_prevents_final_and_aborts_compaction(tmp_path, monkeypatch):
    _, result, backend, logs, ack = _compact(
        tmp_path, monkeypatch, stop_between=True,
    )

    assert result["ok"] is False and result["error"] == "compaction cancelled by stop"
    assert not any("last pass — FINALIZE" in prompt for prompt in backend.sent)
    assert ack == ""
    assert any("stopped" in content for _, content in logs)


def test_switch_off_uses_native_draft_without_agentic_passes(tmp_path, monkeypatch):
    session, result, backend, logs, ack = _compact(
        tmp_path, monkeypatch, enabled="0",
    )

    assert result["ok"] is True
    assert "draft summary" in ack
    assert not any("pass 1 — AUDIT" in prompt or "last pass — FINALIZE" in prompt
                   for prompt in backend.sent)
    assert session.cost_usd == 0.1


def test_limit_warning_during_audit_keeps_final_but_rejection_falls_back(tmp_path, monkeypatch):
    # The weekly-limit warning arrives on every turn above 75%; only a rejection stops the passes.
    _session, result, _backend, _logs, ack = _compact(tmp_path / "warn", monkeypatch, mode="limit_warning")
    assert result["ok"] is True
    assert "FINAL summary" in ack

    _session, result, _backend, logs, ack = _compact(tmp_path / "rej", monkeypatch, mode="limit_rejected")
    assert "draft summary" in ack and "FINAL summary" not in ack
    assert any("provider limit during compact audit" in content for _, content in logs)
