"""Hub pool capacity endpoint: redaction, 5-minute cache, unavailable states."""

import asyncio
import json

import pytest

from app import hub_pool
from app.hub_workspace import HubWorkspaceError

SECRET_ID = "acct-0123456789abcdef"
SECRET_MAIL = "someone@example.invalid"


def _relay() -> dict:
    def account(ident, loaded=True, used=40.0):
        return {
            "id": ident, "creds_loaded": loaded, "email": SECRET_MAIL, "plan": "max",
            "checked_at": "2026-10-22T00:00:00Z", "error": f"bad token for {SECRET_MAIL}",
            "rejected": False,
            "windows": [{"id": "w1", "kind": "five_hour", "label": "5h", "used_pct": used,
                         "resets_at": "2026-10-22T05:00:00Z", "window_minutes": 300}],
            "reset_credits": {"available": 2, "next_id": SECRET_ID,
                              "next_expires_at": "2026-11-01T00:00:00Z"},
            "cooldown_reason": f"limit for {SECRET_MAIL}", "cooldown_until": None,
        }
    return {"providers": {
        "claude": {"active_id": SECRET_ID, "ids": [account("other-id", False, 99), account(SECRET_ID)]},
        "codex": {"active_id": "x", "ids": []},
    }}


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    monkeypatch.setattr(hub_pool, "_cache", {"payload": None, "ts": 0.0, "ttl": 0.0})
    monkeypatch.setattr(hub_pool, "_lock", None)


class _FakeHub:
    calls = 0
    result: object = None

    @classmethod
    def from_env(cls):
        return cls()

    async def run(self, remote, **kw):
        type(self).calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _patch_hub(monkeypatch, result):
    _FakeHub.calls = 0
    _FakeHub.result = result
    monkeypatch.setattr(hub_pool, "HubSsh", _FakeHub)


def test_response_has_no_ids_or_emails_and_uses_the_active_account(monkeypatch):
    _patch_hub(monkeypatch, json.dumps(_relay()).encode())
    pool = asyncio.run(hub_pool.get_hub_pool())
    text = json.dumps(pool)
    assert SECRET_ID not in text and SECRET_MAIL not in text and "other-id" not in text
    assert pool["available"] is True
    claude = pool["providers"]["claude"]
    assert (claude["accounts"], claude["creds_loaded"]) == (2, 1)
    assert claude["windows"] == [{"kind": "five_hour", "label": "5h", "used_pct": 40.0,
                                  "resets_at": "2026-10-22T05:00:00Z", "window_minutes": 300.0}]
    assert claude["reset_credits"] == {"available": 2.0, "next_expires_at": "2026-11-01T00:00:00Z"}
    assert pool["providers"]["codex"]["windows"] == []
    assert "grok" not in pool["providers"]


def test_second_call_is_served_from_cache(monkeypatch):
    _patch_hub(monkeypatch, json.dumps(_relay()).encode())
    asyncio.run(hub_pool.get_hub_pool())
    asyncio.run(hub_pool.get_hub_pool())
    assert _FakeHub.calls == 1
    asyncio.run(hub_pool.get_hub_pool(force=True))
    assert _FakeHub.calls == 2


def test_cache_expires_after_ttl(monkeypatch):
    _patch_hub(monkeypatch, json.dumps(_relay()).encode())
    asyncio.run(hub_pool.get_hub_pool())
    hub_pool._cache["ts"] -= hub_pool.CACHE_TTL + 1
    asyncio.run(hub_pool.get_hub_pool())
    assert _FakeHub.calls == 2


def test_unreachable_hub_is_a_state_not_an_error(monkeypatch):
    _patch_hub(monkeypatch, HubWorkspaceError("hub SSH command failed rc=255: secret-host"))
    pool = asyncio.run(hub_pool.get_hub_pool())
    assert pool["available"] is False and pool["reason"] == "unreachable"
    assert "secret-host" not in json.dumps(pool)
    asyncio.run(hub_pool.get_hub_pool())
    assert _FakeHub.calls == 1  # failure is cached briefly, not retried per poll


def test_garbage_from_hub_is_unavailable(monkeypatch):
    _patch_hub(monkeypatch, b"<html>502</html>")
    assert asyncio.run(hub_pool.get_hub_pool())["reason"] == "bad_response"
    hub_pool._cache["payload"] = None
    _patch_hub(monkeypatch, b'{"nope": 1}')
    assert asyncio.run(hub_pool.get_hub_pool())["reason"] == "bad_response"


def test_not_configured(monkeypatch):
    monkeypatch.delenv("MULTICODE_HUB_SSH", raising=False)
    monkeypatch.delenv("MULTICODE_HUB_SSH_KEY", raising=False)
    pool = asyncio.run(hub_pool.get_hub_pool())
    assert pool["available"] is False and pool["reason"] == "not_configured"


def test_endpoint_returns_pool_and_hides_it_from_non_owner(monkeypatch):
    from fastapi import HTTPException
    from app.routes import system

    _patch_hub(monkeypatch, json.dumps(_relay()).encode())
    monkeypatch.setattr(system, "is_owner_mode", lambda: True)
    assert asyncio.run(system.get_usage_hub_pool())["available"] is True
    monkeypatch.setattr(system, "is_owner_mode", lambda: False)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(system.get_usage_hub_pool())
    assert exc.value.status_code == 404
