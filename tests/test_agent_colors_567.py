"""Core color allocation and startup repair checks for V-567."""

from collections import Counter

import pytest

from app.db import archive_session, get_all_sessions, get_session, save_session
from app.manager import COLOR_PALETTE, SessionManager


@pytest.fixture
def db(tmp_path, monkeypatch):
    db_path = tmp_path / "colors.db"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    from app.db import init_db
    init_db()
    return db_path


def _session(session_id, *, scope="/project", color="", is_orchestrator=False):
    save_session({
        "id": session_id,
        "name": session_id,
        "scope": scope,
        "cwd": scope,
        "model": "claude-sonnet-5[1m]",
        "system_prompt": "",
        "status": "idle",
        "session_id": None,
        "cost_usd": 0.0,
        "worktree_path": None,
        "branch": None,
        "base_branch": "",
        "needs_switch": 0,
        "is_orchestrator": is_orchestrator,
        "color": color,
        "created_at": "2026-09-01T00:00:00+00:00",
        "finished_at": None,
    })


def test_fallback_counts_each_live_color_occurrence(db):
    """The first palette color is not selected merely because it sorts first."""
    for index, color in enumerate(COLOR_PALETTE):
        _session(f"w{index}", color=color)
    _session("w99", color=COLOR_PALETTE[0])

    assert SessionManager()._pick_color("/project") == COLOR_PALETTE[1]


def test_allocator_is_scoped_and_archived_rows_do_not_occupy_colors(db):
    for index, color in enumerate(COLOR_PALETTE):
        _session(f"a{index}", scope="/a", color=color)
    archived_id = "archived"
    _session(archived_id, scope="/b", color=COLOR_PALETTE[0])
    archive_session(archived_id)

    manager = SessionManager()
    assert manager._pick_color("/b") == COLOR_PALETTE[0]
    assert manager._pick_color("/a") == COLOR_PALETTE[0]


def test_startup_recolors_live_workers_per_scope_and_preserves_archived(db):
    for index in range(len(COLOR_PALETTE) + 3):
        _session(f"a{index}", scope="/a", color=COLOR_PALETTE[0])
    _session("b0", scope="/b", color=COLOR_PALETTE[0])
    _session("b1", scope="/b", color=COLOR_PALETTE[0])
    _session("old", scope="/a", color="#123456")
    archive_session("old")
    _session("orch", scope="/a", color="#123456", is_orchestrator=True)

    manager = SessionManager()
    manager.reconcile_live_colors()
    first = {row["id"]: row["color"] for row in get_all_sessions(include_archived=True)}
    manager.reconcile_live_colors()
    second = {row["id"]: row["color"] for row in get_all_sessions(include_archived=True)}

    live_a = [color for sid, color in first.items() if sid.startswith("a")]
    live_b = [color for sid, color in first.items() if sid.startswith("b")]
    assert max(Counter(live_a).values()) - min(Counter(live_a).values()) <= 1
    assert len(set(live_b)) == 2
    assert first["old"] == second["old"] == "#123456"
    assert first["orch"] == second["orch"] == ""
    assert first == second
    assert get_session("old")["status"] == "archived"
