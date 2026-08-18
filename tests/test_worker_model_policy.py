"""Статический допуск моделей воркерам — единственное, что осталось в манифесте (#329).

Всё про расход (проценты, темп, резерв, латчи) вырезано: этим владеет quota-контроллер
(полосы в `quota_controller_policy` + `app/quota_gate.py`). Здесь проверяется, что
- допуск fail-closed: чего нет в списке — не поедет, включая новые модели реестра;
- решение НЕ зависит от телеметрии расхода (отказ происходит, не прочитав её вовсе);
- оркестраторы освобождены;
- quota-гейт на том же спавне остаётся fail-open и громким.
"""

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
        "always_allowed": [
            "gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.3-codex-spark", "claude-opus-5[1m]",
        ],
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


def _forbid_telemetry(monkeypatch):
    """Любое чтение расхода на этом спавне — провал: допуск от него не зависит."""
    import app.routes.system as system

    probe = AsyncMock(side_effect=AssertionError("static model policy read spend telemetry"))
    monkeypatch.setattr(system, "current_quota_observation", probe)
    return probe


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model",
    [
        "claude-fable-5[1m]",   # намеренно не впущена: вдвое дороже Opus по лимитам
        "gpt-5.6-terra",        # намеренно не впущена: решение юзера
        "claude-sonnet-5[1m]",  # зарегистрирована, но воркерам не открыта
        "grok-4.5",             # другой рантайм, тоже не открыт
    ],
)
async def test_model_outside_the_admitted_set_never_reaches_a_session(
    mgr, monkeypatch, model,
):
    probe = _forbid_telemetry(monkeypatch)

    with pytest.raises(ValueError, match=r"not admitted for workers.*gpt-5\.6-sol"):
        await _spawn(mgr, "denied", model)

    assert mgr.sessions == {}
    probe.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model", ["gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.3-codex-spark", "claude-opus-5[1m]"],
)
async def test_admitted_models_spawn(mgr, monkeypatch, model):
    monkeypatch.setattr(
        "app.quota_gate.get_worker_admission",
        AsyncMock(side_effect=RuntimeError("quota telemetry offline")),
    )

    worker = await _spawn(mgr, model.rsplit("-", 1)[-1], model)

    assert worker.model == model


@pytest.mark.asyncio
async def test_override_reason_admits_a_model_outside_the_set_and_is_logged(
    mgr, monkeypatch, caplog,
):
    monkeypatch.setattr(
        "app.quota_gate.get_worker_admission",
        AsyncMock(side_effect=RuntimeError("quota telemetry offline")),
    )

    with caplog.at_level(logging.WARNING, logger="app.manager"):
        worker = await _spawn(
            mgr,
            "override-terra",
            "gpt-5.6-terra",
            model_policy_override_reason="pilot #329 comparison",
        )

    assert worker.model == "gpt-5.6-terra"
    assert "pilot #329 comparison" in caplog.text


@pytest.mark.asyncio
async def test_orchestrators_are_exempt_even_on_a_model_workers_may_not_use(
    mgr, monkeypatch,
):
    probe = _forbid_telemetry(monkeypatch)

    orchestrator = await _spawn(
        mgr,
        "fable-orchestrator",
        "claude-fable-5[1m]",
        role="orchestrator",
        is_orchestrator=True,
    )

    assert orchestrator.is_orchestrator
    assert orchestrator.model == "claude-fable-5[1m]"
    probe.assert_not_awaited()


@pytest.mark.asyncio
async def test_admission_is_independent_of_how_much_quota_is_left(mgr, monkeypatch):
    """Пул на нуле или почти исчерпан — статический допуск отвечает одинаково."""
    import app.routes.system as system

    monkeypatch.setattr(
        "app.quota_gate.get_worker_admission",
        AsyncMock(side_effect=RuntimeError("quota telemetry offline")),
    )
    for utilization, name in ((1, "empty-pool"), (99, "full-pool")):
        now = datetime.now(timezone.utc).timestamp()
        monkeypatch.setattr(
            system, "_usage_cache",
            {"data": _usage(utilization, 50)["anthropic"], "ts": now, "token": None},
        )
        worker = await _spawn(mgr, f"opus-{name}", "claude-opus-5[1m]")
        assert worker.model == "claude-opus-5[1m]"

        with pytest.raises(ValueError, match="not admitted for workers"):
            await _spawn(mgr, f"terra-{name}", "gpt-5.6-terra")


# ── quota-гейт на том же спавне: он и владеет расходом ───────────────────────
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
async def test_quota_gate_blocks_opus_worker_above_the_claude_lane(mgr, monkeypatch):
    """Потолок пула теперь принуждает гейт, а не манифест: 91% > полосы claude 90%."""
    import app.routes.system as system

    now = datetime.now(timezone.utc).timestamp()
    monkeypatch.setattr(
        system, "_usage_cache",
        {"data": _usage(91, 50)["anthropic"], "ts": now, "token": None},
    )
    monkeypatch.setattr("app.quota_gate.get_worker_admission", _real_get_worker_admission)

    from app.quota_gate import QuotaGateError

    with pytest.raises(QuotaGateError) as caught:
        await _spawn(mgr, "opus-over-lane", "claude-opus-5[1m]")

    assert caught.value.code == "weekly_quota_blocked"
    assert caught.value.decision.threshold == 90.0
    assert mgr.sessions == {}


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
    assert "worker quota admission telemetry unavailable; allowing" in caplog.text
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
async def test_quota_admission_exception_is_fail_open_and_loud(
    mgr, monkeypatch, caplog,
):
    monkeypatch.setattr(
        "app.quota_gate.get_worker_admission",
        AsyncMock(side_effect=RuntimeError("admission unavailable")),
    )

    with caplog.at_level(logging.ERROR, logger="app.manager"):
        worker = await _spawn(mgr, "admission-error-opus", "claude-opus-5[1m]")

    assert worker.model == "claude-opus-5[1m]"
    assert "worker quota admission check failed; allowing" in caplog.text
    assert "admission unavailable" in caplog.text
