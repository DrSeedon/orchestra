from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.auth import create_session
from app.routes import system
from app.runtime_router import RoutingDecision, RoutingPolicyV1


def _request(*, cookie="", authorization=""):
    headers = []
    if cookie:
        headers.append((b"cookie", f"session={cookie}".encode()))
    if authorization:
        headers.append((b"authorization", authorization.encode()))
    return Request({"type": "http", "method": "PUT", "path": "/", "headers": headers})


class _Router:
    def __init__(self):
        self.replacements = []
        self.explanations = []

    async def status(self):
        return {"contract_version": "routing-v2", "policy": {"revision": 4}}

    async def replace_policy(self, payload):
        self.replacements.append(payload)
        return RoutingPolicyV1.model_validate(payload)

    async def explain(self, request, observation, **kwargs):
        self.explanations.append((request, observation, kwargs))
        return RoutingDecision(
            policy_revision=4,
            policy_mode="quota",
            task_class=request.task_class,
            state="queued",
            selected_lane=None,
            selected_runtime=None,
            selected_model=None,
            reason="synthetic",
            candidates=(),
        )


@pytest.fixture
def api_router(monkeypatch):
    fake = _Router()
    monkeypatch.setattr(system, "get_runtime_router", lambda: fake)
    return fake


@pytest.mark.asyncio
async def test_policy_status_is_read_only_projection(api_router):
    result = await system.routing_policy_status()

    assert result == {"contract_version": "routing-v2", "policy": {"revision": 4}}
    assert api_router.replacements == []
    assert api_router.explanations == []


@pytest.mark.asyncio
async def test_policy_put_requires_cookie_and_returns_active_document(
    api_router, monkeypatch,
):
    monkeypatch.setenv("DASHBOARD_USER", "operator")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "secret")
    payload = {
        "schema_version": 1,
        "revision": 1,
        "mode": "manifest_default",
        "codex_access": "all",
    }

    result = await system.replace_routing_policy(
        _request(cookie=create_session("operator")),
        payload,
    )

    assert result["contract_version"] == "routing-v2"
    assert result["policy"] == payload
    assert api_router.replacements == [payload]


@pytest.mark.asyncio
async def test_policy_put_rejects_internal_token_without_cookie(
    api_router, monkeypatch,
):
    monkeypatch.setenv("DASHBOARD_USER", "operator")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "secret")
    monkeypatch.setenv("INTERNAL_TOKEN", "agent-token")

    with pytest.raises(HTTPException) as caught:
        await system.replace_routing_policy(
            _request(authorization="Bearer agent-token"),
            {"schema_version": 1, "revision": 1, "mode": "manifest_default"},
        )

    assert caught.value.status_code == 403
    assert api_router.replacements == []


@pytest.mark.asyncio
async def test_explain_uses_only_synthetic_inputs_and_does_not_admit(api_router):
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    result = await system.explain_routing_policy({
        "request": {
            "task_class": "review",
            "implementation_runtimes": ["claude"],
        },
        "observation": {
            "providers": {},
            "observed_at_by_provider": {},
        },
        "claude_baseline": {"pct": 0, "ts": now.isoformat()},
        "latched_window_ids": ["window-1"],
        "terminal_limited_buckets": ["codex"],
        "now": now.isoformat(),
    })

    request, observation, kwargs = api_router.explanations[0]
    assert result["decision"]["reason"] == "synthetic"
    assert request.task_class == "review"
    assert request.implementation_runtimes == frozenset({"claude"})
    assert observation == {"providers": {}, "observed_at_by_provider": {}}
    assert kwargs["latched_window_ids"] == frozenset({"window-1"})
    assert kwargs["terminal_limited_buckets"] == frozenset({"codex"})
    assert api_router.replacements == []


@pytest.mark.asyncio
async def test_explain_rejects_unknown_fields_before_router_call(api_router):
    with pytest.raises(HTTPException) as caught:
        await system.explain_routing_policy({
            "request": {"task_class": "worker_general", "model": "gpt-5.6-sol"},
            "observation": {},
        })

    assert caught.value.status_code == 422
    assert api_router.explanations == []
