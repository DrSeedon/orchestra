import asyncio
import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


def _insert_source_and_handoff(dbmod, *, status: str, locator: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with dbmod._conn() as conn:
        conn.execute(
            """INSERT INTO sessions
               (id, name, scope, cwd, model, backend_type, session_id, created_at)
               VALUES ('s1', 'worker', '/tmp', '/tmp', 'gpt-5.6-sol',
                       'codex', 'old-thread', ?)""",
            (now,),
        )
        conn.execute(
            """INSERT INTO runtime_handoffs
               (handoff_id, session_id, idempotency_key, status,
                source_runtime, source_model, source_session_id,
                target_runtime, target_model, snapshot_log_id,
                snapshot_sha256, packet_json, packet_sha256, preferred_mode,
                created_at, updated_at)
               VALUES ('h1', 's1', 'request-1', ?, 'codex', 'gpt-5.6-sol',
                       'old-thread', 'claude', 'claude-sonnet-5[1m]', 0,
                       ?, '{}', ?, 'packet_delta', ?, ?)""",
            (status, "a" * 64, "b" * 64, now, now),
        )
    attempt = dbmod.allocate_runtime_handoff_attempt(
        "h1",
        mode="packet_delta",
        candidate_sha256="b" * 64,
        cleanup_locator=locator,
    )
    dbmod.update_runtime_handoff_attempt(
        "h1", 1, status="capability_validated", target_session_id="new-thread",
    )
    dbmod.update_runtime_handoff_status("h1", status)
    return dbmod.get_runtime_handoff("h1")


def _session():
    from app.session import AgentSession

    session = AgentSession(
        id="s1", name="worker", scope="/tmp", cwd="/tmp",
        model="gpt-5.6-sol", backend_type="codex",
        session_id="old-thread", system_prompt="test",
    )
    session._persist = MagicMock()
    session._log = MagicMock()
    session._activate_backend_tasks = MagicMock()
    return session


@pytest.mark.asyncio
async def test_same_runtime_preparation_persists_native_resume_ledger(
    tmp_path, monkeypatch,
):
    from app import db as dbmod

    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "native-resume.db")
    dbmod.init_db()
    now = datetime.now(timezone.utc).isoformat()
    with dbmod._conn() as conn:
        conn.execute(
            """INSERT INTO sessions
               (id, name, scope, cwd, model, backend_type, session_id, created_at)
               VALUES ('s1', 'worker', '/tmp', '/tmp', 'gpt-5.6-sol',
                       'codex', 'old-thread', ?)""",
            (now,),
        )
    session = _session()
    session._expected_handoff_capability = MagicMock(return_value={
        "runtime": "codex", "model": "gpt-5.5", "supported": True,
        "raw_ref_runtime_tool": False,
    })

    prepared = await session._prepare_runtime_handoff(
        "gpt-5.5",
        idempotency_key="same-runtime-request",
        project_docs=[],
    )

    handoff = dbmod.get_runtime_handoff(prepared.handoff_id)
    assert handoff is not None
    assert handoff["status"] == "prepared"
    assert handoff["source_runtime"] == "codex"
    assert handoff["target_runtime"] == "codex"
    assert handoff["preferred_mode"] == "native_resume"


@pytest.mark.asyncio
async def test_unreleased_handoff_recovery_discards_target_and_keeps_source(
    tmp_path, monkeypatch,
):
    from app import db as dbmod
    import app.session as sessionmod

    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "recovery.db")
    monkeypatch.setattr(sessionmod, "_HANDOFF_STAGING_ROOT", tmp_path / "staging")
    dbmod.init_db()
    locator = tmp_path / "staging" / "h1" / "1"
    locator.mkdir(parents=True)
    (locator / "provider-state").write_text("owned")
    handoff = _insert_source_and_handoff(
        dbmod, status="capability_validated", locator=str(locator),
    )
    attempts = dbmod.list_runtime_handoff_attempts("h1")
    session = _session()
    session._ensure_backend = AsyncMock(
        side_effect=AssertionError("unreleased source must not reconnect"),
    )

    await session.recover_runtime_handoff(handoff, attempts)

    assert not locator.exists()
    assert dbmod.get_runtime_handoff("h1")["status"] == "failed"
    assert session.session_id == "old-thread"
    assert session._handoff_recovery_required is False
    session._ensure_backend.assert_not_awaited()


@pytest.mark.asyncio
async def test_released_handoff_recovery_requires_exact_source_resume(
    tmp_path, monkeypatch,
):
    from app import db as dbmod
    import app.session as sessionmod

    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "recovery.db")
    monkeypatch.setattr(sessionmod, "_HANDOFF_STAGING_ROOT", tmp_path / "staging")
    dbmod.init_db()
    locator = tmp_path / "staging" / "h1" / "1"
    locator.mkdir(parents=True)
    handoff = _insert_source_and_handoff(
        dbmod, status="source_released", locator=str(locator),
    )
    session = _session()
    session._ensure_backend = AsyncMock(return_value=SimpleNamespace(
        session_id="wrong-thread", resume_failed=False,
    ))

    await session.recover_runtime_handoff(
        handoff, dbmod.list_runtime_handoff_attempts("h1"),
    )

    assert locator.exists()
    assert dbmod.get_runtime_handoff("h1")["status"] == "recovery_required"
    assert session._handoff_recovery_required is True


@pytest.mark.asyncio
async def test_released_handoff_recovery_reconnects_exact_source_once(
    tmp_path, monkeypatch,
):
    from app import db as dbmod
    import app.session as sessionmod

    monkeypatch.setattr(dbmod, "DB_PATH", tmp_path / "recovery.db")
    monkeypatch.setattr(sessionmod, "_HANDOFF_STAGING_ROOT", tmp_path / "staging")
    dbmod.init_db()
    locator = tmp_path / "staging" / "h1" / "1"
    locator.mkdir(parents=True)
    handoff = _insert_source_and_handoff(
        dbmod, status="source_released", locator=str(locator),
    )
    session = _session()
    source = SimpleNamespace(session_id="old-thread", resume_failed=False)
    session._backend = source
    session._ensure_backend = AsyncMock(return_value=source)

    await session.recover_runtime_handoff(
        handoff, dbmod.list_runtime_handoff_attempts("h1"),
    )

    session._ensure_backend.assert_awaited_once_with(activate=False)
    assert not locator.exists()
    assert dbmod.get_runtime_handoff("h1")["status"] == "failed"
    assert session._handoff_recovery_required is False


@pytest.mark.asyncio
async def test_recovery_required_blocks_send_before_backend_use():
    session = _session()
    backend = AsyncMock()
    session._backend = backend
    session._handoff_recovery_required = True

    with pytest.raises(RuntimeError, match="handoff_recovery_required"):
        from app.events import MessageProvenance
        await session.send(
            "must not reach provider",
            provenance=MessageProvenance(origin="user", senders=("user",)),
        )

    backend.connect.assert_not_awaited()
    backend.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_completed_failed_log_write_blocks_handoff_after_callback_cleanup(
    monkeypatch,
):
    from app.session import AgentSession
    import app.session as sessionmod

    session = AgentSession(
        id="s1", name="worker", scope="/tmp", cwd="/tmp",
        model="gpt-5.6-sol", backend_type="codex", session_id="old-thread",
    )

    def fail_log(*_args, **_kwargs):
        raise RuntimeError("disk unavailable")

    monkeypatch.setattr(sessionmod, "add_log", fail_log)
    session._log("tool_result", "effect completed")
    await asyncio.gather(*tuple(session._log_futures), return_exceptions=True)
    await asyncio.sleep(0)

    assert not session._log_futures
    assert session._log_write_failure_generation == 1
    prepared = await session._prepare_runtime_handoff(
        "claude-sonnet-5[1m]",
        idempotency_key="must-not-freeze",
        project_docs=[],
    )
    assert prepared.ok is False
    assert prepared.error_code == "handoff_log_persistence_failed"
    assert prepared.handoff_id is None


@pytest.mark.asyncio
async def test_lazy_id_load_applies_unfinished_handoff_before_start(
    tmp_path, monkeypatch,
):
    import app.manager as managermod
    from app.manager import SessionManager
    from app.session import AgentSession

    created_at = datetime.now(timezone.utc).isoformat()
    row = {
        "id": "lazy-source", "name": "lazy", "scope": str(tmp_path),
        "cwd": str(tmp_path), "model": "gpt-5.6-sol", "backend_type": "codex",
        "session_id": None, "status": "idle", "created_at": created_at,
        "role": "worker", "pipeline": "default", "system_prompt": "test",
        "color": "#123456",
    }
    handoff = {
        "handoff_id": "lazy-handoff", "session_id": "lazy-source",
        "status": "target_staged",
    }
    attempts = [{"attempt_no": 1, "cleanup_locator": str(tmp_path / "stage")}]
    monkeypatch.setattr(managermod, "get_session", lambda _sid: row)
    latest = MagicMock(return_value=handoff)
    monkeypatch.setattr(
        managermod, "get_latest_runtime_handoff_for_session", latest,
    )
    monkeypatch.setattr(
        managermod, "get_confirmed_runtime_handoff_attempt", lambda *_args: None,
    )
    monkeypatch.setattr(
        managermod, "list_runtime_handoff_attempts", lambda _hid: attempts,
    )
    recover = AsyncMock()
    monkeypatch.setattr(AgentSession, "recover_runtime_handoff", recover)
    monkeypatch.setattr(AgentSession, "start", AsyncMock())

    loaded = await SessionManager().ensure_loaded_by_id("lazy-source")

    assert loaded is not None
    latest.assert_called_once_with("lazy-source")
    recover.assert_awaited_once_with(handoff, attempts)
