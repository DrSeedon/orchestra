import pytest
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock
from app.runtime_history import build_runtime_state_packet, classify_handoff_effects
from app.events import MessageProvenance

@pytest.fixture
def session(monkeypatch):
    from app.session import AgentSession

    monkeypatch.setattr("app.session.save_session", MagicMock())
    monkeypatch.setattr("app.session.add_log", MagicMock(return_value=1))
    monkeypatch.setattr("app.bg_jobs.bg_manager", None)
    return AgentSession(
        id="handoff-effects", name="effects-canary", scope="/test", cwd="/tmp",
        model="claude-sonnet-5[1m]", system_prompt="test",
        created_at=datetime.now(timezone.utc),
    )


class _IdleBackend:
    active_turn_id = None
    _events_active = False
    _turn_active = False

    async def retarget_model(self, *_a, **_k):
        return True

    async def disconnect(self, *_a, **_k):
        return None

    async def connect(self, *_a, **_k):
        return None

    async def stop(self, *_a, **_k):
        return None


@pytest.fixture
def schema_db(tmp_path, monkeypatch):
    """Схема поднимается ВО ВРЕМЕННОЙ базе: путь `codex -> claude` пишет в `logs`."""
    import app.db as db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "probe.db")
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(tmp_path / "probe.db"))
    db.init_db()
    # Видимый транскрипт: без него путь codex -> claude отказывает раньше гейта,
    # `text_tail_empty`, и ячейка (б1) остаётся неизмеренной.
    db.save_session({
        "id": "handoff-effects", "name": "effects-canary", "scope": "/test",
        "cwd": "/tmp", "model": "gpt-5.6-sol", "system_prompt": "test",
        "status": "idle", "session_id": "source-thread", "cost_usd": 0.0,
        "worktree_path": "/tmp", "branch": "b", "is_orchestrator": False,
        "color": "#818cf8", "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    })
    now = datetime.now(timezone.utc)
    db.add_log("handoff-effects", now, "user_message", "почини гейт",
               provenance=MessageProvenance(
                   origin="user", senders=("owner",), subtype="chat", ref="probe"))
    db.add_log("handoff-effects", now + timedelta(seconds=1), "text", "смотрю на гейт")
    return tmp_path / "probe.db"


@pytest.mark.asyncio
@pytest.mark.parametrize("start_model,start_runtime,target,label", [
    ("gpt-5.6-sol", "codex", "gpt-5.6-luna", "а: ВНУТРИ рантайма codex"),
    ("gpt-5.6-sol", "codex", "claude-opus-5[1m]", "б1: codex -> claude"),
    ("claude-opus-5[1m]", "claude", "gpt-5.6-sol", "б2: claude -> codex"),
])
async def test_probe(session, schema_db, start_model, start_runtime, target, label):
    from app.runtime_history import PreparationResult
    from app.session import AgentStatus

    session.model = start_model
    session.backend_type = start_runtime
    session.session_id = "source-thread"
    session.status = AgentStatus.IDLE
    session._backend = _IdleBackend()
    session._log = MagicMock()
    session._ensure_backend = AsyncMock()
    session._prepare_runtime_handoff = AsyncMock(return_value=PreparationResult(
        ok=False,
        error_code="handoff_pending_effect",
        handoff_id=None,
        pending_effects=1,
        pending_effect_details=({
            "call_id": "call-9", "tool_name": "Bash",
            "call_log_id": 2, "call_ts": "2026-08-11T10:00:02+00:00",
        },),
    ))
    result = await session.change_model(target)
    print(f"\nПРОБА {label}: ok={result.get('ok')} code={result.get('error_code')!r} "
          f"prepare_called={session._prepare_runtime_handoff.await_count} "
          f"err={str(result.get('error'))[:70]!r}")
