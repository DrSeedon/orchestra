"""#192: change-model must load an idle unloaded session instead of 404."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.responses import JSONResponse


def _status_body(response):
    if isinstance(response, JSONResponse):
        return response.status_code, json.loads(response.body)
    return 200, response


@pytest.mark.asyncio
async def test_change_model_loads_unloaded_idle_worker(monkeypatch):
    from app.routes import sessions as routes

    live = SimpleNamespace(
        loaded=True,
        change_model=AsyncMock(
            return_value={"ok": True, "model": "gpt-5.6-sol", "changed": False},
        ),
    )
    detached = SimpleNamespace(loaded=False)
    monkeypatch.setattr(routes.manager, "get_by_name", lambda *_a, **_k: detached)
    monkeypatch.setattr(routes.manager, "ensure_loaded", AsyncMock(return_value=live))

    response = await routes.change_model(
        "feat-charts", {"scope": "/s", "model": "gpt-5.6-sol"},
    )
    status, body = _status_body(response)
    assert status == 200
    assert body["ok"] is True
    assert body["model"] == "gpt-5.6-sol"
    routes.manager.ensure_loaded.assert_awaited_once_with("feat-charts", "/s")
    live.change_model.assert_awaited_once_with("gpt-5.6-sol", fresh=False)


@pytest.mark.asyncio
async def test_change_model_missing_session_is_404(monkeypatch):
    from app.routes import sessions as routes

    monkeypatch.setattr(routes.manager, "get_by_name", lambda *_a, **_k: None)
    monkeypatch.setattr(routes.manager, "ensure_loaded", AsyncMock(return_value=None))
    monkeypatch.setattr(routes.manager, "sessions", {})
    monkeypatch.setattr(routes, "get_all_sessions", lambda: [])

    response = await routes.change_model(
        "ghost", {"scope": "/s", "model": "gpt-5.6-sol"},
    )
    status, body = _status_body(response)
    assert status == 404
    assert body["code"] == "worker_not_found"
    assert body["worker"] == "ghost"


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", [
    "compact", "history", "rollback", "restart", "clear", "change_model",
])
async def test_worker_name_refusal_distinguishes_foreign_scope_for_all_loaded_routes(
    operation, monkeypatch,
):
    from app.routes import sessions as routes

    calls = {
        "compact": lambda: routes.compact_session(
            "globe-astra", routes.ScopeRequest(scope="/requested"),
        ),
        "history": lambda: routes.session_history("globe-astra", "/requested"),
        "rollback": lambda: routes.rollback_session(
            "globe-astra", routes.ScopeRequest(scope="/requested"),
        ),
        "restart": lambda: routes.restart_cli(
            "globe-astra", routes.ScopeRequest(scope="/requested"),
        ),
        "clear": lambda: routes.clear_session(
            "globe-astra", routes.ScopeRequest(scope="/requested"),
        ),
        "change_model": lambda: routes.change_model(
            "globe-astra", {"scope": "/requested", "model": "gpt-5.6-sol"},
        ),
    }
    monkeypatch.setattr(routes.manager, "ensure_loaded", AsyncMock(return_value=None))
    monkeypatch.setattr(
        routes.manager,
        "sessions",
        {"foreign-id": SimpleNamespace(name="globe-astra", scope="/foreign")},
    )
    monkeypatch.setattr(routes, "get_all_sessions", lambda: [])

    response = await calls[operation]()
    status, body = _status_body(response)
    assert status == 404
    assert body["code"] == "worker_in_other_scope"
    assert body["worker"] == "globe-astra"
    assert body["scopes"] == ["/foreign"]


@pytest.mark.asyncio
async def test_change_model_keeps_explicit_fresh_escape_hatch(monkeypatch):
    from app.routes import sessions as routes

    live = SimpleNamespace(
        loaded=True,
        change_model=AsyncMock(return_value={"ok": True, "changed": True}),
    )
    monkeypatch.setattr(routes.manager, "ensure_loaded", AsyncMock(return_value=live))

    response = await routes.change_model(
        "feat-charts",
        {"scope": "/s", "model": "gpt-5.6-sol", "fresh": True},
    )

    status, body = _status_body(response)
    assert status == 200
    assert body["ok"] is True
    live.change_model.assert_awaited_once_with("gpt-5.6-sol", fresh=True)
