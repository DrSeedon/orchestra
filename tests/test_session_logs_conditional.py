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
