"""Integrity and retry contracts raised by the #418 implementation review."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def portfolio_state(tmp_path, monkeypatch):
    from app import db, portfolio

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "portfolio-integrity.sqlite")
    db.init_db()
    owner = "owner-integrity-418"
    db.save_session(
        {
            "id": owner,
            "name": owner,
            "scope": "/portfolio",
            "cwd": "/portfolio",
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
    return db, portfolio, owner


def test_unlinked_portfolio_receipt_does_not_block_task_delete(portfolio_state):
    db, portfolio, owner = portfolio_state
    from app import tm

    with tm._conn() as conn:
        tm.ensure_project(conn, "namespace", name="Namespace", scope="/portfolio")
        task = tm.create_task(conn, "namespace", "Disposable", par_number=1)
    portfolio.link_task(owner, "alpha", "namespace", "1")
    portfolio.unlink_task(owner, "alpha", "namespace", "1")
    with db._conn() as conn:
        conn.execute("DELETE FROM tm_tasks WHERE id=?", (task["id"],))
        assert conn.execute(
            "SELECT COUNT(*) FROM portfolio_task_links WHERE task_row_id=?",
            (task["id"],),
        ).fetchone()[0] == 0


def test_goal_progress_and_wait_retries_are_idempotent(portfolio_state):
    _db, portfolio, owner = portfolio_state
    goal = portfolio.create_goal(owner, "alpha", "Ship Alpha")

    unchanged = portfolio.update_goal(
        owner, "alpha", goal["id"], watchdog_enabled=False
    )
    assert unchanged["revision"] == goal["revision"]

    default_progress = portfolio.record_progress(owner, "alpha", goal["id"])
    default_replay = portfolio.record_progress(owner, "alpha", goal["id"])
    assert default_progress["note"] == "Progress recorded"
    assert default_replay["replayed"] is True
    assert (
        default_replay["goal"]["stall_generation"]
        == default_progress["goal"]["stall_generation"]
    )

    first_progress = portfolio.record_progress(
        owner, "alpha", goal["id"], "Checkpoint reached"
    )
    replayed_progress = portfolio.record_progress(
        owner, "alpha", goal["id"], "Checkpoint reached"
    )
    assert replayed_progress["replayed"] is True
    assert (
        replayed_progress["goal"]["stall_generation"]
        == first_progress["goal"]["stall_generation"]
    )

    first_wait, inserted = portfolio.open_wait(owner, "alpha", "Choose A or B")
    assert inserted is True
    portfolio.record_progress(owner, "alpha", goal["id"], "Other progress")
    replayed_wait, inserted = portfolio.open_wait(owner, "alpha", "Choose A or B")
    assert inserted is False
    assert replayed_wait["id"] == first_wait["id"]

    resolved = portfolio.close_wait(owner, "alpha", first_wait["id"], "resolved")
    replayed_resolve = portfolio.close_wait(
        owner, "alpha", first_wait["id"], "resolved"
    )
    assert replayed_resolve == resolved


def test_future_progress_timestamp_is_rejected(portfolio_state):
    _db, portfolio, owner = portfolio_state
    goal = portfolio.create_goal(owner, "alpha", "Ship Alpha")

    with pytest.raises(portfolio.PortfolioError, match="future timestamps"):
        portfolio.record_progress(
            owner,
            "alpha",
            goal["id"],
            "Time travel",
            now=datetime.now(timezone.utc) + timedelta(days=1),
        )


def _seed_progress_receipt_order(
    db, portfolio, owner: str, *, old_created_at: str, current_created_at: str,
    old_id: str = "old-generation", current_id: str = "current-generation",
):
    goal = portfolio.create_goal(owner, "alpha", "Ship Alpha")
    with db._conn() as conn:
        conn.execute(
            "UPDATE portfolio_goals SET stall_generation=3 WHERE id=?", (goal["id"],)
        )
        conn.execute(
            """INSERT INTO portfolio_goal_progress(
                   id,claim_key,goal_id,session_id,note,stall_generation,created_at)
               VALUES(?,?,?,?,?,?,?)""",
            (old_id, f"claim-{old_id}", goal["id"], owner, "Same note", 2, old_created_at),
        )
        conn.execute(
            """INSERT INTO portfolio_goal_progress(
                   id,claim_key,goal_id,session_id,note,stall_generation,created_at)
               VALUES(?,?,?,?,?,?,?)""",
            (
                current_id,
                f"claim-{current_id}",
                goal["id"],
                owner,
                "Same note",
                3,
                current_created_at,
            ),
        )
    return goal


def test_progress_retry_uses_generation_when_timestamps_are_out_of_order(
    portfolio_state,
):
    db, portfolio, owner = portfolio_state
    goal = _seed_progress_receipt_order(
        db,
        portfolio,
        owner,
        old_created_at="2026-08-30T13:00:00+00:00",
        current_created_at="2026-08-30T12:00:00+00:00",
    )

    replay = portfolio.record_progress(owner, "alpha", goal["id"], "Same note")

    assert replay["replayed"] is True
    assert replay["goal"]["stall_generation"] == 3


def test_progress_retry_uses_generation_when_timestamps_are_equal(portfolio_state):
    db, portfolio, owner = portfolio_state
    goal = _seed_progress_receipt_order(
        db,
        portfolio,
        owner,
        old_created_at="2026-08-30T12:00:00+00:00",
        current_created_at="2026-08-30T12:00:00+00:00",
        old_id="zz-old-generation",
        current_id="aa-current-generation",
    )

    replay = portfolio.record_progress(owner, "alpha", goal["id"], "Same note")

    assert replay["replayed"] is True
    assert replay["goal"]["stall_generation"] == 3
