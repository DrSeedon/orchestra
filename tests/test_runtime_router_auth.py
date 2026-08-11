import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.auth import create_session, require_operator_session


def _request(*, cookie="", authorization=""):
    headers = []
    if cookie:
        headers.append((b"cookie", f"session={cookie}".encode()))
    if authorization:
        headers.append((b"authorization", authorization.encode()))
    return Request({"type": "http", "method": "PUT", "path": "/", "headers": headers})


def test_operator_mutation_requires_enabled_dashboard_auth(monkeypatch):
    monkeypatch.delenv("DASHBOARD_USER", raising=False)
    monkeypatch.delenv("DASHBOARD_PASSWORD", raising=False)

    with pytest.raises(HTTPException) as caught:
        require_operator_session(_request())

    assert caught.value.status_code == 403


def test_operator_mutation_accepts_valid_dashboard_cookie(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USER", "operator")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "secret")

    require_operator_session(_request(cookie=create_session("operator")))


def test_internal_token_without_cookie_is_not_operator_authority(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USER", "operator")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "secret")
    monkeypatch.setenv("INTERNAL_TOKEN", "agent-token")

    with pytest.raises(HTTPException) as caught:
        require_operator_session(_request(authorization="Bearer agent-token"))

    assert caught.value.status_code == 403
