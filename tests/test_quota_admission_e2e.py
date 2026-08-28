"""#343: приёмка правила на реальном пути допуска, а не только в арифметике.

Проверяется то, что видит пользователь: создаётся воркер или нет. Обе стороны линии,
обе негейтящиеся полосы, и оркестратор — который не блокируется ничем.
"""

from datetime import datetime, timezone

import pytest

from app.quota_gate import QuotaGateError, evaluate_worker_admission, line_limit

NOW = 1_770_000_000.0
# Десятая часть окна: линия = 10 + 9.1 = 19.1 п.п.
PROGRESS = 0.1
# Порог теперь свойство ПОЛОСЫ: Sol идёт по кривой, Claude по прежней прямой, поэтому
# одного общего числа больше не существует (решение юзера 28.08.2026).
LIMIT = {lane: line_limit(PROGRESS, lane) for lane in ("sol", "claude")}
ABOVE = {lane: value + 20.0 for lane, value in LIMIT.items()}
BELOW = {lane: value - 5.0 for lane, value in LIMIT.items()}
# Значение, стопорящее ОБЕ гейтящиеся полосы: выше самого высокого из двух порогов.
ABOVE_BOTH = max(ABOVE.values())


def _window(minutes, utilization):
    return {
        "id": "seven_day" if minutes == 10080 else "primary",
        "window_minutes": minutes,
        "utilization": utilization,
        "resets_at": datetime.fromtimestamp(
            NOW + minutes * 60 * (1.0 - PROGRESS), timezone.utc,
        ).isoformat(),
    }


def _admission(utilization):
    """Один и тот же расход во всех трёх пулах — чтобы разошлись только полосы."""
    async def loader(model, observation_loader=None):
        return evaluate_worker_admission(
            model,
            {
                "anthropic": {"label": "Claude", "windows": [_window(10080, utilization)]},
                "codex": {"label": "Codex", "windows": [_window(300, utilization)]},
                "codex_spark": {
                    "label": "Codex Spark", "windows": [_window(300, utilization)],
                },
            },
            {"anthropic": NOW, "codex": NOW, "codex_spark": NOW},
            now=NOW,
        )
    return loader


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr("app.db.DB_PATH", tmp_path / "test.db")
    from app.db import init_db

    init_db()


@pytest.fixture
def mgr(db, tmp_path, monkeypatch):
    wt_root = tmp_path / "worktrees"
    wt_root.mkdir()
    monkeypatch.setattr("app.workspace.WORKTREE_ROOT", wt_root)
    from app.manager import SessionManager

    return SessionManager()


@pytest.fixture(autouse=True)
def _real_pipelines(monkeypatch):
    """ROLE_SYSTEM_PROMPT падает без манифеста — этим тестам нужен настоящий default."""
    from pathlib import Path

    import app.pipeline as pl

    monkeypatch.setattr(pl, "PIPELINES_DIR", Path(__file__).parent.parent / "pipelines")
    pl.load_pipeline.cache_clear()
    yield
    pl.load_pipeline.cache_clear()


async def _spawn(mgr, name, model, **over):
    return await mgr.create_session(
        name=name, scope="/s", cwd="/tmp", model=model,
        planned_initial_turn=True, **over,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("name, model", [
    ("sol", "gpt-5.6-sol"),
    ("claude", "claude-opus-5[1m]"),
])
async def test_gated_worker_is_refused_above_the_line(mgr, monkeypatch, name, model):
    monkeypatch.setattr("app.quota_gate.get_worker_admission", _admission(ABOVE[name]))

    with pytest.raises(QuotaGateError):
        await _spawn(mgr, f"{name}-above", model)

    assert mgr.sessions == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("name, model", [
    ("sol", "gpt-5.6-sol"),
    ("claude", "claude-opus-5[1m]"),
])
async def test_gated_worker_is_created_below_the_line(mgr, monkeypatch, name, model):
    """Вторая сторона: гейт, отказывающий всегда, прошёл бы проверку выше."""
    monkeypatch.setattr("app.quota_gate.get_worker_admission", _admission(BELOW[name]))

    session = await _spawn(mgr, f"{name}-below", model)

    assert session.name == f"{name}-below"


@pytest.mark.asyncio
@pytest.mark.parametrize("name, model", [
    ("luna", "gpt-5.6-luna"),
    ("spark", "gpt-5.3-codex-spark"),
])
async def test_luna_and_spark_are_created_at_the_value_that_stops_sol(
    mgr, monkeypatch, name, model,
):
    monkeypatch.setattr("app.quota_gate.get_worker_admission", _admission(ABOVE_BOTH))

    session = await _spawn(mgr, f"{name}-ok", model)

    assert session.name == f"{name}-ok"


@pytest.mark.asyncio
@pytest.mark.parametrize("name, model", [
    ("luna", "gpt-5.6-luna"),
    ("spark", "gpt-5.3-codex-spark"),
])
async def test_luna_and_spark_are_refused_at_the_hard_stop(mgr, monkeypatch, name, model):
    monkeypatch.setattr("app.quota_gate.get_worker_admission", _admission(99.0))

    with pytest.raises(QuotaGateError):
        await _spawn(mgr, f"{name}-hard", model)

    assert mgr.sessions == {}


@pytest.mark.asyncio
async def test_orchestrator_is_created_at_a_hundred_percent(mgr, monkeypatch):
    """Оркестраторы не блокируются НИКОГДА — ни на 99, ни на 100."""
    from unittest.mock import AsyncMock

    gate = AsyncMock(side_effect=AssertionError("orchestrator must not read quota"))
    monkeypatch.setattr("app.quota_gate.get_worker_admission", gate)

    session = await _spawn(
        mgr, "root-orchestrator", "claude-opus-5[1m]",
        role="orchestrator", is_orchestrator=True,
    )

    assert session.is_orchestrator
    gate.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_quota_admits_the_spawn_and_the_following_send(mgr, monkeypatch):
    """Сквозной fail-open: спавн и обязательный первый `/send` отвечают одинаково.

    Раньше спавн проходил на `quota=unknown`, а `/send` тем же вопросом отвечал 429 —
    получалась мёртвая сессия (#227).
    """
    from app.quota_gate import require_worker_admission

    async def blind(model, observation_loader=None):
        return evaluate_worker_admission(model, {}, {}, now=NOW)

    monkeypatch.setattr("app.quota_gate.get_worker_admission", blind)

    session = await _spawn(mgr, "blind-worker", "gpt-5.6-sol")

    assert session.name == "blind-worker"
    # Тот же вопрос, который задаёт `/send` следующим шагом.
    require_worker_admission(await blind("gpt-5.6-sol"))
