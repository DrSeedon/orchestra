from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import db, session_turns
from app.routes.sessions import CreateSessionRequest, SendRequest


def test_orchestra_wave15_schemas_and_push(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "w15.db")
    db.init_db()

    req = CreateSessionRequest(name="w-kesha", cwd=str(tmp_path), kesha_worker=True)
    assert req.kesha_worker is True

    sreq = SendRequest(channel="kesha_worker", message="do task", scope=str(tmp_path))
    assert sreq.channel == "kesha_worker"


@pytest.mark.asyncio
async def test_push_kesha_inbox_if_subscribed_posts_with_bearer(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "w15_push.db")
    db.init_db()
    db.kv_set("kesha_notify:sid-1", "1")
    monkeypatch.setenv("ORCHESTRA_ALLOW_KESHA_INBOX_TEST", "1")
    monkeypatch.setenv("INTERNAL_TOKEN", "tok-123")
    monkeypatch.setenv("KESHA_INBOX_URL", "http://127.0.0.1:18081/inbox")

    posted = []

    class FakeResp:
        status = 200
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False

    class FakeClient:
        def __init__(self, **_kw):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
        def post(self, url, json=None, headers=None):
            posted.append((url, json, headers))
            return FakeResp()

    import aiohttp
    monkeypatch.setattr(aiohttp, "ClientSession", FakeClient)

    await session_turns._push_kesha_inbox_if_subscribed(
        "sid-1", "worker-1", "/home/kesha/proj", ok=True, stop_reason="end_turn", summary_text="All green!"
    )
    assert len(posted) == 1
    url, body, headers = posted[0]
    assert url == "http://127.0.0.1:18081/inbox"
    assert headers == {"Authorization": "Bearer tok-123"}
    assert body["sender"] == "worker-1" and "All green!" in body["message"]
