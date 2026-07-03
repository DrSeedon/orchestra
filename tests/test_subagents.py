"""Sub-agent telemetry: upsert (start→progress→end), no-wipe, latest-tokens."""

from datetime import datetime, timezone

import pytest


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    from app.db import init_db, save_session
    init_db()
    save_session({
        "id": "sess-1", "name": "w", "scope": "/s", "cwd": "/c",
        "model": "claude-sonnet-5[1m]", "system_prompt": "",
        "status": "running", "session_id": "550e8400-e29b-41d4-a716-446655440000",
        "cost_usd": 0.0, "worktree_path": "/w", "branch": "b",
        "is_orchestrator": False, "color": "#fff",
        "created_at": datetime.now(timezone.utc).isoformat(), "finished_at": None,
    })
    return db_path


def test_start_creates_row(db):
    from app.db import subagent_upsert, get_subagents
    subagent_upsert("sess-1", "task-a", description="Explore X", task_type="Explore",
                    status="running", sdk_session_id="550e8400-e29b-41d4-a716-446655440000")
    rows = get_subagents("sess-1")
    assert len(rows) == 1
    assert rows[0]["task_id"] == "task-a"
    assert rows[0]["description"] == "Explore X"
    assert rows[0]["status"] == "running"
    assert rows[0]["sdk_session_id"] == "550e8400-e29b-41d4-a716-446655440000"


def test_progress_updates_tokens_without_wiping_desc(db):
    from app.db import subagent_upsert, get_subagent
    subagent_upsert("sess-1", "task-a", description="Explore X", task_type="Explore")
    # progress carries tokens + last_tool but empty description
    subagent_upsert("sess-1", "task-a", description="", last_tool_name="Bash",
                    total_tokens=1500, tool_uses=3, duration_ms=4200)
    sa = get_subagent("sess-1", "task-a")
    assert sa["description"] == "Explore X"  # NOT wiped by empty progress
    assert sa["last_tool_name"] == "Bash"
    assert sa["total_tokens"] == 1500
    assert sa["tool_uses"] == 3


def test_tokens_take_latest_max_not_summed(db):
    from app.db import subagent_upsert, get_subagent
    subagent_upsert("sess-1", "task-a", description="X")
    subagent_upsert("sess-1", "task-a", total_tokens=1000)
    subagent_upsert("sess-1", "task-a", total_tokens=2500)  # cumulative → latest
    sa = get_subagent("sess-1", "task-a")
    assert sa["total_tokens"] == 2500  # max/latest, NOT 3500 (no double-count)


def test_end_sets_summary_output_status(db):
    from app.db import subagent_upsert, get_subagent
    subagent_upsert("sess-1", "task-a", description="X")
    subagent_upsert("sess-1", "task-a", total_tokens=900)
    subagent_upsert("sess-1", "task-a", status="completed", summary="Found 3 files",
                    output_file="/tmp/out.md", total_tokens=1200,
                    ended_at=datetime.now(timezone.utc).isoformat())
    sa = get_subagent("sess-1", "task-a")
    assert sa["status"] == "completed"
    assert sa["summary"] == "Found 3 files"
    assert sa["output_file"] == "/tmp/out.md"
    assert sa["total_tokens"] == 1200
    assert sa["ended_at"]


def test_two_subagents_same_session_distinct(db):
    from app.db import subagent_upsert, get_subagents
    subagent_upsert("sess-1", "task-a", description="A")
    subagent_upsert("sess-1", "task-b", description="B")
    rows = get_subagents("sess-1")
    assert {r["task_id"] for r in rows} == {"task-a", "task-b"}


def test_get_subagent_missing_returns_none(db):
    from app.db import get_subagent
    assert get_subagent("sess-1", "nope") is None


def test_concurrent_upserts_no_data_loss(db):
    # fire-and-forget upserts run on a thread pool → simulate the race
    import threading
    from app.db import subagent_upsert, get_subagent
    subagent_upsert("sess-1", "task-a", description="X", status="running")

    def worker(n):
        subagent_upsert("sess-1", "task-a", total_tokens=n * 100, last_tool_name=f"t{n}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(1, 11)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    sa = get_subagent("sess-1", "task-a")
    assert sa["total_tokens"] == 1000   # MAX wins, not summed (no double-count)
    assert sa["description"] == "X"     # NULLIF-COALESCE: not wiped by race
    assert sa["status"] == "running"
