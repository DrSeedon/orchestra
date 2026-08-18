import asyncio

import pytest
from fastapi import HTTPException
from starlette.requests import Request

import app.db as db
from app.auth import create_session
from app.routes.system import (
    quota_controller_policy,
    replace_quota_controller_policy,
    rollback_quota_controller_policy,
)


def _request(method: str, *, cookie: str = "", authorization: str = "") -> Request:
    headers = []
    if cookie:
        headers.append((b"cookie", f"session={cookie}".encode()))
    if authorization:
        headers.append((b"authorization", authorization.encode()))
    return Request({"type": "http", "method": method, "path": "/api/usage/quota-controller/policy", "headers": headers})


@pytest.fixture
def api_policy_db(tmp_path, monkeypatch):
    path = tmp_path / "quota-api.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    db.quota_controller_connection(path).close()
    monkeypatch.setenv("DASHBOARD_USER", "owner")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "secret")
    return path


def test_policy_get_and_put_require_operator_cookie(api_policy_db, monkeypatch):
    monkeypatch.setenv("INTERNAL_TOKEN", "internal")
    with pytest.raises(HTTPException) as denied:
        asyncio.run(quota_controller_policy(_request("GET", authorization="Bearer internal")))
    assert denied.value.status_code == 403

    cookie = create_session("owner")
    result = asyncio.run(quota_controller_policy(_request("GET", cookie=cookie)))
    assert result["lanes"]["luna"]["threshold"] == 98

    updated = asyncio.run(replace_quota_controller_policy(
        _request("PUT", cookie=cookie),
        {"thresholds": {"luna": 97}, "reason": "operator test", "actor": "forged"},
    ))
    assert updated["lanes"]["luna"]["threshold"] == 97
    assert updated["audit"][0]["actor"] == "owner"


def test_policy_rollback_route_is_audited(api_policy_db):
    cookie = create_session("owner")
    asyncio.run(replace_quota_controller_policy(
        _request("PUT", cookie=cookie),
        {"thresholds": {"luna": 97}, "reason": "operator test"},
    ))
    restored = asyncio.run(rollback_quota_controller_policy(
        _request("POST", cookie=cookie), {"reason": "button rollback"},
    ))
    assert restored["lanes"]["luna"]["threshold"] == 98
    assert restored["audit"][0]["action"] == "rollback"
