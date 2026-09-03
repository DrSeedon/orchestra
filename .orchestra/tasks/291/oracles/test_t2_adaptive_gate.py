import importlib
import importlib.util
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier


def _controller():
    spec = importlib.util.find_spec("app.quota_controller")
    assert spec is not None, "app.quota_controller is not implemented"
    return importlib.import_module("app.quota_controller")


def _constraint(
    utilization,
    *,
    bucket="codex:primary",
    inflight=0.0,
    q95=3.0,
    guard=1.0,
    reserve=2.0,
):
    return {
        "bucket": bucket,
        "utilization": utilization,
        "inflight_reserved_pp": inflight,
        "q95_next_turn_pp": q95,
        "guard_pp": guard,
        "reserve_pp": reserve,
        "reset_at": "2030-01-07T00:00:00Z",
        "observed_at": "2030-01-01T00:00:00Z",
        "regime_key": f"r:{bucket}",
        "confidence": "operational",
    }


def test_t2_exact_inclusive_gate_and_parallel_reservation():
    controller = _controller()
    exact = controller.evaluate_dispatch(
        constraints=[_constraint(93)],
        target_pct=99,
    )
    over = controller.evaluate_dispatch(
        constraints=[_constraint(93, inflight=1)],
        target_pct=99,
    )

    assert exact.constraints[0].lhs_pp == exact.constraints[0].rhs_pp == 97
    assert exact.would_allow is True
    assert over.constraints[0].lhs_pp == 98
    assert over.would_allow is False


def test_t2_fable_requires_all_three_constraints():
    controller = _controller()
    decision = controller.evaluate_dispatch(
        constraints=[
            _constraint(
                20, bucket="anthropic:five_hour", q95=4, guard=0.5, reserve=1,
            ),
            _constraint(
                40, bucket="anthropic:seven_day", q95=1, guard=1, reserve=8,
            ),
            _constraint(
                98.5,
                bucket="anthropic_fable:weekly_scoped",
                q95=0.25,
                guard=0.5,
                reserve=0,
            ),
        ],
        target_pct=99,
    )

    assert len(decision.constraints) == 3
    assert [item.q95_next_turn_pp for item in decision.constraints] == [4, 1, 0.25]
    assert [item.reserve_pp for item in decision.constraints] == [1, 8, 0]
    assert decision.would_allow is False
    assert decision.binding_constraint == "anthropic_fable:weekly_scoped"


def test_t2_two_db_reservations_cannot_both_spend_final_headroom(tmp_path):
    controller = _controller()
    store = controller.SQLiteControllerStore(tmp_path / "controller.db")
    barrier = Barrier(2)

    def reserve(decision_id):
        barrier.wait()
        return store.reserve_shadow_dispatch(
            decision_id=decision_id,
            constraints=[
                _constraint(95, q95=2, guard=0.5, reserve=0),
            ],
            target_pct=99,
            context={"session_id": decision_id, "turn_gen": 1},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, ("d-a", "d-b")))

    assert sorted(result.would_allow for result in results) == [False, True]
    assert store.active_reserved_pp("codex:primary", "r:codex:primary") == 2
    assert store.decision_count() == 2


def test_t2_fast_multiplies_codex_primary_only():
    controller = _controller()

    assert controller.constraints_for_model(
        "gpt-5.6-sol", fast_mode=True
    ) == ({"bucket": "codex:primary", "q95_multiplier": 2.5},)
    assert controller.constraints_for_model(
        "gpt-5.3-codex-spark", fast_mode=False
    ) == ({"bucket": "codex_spark:primary", "q95_multiplier": 1.0},)
    assert controller.constraints_for_model(
        "grok-4.6", fast_mode=False
    ) == ({"bucket": "grok:primary", "q95_multiplier": 1.0},)


def test_t2_unknown_drift_and_corruption_are_indeterminate_not_hard_stops():
    controller = _controller()

    for reason in ("telemetry_stale", "plan_changed", "counter_drop", "value_corrupt"):
        decision = controller.evaluate_dispatch(
            constraints=[{
                **_constraint(30, q95=2, guard=0.5, reserve=1),
                "invalid_reason": reason,
            }],
            target_pct=99,
        )
        assert decision.would_allow is None
        assert decision.zone == "FAIL_SAFE"
        assert reason in decision.reasons
