"""Гейт по исчерпанной квоте Codex в трёх MCP-тулах (#154).

Обе стороны обязательны. Гард, который проверяет только закрытую сторону, зеленеет
в пустой комнате: он не отличит «блокируем исчерпанный бакет» от «блокируем всегда».
Поэтому каждый тул проверяется и закрытым, и открытым, плюс четыре ветки fail-open.
"""

import re
from datetime import datetime, timedelta, timezone

import pytest

import app.mcp_stdio as mcp

RESET_AT = "2026-08-08T05:53:45+00:00"


def _readiness(state, provider="codex", reset_at=RESET_AT):
    return {"provider": provider, "state": state, "reason": "test", "reset_at": reset_at}


@pytest.fixture
def api(monkeypatch, tmp_path):
    """Перехватывает _api, пишет все пути и отдаёт заранее заданный вердикт квоты."""
    calls = []
    state = {"readiness": _readiness("available")}

    async def fake_api(method, path, **kwargs):
        calls.append(path)
        if path == "/api/usage/readiness":
            answer = state["readiness"]
            if isinstance(answer, Exception):
                raise answer
            return answer
        if path.startswith("/api/sessions/") and path.endswith("/send"):
            return {"ok": True}
        if path == "/api/sessions":
            return {"worktree_path": str(tmp_path), "branch": "b",
                    "repo_path": str(tmp_path), "git_common_dir": str(tmp_path / ".git")}
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


async def _change(api):
    return await mcp.change_worker_model(name="w", model="gpt-5.6-sol")


# --- закрытая сторона -------------------------------------------------------

@pytest.mark.asyncio
async def test_spawn_is_refused_before_any_session_is_created(api):
    api.state["readiness"] = _readiness("reset")

    with pytest.raises(mcp.ApiToolError) as caught:
        await _spawn(api)

    assert caught.value.code == "quota_exhausted"
    # Главное: обречённый worktree не создан.
    assert api.calls == ["/api/usage/readiness"]


@pytest.mark.asyncio
async def test_refusal_names_cause_reset_time_and_the_way_out(api):
    api.state["readiness"] = _readiness("reset")

    with pytest.raises(mcp.ApiToolError) as caught:
        await _spawn(api)

    message = caught.value.message
    assert "квота Codex исчерпана" in message
    assert "codex" in message
    assert "claude-opus-5[1m]" in message
    # Зону НЕ приколачиваем: тест, зависящий от TZ машины, читает живое состояние.
    # Проверяем сам факт перевода — момент отрендерен в локальной зоне И в UTC.
    reset = datetime.fromisoformat(RESET_AT)
    assert f"{reset.astimezone():%Y-%m-%d %H:%M %Z}" in message
    assert f"{reset:%H:%M}Z" in message


@pytest.mark.asyncio
async def test_refusal_carries_time_but_no_permission_to_retry(api):
    """Агент, увидевший retryable=True, ждёт сутки вместо того, чтобы взять Opus."""
    reset = datetime.now(timezone.utc) + timedelta(hours=3)
    api.state["readiness"] = _readiness("reset", reset_at=reset.isoformat())

    with pytest.raises(mcp.ApiToolError) as caught:
        await _spawn(api)

    envelope = caught.value.envelope()
    assert envelope["retryable"] is False
    assert 3 * 3600 - 60 < envelope["retry_after_seconds"] <= 3 * 3600
    assert envelope["details"]["provider"] == "codex"


@pytest.mark.asyncio
async def test_change_worker_model_is_refused(api):
    api.state["readiness"] = _readiness("reset")

    with pytest.raises(mcp.ApiToolError):
        await _change(api)

    assert not [path for path in api.calls if "change-model" in path]


@pytest.mark.asyncio
async def test_codex_review_is_refused_without_creating_a_job(api):
    api.state["readiness"] = _readiness("reset")

    with pytest.raises(mcp.ApiToolError):
        await _review(api)

    assert "/api/bg/jobs" not in api.calls


# --- открытая сторона -------------------------------------------------------

@pytest.mark.asyncio
async def test_all_three_tools_work_when_capacity_is_open(api):
    api.state["readiness"] = _readiness("available")

    assert "spawned" in await _spawn(api)
    assert "/api/sessions" in api.calls
    assert "bg-test" in await _review(api)
    assert "/api/bg/jobs" in api.calls
    assert "Model changed" in await _change(api)


@pytest.mark.asyncio
async def test_claude_model_passes_while_codex_is_exhausted(api):
    """Гейт по ПРОВАЙДЕРУ. Ошибка здесь заблокировала бы вообще все спавны."""
    api.state["readiness"] = _readiness("reset", provider="anthropic")

    result = await mcp.spawn_worker(
        name="w", task="t", repo_path=str(api.tmp_path), model="claude-opus-5[1m]",
    )

    assert "spawned" in result


@pytest.mark.asyncio
async def test_exhausted_codex_does_not_block_spark(api):
    api.state["readiness"] = _readiness("available", provider="codex_spark")

    assert "spawned" in await mcp.spawn_worker(
        name="w", task="t", repo_path=str(api.tmp_path), model="gpt-5.3-codex-spark",
    )


# --- fail-open: четыре ветки, каждая отдельно -------------------------------

@pytest.mark.asyncio
async def test_missing_endpoint_before_restart_keeps_the_gate_open(api):
    """MCP подхватывается сразу, app/routes — только после рестарта. В окне между
    ними эндпоинта ещё нет, и 404 обязан читаться как «не знаю», а не как отказ."""
    api.state["readiness"] = mcp.ApiToolError(
        code="not_found", message="404: Not Found", status=404,
    )

    assert "spawned" in await _spawn(api)


@pytest.mark.asyncio
async def test_transport_failure_keeps_the_gate_open(api):
    api.state["readiness"] = mcp.ApiToolError(
        code="transport_error", message="ConnectError: connection refused",
    )

    assert "spawned" in await _spawn(api)


@pytest.mark.asyncio
async def test_unavailable_state_keeps_the_gate_open(api):
    api.state["readiness"] = _readiness("unavailable", provider="", reset_at=None)

    assert "spawned" in await _spawn(api)


@pytest.mark.asyncio
async def test_malformed_answer_keeps_the_gate_open(api):
    api.state["readiness"] = {"unexpected": "shape"}

    assert "spawned" in await _spawn(api)


@pytest.mark.asyncio
async def test_unparsable_reset_time_keeps_the_gate_open(api):
    """Время сброса не распарсилось → гейт открывается, а не залипает навсегда."""
    api.state["readiness"] = _readiness("reset", reset_at="не-дата")

    assert "spawned" in await _spawn(api)


# --- T3: формулировка провала фоновой джобы ---------------------------------

@pytest.mark.asyncio
async def test_job_message_reads_correctly_under_the_failure_prefix(api):
    captured = {}
    inner = mcp._api

    async def capture(method, path, **kwargs):
        if path == "/api/bg/jobs":
            captured.update(kwargs["json"])
        return await inner(method, path, **kwargs)

    mcp._api = capture
    try:
        await _review(api)
    finally:
        mcp._api = inner

    message = captured["message"]
    assert "done" not in message
    assert not re.search(r"\bdone\b", f"[Background job FAILED] {message}")
    assert message == "Codex exec → r.md"
