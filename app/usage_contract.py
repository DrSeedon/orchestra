"""Typed usage values shared by runtime backends and turn accounting."""

from dataclasses import dataclass
from typing import TypeAlias


def _count(value: object) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _optional_count(value: object) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return None


@dataclass(frozen=True)
class AggregateUsage:
    """Billed totals accumulated across every model call in one runtime turn."""

    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_create_tokens: int = 0
    model_calls: int | None = None

    @classmethod
    def normalized(
        cls,
        *,
        input_tokens: object = 0,
        output_tokens: object = 0,
        cache_read_tokens: object = 0,
        cache_create_tokens: object = 0,
        model_calls: object = None,
    ) -> "AggregateUsage":
        return cls(
            input_tokens=_count(input_tokens),
            output_tokens=_count(output_tokens),
            cache_read_tokens=_count(cache_read_tokens),
            cache_create_tokens=_count(cache_create_tokens),
            model_calls=_optional_count(model_calls),
        )


@dataclass(frozen=True)
class KnownContext:
    """Occupied prompt/window measured at the end of the latest model call."""

    tokens: int
    max_tokens: int
    percentage: int


@dataclass(frozen=True)
class UnknownContext:
    """No valid current-context measurement is available for this turn."""

    max_tokens: int
    reason: str


@dataclass(frozen=True)
class DeferredContext:
    """The provider reports context through a separate authoritative channel."""

    max_tokens: int
    source: str


CurrentContext: TypeAlias = KnownContext | UnknownContext | DeferredContext


def current_context(
    current_tokens: object,
    max_tokens: object,
    *,
    semantics_known: bool = True,
    percentage: object = None,
    unknown_reason: str = "",
) -> KnownContext | UnknownContext:
    """Validate a current-context measurement without rejecting the turn."""
    valid_max = _optional_count(max_tokens)
    normalized_max = valid_max or 0
    if not semantics_known:
        return UnknownContext(
            normalized_max,
            unknown_reason or "current context semantics are not proven",
        )
    if current_tokens is None:
        return UnknownContext(
            normalized_max,
            unknown_reason or "current context is missing",
        )
    if isinstance(current_tokens, bool):
        return UnknownContext(normalized_max, "current context is not an integer")
    try:
        normalized_current = int(current_tokens)
    except (TypeError, ValueError, OverflowError):
        return UnknownContext(normalized_max, "current context is not an integer")
    if normalized_current < 0:
        return UnknownContext(normalized_max, "current context is negative")
    if not valid_max:
        return UnknownContext(normalized_max, "maximum context is missing or invalid")
    if normalized_current > valid_max:
        return UnknownContext(
            normalized_max,
            f"current context {normalized_current} exceeds maximum {valid_max}",
        )

    if percentage is None:
        normalized_percentage = int(normalized_current * 100 / valid_max)
    elif isinstance(percentage, bool):
        return UnknownContext(normalized_max, "context percentage is not numeric")
    else:
        try:
            normalized_percentage = int(percentage)
        except (TypeError, ValueError, OverflowError):
            return UnknownContext(normalized_max, "context percentage is not numeric")
        if not 0 <= normalized_percentage <= 100:
            return UnknownContext(normalized_max, "context percentage is outside 0..100")

    return KnownContext(
        tokens=normalized_current,
        max_tokens=valid_max,
        percentage=normalized_percentage,
    )


def deferred_context(max_tokens: object, source: str) -> DeferredContext:
    return DeferredContext(max_tokens=_optional_count(max_tokens) or 0, source=source)


@dataclass(frozen=True)
class TurnUsage:
    """One turn's billed aggregate plus a semantically distinct current context."""

    aggregate: AggregateUsage
    current: CurrentContext

    def metadata(self) -> dict:
        aggregate = self.aggregate
        result = {
            "input_tokens": aggregate.input_tokens,
            "output_tokens": aggregate.output_tokens,
            "cached_input_tokens": aggregate.cache_read_tokens,
            "cache_read": aggregate.cache_read_tokens,
            "cache_create": aggregate.cache_create_tokens,
            "model_calls": aggregate.model_calls,
        }
        current = self.current
        if isinstance(current, KnownContext):
            result.update({
                "context_pct": current.percentage,
                "context_tokens": current.tokens,
                "context_known": True,
                "max_tokens": current.max_tokens,
            })
        elif isinstance(current, DeferredContext):
            result.update({
                "context_pct": 0,
                "context_tokens": 0,
                "context_known": False,
                "context_deferred": True,
                "context_source": current.source,
                "max_tokens": current.max_tokens,
            })
        else:
            result.update({
                "context_pct": 0,
                "context_tokens": 0,
                "context_known": False,
                "context_unknown_reason": current.reason,
                "max_tokens": current.max_tokens,
            })
        return result
