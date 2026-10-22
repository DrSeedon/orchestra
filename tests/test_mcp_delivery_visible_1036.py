"""V-1036: actual MCP HTTP decoding and initial cancellation route."""

import json
import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
from starlette.requests import Request

from app import mcp_stdio as mcp


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["WAITING_QUOTA", "FAILED_BEFORE_SUBMIT", "DELIVERY_UNKNOWN"])
async def test_accepted_receipt_error_is_not_an_api_rejection(monkeypatch, state):
    did = str(uuid.uuid4())
    payload = {
        "ok": True, "delivery_id": did, "delivery_state": state,
        "error": {"code": state, "message": "exact error", "outcome_unknown": False},
        "next_action": {"code": state, "eta_at": 2_000_000_000},
    }
    transport = httpx.MockTransport(lambda _request: httpx.Response(202, json=payload))
    client = httpx.AsyncClient
    monkeypatch.setattr(mcp.httpx, "AsyncClient", lambda **kwargs: client(transport=transport, **kwargs))
    assert await mcp._api("POST", "/api/sessions/target/send", json={}) == payload


@pytest.mark.asyncio
async def test_real_http_rejection_stays_loud_and_keeps_delivery_id(monkeypatch):
    did = str(uuid.uuid4())
    payload = {"ok": False, "delivery_id": did,
               "error": {"code": "DELIVERY_NOT_SUBMITTED", "message": "exact failure"}}
    transport = httpx.MockTransport(lambda _request: httpx.Response(409, json=payload))
    client = httpx.AsyncClient
    monkeypatch.setattr(mcp.httpx, "AsyncClient", lambda **kwargs: client(transport=transport, **kwargs))
    with pytest.raises(mcp.ApiToolError) as caught:
        await mcp._api("POST", "/api/sessions/target/send", json={})
    assert caught.value.details["delivery_id"] == did
    assert "exact failure" in caught.value.message
    assert did in caught.value.message


@pytest.mark.asyncio
async def test_list_pending_mcp_calls_authenticated_view_and_is_read_only(monkeypatch):
    api = AsyncMock(return_value={"deliveries": []})
    monkeypatch.setattr(mcp, "_api", api)
    assert await mcp.list_pending_deliveries(target="worker") == {"deliveries": []}
    api.assert_awaited_once_with("GET", "/api/pending-deliveries", params={"target": "worker"})
    assert "list_pending_deliveries" in mcp.READ_ONLY_MCP_TOOLS
    assert "cancel_message_delivery" not in mcp.READ_ONLY_MCP_TOOLS


@pytest.mark.asyncio
async def test_cancel_route_uses_initial_fallback_with_authenticated_source(monkeypatch):
    from app import initial_deliveries, message_deliveries
    from app.routes import sessions

    did = str(uuid.uuid4())
    monkeypatch.setattr(sessions, "_delivery_caller", lambda _request: (False, "source-id"))
    monkeypatch.setattr(message_deliveries, "cancel_message_delivery", lambda *_args: ({}, 404))
    called = []

    def cancel(delivery_id, source_id):
        called.append((delivery_id, source_id))
        return {"ok": True, "delivery_state": "CANCELLED", "delivery_id": delivery_id}, 200

    monkeypatch.setattr(initial_deliveries, "cancel_initial_delivery", cancel)
    response = await sessions.cancel_message_delivery(did, Request({"type": "http"}))
    assert response.status_code == 200
    assert json.loads(response.body)["delivery_state"] == "CANCELLED"
    assert called == [(did, "source-id")]


@pytest.mark.asyncio
async def test_pending_route_requires_identity_and_passes_only_caller(monkeypatch):
    from app import message_deliveries
    from app.routes import sessions

    monkeypatch.setattr(sessions, "_delivery_caller", lambda _request: None)
    response = await sessions.list_pending_deliveries()
    assert response.status_code in {401, 403}
    monkeypatch.setattr(sessions, "_delivery_caller", lambda _request: (False, "source-id"))
    called = []

    def pending(source, target):
        called.append((source, target))
        return []

    monkeypatch.setattr(message_deliveries, "list_pending_deliveries", pending)
    assert await sessions.list_pending_deliveries(target="worker") == {"deliveries": []}
    assert called == [("source-id", "worker")]
