import logging
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def mgr(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    from app.db import init_db
    init_db()
    worktree_root = tmp_path / "worktrees"
    worktree_root.mkdir()
    monkeypatch.setattr("app.workspace.WORKTREE_ROOT", worktree_root)
    from app.manager import SessionManager
    return SessionManager()


def _usage(claude: float, codex: float) -> dict:
    return {
        "anthropic": {"seven_day": {"utilization": claude}},
        "codex": {"primary": {"utilization": codex}},
    }


async def _spawn(mgr, name: str, model: str, **kwargs):
    from tests.conftest import make_backend_mock

    with patch("app.session.AgentSession._make_backend", return_value=make_backend_mock()):
        return await mgr.create_session(
            name=name,
            scope="/model-policy",
            cwd="/tmp",
            model=model,
            role=kwargs.pop("role", "worker"),
            planned_initial_turn=True,
            **kwargs,
        )


@pytest.mark.asyncio
async def test_skewed_pools_reject_opus_worker_before_publish(mgr, monkeypatch):
    monkeypatch.setattr(
        "app.manager._worker_model_policy_usage",
        AsyncMock(return_value=_usage(63, 8)),
    )

    with pytest.raises(ValueError, match=r"Claude 7d 63%.*Codex 8%.*gpt-5\.6-sol.*gpt-5\.6-luna"):
        await _spawn(mgr, "blocked-opus", "claude-opus-5[1m]")

    assert mgr.sessions == {}


@pytest.mark.asyncio
async def test_opus_override_requires_reason_and_logs_it(mgr, monkeypatch, caplog):
    monkeypatch.setattr(
        "app.manager._worker_model_policy_usage",
        AsyncMock(return_value=_usage(63, 8)),
    )

    with caplog.at_level(logging.WARNING, logger="app.manager"):
        worker = await _spawn(
            mgr,
            "override-opus",
            "claude-opus-5[1m]",
            model_policy_override_reason="pilot #227 comparison",
        )

    assert worker.model == "claude-opus-5[1m]"
    assert "pilot #227 comparison" in caplog.text


@pytest.mark.asyncio
async def test_orchestrators_are_exempt_from_worker_model_policy(mgr, monkeypatch):
    usage = AsyncMock(side_effect=AssertionError("orchestrator read worker policy telemetry"))
    monkeypatch.setattr("app.manager._worker_model_policy_usage", usage)

    orchestrator = await _spawn(
        mgr,
        "opus-orchestrator",
        "claude-opus-5[1m]",
        role="orchestrator",
        is_orchestrator=True,
    )

    assert orchestrator.is_orchestrator
    usage.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["gpt-5.6-sol", "gpt-5.6-luna"])
async def test_allowed_codex_worker_models_do_not_read_balance(mgr, monkeypatch, model):
    usage = AsyncMock(side_effect=AssertionError("allowed model read balance telemetry"))
    monkeypatch.setattr("app.manager._worker_model_policy_usage", usage)

    worker = await _spawn(mgr, model.rsplit("-", 1)[-1], model)

    assert worker.model == model
    usage.assert_not_awaited()


@pytest.mark.asyncio
async def test_balanced_pools_allow_opus_worker(mgr, monkeypatch):
    monkeypatch.setattr(
        "app.manager._worker_model_policy_usage",
        AsyncMock(return_value=_usage(14, 12)),
    )

    worker = await _spawn(mgr, "balanced-opus", "claude-opus-5[1m]")

    assert worker.model == "claude-opus-5[1m]"


@pytest.mark.asyncio
async def test_opus_balance_gate_has_hysteresis(mgr, monkeypatch):
    usage = AsyncMock(side_effect=[
        _usage(20, 13),  # gap 7: latch blocked
        _usage(20, 16),  # gap 4: remain blocked
        _usage(20, 17),  # gap 3: unlock
        _usage(20, 16),  # gap 4: remain open
        _usage(20, 14),  # gap 6: block again
    ])
    monkeypatch.setattr("app.manager._worker_model_policy_usage", usage)

    with pytest.raises(ValueError):
        await _spawn(mgr, "gap-7", "claude-opus-5[1m]")
    with pytest.raises(ValueError):
        await _spawn(mgr, "gap-4-blocked", "claude-opus-5[1m]")
    assert (await _spawn(mgr, "gap-3", "claude-opus-5[1m]")).model == "claude-opus-5[1m]"
    assert (await _spawn(mgr, "gap-4-open", "claude-opus-5[1m]")).model == "claude-opus-5[1m]"
    with pytest.raises(ValueError):
        await _spawn(mgr, "gap-6", "claude-opus-5[1m]")


@pytest.mark.asyncio
async def test_fable_is_denied_by_manifest_policy(mgr, monkeypatch):
    usage = AsyncMock(side_effect=AssertionError("static deny read balance telemetry"))
    monkeypatch.setattr("app.manager._worker_model_policy_usage", usage)

    with pytest.raises(ValueError, match=r"claude-fable-5\[1m\].*not allowed.*gpt-5\.6-sol"):
        await _spawn(mgr, "fable", "claude-fable-5[1m]")

    usage.assert_not_awaited()


@pytest.mark.asyncio
async def test_balance_telemetry_failure_is_fail_open_and_loud(mgr, monkeypatch, caplog):
    monkeypatch.setattr(
        "app.manager._worker_model_policy_usage",
        AsyncMock(side_effect=RuntimeError("usage unavailable")),
    )

    with caplog.at_level(logging.ERROR, logger="app.manager"):
        worker = await _spawn(mgr, "fail-open-opus", "claude-opus-5[1m]")

    assert worker.model == "claude-opus-5[1m]"
    assert "usage unavailable" in caplog.text


@pytest.mark.asyncio
async def test_balance_telemetry_timeout_is_fail_open_and_loud(mgr, monkeypatch, caplog):
    import asyncio

    entered = asyncio.Event()

    async def stuck_usage():
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("app.manager._worker_model_policy_usage", stuck_usage)
    monkeypatch.setattr("app.manager.WORKER_MODEL_POLICY_TIMEOUT_SECONDS", 0.01)

    with caplog.at_level(logging.ERROR, logger="app.manager"):
        worker = await _spawn(mgr, "timeout-opus", "claude-opus-5[1m]")

    assert entered.is_set(), "timeout probe never entered the telemetry loader"
    assert worker.model == "claude-opus-5[1m]"
    assert "TimeoutError" in caplog.text
