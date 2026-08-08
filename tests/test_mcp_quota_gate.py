"""MCP edges consume the central weekly worker quota contract (#168)."""

import pytest

import app.mcp_stdio as mcp


def _readiness(state="available", provider="codex", *, alternatives=None):
    return {
        "policy": "worker-weekly-v1",
        "state": state,
        "provider": provider,
        "provider_label": "Codex" if provider == "codex" else "Codex Spark",
        "weekly_utilization": 95 if state == "blocked" else 1,
        "threshold": 95,
        "observed_at": 2_000_000_000,
        "valid_until": 2_000_000_300,
        "reset_at": None,
        "alternatives": alternatives or [],
        "reason": "test",
    }


@pytest.fixture
def api(monkeypatch, tmp_path):
    calls = []
    state = {
        "readiness": _readiness(),
        "create_error": None,
    }

    async def fake_api(method, path, **kwargs):
        calls.append((path, kwargs.get("json")))
        if path == "/api/usage/readiness":
            answer = state["readiness"]
            if isinstance(answer, Exception):
                raise answer
            return answer
        if path == "/api/sessions":
            if state["create_error"]:
                raise state["create_error"]
            return {
                "worktree_path": str(tmp_path), "branch": "b",
                "repo_path": str(tmp_path), "git_common_dir": str(tmp_path / ".git"),
            }
        if path.startswith("/api/sessions/") and path.endswith("/send"):
            return {"ok": True}
        if path == "/api/bg/jobs":
            return {"id": "bg-test"}
        if path.endswith("/change-model"):
            return {"changed": True, "old_model": "claude-opus-5[1m]", "model": "gpt-5.6-sol"}
        return {"cwd": str(tmp_path), "worktree_path": str(tmp_path), "scope": str(tmp_path)}

    monkeypatch.setattr(mcp, "_api", fake_api)
    monkeypatch.setattr(mcp, "WORKER_NAME", "gate-test")
    monkeypatch.setattr(mcp, "SCOPE", str(tmp_path))
    monkeypatch.setattr(mcp, "_codex_bin", lambda: "/usr/bin/codex")
    return type("Api", (), {"calls": calls, "state": state, "tmp_path": tmp_path})


async def _spawn(api):
    return await mcp.spawn_worker(
        name="w", task="t", repo_path=str(api.tmp_path), model="gpt-5.6-sol",
    )


async def _review(api):
    return await mcp.codex_review(target="research.md", output="r.md", mode="exec")


@pytest.mark.asyncio
async def test_spawn_uses_role_aware_server_preflight_and_execution_recheck(api):
    assert "spawned" in await _spawn(api)
    create = next(body for path, body in api.calls if path == "/api/sessions")
    assert create["planned_initial_turn"] is True
    assert not [path for path, _body in api.calls if path == "/api/usage/readiness"]
    assert [path for path, _body in api.calls][-1].endswith("/send")


@pytest.mark.asyncio
async def test_spawn_server_quota_refusal_creates_no_delivery(api):
    api.state["create_error"] = mcp.ApiToolError(
        code="weekly_quota_blocked",
        message="Claude weekly quota is 97%; available provider: Codex",
        status=429,
        retryable=False,
    )

    with pytest.raises(mcp.ApiToolError) as caught:
        await _spawn(api)

    assert caught.value.code == "weekly_quota_blocked"
    assert [path for path, _body in api.calls] == ["/api/sessions"]


@pytest.mark.asyncio
async def test_codex_review_is_blocked_before_bg_job_with_dynamic_alternative(api):
    api.state["readiness"] = _readiness(
        "blocked",
        alternatives=[{"provider": "anthropic", "label": "Claude"}],
    )

    with pytest.raises(mcp.ApiToolError) as caught:
        await _review(api)

    assert caught.value.code == "weekly_quota_blocked"
    assert caught.value.retryable is False
    assert "Claude" in caught.value.message
    assert "/api/bg/jobs" not in [path for path, _body in api.calls]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "answer",
    [
        _readiness("unknown"),
        {"unexpected": "shape"},
        {**_readiness(), "policy": "legacy"},
        mcp.ApiToolError(code="transport_error", message="offline"),
    ],
)
async def test_codex_review_fails_closed_on_unknown_malformed_legacy_or_transport(api, answer):
    api.state["readiness"] = answer

    with pytest.raises(mcp.ApiToolError) as caught:
        await _review(api)

    assert caught.value.code == "weekly_quota_unknown"
    assert caught.value.retryable is False
    assert "/api/bg/jobs" not in [path for path, _body in api.calls]


@pytest.mark.asyncio
async def test_available_review_starts_job(api):
    result = await _review(api)
    assert "bg-test" in result
    assert "/api/bg/jobs" in [path for path, _body in api.calls]


@pytest.mark.asyncio
async def test_change_model_is_control_action_even_when_target_bucket_blocked(api):
    api.state["readiness"] = _readiness("blocked")

    result = await mcp.change_worker_model(name="w", model="gpt-5.6-sol")

    assert "Model changed" in result
    assert not [path for path, _body in api.calls if path == "/api/usage/readiness"]
    assert [path for path, _body in api.calls] == ["/api/sessions/w/change-model"]
