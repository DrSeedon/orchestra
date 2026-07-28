import pytest

from app.usage_contract import (
    AggregateUsage,
    KnownContext,
    TurnUsage,
    UnknownContext,
    current_context,
)


def test_aggregate_usage_cannot_masquerade_as_current_context():
    usage = TurnUsage(
        aggregate=AggregateUsage.normalized(
            input_tokens=1_665_949,
            output_tokens=12_522,
            cache_read_tokens=1_581_056,
            model_calls=25,
        ),
        current=current_context(
            None,
            500_000,
            unknown_reason="aggregate totals are not current context",
        ),
    )

    metadata = usage.metadata()

    assert usage.aggregate.input_tokens == 1_665_949
    assert usage.aggregate.model_calls == 25
    assert isinstance(usage.current, UnknownContext)
    assert metadata["input_tokens"] == 1_665_949
    assert metadata["context_known"] is False
    assert metadata["context_tokens"] == 0
    assert metadata["context_pct"] == 0
    assert "total_tokens" not in metadata


def test_known_current_context_has_its_own_type_and_percentage():
    usage = TurnUsage(
        AggregateUsage.normalized(input_tokens=1_665_949),
        current_context(84_482, 500_000),
    )

    assert isinstance(usage.current, KnownContext)
    assert usage.current.tokens == 84_482
    assert usage.metadata()["context_pct"] == 16
    assert usage.metadata()["context_known"] is True


@pytest.mark.parametrize("current", [None, -1, 500_001])
def test_missing_negative_and_impossible_current_context_are_unknown(current):
    context = current_context(current, 500_000)

    assert isinstance(context, UnknownContext)


def test_non_finite_numbers_are_fail_soft():
    aggregate = AggregateUsage.normalized(
        input_tokens=float("inf"),
        output_tokens=float("-inf"),
        model_calls=float("inf"),
    )

    assert aggregate.input_tokens == 0
    assert aggregate.output_tokens == 0
    assert aggregate.model_calls is None
    assert isinstance(current_context(float("inf"), 500_000), UnknownContext)
    assert isinstance(current_context(1, float("inf")), UnknownContext)
    assert isinstance(
        current_context(1, 500_000, percentage=float("inf")),
        UnknownContext,
    )
