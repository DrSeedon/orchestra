"""#343: единственное правило допуска — диагональ с допуском плюс жёсткие 99%."""

from datetime import datetime, timezone

import pytest

from app.quota_gate import (
    HARD_STOP_PCT,
    QuotaDecision,
    QuotaGateError,
    TOLERANCE_END_PP,
    TOLERANCE_START_PP,
    evaluate_worker_admission,
    line_limit,
    require_worker_admission,
    tolerance_pp,
)

NOW = 1_770_000_000.0
WEEK_SECONDS = 10080 * 60
CODEX_WINDOW_MINUTES = 300


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def _window(window_id: str, minutes: int, utilization, progress: float | None):
    window = {
        "id": window_id,
        "label": window_id,
        "window_minutes": minutes,
        "utilization": utilization,
    }
    if progress is not None:
        window["resets_at"] = _iso(NOW + minutes * 60 * (1.0 - progress))
    return window


def _providers(*, claude=None, codex=None, spark=None, progress=0.5, extra_claude=()):
    """Один снимок телеметрии; `progress` — доля пройденного окна во всех пулах."""
    providers = {}
    if claude is not None:
        providers["anthropic"] = {"label": "Claude", "windows": [
            _window("seven_day", 10080, claude, progress), *extra_claude,
        ]}
    if codex is not None:
        providers["codex"] = {"label": "Codex", "windows": [
            _window("primary", CODEX_WINDOW_MINUTES, codex, progress),
        ]}
    if spark is not None:
        providers["codex_spark"] = {"label": "Codex Spark", "windows": [
            _window("primary", CODEX_WINDOW_MINUTES, spark, progress),
        ]}
    return providers


def _decide(model, providers, *, observed_at=NOW, now=NOW):
    stamps = {bucket: observed_at for bucket in
              ("anthropic", "anthropic_fable", "codex", "codex_spark")}
    return evaluate_worker_admission(model, providers, stamps, now=now)


# ── сама линия ────────────────────────────────────────────────────────────────

def test_tolerance_runs_from_ten_points_to_one_across_the_window():
    assert tolerance_pp(0.0) == TOLERANCE_START_PP == 10.0
    assert tolerance_pp(1.0) == TOLERANCE_END_PP == 1.0
    assert tolerance_pp(0.5) == pytest.approx(5.5)


def test_line_is_norm_plus_tolerance_and_never_exceeds_the_hard_stop():
    assert line_limit(0.0) == pytest.approx(10.0)
    assert line_limit(0.5) == pytest.approx(55.5)
    # 0.95 → 95 + 1.45 = 96.45, ещё под жёстким стопом
    assert line_limit(0.95) == pytest.approx(96.45)
    # у самого сброса норма 100 — линия упирается в жёсткие 99, а не уходит выше
    assert line_limit(1.0) == HARD_STOP_PCT


# ── обе стороны диагонали для гейтящихся полос ────────────────────────────────

@pytest.mark.parametrize("model, key", [
    ("gpt-5.6-sol", "codex"),
    ("claude-opus-5[1m]", "claude"),
])
@pytest.mark.parametrize("progress", [0.1, 0.5, 0.9])
def test_gated_lane_blocks_just_above_the_line_and_admits_just_below(
    model, key, progress,
):
    """Обе стороны, а не только отказ: гейт, блокирующий всё, прошёл бы проверку из одной."""
    limit = line_limit(progress)

    below = _decide(model, _providers(progress=progress, **{key: limit - 0.5}))
    above = _decide(model, _providers(progress=progress, **{key: limit + 0.5}))

    assert below.state == "available" and below.allowed, below.reason
    assert above.state == "blocked" and not above.allowed, above.reason
    assert above.limit_pct == pytest.approx(limit)
    assert above.progress == pytest.approx(progress)


def test_exactly_on_the_line_is_admitted():
    """Отказ строго ВЫШЕ линии: `>`, не `>=`. Граница принадлежит разрешению."""
    decision = _decide("gpt-5.6-sol", _providers(progress=0.5, codex=line_limit(0.5)))
    assert decision.state == "available"


def test_the_same_percent_flips_verdict_as_the_window_advances():
    """Правило смотрит на точку, а не на процент: 40% рано — блок, поздно — норма."""
    early = _decide("gpt-5.6-sol", _providers(progress=0.2, codex=40.0))
    late = _decide("gpt-5.6-sol", _providers(progress=0.8, codex=40.0))

    assert early.state == "blocked"
    assert late.state == "available"


# ── Luna и Spark: диагонали нет вовсе ─────────────────────────────────────────

@pytest.mark.parametrize("model, key", [
    ("gpt-5.6-luna", "codex"),
    ("gpt-5.3-codex-spark", "spark"),
])
def test_luna_and_spark_ignore_the_line_and_stop_only_at_the_hard_limit(model, key):
    over_the_line = _decide(model, _providers(progress=0.1, **{key: 90.0}))
    at_hard_stop = _decide(model, _providers(progress=0.1, **{key: HARD_STOP_PCT}))
    # Sol на том же значении и в той же точке окна — заблокирован.
    sol = _decide("gpt-5.6-sol", _providers(progress=0.1, codex=90.0))

    assert over_the_line.state == "available", over_the_line.reason
    assert over_the_line.gated is False and over_the_line.limit_pct is None
    assert at_hard_stop.state == "blocked"
    assert sol.state == "blocked"


@pytest.mark.parametrize("model", [
    "gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.3-codex-spark", "claude-opus-5[1m]",
])
def test_hard_stop_applies_to_every_worker_lane(model):
    providers = _providers(progress=0.99, claude=99.4, codex=99.4, spark=99.4)
    assert _decide(model, providers).state == "blocked"


@pytest.mark.parametrize("model", ["gpt-5.6-luna", "gpt-5.6-sol"])
def test_just_under_the_hard_stop_at_the_end_of_the_window_is_admitted(model):
    """Стоп именно `>= 99`, и линия у сброса совпадает с ним, а не режет раньше."""
    decision = _decide(model, _providers(progress=1.0, codex=98.9))
    assert decision.state == "available", decision.reason


# ── пулы и окна ───────────────────────────────────────────────────────────────

def test_spark_is_measured_by_its_own_counter_not_by_the_shared_codex_one():
    """Живой случай: Codex 100%, Spark 39%. Одним числом их мерить нельзя."""
    providers = _providers(progress=0.5, codex=100.0, spark=39.0)

    assert _decide("gpt-5.6-sol", providers).state == "blocked"
    assert _decide("gpt-5.6-luna", providers).state == "blocked"
    spark = _decide("gpt-5.3-codex-spark", providers)
    assert spark.state == "available" and spark.utilization == 39.0


def test_window_start_is_reset_minus_window_length_for_both_pool_shapes():
    claude = _decide("claude-opus-5[1m]", _providers(progress=0.25, claude=10.0))
    codex = _decide("gpt-5.6-sol", _providers(progress=0.25, codex=10.0))

    assert claude.progress == pytest.approx(0.25)
    assert codex.progress == pytest.approx(0.25)
    # Начало недели Claude ровно на 7 суток раньше сброса.
    started = datetime.fromisoformat(claude.window_starts_at).timestamp()
    reset = datetime.fromisoformat(claude.reset_at).timestamp()
    assert reset - started == pytest.approx(WEEK_SECONDS)


def test_claude_decides_by_the_weekly_window_and_ignores_the_five_hour_one():
    providers = _providers(
        progress=0.9, claude=50.0,
        extra_claude=[_window("five_hour", 300, 99.9, 0.9)],
    )
    assert _decide("claude-opus-5[1m]", providers).state == "available"


def test_a_reset_already_in_the_past_collapses_the_line_onto_the_hard_stop():
    """Окно пройдено целиком: `progress` зажат в 1.0, и линия равна жёсткому стопу."""
    window = _window("primary", CODEX_WINDOW_MINUTES, 97.0, None)
    window["resets_at"] = _iso(NOW - 60)
    providers = {"codex": {"label": "Codex", "windows": [window]}}

    decision = _decide("gpt-5.6-sol", providers)

    assert decision.progress == 1.0
    assert decision.limit_pct == HARD_STOP_PCT
    assert decision.state == "available"


def test_window_without_a_parseable_reset_falls_back_to_the_hard_stop_only():
    providers = {"codex": {"label": "Codex", "windows": [
        _window("primary", CODEX_WINDOW_MINUTES, 80.0, None),
    ]}}

    decision = _decide("gpt-5.6-sol", providers)

    assert decision.progress is None and decision.limit_pct is None
    assert decision.state == "available"
    assert "no parseable reset" in decision.reason


# ── неизвестная квота пропускает ──────────────────────────────────────────────

@pytest.mark.parametrize("observed_at", [None, "", "not-a-time", NOW - 301, NOW + 60])
def test_missing_stale_and_future_observations_fail_open(observed_at):
    """Сквозное решение #343: `unknown` ПРОПУСКАЕТ.

    Отказ на неизвестной квоте создавал сессию, которую первый же обязательный
    `/send` отбивал 429 — мёртвую (#227).
    """
    decision = _decide(
        "gpt-5.6-sol", _providers(progress=0.5, codex=10.0), observed_at=observed_at,
    )

    assert decision.state == "unknown"
    assert decision.allowed
    require_worker_admission(decision)  # не поднимает


@pytest.mark.parametrize("utilization", [None, "97", float("nan"), -1, True])
def test_malformed_utilization_is_unknown_and_fails_open(utilization):
    providers = {"codex": {"label": "Codex", "windows": [
        _window("primary", CODEX_WINDOW_MINUTES, utilization, 0.5),
    ]}}

    decision = _decide("gpt-5.6-sol", providers)

    assert decision.state == "unknown" and decision.allowed


def test_missing_provider_and_missing_window_are_unknown_not_blocked():
    assert _decide("gpt-5.6-sol", {}).state == "unknown"
    empty = {"codex": {"label": "Codex", "windows": []}}
    assert _decide("gpt-5.6-sol", empty).state == "unknown"


# ── модели вне политики ───────────────────────────────────────────────────────

def test_only_positively_resolved_grok_is_exempt():
    grok = _decide("grok-4.6", _providers(progress=0.5, codex=100.0))
    assert grok.state == "not_applicable" and grok.allowed
    assert grok.lane is None and grok.gated is False


@pytest.mark.parametrize("model", [None, 42, "", "no-such-model"])
def test_unknown_model_is_unknown_not_exempt(model):
    decision = evaluate_worker_admission(model, {}, {}, now=NOW)
    assert decision.state == "unknown"


# ── форма отказа ──────────────────────────────────────────────────────────────

def test_refusal_is_non_retryable_and_names_the_numbers_that_produced_it():
    decision = _decide("gpt-5.6-sol", _providers(progress=0.5, codex=70.0))
    with pytest.raises(QuotaGateError) as error:
        require_worker_admission(decision)

    assert error.value.retryable is False
    assert error.value.status_code == 429
    envelope = error.value.envelope()["error"]
    assert envelope["code"] == "weekly_quota_blocked"
    assert envelope["retryable"] is False
    assert envelope["details"]["limit_pct"] == pytest.approx(55.5)
    assert envelope["details"]["utilization"] == 70.0
    assert "55.5" in str(error.value) and "70%" in str(error.value)


def test_a_non_blocked_decision_cannot_be_turned_into_a_refusal():
    decision = _decide("gpt-5.6-sol", _providers(progress=0.5, codex=10.0))
    with pytest.raises(ValueError):
        QuotaGateError(decision)


def test_decision_serializes_every_field_the_panel_draws():
    decision = _decide("gpt-5.6-sol", _providers(progress=0.5, codex=70.0))
    payload = decision.to_dict()

    assert payload["state"] == "blocked" and payload["allowed"] is False
    assert payload["lane"] == "sol" and payload["gated"] is True
    assert payload["hard_limit_pct"] == HARD_STOP_PCT
    assert set(payload) == set(QuotaDecision.__dataclass_fields__) | {"allowed"}
