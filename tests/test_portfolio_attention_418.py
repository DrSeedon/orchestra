"""Durable attention integration for #418."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def attention_app(tmp_path, monkeypatch):
    from app import db, portfolio
    from app.routes.portfolio import router

    isolated = tmp_path / "portfolio-attention.sqlite"
    production = db._DEFAULT_DB_PATH.resolve()
    real_connect = sqlite3.connect

    def guarded_connect(database, *args, **kwargs):
        raw = str(database)
        if raw.startswith("file:"):
            raw = raw.removeprefix("file:").split("?", 1)[0]
        if raw != ":memory:" and Path(raw).resolve() == production:
            raise AssertionError(f"#418 attention test attempted production DB: {production}")
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(db, "DB_PATH", isolated)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(isolated))
    monkeypatch.setattr(sqlite3, "connect", guarded_connect)
    db.init_db()
    owner = "owner-attention-418"
    db.save_session(
        {
            "id": owner,
            "name": owner,
            "scope": "/attention",
            "cwd": "/attention",
            "model": "test",
            "system_prompt": "",
            "status": "idle",
            "session_id": None,
            "cost_usd": 0.0,
            "worktree_path": "",
            "branch": "",
            "base_branch": "main",
            "needs_switch": 0,
            "is_orchestrator": True,
            "color": "",
            "role": "orchestrator",
            "parent_id": "",
            "parent_name": "",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
        }
    )
    portfolio.create_project(owner, "alpha", "Alpha")
    app = FastAPI()
    app.include_router(router)
    return db, owner, app


def test_attention_route_commits_before_bridge_marker_is_eligible(attention_app):
    db, owner, app = attention_app
    from app import tg_bridge

    headers = {"x-orchestra-session-id": owner}
    with TestClient(app) as client:
        response = client.post(
            "/api/portfolio/projects/alpha/attention",
            headers=headers,
            json={"reason": "Production incident", "kind": "incident"},
        )
    assert response.status_code == 201, response.text
    event_id = response.json()["event_id"]
    with db._conn() as conn:
        row = conn.execute(
            "SELECT * FROM portfolio_attention_events WHERE id=?", (event_id,)
        ).fetchone()
        assert row["reason"] == "Production incident"
        assert row["kind"] == "incident"

    marker = f"ATTENTION_DURABLE:{event_id}"
    event = tg_bridge._durable_attention_from_tool_result(marker, owner)
    assert event is not None
    assert event["id"] == event_id
    assert tg_bridge._durable_attention_from_tool_result(marker, "other-session") is None
    assert tg_bridge._durable_attention_from_tool_result(
        "ATTENTION_DURABLE:missing-event", owner
    ) is None
    assert tg_bridge._notify_attention_from_tool_result(
        marker, owner, tool_name="Bash"
    ) is None
    assert tg_bridge._notify_attention_from_tool_result(
        marker,
        owner,
        resolved_tool_name="mcp__orchestra__notify_user",
    )["id"] == event_id


def test_wait_and_watchdog_markers_can_never_be_attention(attention_app):
    _db, owner, _app = attention_app
    from app import tg_bridge

    assert tg_bridge._attention_from_tool_result("PROJECT_WAIT_DURABLE:wait-1") is None
    assert tg_bridge._attention_from_tool_result("WATCHDOG_WAKE_DURABLE:wake-1") is None
    assert tg_bridge._durable_attention_from_tool_result(
        "PROJECT_WAIT_DURABLE:wait-1", owner
    ) is None


def test_projectless_attention_rejects_worker_and_list_requires_identity(
    attention_app, monkeypatch
):
    db, owner, app = attention_app
    worker = "worker-attention-418"
    db.save_session(
        {
            "id": worker,
            "name": worker,
            "scope": "/attention",
            "cwd": "/attention",
            "model": "test",
            "system_prompt": "",
            "status": "idle",
            "session_id": None,
            "cost_usd": 0.0,
            "worktree_path": "",
            "branch": "",
            "base_branch": "main",
            "needs_switch": 0,
            "is_orchestrator": False,
            "color": "",
            "role": "worker",
            "parent_id": owner,
            "parent_name": owner,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
        }
    )
    monkeypatch.setenv("DASHBOARD_USER", "owner")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "secret")
    with TestClient(app) as client:
        denied_attention = client.post(
            "/api/portfolio/attention",
            headers={"x-orchestra-session-id": worker},
            json={"reason": "worker asks for tag", "kind": "legacy"},
        )
        denied_list = client.get("/api/portfolio/projects")
        member_list = client.get(
            "/api/portfolio/projects",
            headers={"x-orchestra-session-id": owner},
        )
    assert denied_attention.status_code == 403
    assert denied_list.status_code == 403
    assert [project["id"] for project in member_list.json()["projects"]] == ["alpha"]
