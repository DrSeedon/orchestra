"""Regressions found by the required post-review adversarial self-check."""

from datetime import datetime, timezone


def _db(tmp_path, monkeypatch):
    import app.db as db

    path = tmp_path / "self-review-466.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setenv("ORCHESTRA_DB_PATH", str(path))
    db.init_db()
    return db


def _session(session_id: str):
    return {
        "id": session_id,
        "name": session_id,
        "scope": "/scope",
        "cwd": "/worktree",
        "model": "gpt-5.6-sol",
        "system_prompt": "",
        "status": "idle",
        "session_id": None,
        "cost_usd": 0.0,
        "worktree_path": "/worktree",
        "branch": f"task-466/{session_id}",
        "base_branch": "main",
        "needs_switch": 0,
        "task_id": "466",
        "is_orchestrator": False,
        "parent_name": "orchestrator",
        "color": "",
        "template_hash": "prompt-466",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    }


def _open(db, session_id: str):
    return db.task_run_receipt_open(
        session_id=session_id,
        worker_name=session_id,
        scope="/scope",
        task_id="466",
        task_stable_id="46646646-6466-4466-8466-466466466466",
        task_snapshot_ref="orch://project/project/tasks/466@sha256:same",
        prompt_template_start="prompt-466",
        requested_at="2026-09-04T00:00:00+00:00",
    )


def test_t2_old_completion_replay_does_not_close_reopened_run(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    first = _open(db, "replay-466")
    db.task_run_receipt_finish(
        session_id="replay-466",
        task_id="466",
        status="completed",
        prompt_template_end="prompt-466",
        terminal_operation_id="operation-old-466",
    )
    reopened = _open(db, "replay-466")

    replayed = db.task_run_receipt_finish(
        session_id="replay-466",
        task_id="466",
        status="completed",
        prompt_template_end="prompt-466",
        terminal_operation_id="operation-old-466",
    )

    assert replayed["receipt_id"] == first["receipt_id"], (
        "T2 self-review: old completion replay targeted the reopened run"
    )
    with db._conn() as connection:
        current = dict(connection.execute(
            "SELECT * FROM review_receipts WHERE receipt_id=?",
            (reopened["receipt_id"],),
        ).fetchone())
    assert current["status"] == "requested"
    assert current["terminal_operation_id"] == ""


def test_t2_unaccounted_cost_is_a_gap_not_zero(tmp_path, monkeypatch):
    db = _db(tmp_path, monkeypatch)
    db.save_session(_session("cost-gap-466"))
    run = _open(db, "cost-gap-466")
    db.turn_usage_add(
        event_id="unaccounted-466",
        session_id="cost-gap-466",
        scope="/scope",
        task_id="466",
        runtime="codex",
        model="gpt-5.6-sol",
        ok=True,
        stop_reason="end_turn",
        cost_usd=None,
        cost_unaccounted=True,
        input_tokens=100,
        output_tokens=10,
        cache_read_tokens=50,
        cache_create_tokens=0,
        ts="2026-09-04T00:10:00+00:00",
    )
    from app.run_receipts import build_task_run_trace

    trace = build_task_run_trace(
        run["receipt_id"], as_of="2026-09-04T00:20:00+00:00",
    )

    assert trace["usage"]["cost_usd"] is None, (
        "T2 self-review: unaccounted cost was normalized to zero"
    )
    assert "usage_cost_unaccounted" in trace["gaps"]
