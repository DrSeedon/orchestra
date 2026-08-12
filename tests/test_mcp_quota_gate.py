"""MCP edges consume the central weekly worker quota contract (#168)."""

import pytest
from datetime import datetime, timezone

import app.mcp_stdio as mcp

NOW = 2_000_000_000.0


def _readiness(state="available", provider="codex", *, alternatives=None):
    return {
        "policy": "worker-weekly-v1",
        "state": state,
        "model": "gpt-5.6-sol",
        "provider": provider,
        "provider_label": "Codex" if provider == "codex" else "Codex Spark",
        "weekly_utilization": 95 if state == "blocked" else 1,
        "threshold": 95,
        "observed_at": NOW - 10,
        "valid_until": NOW + 290,
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
        return {
            "id": "gate-requester", "cwd": str(tmp_path),
            "worktree_path": str(tmp_path), "scope": str(tmp_path),
        }

    monkeypatch.setattr(mcp, "_api", fake_api)
    monkeypatch.setattr(mcp, "WORKER_NAME", "gate-test")
    monkeypatch.setattr(mcp, "SCOPE", str(tmp_path))
    monkeypatch.setattr(mcp, "_codex_bin", lambda: "/usr/bin/codex")
    monkeypatch.setattr(mcp.time, "time", lambda: NOW)
    return type("Api", (), {"calls": calls, "state": state, "tmp_path": tmp_path})


async def _spawn(api):
    return await mcp.spawn_worker(
        name="w", task="t", repo_path=str(api.tmp_path), model="gpt-5.6-sol",
    )


async def _review(api):
    return await mcp.codex_review(
        context="PROJECT CONTEXT: quota-gate test fixture",
        target="research.md", output="r.md", mode="exec",
    )


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
    ("answer", "expected_code"),
    [
        (_readiness("unknown"), "weekly_quota_unknown"),
        ({"unexpected": "shape"}, "weekly_quota_upgrade_required"),
        ({**_readiness(), "policy": "legacy"}, "weekly_quota_upgrade_required"),
        (mcp.ApiToolError(code="transport_error", message="offline"), "weekly_quota_unknown"),
    ],
)
async def test_codex_review_fails_closed_on_unknown_malformed_legacy_or_transport(
    api, answer, expected_code,
):
    api.state["readiness"] = answer

    with pytest.raises(mcp.ApiToolError) as caught:
        await _review(api)

    assert caught.value.code == expected_code
    assert caught.value.retryable is False
    assert "/api/bg/jobs" not in [path for path, _body in api.calls]


@pytest.mark.asyncio
async def test_legacy_server_requires_explicit_upgrade_before_review(api):
    api.state["readiness"] = {
        "provider": "codex", "state": "available",
        "reason": "provider capacity is open", "reset_at": None,
    }

    with pytest.raises(mcp.ApiToolError) as caught:
        await _review(api)

    assert caught.value.code == "weekly_quota_upgrade_required"
    assert "FastAPI" in caught.value.message
    assert "/api/bg/jobs" not in [path for path, _body in api.calls]


@pytest.mark.asyncio
async def test_expired_available_readiness_is_rejected_before_review(api):
    api.state["readiness"] = {
        **_readiness(),
        "observed_at": 1_999_999_699.0,
        "valid_until": 1_999_999_999.0,
    }

    with pytest.raises(mcp.ApiToolError) as caught:
        await _review(api)

    assert caught.value.code == "weekly_quota_unknown"
    assert "expired" in caught.value.message
    assert "/api/bg/jobs" not in [path for path, _body in api.calls]


def _legacy_client_allows(readiness):
    if readiness.get("state") != "reset":
        return True
    if readiness.get("provider") not in {"codex", "codex_spark"}:
        return True
    try:
        datetime.fromisoformat(str(readiness.get("reset_at")).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return True
    return False


def _current_v1_client_allows(readiness):
    if readiness.get("policy") != "worker-weekly-v1":
        return False
    return readiness.get("state") in {"available", "not_applicable"}


@pytest.mark.parametrize(
    ("name", "client", "response", "allows"),
    [
        ("legacy+legacy historical", _legacy_client_allows,
         {"provider": "codex", "state": "available", "reset_at": None}, True),
        ("legacy+current forbidden", _legacy_client_allows, _readiness("blocked"), True),
        ("legacy+dual below95", _legacy_client_allows,
         {**_readiness(), "wire_version": 2, "decision_state": "available"}, True),
        ("legacy+dual blocked", _legacy_client_allows,
         {**_readiness(), "wire_version": 2, "decision_state": "blocked",
          "state": "reset", "reset_at": "2033-05-18T04:33:20+00:00"}, False),
        ("current+legacy", _current_v1_client_allows,
         {"provider": "codex", "state": "available", "reset_at": None}, False),
        ("current+dual below95", _current_v1_client_allows,
         {**_readiness(), "wire_version": 2, "decision_state": "available"}, True),
        ("current+dual blocked", _current_v1_client_allows,
         {**_readiness(), "wire_version": 2, "decision_state": "blocked",
          "state": "reset", "reset_at": "2033-05-18T04:33:20+00:00"}, False),
    ],
)
def test_old_and_current_client_rollout_matrix(name, client, response, allows):
    assert client(response) is allows, name


@pytest.mark.parametrize("state", ["available", "blocked"])
def test_new_client_accepts_current_v1_envelope_with_fresh_unix_timestamps(state):
    refusal = mcp._quota_refusal_from_readiness(
        "gpt-5.6-sol", _readiness(state), now=NOW,
    )
    assert (refusal is None) is (state == "available")
    if refusal is not None:
        assert refusal.code == "weekly_quota_blocked"


@pytest.mark.parametrize(
    "observed_at", [NOW - 299.999, "2033-05-18T03:28:20.001000+00:00"],
)
def test_new_client_accepts_fresh_unix_and_timezone_aware_iso(observed_at):
    response = {**_readiness(), "observed_at": observed_at, "valid_until": NOW + 0.001}
    assert mcp._quota_refusal_from_readiness(
        "gpt-5.6-sol", response, now=NOW,
    ) is None


@pytest.mark.parametrize(
    ("observed_at", "valid_until", "reason"),
    [
        (NOW - 300, NOW, "expired"),
        (NOW - 1, NOW + 300, "300s policy"),
        (NOW + 5.001, NOW + 200, "future"),
        ("2033-05-18T03:33:20", NOW + 1, "missing or malformed"),
        ("not-a-date", NOW + 1, "missing or malformed"),
    ],
)
def test_new_client_fails_closed_on_freshness_boundaries(observed_at, valid_until, reason):
    response = {**_readiness(), "observed_at": observed_at, "valid_until": valid_until}
    refusal = mcp._quota_refusal_from_readiness(
        "gpt-5.6-sol", response, now=NOW,
    )
    assert refusal is not None
    assert refusal.code == "weekly_quota_unknown"
    assert reason in refusal.message


def test_not_applicable_requires_matching_grok_model_and_provider():
    response = {
        **_readiness("not_applicable", provider="grok"),
        "model": "grok-4.5",
    }
    assert mcp._quota_refusal_from_readiness("grok-4.5", response, now=NOW) is None
    refusal = mcp._quota_refusal_from_readiness("gpt-5.6-sol", response, now=NOW)
    assert refusal is not None
    assert refusal.code == "weekly_quota_unknown"


def test_new_client_prefers_dual_canonical_state_over_legacy_projection():
    response = {
        **_readiness(), "wire_version": 2,
        "decision_state": "blocked", "state": "reset",
    }
    refusal = mcp._quota_refusal_from_readiness(
        "gpt-5.6-sol", response, now=NOW,
    )
    assert refusal is not None
    assert refusal.code == "weekly_quota_blocked"


@pytest.mark.parametrize(
    "response",
    [
        {**_readiness("blocked"), "decision_state": "available"},
        {**_readiness(), "wire_version": 2},
        {**_readiness(), "wire_version": 2.0, "decision_state": "available"},
        {**_readiness(), "wire_version": True, "decision_state": "available"},
    ],
)
def test_new_client_binds_canonical_state_to_exact_dual_wire_version(response):
    refusal = mcp._quota_refusal_from_readiness(
        "gpt-5.6-sol", response, now=NOW,
    )
    assert refusal is not None
    assert refusal.code == "weekly_quota_unknown"


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
