import json
from datetime import datetime, timezone

from starlette.requests import Request
import pytest


def _request(if_none_match=""):
    headers = []
    if if_none_match:
        headers.append((b"if-none-match", if_none_match.encode()))
    return Request({
        "type": "http",
        "method": "GET",
        "path": "/api/sessions/worker/logs",
        "headers": headers,
        "query_string": b"",
        "server": ("test", 80),
        "client": ("test", 1),
        "scheme": "http",
    })


@pytest.mark.asyncio
async def test_logs_revalidate_without_browser_history_cache(monkeypatch):
    from app.routes import sessions

    monkeypatch.setattr(sessions.manager, "get_session_id", lambda _name, _scope: "session-1")
    monkeypatch.setattr(sessions, "get_logs", lambda *_args, **_kwargs: [
        {"id": 1, "type": "text", "content": "current", "ts": "now"},
    ])

    first = await sessions.get_session_logs(
        "worker", _request(), "/scope",
    )
    assert first.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    assert first.headers.get("etag")

    unchanged = await sessions.get_session_logs(
        "worker", _request(first.headers["etag"]), "/scope",
    )
    assert unchanged.status_code == 304
    assert unchanged.body == b""
    assert unchanged.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_logs_stale_etag_returns_fresh_network_snapshot(monkeypatch):
    from app.routes import sessions

    monkeypatch.setattr(sessions.manager, "get_session_id", lambda _name, _scope: "session-1")
    monkeypatch.setattr(sessions, "get_logs", lambda *_args, **_kwargs: [
        {"id": 1, "type": "text", "content": "current", "ts": "now"},
    ])

    response = await sessions.get_session_logs(
        "worker", _request('"stale"'), "/scope",
    )
    assert response.status_code == 200
    assert b'"current"' in response.body
    assert response.headers["etag"] != '"stale"'


@pytest.mark.asyncio
async def test_logs_limit_returns_latest_rows_in_order_and_after_id_still_pages(
    tmp_path, monkeypatch,
):
    from app import db
    from app.routes import sessions

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "long-history.db")
    db.init_db()
    monkeypatch.setattr(sessions.manager, "get_session_id", lambda _name, _scope: "session-1")
    monkeypatch.setattr(sessions, "get_logs", db.get_logs)
    timestamp = datetime.now(timezone.utc)
    db.save_session({
        "id": "session-1", "name": "worker", "scope": "/scope",
        "cwd": "/scope", "model": "test", "system_prompt": "",
        "status": "idle", "session_id": None, "cost_usd": 0,
        "worktree_path": "/scope", "branch": "test", "is_orchestrator": False,
        "color": "#000000", "created_at": timestamp.isoformat(), "finished_at": None,
    })
    for index in range(1200):
        db.add_log("session-1", timestamp, "text", f"row-{index}")

    tail = await sessions.get_session_logs("worker", _request(), "/scope", limit=3)
    full = await sessions.get_session_logs("worker", _request(), "/scope")
    page = await sessions.get_session_logs(
        "worker", _request(), "/scope", after_id=1197,
    )

    assert [row["id"] for row in json.loads(tail.body)] == [1198, 1199, 1200]
    assert [row["content"] for row in json.loads(tail.body)] == [
        "row-1197", "row-1198", "row-1199",
    ]
    full_rows = json.loads(full.body)
    assert len(full_rows) == 1200
    assert [full_rows[0]["id"], full_rows[-1]["id"]] == [1, 1200]
    assert [row["id"] for row in json.loads(page.body)] == [1198, 1199, 1200]
