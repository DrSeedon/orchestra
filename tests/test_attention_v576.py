"""Durable attention: единственное, что пережило портфельный слой (#418, V-576)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def attention_app(tmp_path, monkeypatch):
    from app import db
    from app.routes.attention import router

    isolated = tmp_path / "attention.sqlite"
    production = db._DEFAULT_DB_PATH.resolve()
    real_connect = sqlite3.connect

    def guarded_connect(database, *args, **kwargs):
        raw = str(database)
        if raw.startswith("file:"):
            raw = raw.removeprefix("file:").split("?", 1)[0]
        if raw != ":memory:" and Path(raw).resolve() == production:
            raise AssertionError(f"attention test attempted production DB: {production}")
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(db, "DB_PATH", isolated)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(isolated))
    monkeypatch.setattr(sqlite3, "connect", guarded_connect)
    db.init_db()
    owner = "owner-attention-418"
    db.save_session(_session_row(owner, role="orchestrator", is_orchestrator=True))
    app = FastAPI()
    app.include_router(router)
    return db, owner, app


def _session_row(name: str, *, role: str, is_orchestrator: bool, parent: str = "") -> dict:
    return {
        "id": name, "name": name, "scope": "/attention", "cwd": "/attention",
        "model": "test", "system_prompt": "", "status": "idle", "session_id": None,
        "cost_usd": 0.0, "worktree_path": "", "branch": "", "base_branch": "main",
        "needs_switch": 0, "is_orchestrator": is_orchestrator, "color": "", "role": role,
        "parent_id": parent, "parent_name": parent,
        "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
    }


def test_attention_route_commits_before_bridge_marker_is_eligible(attention_app):
    db, owner, app = attention_app
    from app import tg_bridge

    with TestClient(app) as client:
        response = client.post(
            "/api/attention",
            headers={"x-orchestra-session-id": owner},
            json={"reason": "Production incident", "kind": "incident"},
        )
    assert response.status_code == 201, response.text
    event_id = response.json()["event_id"]
    with db._conn() as conn:
        row = conn.execute("SELECT * FROM attention_events WHERE id=?", (event_id,)).fetchone()
        assert (row["reason"], row["kind"]) == ("Production incident", "incident")

    marker = f"ATTENTION_DURABLE:{event_id}"
    event = tg_bridge._durable_attention_from_tool_result(marker, owner)
    assert event is not None and event["id"] == event_id
    assert tg_bridge._durable_attention_from_tool_result(marker, "other-session") is None
    assert tg_bridge._durable_attention_from_tool_result(
        "ATTENTION_DURABLE:missing-event", owner
    ) is None
    assert tg_bridge._notify_attention_from_tool_result(marker, owner, tool_name="Bash") is None
    assert tg_bridge._notify_attention_from_tool_result(
        marker, owner, resolved_tool_name="mcp__orchestra__notify_user",
    )["id"] == event_id


def test_a_foreign_durable_marker_is_never_attention(attention_app):
    _db, owner, _app = attention_app
    from app import tg_bridge

    for marker in ("PROJECT_WAIT_DURABLE:wait-1", "WATCHDOG_WAKE_DURABLE:wake-1"):
        assert tg_bridge._attention_from_tool_result(marker) is None
        assert tg_bridge._durable_attention_from_tool_result(marker, owner) is None


def test_attention_is_orchestrator_only(attention_app):
    db, owner, app = attention_app
    worker = "worker-attention-418"
    db.save_session(_session_row(worker, role="worker", is_orchestrator=False, parent=owner))

    with TestClient(app) as client:
        denied = client.post(
            "/api/attention",
            headers={"x-orchestra-session-id": worker},
            json={"reason": "worker asks for tag", "kind": "legacy"},
        )
        anonymous = client.post("/api/attention", json={"reason": "no identity"})
    assert denied.status_code == 403
    assert anonymous.status_code == 403


def test_waiting_records_a_blocked_decision(attention_app):
    """Замена project_wait: оркестратор обязан иметь способ зафиксировать ожидание."""
    db, owner, app = attention_app
    with TestClient(app) as client:
        accepted = client.post(
            "/api/attention",
            headers={"x-orchestra-session-id": owner},
            json={"reason": "Нужно решение: сносим ли второй ICP", "kind": "waiting"},
        )
        refused = client.post(
            "/api/attention",
            headers={"x-orchestra-session-id": owner},
            json={"reason": "typo", "kind": "not-a-kind"},
        )
    assert accepted.status_code == 201, accepted.text
    assert refused.status_code == 422
    with db._conn() as conn:
        assert conn.execute(
            "SELECT kind FROM attention_events WHERE id=?", (accepted.json()["event_id"],)
        ).fetchone()[0] == "waiting"
