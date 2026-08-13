import asyncio
import logging
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.quota_gate import get_worker_admission as _real_get_worker_admission


@pytest.fixture
def mgr(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setattr("app.db.DB_PATH", db_path)
    from app.db import init_db
    init_db()
    worktree_root = tmp_path / "worktrees"
    worktree_root.mkdir()
    monkeypatch.setattr("app.workspace.WORKTREE_ROOT", worktree_root)
    import app.manager as manager
    from app.pipeline import WorkerModelPolicy, load_pipeline

    policy = WorkerModelPolicy.model_validate({
        "always_allowed": ["gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.3-codex-spark"],
        "denied": ["claude-fable-5[1m]", "gpt-5.6-terra"],
        "quota_guarded": {
            "model": "claude-opus-5[1m]",
            "pace_block_lead_pp": 11,
            "pace_unblock_lead_pp": 7,
            "absolute_block_pct": 90,
            "absolute_unblock_pct": 87,
        },
        "alternatives": ["gpt-5.6-sol", "gpt-5.6-luna"],
    })
    config = load_pipeline("default").model_copy(update={"worker_model_policy": policy})
    monkeypatch.setattr(manager, "load_pipeline", lambda _name: config)
    SessionManager = manager.SessionManager
    return SessionManager()


def _usage(utilization: float, elapsed_pct: float | None = None) -> dict:
    seven_day = {"utilization": utilization}
    if elapsed_pct is not None:
        remaining = timedelta(days=7 * (1 - elapsed_pct / 100))
        seven_day["resets_at"] = (datetime.now(timezone.utc) + remaining).isoformat()
    return {"anthropic": {"seven_day": seven_day}}


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
async def test_policy_loader_requests_only_anthropic(monkeypatch):
    import app.manager as manager
    import app.routes.system as system

    now = datetime.now(timezone.utc).timestamp()
    loader = AsyncMock(return_value={
        "providers": {
            "anthropic": {
                "windows": [{
                    "id": "seven_day",
                    "utilization": 10,
                    "resets_at": datetime.now(timezone.utc).isoformat(),
                }],
            },
        },
        "observed_at_by_provider": {"anthropic": now},
    })
    monkeypatch.setattr(system, "current_quota_observation", loader)

    await manager._worker_model_policy_usage()

    loader.assert_awaited_once_with(required_provider="anthropic")


@pytest.mark.asyncio
async def test_warm_anthropic_cache_still_blocks_fast_opus_without_other_refresh(
    mgr, monkeypatch,
):
    import app.routes.system as system

    now = datetime.now(timezone.utc).timestamp()
    warm = _usage(64, 28)["anthropic"]
    monkeypatch.setattr(
        system,
        "_usage_cache",
        {"data": warm, "ts": now, "token": None},
    )
    fetch_anthropic = AsyncMock(side_effect=AssertionError("warm cache was refreshed"))
    fetch_codex = AsyncMock(side_effect=AssertionError("Codex telemetry was requested"))
    monkeypatch.setattr(system, "_fetch_anthropic_usage", fetch_anthropic)
    monkeypatch.setattr(system, "_fetch_codex_usage", fetch_codex)

    with pytest.raises(ValueError, match=r"Claude 7d 64%.*window elapsed 28%"):
        await _spawn(mgr, "warm-cache-opus", "claude-opus-5[1m]")

    assert mgr.sessions == {}
    fetch_anthropic.assert_not_awaited()
    fetch_codex.assert_not_awaited()


@pytest.mark.asyncio
async def test_warm_anthropic_cache_normal_control_passes_real_spawn_seam(
    mgr, monkeypatch,
):
    import app.routes.system as system

    now = datetime.now(timezone.utc).timestamp()
    warm = _usage(39, 30)["anthropic"]
    monkeypatch.setattr(system, "_usage_cache", {"data": warm, "ts": now, "token": None})
    fetch_anthropic = AsyncMock(side_effect=AssertionError("warm cache was refreshed"))
    fetch_codex = AsyncMock(side_effect=AssertionError("Codex telemetry was requested"))
    monkeypatch.setattr(system, "_fetch_anthropic_usage", fetch_anthropic)
    monkeypatch.setattr(system, "_fetch_codex_usage", fetch_codex)
    monkeypatch.setattr("app.quota_gate.get_worker_admission", _real_get_worker_admission)

    worker = await _spawn(mgr, "warm-normal-opus", "claude-opus-5[1m]")

    assert worker.model == "claude-opus-5[1m]"
    fetch_anthropic.assert_not_awaited()
    fetch_codex.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_anthropic_cache_refresh_failure_is_fail_open_and_loud(
    mgr, monkeypatch, caplog,
):
    import app.routes.system as system

    now = datetime.now(timezone.utc).timestamp()
    stale = _usage(95, 95)["anthropic"]
    monkeypatch.setattr(
        system,
        "_usage_cache",
        {"data": stale, "ts": now - 301, "token": None},
    )
    monkeypatch.setattr(system, "_read_oauth_credentials", lambda: ("token", None, None))
    fetch_anthropic = AsyncMock(side_effect=RuntimeError("offline"))
    fetch_codex = AsyncMock(side_effect=AssertionError("Codex telemetry was requested"))
    monkeypatch.setattr(system, "_fetch_anthropic_usage", fetch_anthropic)
    monkeypatch.setattr(system, "_fetch_codex_usage", fetch_codex)
    monkeypatch.setattr("app.quota_gate.get_worker_admission", _real_get_worker_admission)

    with caplog.at_level(logging.ERROR, logger="app.manager"):
        worker = await _spawn(mgr, "stale-cache-opus", "claude-opus-5[1m]")

    assert worker.model == "claude-opus-5[1m]"
    assert "fresh Anthropic worker quota telemetry is unavailable" in caplog.text
    assert "worker quota admission telemetry unavailable; allowing" in caplog.text
    assert fetch_anthropic.await_count == 2
    fetch_codex.assert_not_awaited()


@pytest.mark.asyncio
async def test_unavailable_anthropic_cache_is_fail_open_at_real_spawn_seam(
    mgr, monkeypatch, caplog,
):
    import app.routes.system as system

    monkeypatch.setattr(system, "_usage_cache", {"data": None, "ts": 0.0, "token": None})
    monkeypatch.setattr(system, "_read_oauth_credentials", lambda: (None, None, None))
    monkeypatch.setattr("app.quota_gate.get_worker_admission", _real_get_worker_admission)

    with caplog.at_level(logging.ERROR, logger="app.manager"):
        worker = await _spawn(mgr, "unavailable-opus", "claude-opus-5[1m]")

    assert worker.model == "claude-opus-5[1m]"
    assert "worker quota admission telemetry unavailable; allowing" in caplog.text


@pytest.mark.asyncio
async def test_slow_anthropic_telemetry_is_fail_open_at_real_spawn_seam(
    mgr, monkeypatch, caplog,
):
    import app.routes.system as system

    calls = 0

    async def slow_then_unavailable(*, required_provider):
        nonlocal calls
        assert required_provider == "anthropic"
        calls += 1
        if calls == 1:
            await asyncio.Event().wait()
        return {
            "providers": {},
            "observed_at_by_provider": {},
        }

    monkeypatch.setattr(system, "current_quota_observation", slow_then_unavailable)
    monkeypatch.setattr("app.manager.WORKER_MODEL_POLICY_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr("app.quota_gate.get_worker_admission", _real_get_worker_admission)

    with caplog.at_level(logging.ERROR, logger="app.manager"):
        worker = await _spawn(mgr, "slow-telemetry-opus", "claude-opus-5[1m]")

    assert worker.model == "claude-opus-5[1m]"
    assert calls == 2
    assert "TimeoutError" in caplog.text
    assert "worker quota admission telemetry unavailable; allowing" in caplog.text


@pytest.mark.asyncio
async def test_quota_admission_exception_is_fail_open_and_loud(
    mgr, monkeypatch, caplog,
):
    monkeypatch.setattr(
        "app.manager._worker_model_policy_usage",
        AsyncMock(return_value=_usage(39, 30)),
    )
    monkeypatch.setattr(
        "app.quota_gate.get_worker_admission",
        AsyncMock(side_effect=RuntimeError("admission unavailable")),
    )

    with caplog.at_level(logging.ERROR, logger="app.manager"):
        worker = await _spawn(mgr, "admission-error-opus", "claude-opus-5[1m]")

    assert worker.model == "claude-opus-5[1m]"
    assert "worker quota admission check failed; allowing" in caplog.text
    assert "admission unavailable" in caplog.text


@pytest.mark.asyncio
async def test_fast_claude_pace_rejects_opus_worker_before_publish(mgr, monkeypatch):
    monkeypatch.setattr(
        "app.manager._worker_model_policy_usage",
        AsyncMock(return_value=_usage(64, 28)),
    )

    with pytest.raises(
        ValueError,
        match=r"Claude 7d 64%.*window elapsed 28%.*gpt-5\.6-sol.*gpt-5\.6-luna",
    ):
        await _spawn(mgr, "blocked-opus", "claude-opus-5[1m]")

    assert mgr.sessions == {}


@pytest.mark.asyncio
async def test_opus_override_requires_reason_and_logs_it(mgr, monkeypatch, caplog):
    monkeypatch.setattr(
        "app.manager._worker_model_policy_usage",
        AsyncMock(return_value=_usage(64, 28)),
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
async def test_normal_claude_pace_allows_opus_worker(mgr, monkeypatch):
    monkeypatch.setattr(
        "app.manager._worker_model_policy_usage",
        AsyncMock(return_value=_usage(39, 30)),
    )

    worker = await _spawn(mgr, "normal-pace-opus", "claude-opus-5[1m]")

    assert worker.model == "claude-opus-5[1m]"


@pytest.mark.asyncio
async def test_cold_start_below_absolute_ceiling_allows_opus(mgr, monkeypatch):
    monkeypatch.setattr(
        "app.manager._worker_model_policy_usage",
        AsyncMock(return_value=_usage(88, 85)),
    )

    worker = await _spawn(mgr, "below-ceiling-opus", "claude-opus-5[1m]")

    assert worker.model == "claude-opus-5[1m]"


@pytest.mark.asyncio
async def test_opus_pace_gate_has_hysteresis(mgr, monkeypatch):
    usage = AsyncMock(side_effect=[
        _usage(62, 50),  # lead 12: latch blocked
        _usage(59, 50),  # lead 9: remain blocked
        _usage(57, 50),  # lead 7: unlock
        _usage(59, 50),  # lead 9: remain open
        _usage(61.1, 50),  # lead 11.1: block again (headroom for clock movement)
    ])
    monkeypatch.setattr("app.manager._worker_model_policy_usage", usage)

    with pytest.raises(ValueError):
        await _spawn(mgr, "lead-12", "claude-opus-5[1m]")
    with pytest.raises(ValueError):
        await _spawn(mgr, "lead-9-blocked", "claude-opus-5[1m]")
    assert (await _spawn(mgr, "lead-7", "claude-opus-5[1m]")).model == "claude-opus-5[1m]"
    assert (await _spawn(mgr, "lead-9-open", "claude-opus-5[1m]")).model == "claude-opus-5[1m]"
    with pytest.raises(ValueError):
        await _spawn(mgr, "lead-11", "claude-opus-5[1m]")


@pytest.mark.asyncio
async def test_opus_absolute_ceiling_has_independent_hysteresis(mgr, monkeypatch):
    usage = AsyncMock(side_effect=[
        _usage(91, 95),  # >=90: latch blocked, pace normal
        _usage(88, 95),  # remain blocked
        _usage(87, 95),  # unlock
        _usage(88, 95),  # remain open
        _usage(90, 95),  # block again
    ])
    monkeypatch.setattr("app.manager._worker_model_policy_usage", usage)

    with pytest.raises(ValueError, match=r"absolute worker stop 90%"):
        await _spawn(mgr, "ceiling-91", "claude-opus-5[1m]")
    with pytest.raises(ValueError, match=r"absolute worker stop 90%"):
        await _spawn(mgr, "ceiling-88-blocked", "claude-opus-5[1m]")
    assert (await _spawn(mgr, "ceiling-87", "claude-opus-5[1m]")).model == "claude-opus-5[1m]"
    assert (await _spawn(mgr, "ceiling-88-open", "claude-opus-5[1m]")).model == "claude-opus-5[1m]"
    with pytest.raises(ValueError, match=r"absolute worker stop 90%"):
        await _spawn(mgr, "ceiling-90", "claude-opus-5[1m]")


@pytest.mark.asyncio
@pytest.mark.parametrize("resets_at", ["", "2020-01-01T00:00:00+00:00"])
async def test_unusable_reset_skips_pace_but_keeps_absolute_ceiling(
    mgr, monkeypatch, caplog, resets_at,
):
    normal = _usage(64)
    ceiling = _usage(95)
    normal["anthropic"]["seven_day"]["resets_at"] = resets_at
    ceiling["anthropic"]["seven_day"]["resets_at"] = resets_at
    usage = AsyncMock(side_effect=[normal, ceiling])
    monkeypatch.setattr("app.manager._worker_model_policy_usage", usage)

    with caplog.at_level(logging.WARNING, logger="app.manager"):
        worker = await _spawn(mgr, "no-reset-pace", "claude-opus-5[1m]")
    assert worker.model == "claude-opus-5[1m]"
    assert "pace check skipped" in caplog.text
    with pytest.raises(ValueError, match=r"absolute worker stop 90%"):
        await _spawn(mgr, "no-reset-ceiling", "claude-opus-5[1m]")


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
