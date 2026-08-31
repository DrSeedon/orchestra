"""Focused watchdog persistence and rollout contracts for #418."""

from __future__ import annotations

import uuid
import asyncio
from datetime import datetime, timedelta, timezone

import pytest


def _session(db, name: str, *, role: str, parent_id: str = "", scope: str = "/p"):
    session_id = str(uuid.uuid4())
    db.save_session(
        {
            "id": session_id,
            "name": f"{name}-{session_id[:8]}",
            "scope": scope,
            "cwd": scope,
            "model": "test",
            "system_prompt": "",
            "status": "idle",
            "session_id": None,
            "cost_usd": 0.0,
            "worktree_path": "",
            "branch": "",
            "base_branch": "main",
            "needs_switch": 0,
            "is_orchestrator": role in {"orchestrator", "sub-orchestrator"},
            "color": "",
            "role": role,
            "parent_id": parent_id,
            "parent_name": "",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
        }
    )
    return session_id


@pytest.fixture
def portfolio_db(tmp_path, monkeypatch):
    from app import db

    path = tmp_path / "portfolio-watchdog.sqlite"
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(path))
    db.init_db()
    return db


def _goal(portfolio_db, *, enabled: bool, started: datetime):
    from app import portfolio

    owner = _session(portfolio_db, "owner", role="orchestrator")
    portfolio.create_project(owner, "alpha", "Alpha")
    goal = portfolio.create_goal(
        owner,
        "alpha",
        "Ship Alpha",
        watchdog_enabled=enabled,
        now=started,
    )
    return owner, goal


@pytest.mark.asyncio
async def test_fresh_migration_and_shadow_mode_emit_no_delivery(portfolio_db):
    from app.portfolio_watchdog import evaluate_once

    calls = []
    now = datetime.now(timezone.utc).replace(microsecond=0)

    async def deliver(payload):
        calls.append(payload)

    fresh = await evaluate_once(now=now, deliver=deliver)
    assert fresh["candidates"] == 0
    _goal(portfolio_db, enabled=True, started=now - timedelta(minutes=31))
    shadow = await evaluate_once(now=now, deliver=deliver, shadow=True)
    assert shadow["candidates"] == 1
    assert shadow["shadow"] == 1
    assert calls == []
    with portfolio_db._conn() as conn:
        assert conn.execute("SELECT COUNT(*) FROM portfolio_watchdog_outbox").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_retry_reopens_database_and_reuses_delivery_id(portfolio_db):
    from app.portfolio_watchdog import evaluate_once

    now = datetime.now(timezone.utc).replace(microsecond=0)
    _goal(portfolio_db, enabled=True, started=now - timedelta(minutes=31))
    failed_ids: list[str] = []

    async def fail(payload):
        failed_ids.append(payload["delivery_id"])
        raise RuntimeError("transport down")

    failed = await evaluate_once(now=now, deliver=fail)
    assert failed["failed"] == 1
    with portfolio_db._conn() as reopened:
        row = reopened.execute(
            "SELECT delivery_id,state FROM portfolio_watchdog_outbox"
        ).fetchone()
        assert (row["delivery_id"], row["state"]) == (failed_ids[0], "retryable")

    recovered_ids: list[str] = []

    async def recover(payload):
        recovered_ids.append(payload["delivery_id"])

    recovered = await evaluate_once(now=now + timedelta(minutes=5), deliver=recover)
    assert recovered["delivered"] == 1
    assert recovered_ids == failed_ids


@pytest.mark.asyncio
async def test_stale_failed_callback_cannot_reopen_accepted_claim(portfolio_db):
    from app.portfolio_watchdog import evaluate_once

    now = datetime.now(timezone.utc).replace(microsecond=0)
    _goal(portfolio_db, enabled=True, started=now - timedelta(minutes=31))
    entered = asyncio.Event()
    release = asyncio.Event()
    first_payloads = []

    async def delayed_failure(payload):
        first_payloads.append(payload)
        entered.set()
        await release.wait()
        raise RuntimeError("stale callback")

    first = asyncio.create_task(evaluate_once(now=now, deliver=delayed_failure))
    await entered.wait()
    second_payloads = []

    async def accepted(payload):
        second_payloads.append(payload)

    second = await evaluate_once(
        now=now + timedelta(seconds=301), deliver=accepted
    )
    release.set()
    stale = await first

    assert second["delivered"] == 1
    assert stale["failed"] == 1
    assert first_payloads[0]["delivery_id"] == second_payloads[0]["delivery_id"]
    assert first_payloads[0]["claim_token"] != second_payloads[0]["claim_token"]
    with portfolio_db._conn() as conn:
        row = conn.execute(
            "SELECT state,claim_token FROM portfolio_watchdog_outbox"
        ).fetchone()
        assert (row["state"], row["claim_token"]) == (
            "accepted",
            second_payloads[0]["claim_token"],
        )


@pytest.mark.asyncio
async def test_open_wait_suppresses_goal_only_candidate(portfolio_db):
    from app import portfolio
    from app.portfolio_watchdog import evaluate_once

    now = datetime.now(timezone.utc).replace(microsecond=0)
    owner, _goal_row = _goal(
        portfolio_db, enabled=True, started=now - timedelta(minutes=31)
    )
    portfolio.open_wait(owner, "alpha", "Need a decision", now=now)
    calls = []

    async def deliver(payload):
        calls.append(payload)

    result = await evaluate_once(now=now + timedelta(hours=1), deliver=deliver)
    assert result["claimed"] == 0
    assert calls == []


@pytest.mark.asyncio
async def test_lifespan_task_factory_keeps_exactly_one_cancellable_loop(monkeypatch):
    from fastapi import FastAPI
    from app import portfolio_watchdog

    entered = asyncio.Event()

    async def loop():
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(portfolio_watchdog, "run_loop", loop)
    app = FastAPI()
    first = portfolio_watchdog.ensure_task(app)
    second = portfolio_watchdog.ensure_task(app)
    await entered.wait()
    assert first is second
    assert first.get_name() == "portfolio-watchdog"
    first.cancel()
    await asyncio.gather(first, return_exceptions=True)
    assert first.cancelled()

    replacement = portfolio_watchdog.ensure_task(app)
    assert replacement is not first
    replacement.cancel()
    await asyncio.gather(replacement, return_exceptions=True)


@pytest.mark.asyncio
async def test_watchdog_delivery_uses_internal_message_receipt_not_user_tag(monkeypatch):
    from app import message_deliveries, portfolio_watchdog

    captured = {}

    async def accept(**kwargs):
        captured.update(kwargs)
        return {"delivery_id": kwargs["delivery_id"]}, 202

    monkeypatch.setattr(message_deliveries, "accept_message_delivery", accept)
    payload = {
        "delivery_id": str(uuid.uuid4()),
        "target_session_id": "owner-1",
        "target_name": "owner",
        "target_scope": "/p",
        "target_task_id": "",
        "target_generation": "session=owner-1|task=|branch=|needs_switch=0",
        "message": "continue the project",
    }
    await portfolio_watchdog._deliver_to_owner(payload)
    assert captured["target_session_id"] == "owner-1"
    assert captured["message_kind"] == "portfolio_watchdog"
    assert captured["wake"] is True
