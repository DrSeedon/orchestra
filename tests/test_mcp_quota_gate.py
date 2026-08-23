"""Края MCP потребляют один центральный вердикт допуска; `unknown` пропускает (#343)."""

import pytest

import app.mcp_stdio as mcp

NOW = 2_000_000_000.0


def _review_text(result):
    if isinstance(result, str):
        return result
    return "\n".join(block.text for block in result.content if block.type == "text")


def _readiness(state="available", provider="codex"):
    """Ровно то, что отдаёт `/api/usage/readiness` — `QuotaDecision.to_dict()`."""
    return {
        "state": state,
        "allowed": state != "blocked",
        "model": "gpt-5.6-sol",
        "provider": provider,
        "provider_label": "Codex" if provider == "codex" else "Codex Spark",
        "lane": "sol",
        "gated": True,
        "utilization": 70 if state == "blocked" else 1,
        "progress": 0.5,
        "tolerance_pp": 5.5,
        "limit_pct": 55.5,
        "hard_limit_pct": 99.0,
        "observed_at": NOW - 10,
        "valid_until": NOW + 290,
        "reset_at": None,
        "window_starts_at": None,
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
        if path.endswith("/initial-deliveries"):
            return {
                "ok": True,
                "delivery_id": (kwargs.get("json") or {}).get("delivery_id"),
                "delivery_state": "ACCEPTED",
            }
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
    assert [path for path, _body in api.calls][-1].endswith("/initial-deliveries")


@pytest.mark.asyncio
async def test_spawn_server_quota_refusal_creates_no_delivery(api):
    api.state["create_error"] = mcp.ApiToolError(
        code="weekly_quota_blocked",
        message="Claude quota is 97% — above the line limit 60%",
        status=429,
        retryable=False,
    )

    with pytest.raises(mcp.ApiToolError) as caught:
        await _spawn(api)

    assert caught.value.code == "weekly_quota_blocked"
    assert [path for path, _body in api.calls] == ["/api/sessions"]


@pytest.mark.asyncio
async def test_codex_review_is_blocked_before_the_bg_job(api):
    api.state["readiness"] = _readiness("blocked")

    with pytest.raises(mcp.ApiToolError) as caught:
        await _review(api)

    assert caught.value.code == "weekly_quota_blocked"
    assert caught.value.retryable is False
    assert "70%" in caught.value.message
    assert "/api/bg/jobs" not in [path for path, _body in api.calls]


@pytest.mark.asyncio
@pytest.mark.parametrize("answer", [
    _readiness("unknown"),
    _readiness("not_applicable"),
    {"unexpected": "shape"},
    None,
    mcp.ApiToolError(code="transport_error", message="offline"),
])
async def test_review_fails_open_on_unknown_malformed_or_transport(api, answer):
    """Сквозное решение: неизвестная квота ПРОПУСКАЕТ и здесь.

    Раньше ревью упиралось в 429 там, где спавн той же модели проходил, — два
    разных ответа одного правила (#227).
    """
    api.state["readiness"] = answer

    assert "bg-test" in _review_text(await _review(api))
    assert "/api/bg/jobs" in [path for path, _body in api.calls]


@pytest.mark.parametrize("state", ["available", "blocked"])
def test_only_a_blocked_verdict_produces_a_refusal(state):
    refusal = mcp._quota_refusal_from_readiness("gpt-5.6-sol", _readiness(state))
    assert (refusal is None) is (state == "available")
    if refusal is not None:
        assert refusal.code == "weekly_quota_blocked"
        assert refusal.retryable is False


@pytest.mark.parametrize("utilization", [None, "70", True])
def test_blocked_without_a_usable_number_does_not_invent_a_refusal(utilization):
    """Отказ обязан назвать число. Нет числа — нет и отказа, а не отказ без причины."""
    response = {**_readiness("blocked"), "utilization": utilization}
    assert mcp._quota_refusal_from_readiness("gpt-5.6-sol", response) is None


@pytest.mark.asyncio
async def test_available_review_starts_job(api):
    result = await _review(api)
    assert "bg-test" in _review_text(result)
    assert "/api/bg/jobs" in [path for path, _body in api.calls]


@pytest.mark.asyncio
async def test_review_defaults_to_luna_the_always_fast_lane(api):
    """Luna всегда Fast и всегда по умолчанию, включая `codex_review` (#343)."""
    assert mcp._CODEX_REVIEW_DEFAULT_MODEL == "gpt-5.6-luna"
    assert mcp._resolve_codex_review_model("luna") == "gpt-5.6-luna"


@pytest.mark.asyncio
async def test_change_model_is_control_action_even_when_target_bucket_blocked(api):
    api.state["readiness"] = _readiness("blocked")

    result = await mcp.change_worker_model(name="w", model="gpt-5.6-sol")

    assert "Model changed" in result
    assert not [path for path, _body in api.calls if path == "/api/usage/readiness"]
    assert [path for path, _body in api.calls] == ["/api/sessions/w/change-model"]
    assert api.calls[0][1]["fresh"] is True
