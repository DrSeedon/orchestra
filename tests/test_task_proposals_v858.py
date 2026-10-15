from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _session_row(name: str, *, role: str, is_orchestrator: bool, parent: str = "") -> dict:
    return {
        "id": name, "name": name, "scope": "/v858", "cwd": "/v858",
        "model": "test-model", "system_prompt": "", "status": "idle", "session_id": None,
        "cost_usd": 0.0, "worktree_path": "", "branch": "", "base_branch": "main",
        "needs_switch": 0, "is_orchestrator": is_orchestrator, "color": "", "role": role,
        "parent_id": parent, "parent_name": parent,
        "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
        "task_id": "",
    }


@pytest.fixture
def proposal_client(tmp_path, monkeypatch):
    from app import db
    from app.mcp_proof import issue_mcp_proof
    from app.routes import sessions

    path = tmp_path / "proposals.sqlite"
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(path))
    monkeypatch.delenv("DASHBOARD_USER", raising=False)
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)
    db.init_db()
    db.save_session(_session_row("orch", role="orchestrator", is_orchestrator=True))
    db.save_session(_session_row("worker", role="worker", is_orchestrator=False, parent="orch"))
    app = FastAPI()
    app.include_router(sessions.router)
    return TestClient(app), db, sessions, issue_mcp_proof


def _proof_headers(session_id: str, issue_mcp_proof) -> dict[str, str]:
    return {
        "x-orchestra-session-id": session_id,
        "x-orchestra-mcp-proof": issue_mcp_proof(session_id),
    }


def _proposal_payload() -> dict[str, str]:
    return {
        "title": "Добавить проверку ширины панели",
        "summary": "Проверить ресайз панели на телефоне и десктопе.",
        "project": "Orchestra",
        "model": "Codex · Luna",
        "quota_pool": "Codex",
    }


def test_proposal_tool_route_refuses_workers_and_accepts_orchestrators(proposal_client):
    client, db, _routes, issue = proposal_client
    denied = client.post("/api/task-proposals", headers=_proof_headers("worker", issue), json=_proposal_payload())
    accepted = client.post("/api/task-proposals", headers=_proof_headers("orch", issue), json=_proposal_payload())
    anonymous = client.post("/api/task-proposals", json=_proposal_payload())

    assert denied.status_code == 403
    assert "Only orchestrator" in denied.json()["error"]
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["proposal"]["status"] == "proposed"
    assert anonymous.status_code == 403
    from app.task_proposals import list_for_session
    assert len(list_for_session("orch")) == 1
    assert list_for_session("worker") == []


def test_mcp_registers_proposal_and_checklist_tools():
    import app.mcp_stdio as mcp_stdio

    registered = {tool.name for tool in mcp_stdio.mcp._tool_manager.list_tools()}
    assert {"propose_task", "update_checklist"} <= registered


def test_cancelled_decision_receipt_can_be_retried_without_reusing_its_id(proposal_client):
    _client, _db, _routes, _issue = proposal_client
    from app import task_proposals

    proposal = task_proposals.create("orch", **_proposal_payload())
    pending = task_proposals.begin_decision(proposal["id"], action="approve")
    retry = task_proposals.rotate_unsent_decision(
        proposal["id"], pending["approval_delivery_id"],
    )

    assert retry["status"] == "approving"
    assert retry["approval_delivery_id"] != pending["approval_delivery_id"]


def test_legacy_inflight_approval_gets_recoverable_decision_intent(proposal_client):
    _client, db, _routes, _issue = proposal_client
    from app import task_proposals

    with db._conn() as connection:
        connection.execute("DROP TABLE task_proposals")
        connection.execute("""CREATE TABLE task_proposals (
            id TEXT PRIMARY KEY, session_id TEXT NOT NULL, title TEXT NOT NULL,
            summary TEXT NOT NULL, project TEXT NOT NULL, model TEXT NOT NULL,
            quota_pool TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
            decided_at TEXT NOT NULL DEFAULT '', approval_delivery_id TEXT NOT NULL UNIQUE
        )""")
        connection.execute(
            """INSERT INTO task_proposals VALUES(
                'legacy','orch','Старая задача','Старое описание','Orchestra','Codex','Codex',
                'approving','2026-10-15T00:00:00+00:00','', 'legacy-delivery')"""
        )
        task_proposals.ensure_schema(connection)
        row = task_proposals.get("legacy", connection=connection)

    assert row["decision_action"] == "approve"
    assert row["decision_message"] == "владелец одобрил: Старая задача — Старое описание"


@pytest.mark.asyncio
async def test_approval_is_one_durable_message_to_orchestrator_and_never_spawns(
    proposal_client, monkeypatch,
):
    client, db, routes, _issue = proposal_client
    from app import message_deliveries, task_proposals

    proposal = task_proposals.create("orch", **_proposal_payload())
    target = SimpleNamespace(
        id="orch", name="orch", scope="/v858", task_id="", branch="main", needs_switch=False,
    )
    monkeypatch.setattr(routes.manager, "sessions", {"orch": target})
    monkeypatch.setattr(routes, "_preflight_or_quota_wait", AsyncMock(return_value=None))
    runner_wakes: list[str] = []
    monkeypatch.setattr(message_deliveries, "ensure_target_runner", runner_wakes.append)
    spawn = AsyncMock(side_effect=AssertionError("approval must not spawn a worker"))
    monkeypatch.setattr(routes.manager, "create_session", spawn)

    denied = await routes.approve_task_proposal(
        proposal["id"], SimpleNamespace(cookies={}, headers={"x-orchestra-session-id": "worker"}),
    )
    first = await routes.approve_task_proposal(proposal["id"], SimpleNamespace(cookies={}, headers={}))
    second = await routes.approve_task_proposal(proposal["id"], SimpleNamespace(cookies={}, headers={}))

    assert denied.status_code == 403
    assert first["proposal"]["status"] == "approved"
    assert second["already_decided"] is True
    receipt = message_deliveries._row(proposal["approval_delivery_id"])
    assert receipt["target_session_id"] == "orch"
    assert receipt["message"] == (
        "владелец одобрил: Добавить проверку ширины панели — "
        "Проверить ресайз панели на телефоне и десктопе."
    )
    with db._conn() as connection:
        deliveries = connection.execute(
            "SELECT COUNT(*) FROM message_deliveries WHERE target_session_id='orch'"
        ).fetchone()[0]
    assert deliveries == 1
    assert runner_wakes == ["orch"]
    spawn.assert_not_awaited()
    assert task_proposals.get(proposal["id"])["status"] == "approved"


@pytest.mark.asyncio
async def test_rejection_is_one_durable_message_and_never_spawns(proposal_client, monkeypatch):
    _client, db, routes, _issue = proposal_client
    from app import message_deliveries, task_proposals

    proposal = task_proposals.create("orch", **_proposal_payload())
    target = SimpleNamespace(
        id="orch", name="orch", scope="/v858", task_id="", branch="main", needs_switch=False,
    )
    monkeypatch.setattr(routes.manager, "sessions", {"orch": target})
    monkeypatch.setattr(routes, "_preflight_or_quota_wait", AsyncMock(return_value=None))
    wakes: list[str] = []
    monkeypatch.setattr(message_deliveries, "ensure_target_runner", wakes.append)
    spawn = AsyncMock(side_effect=AssertionError("rejection must not spawn a worker"))
    monkeypatch.setattr(routes.manager, "create_session", spawn)
    request = SimpleNamespace(cookies={}, headers={})

    first = await routes.reject_task_proposal(proposal["id"], request)
    second = await routes.reject_task_proposal(proposal["id"], request)

    assert first["proposal"]["status"] == "rejected"
    assert second["already_decided"] is True
    receipt = message_deliveries._row(proposal["approval_delivery_id"])
    assert receipt["target_session_id"] == "orch"
    assert receipt["message"] == "владелец отклонил: Добавить проверку ширины панели"
    with db._conn() as connection:
        deliveries = connection.execute(
            "SELECT COUNT(*) FROM message_deliveries WHERE target_session_id='orch'"
        ).fetchone()[0]
    assert deliveries == 1
    assert wakes == ["orch"]
    spawn.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["approve", "reject"])
async def test_decision_reason_is_sent_to_orchestrator(action, proposal_client, monkeypatch):
    _client, _db, routes, _issue = proposal_client
    from app import message_deliveries, task_proposals
    from app.routes.sessions import TaskProposalDecisionRequest

    proposal = task_proposals.create("orch", **_proposal_payload())
    target = SimpleNamespace(
        id="orch", name="orch", scope="/v858", task_id="", branch="main", needs_switch=False,
    )
    monkeypatch.setattr(routes.manager, "sessions", {"orch": target})
    monkeypatch.setattr(routes, "_preflight_or_quota_wait", AsyncMock(return_value=None))
    monkeypatch.setattr(message_deliveries, "ensure_target_runner", lambda _session: None)
    request = SimpleNamespace(cookies={}, headers={})
    decision = getattr(routes, f"{action}_task_proposal")
    reason = "Сначала проверьте ширину на телефоне"

    response = await decision(
        proposal["id"], request, TaskProposalDecisionRequest(reason=reason),
    )

    receipt = message_deliveries._row(proposal["approval_delivery_id"])
    assert response["proposal"]["status"] == ("approved" if action == "approve" else "rejected")
    assert receipt["message"].endswith(f"\nПричина / указания владельца: {reason}")
    assert receipt["target_session_id"] == "orch"
