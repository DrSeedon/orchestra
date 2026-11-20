import hashlib
import hmac
import time
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.mcp_proof import issue_mcp_proof
from app.routes import skillcache
from app.session import AgentStatus


def test_only_mcp_proof_and_current_authorized_turn_can_run(monkeypatch):
    monkeypatch.setenv("INTERNAL_TOKEN", "fixture")
    sid = "test-session"
    session = SimpleNamespace(status=AgentStatus.RUNNING, role="worker", scope="fixture", disabled_tools=[],
                              _skillcache_invocation_id="test-invocation", _skillcache_exclusion=None)
    monkeypatch.setitem(skillcache.manager.sessions, sid, session)
    monkeypatch.setattr(skillcache.service, "settings", lambda: {})
    monkeypatch.setattr(skillcache.service, "access", lambda _, **access: access)
    monkeypatch.setattr(skillcache.service, "execute", lambda request, authorize: authorize() or {"status": "revoked"})
    app = FastAPI()
    app.include_router(skillcache.router)
    headers = {"X-Orchestra-Session-Id": sid, "X-Orchestra-Mcp-Proof": issue_mcp_proof(sid)}
    with TestClient(app) as client:
        assert client.post(skillcache.ENDPOINT, json={}, headers={"X-Orchestra-Session-Id": sid}).status_code == 403
        reply = client.post(skillcache.ENDPOINT, json={}, headers=headers)
        assert reply.json() == {"principal": f"orchestra:{sid}", "invocation": "test-invocation",
                                "origin": "orchestra", "scope": "fixture"}
        session._skillcache_exclusion = "steered"
        assert client.post(skillcache.ENDPOINT, json={}, headers=headers).json() == {"status": "revoked"}


def test_kesha_proof_is_bound_to_chat_turn_timestamp_and_body(monkeypatch):
    key = "a" * 32
    monkeypatch.setenv("ORCHESTRA_SKILLCACHE_KESHA_KEY", key)
    monkeypatch.setattr(skillcache.service, "settings", lambda: {})
    monkeypatch.setattr(skillcache.service, "access", lambda _, **access: access)
    monkeypatch.setattr(skillcache.service, "execute", lambda request, authorize: authorize() or {"status": "revoked"})
    app = FastAPI()
    app.include_router(skillcache.router)
    invocation = "b" * 32
    timestamp = str(int(time.time()))
    body = b'{"action":"run"}'
    payload = f"skillcache-v1:42:{invocation}:{timestamp}:".encode() + body
    headers = {"X-SkillCache-Chat": "42", "X-SkillCache-Invocation": invocation,
               "X-SkillCache-At": timestamp, "X-SkillCache-Proof": hmac.new(key.encode(), payload, hashlib.sha256).hexdigest()}
    with TestClient(app) as client:
        assert client.post(skillcache.ENDPOINT, content=body, headers=headers).json() == {
            "principal": "kesha:42", "invocation": invocation, "origin": "kesha",
        }
        assert client.post(skillcache.ENDPOINT, content=body + b" ", headers=headers).status_code == 403
        assert client.post(skillcache.ENDPOINT, content=body, headers={**headers, "X-SkillCache-Chat": "43"}).status_code == 403

