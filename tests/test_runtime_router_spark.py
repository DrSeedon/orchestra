"""T1: Spark is its own quota lane — observed from its own bucket, never selected yet."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.runtime_router import (
    LANE_CLAUDE,
    LANE_CODEX,
    LANE_CODEX_SPARK,
    ROUTING_CONTRACT_VERSION,
    RoutingInput,
    RoutingPolicyV1,
    RuntimeRouter,
    _choose_candidate,
    _candidate,
    evaluate_routing,
)


NOW = datetime(2030, 1, 8, 12, tzinfo=timezone.utc)
SPARK_MODEL = "gpt-5.3-codex-spark"


def _policy(*, access="all", spark=SPARK_MODEL, revision=1):
    payload = {
        "schema_version": 1,
        "revision": revision,
        "mode": "quota",
        "codex_access": access,
        "models": {"claude": "claude-opus-5[1m]", "codex": "gpt-5.6-sol"},
        "claude": {
            "alert_deficit_hours": 14,
            "weekly_unavailable_pct": 95,
            "weekly_min_remaining_pp": 0.3,
            "five_hour_unavailable_pct": 95,
        },
        "codex": {"normal_below_pct": 90, "unavailable_at_pct": 95},
    }
    if spark is not None:
        payload["models"]["spark"] = spark
    return RoutingPolicyV1.model_validate(payload)


def _window(minutes, utilization, *, reset_hours=24):
    return {
        "window_minutes": minutes,
        "utilization": utilization,
        "resets_at": (NOW + timedelta(hours=reset_hours)).isoformat(),
    }


def _observation(*, codex=51, spark=0, age=1):
    """Buckets deliberately differ: reading the wrong one is visible, not a coincidence."""
    return {
        "providers": {
            "anthropic": {
                "label": "Claude",
                "windows": [
                    _window(300, 10, reset_hours=2),
                    _window(10080, 10, reset_hours=24 * 6),
                ],
            },
            "codex": {"label": "Codex", "windows": [_window(10080, codex, reset_hours=24 * 6)]},
            "codex_spark": {
                "label": "Codex Spark",
                "windows": [_window(10080, spark, reset_hours=24 * 6)],
            },
        },
        "observed_at_by_provider": {
            "anthropic": NOW.timestamp() - age,
            "codex": NOW.timestamp() - age,
            "codex_spark": NOW.timestamp() - age,
        },
    }


def _baseline():
    return 0.0, NOW - timedelta(days=2)


def _decide(policy, observation=None, **kwargs):
    return evaluate_routing(
        policy,
        kwargs.pop("request", RoutingInput(task_class="worker_general")),
        _observation() if observation is None else observation,
        claude_baseline=_baseline(),
        now=NOW,
        **kwargs,
    )


def _lane(decision, lane):
    return next(item for item in decision.candidates if item.lane == lane)


def test_spark_must_be_configured_as_its_own_lane_not_as_codex():
    with pytest.raises(ValidationError, match="configure it as models.spark"):
        RoutingPolicyV1.model_validate(
            {
                "schema_version": 1,
                "revision": 1,
                "mode": "quota",
                "models": {"claude": "claude-opus-5[1m]", "codex": SPARK_MODEL},
                "claude": {
                    "alert_deficit_hours": 14,
                    "weekly_unavailable_pct": 95,
                    "weekly_min_remaining_pp": 0.3,
                    "five_hour_unavailable_pct": 95,
                },
                "codex": {"normal_below_pct": 90, "unavailable_at_pct": 95},
            }
        )


def test_spark_lane_rejects_a_model_from_another_bucket():
    with pytest.raises(ValidationError, match="codex_spark bucket"):
        _policy(spark="gpt-5.6-sol")

    with pytest.raises(ValidationError, match="must resolve to the Codex runtime"):
        _policy(spark="claude-opus-5[1m]")


def test_spark_lane_is_observed_from_its_own_bucket_and_never_selected():
    decision = _decide(_policy())
    spark = _lane(decision, LANE_CODEX_SPARK)

    assert spark.state == "excluded"
    assert spark.reason == "spark_not_eligible"
    assert spark.runtime == "codex"
    assert spark.bucket == "codex_spark"
    assert spark.model == SPARK_MODEL
    # The mutation this pins: reading utilization from the `codex` bucket would give 51.
    assert spark.utilization == 0
    assert _lane(decision, LANE_CODEX).utilization == 51
    assert decision.selected_lane == LANE_CODEX
    assert decision.state == "selected"


def test_absent_spark_configuration_leaves_the_candidate_set_untouched():
    decision = _decide(_policy(spark=None))

    assert [item.lane for item in decision.candidates] == [LANE_CODEX, LANE_CLAUDE]


@pytest.mark.asyncio
async def test_spark_bucket_is_requested_only_when_the_lane_is_configured():
    async def loader(*, required_provider):
        requested.append(required_provider)
        return _observation()

    for spark, expected in ((None, ["anthropic", "codex"]),
                            (SPARK_MODEL, ["anthropic", "codex", "codex_spark"])):
        requested: list[str] = []
        router = RuntimeRouter(
            store=_PolicyOnlyStore(_policy(spark=spark)),
            observation_loader=loader,
            baseline_loader=lambda _reset: None,
        )
        await router._load_observation(
            _policy(spark=spark), RoutingInput(task_class="worker_general")
        )
        assert requested == expected


def test_terminal_limit_on_one_codex_bucket_does_not_disable_the_other():
    codex_down = _decide(_policy(), terminal_limited_buckets=frozenset({"codex"}))
    assert _lane(codex_down, LANE_CODEX).state == "unavailable"
    assert _lane(codex_down, LANE_CODEX).reason == "codex_terminal_limit"
    assert _lane(codex_down, LANE_CODEX_SPARK).state == "excluded"
    assert _lane(codex_down, LANE_CODEX_SPARK).reason == "spark_not_eligible"

    spark_down = _decide(_policy(), terminal_limited_buckets=frozenset({"codex_spark"}))
    assert _lane(spark_down, LANE_CODEX_SPARK).state == "unavailable"
    assert _lane(spark_down, LANE_CODEX_SPARK).reason == "spark_terminal_limit"
    assert _lane(spark_down, LANE_CODEX).state == "normal"


@pytest.mark.parametrize("task_class", ["worker_general", "review"])
def test_both_codex_lanes_are_observed_or_excluded_together(task_class):
    """Candidate shape must not depend on the task class — only on the policy.

    Under `review_only` a review sees telemetry and a worker_general does not; whatever the
    access gate decides, it must decide it for BOTH Codex lanes at once. Observing Spark while
    Sol is access-excluded would make the same policy produce two different decision shapes.
    """
    decision = _decide(
        _policy(access="review_only"),
        request=RoutingInput(task_class=task_class),
    )
    codex = _lane(decision, LANE_CODEX)
    spark = _lane(decision, LANE_CODEX_SPARK)

    assert (codex.utilization is None) == (spark.utilization is None)
    assert (codex.observed_at is None) == (spark.observed_at is None)
    if task_class == "review":
        assert codex.utilization == 51 and spark.utilization == 0
        assert spark.reason == "spark_not_eligible"
    else:
        assert codex.state == spark.state == "excluded"
        assert codex.reason == spark.reason
        assert "codex_access=review_only" in spark.reason


def test_codex_access_off_leaves_both_codex_lanes_without_telemetry():
    decision = _decide(_policy(access="off"))
    codex = _lane(decision, LANE_CODEX)
    spark = _lane(decision, LANE_CODEX_SPARK)

    assert codex.state == spark.state == "excluded"
    assert codex.utilization is None and spark.utilization is None
    assert decision.selected_lane == LANE_CLAUDE


def test_stale_spark_bucket_does_not_inherit_freshness_from_codex():
    observation = _observation()
    observation["observed_at_by_provider"]["codex_spark"] = NOW.timestamp() - 10_000
    spark = _lane(_decide(_policy(), observation), LANE_CODEX_SPARK)

    assert spark.state == "unavailable"
    assert "stale" in spark.reason or "age" in spark.reason


def test_continuation_follows_the_lane_of_its_model_not_the_runtime():
    decision = _decide(
        _policy(),
        request=RoutingInput(task_class="continuation", current_model="gpt-5.6-sol"),
    )

    assert decision.selected_lane == LANE_CODEX
    assert decision.selected_model == "gpt-5.6-sol"


def test_continuation_on_spark_is_not_mistaken_for_the_sol_lane():
    """The case that actually separates lane from runtime.

    For Sol both keys read `codex`, so a runtime-based lookup would pass the test above while
    being wrong. A Spark session is where the two disagree: its lane is `codex_spark` and its
    runtime is `codex`, and answering with the Sol lane would silently move the session to
    another model and another bucket.
    """
    candidates = {
        LANE_CODEX_SPARK: _candidate(LANE_CODEX_SPARK, SPARK_MODEL, "normal", "spark_normal"),
        LANE_CODEX: _candidate(LANE_CODEX, "gpt-5.6-sol", "normal", "codex_normal"),
        LANE_CLAUDE: _candidate(LANE_CLAUDE, "claude-opus-5[1m]", "normal", "claude_normal"),
    }
    chosen, _degraded = _choose_candidate(
        RoutingInput(task_class="continuation", current_model=SPARK_MODEL),
        candidates,
    )

    assert chosen.lane == LANE_CODEX_SPARK
    assert chosen.model == SPARK_MODEL


def test_spark_is_never_an_independent_reviewer_for_codex_work():
    """Holds even if Spark were selectable: one runtime, so the amplification loop stays a loop."""
    candidates = {
        LANE_CODEX_SPARK: _candidate(LANE_CODEX_SPARK, SPARK_MODEL, "normal", "spark_normal"),
        LANE_CODEX: _candidate(LANE_CODEX, "gpt-5.6-sol", "normal", "codex_normal"),
        LANE_CLAUDE: _candidate(LANE_CLAUDE, "claude-opus-5[1m]", "normal", "claude_normal"),
    }
    chosen, degraded = _choose_candidate(
        RoutingInput(task_class="review", implementation_runtimes=frozenset({"codex"})),
        candidates,
    )

    assert chosen.lane == LANE_CLAUDE
    assert degraded is None


def test_decision_contract_is_versioned_and_pins_the_lane_shape():
    decision = _decide(_policy())
    payload = decision.to_dict()

    assert ROUTING_CONTRACT_VERSION == "routing-v2"
    assert payload["selected_lane"] == LANE_CODEX
    assert {item["lane"] for item in payload["candidates"]} == {
        LANE_CODEX_SPARK,
        LANE_CODEX,
        LANE_CLAUDE,
    }
    for item in payload["candidates"]:
        assert item["bucket"] and item["runtime"]


def test_old_policy_document_without_spark_stays_valid():
    document = _policy(spark=None).model_dump_json(exclude_none=True)
    restored = RoutingPolicyV1.model_validate_json(document)

    assert restored.models is not None
    assert restored.models.spark is None
    assert restored.schema_version == 1


class _PolicyOnlyStore:
    def __init__(self, policy):
        self._policy = policy

    def policy_document(self):
        return self._policy.model_dump_json(exclude_none=True)


# --- T2: Spark becomes selectable, but only by explicit operator opt-in -------------------

def _spark_policy(*, eligible=("worker_general",), normal=90, stop=95, access="all"):
    payload = {
        "schema_version": 1,
        "revision": 1,
        "mode": "quota",
        "codex_access": access,
        "models": {
            "claude": "claude-opus-5[1m]",
            "codex": "gpt-5.6-sol",
            "spark": SPARK_MODEL,
        },
        "claude": {
            "alert_deficit_hours": 14,
            "weekly_unavailable_pct": 95,
            "weekly_min_remaining_pp": 0.3,
            "five_hour_unavailable_pct": 95,
        },
        "codex": {"normal_below_pct": 90, "unavailable_at_pct": 95},
        "spark": {
            "normal_below_pct": normal,
            "unavailable_at_pct": stop,
            "eligible_classes": list(eligible),
        },
    }
    return RoutingPolicyV1.model_validate(payload)


@pytest.mark.parametrize("forbidden", ["review", "continuation"])
def test_forbidden_classes_are_rejected_when_the_policy_is_written(forbidden):
    with pytest.raises(ValidationError, match=f"must not contain '{forbidden}'"):
        _spark_policy(eligible=(forbidden,))


def test_unknown_eligible_class_is_rejected_rather_than_ignored():
    with pytest.raises(ValidationError, match="unknown task class"):
        _spark_policy(eligible=("worker_genral",))


def test_spark_thresholds_without_a_spark_model_are_rejected():
    with pytest.raises(ValidationError, match="spark thresholds require models.spark"):
        RoutingPolicyV1.model_validate(
            {
                "schema_version": 1,
                "revision": 1,
                "mode": "quota",
                "models": {"claude": "claude-opus-5[1m]", "codex": "gpt-5.6-sol"},
                "claude": {
                    "alert_deficit_hours": 14,
                    "weekly_unavailable_pct": 95,
                    "weekly_min_remaining_pp": 0.3,
                    "five_hour_unavailable_pct": 95,
                },
                "codex": {"normal_below_pct": 90, "unavailable_at_pct": 95},
                "spark": {"normal_below_pct": 90, "unavailable_at_pct": 95},
            }
        )


def test_spark_threshold_order_is_validated():
    with pytest.raises(ValidationError, match="normal_below_pct must be below"):
        _spark_policy(normal=95, stop=90)


def test_empty_eligible_classes_keeps_spark_unselectable():
    decision = _decide(_spark_policy(eligible=()))
    spark = _lane(decision, LANE_CODEX_SPARK)

    assert spark.state == "excluded"
    assert spark.reason == "spark_not_eligible_for_worker_general"
    assert decision.selected_lane == LANE_CODEX


def test_healthy_sol_keeps_the_work_even_when_spark_is_eligible_and_free():
    """The invariant that stops this feature from being a silent downgrade.

    Spark is the weaker lane. It exists to add capacity when the Sol bucket is burning, not to
    become a cheaper default: with both lanes normal the work stays on Sol.
    """
    decision = _decide(_spark_policy(), _observation(codex=10, spark=0))

    assert decision.selected_lane == LANE_CODEX
    assert _lane(decision, LANE_CODEX_SPARK).state == "normal"


def test_spark_takes_eligible_work_once_the_sol_bucket_is_reserved():
    decision = _decide(_spark_policy(), _observation(codex=91, spark=0))
    spark = _lane(decision, LANE_CODEX_SPARK)

    assert _lane(decision, LANE_CODEX).state == "reserve_only"
    assert decision.selected_lane == LANE_CODEX_SPARK
    assert decision.selected_model == SPARK_MODEL
    assert spark.reason == "spark_quota_normal"
    assert spark.bucket == "codex_spark"
    assert spark.detail == "worker_general"


@pytest.mark.parametrize(
    "provenance",
    [frozenset({"claude"}), frozenset({"codex"}), frozenset({"claude", "codex"}), frozenset()],
)
def test_review_never_reaches_spark_whatever_wrote_the_code(provenance):
    decision = _decide(
        _spark_policy(),
        _observation(codex=91, spark=0),
        request=RoutingInput(task_class="review", implementation_runtimes=provenance),
    )
    spark = _lane(decision, LANE_CODEX_SPARK)

    assert spark.state == "excluded"
    assert spark.reason == "spark_not_eligible_for_review"
    assert decision.selected_lane != LANE_CODEX_SPARK


def test_a_session_already_on_spark_keeps_its_lane():
    """Eligibility places NEW work; it never evicts running work.

    `continuation` can never be opted in, so a naive reading would move a live Spark session onto
    another model — which resets the native session, the exact harm the prohibition prevents.
    """
    decision = _decide(
        _spark_policy(),
        _observation(codex=10, spark=0),
        request=RoutingInput(task_class="continuation", current_model=SPARK_MODEL),
    )

    assert decision.selected_lane == LANE_CODEX_SPARK
    assert decision.selected_model == SPARK_MODEL
    assert _lane(decision, LANE_CODEX_SPARK).reason == "spark_quota_normal"


def test_a_sol_session_is_never_moved_onto_spark_when_its_own_bucket_dies():
    decision = _decide(
        _spark_policy(),
        _observation(codex=99, spark=0),
        request=RoutingInput(task_class="continuation", current_model="gpt-5.6-sol"),
    )

    assert _lane(decision, LANE_CODEX).state == "unavailable"
    assert _lane(decision, LANE_CODEX_SPARK).state == "excluded"
    assert decision.selected_lane != LANE_CODEX_SPARK


@pytest.mark.parametrize(
    ("utilization", "state", "reason"),
    [(10, "normal", "spark_quota_normal"),
     (60, "reserve_only", "spark_weekly_reserve"),
     (80, "unavailable", "spark_weekly_hard_stop")],
)
def test_spark_reads_its_own_thresholds(utilization, state, reason):
    """Spark thresholds are deliberately unlike Sol's (50/70 against 90/95).

    With both set to the same numbers the assertion cannot tell which policy block was read, and
    a mutation swapping `policy.spark` for `policy.codex` survives — measured, not assumed.
    """
    decision = _decide(
        _spark_policy(normal=50, stop=70),
        _observation(codex=91, spark=utilization),
    )
    spark = _lane(decision, LANE_CODEX_SPARK)

    assert (spark.state, spark.reason) == (state, reason)


def test_spark_thresholds_require_a_model_in_manifest_mode_too():
    """The invariant is about document consistency, so it cannot depend on the active mode."""
    with pytest.raises(ValidationError, match="spark thresholds require models.spark"):
        RoutingPolicyV1.model_validate(
            {
                "schema_version": 1,
                "revision": 1,
                "mode": "manifest_default",
                "spark": {"normal_below_pct": 50, "unavailable_at_pct": 70},
            }
        )


@pytest.mark.parametrize(
    ("case", "expected_state", "expected_reason"),
    [
        ("access_off", "excluded", "codex_access=off excludes continuation"),
        ("terminal", "unavailable", "spark_terminal_limit"),
        ("stale", "unavailable", None),
        ("hard_stop", "unavailable", "spark_weekly_hard_stop"),
    ],
)
def test_a_staying_spark_session_is_still_subject_to_every_guard(
    case, expected_state, expected_reason
):
    """The carve-out must not become a bypass.

    Ordering in the code puts access, terminal, freshness and thresholds ahead of `staying`.
    Without these cases the continuation test would stay green if a guard were ever moved below
    the carve-out, which would let a dead or unobserved bucket keep taking work.
    """
    policy = _spark_policy(normal=50, stop=70, access="off" if case == "access_off" else "all")
    observation = _observation(codex=10, spark=80 if case == "hard_stop" else 0)
    if case == "stale":
        observation["observed_at_by_provider"]["codex_spark"] = NOW.timestamp() - 10_000
    terminal = frozenset({"codex_spark"}) if case == "terminal" else frozenset()

    decision = _decide(
        policy,
        observation,
        request=RoutingInput(task_class="continuation", current_model=SPARK_MODEL),
        terminal_limited_buckets=terminal,
    )
    spark = _lane(decision, LANE_CODEX_SPARK)

    assert spark.state == expected_state
    if expected_reason is not None:
        assert spark.reason == expected_reason
    assert decision.selected_lane != LANE_CODEX_SPARK
