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
    # Legacy input_tokens semantics differ by runtime. Never change that field.
    input_includes_cache: bool = False
    accuracy: str = "reported"

    @classmethod
    def normalized(
        cls,
        *,
        input_tokens: object = 0,
        output_tokens: object = 0,
        cache_read_tokens: object = 0,
        cache_create_tokens: object = 0,
        model_calls: object = None,
        input_includes_cache: bool = False,
        accuracy: str = "reported",
    ) -> "AggregateUsage":
        valid_accuracy = accuracy if accuracy in {"reported", "estimated", "unknown"} else "unknown"
        for value in (input_tokens, output_tokens, cache_read_tokens, cache_create_tokens):
            try:
                if value is None or isinstance(value, bool) or int(value) < 0 or float(value) != int(value):
                    valid_accuracy = "unknown"
            except (TypeError, ValueError, OverflowError):
                valid_accuracy = "unknown"
        if input_includes_cache and _count(cache_read_tokens) + _count(cache_create_tokens) > _count(input_tokens):
            valid_accuracy = "unknown"
        return cls(
            input_tokens=_count(input_tokens),
            output_tokens=_count(output_tokens),
            cache_read_tokens=_count(cache_read_tokens),
            cache_create_tokens=_count(cache_create_tokens),
            model_calls=_optional_count(model_calls),
            input_includes_cache=input_includes_cache,
            accuracy=valid_accuracy,
        )

    def derived(self) -> dict:
        """Disjoint token buckets; unknown measurements are nullable, never zero."""
        if self.accuracy == "unknown":
            return {**dict.fromkeys(("prompt_total", "fresh_input", "cache_read", "cache_write",
                                    "output", "cache_read_fraction")), "accuracy": "unknown"}
        cached = self.cache_read_tokens + self.cache_create_tokens
        fresh = max(0, self.input_tokens - cached) if self.input_includes_cache else self.input_tokens
        total = fresh + cached
        return {
            "prompt_total": total, "fresh_input": fresh,
            "cache_read": self.cache_read_tokens, "cache_write": self.cache_create_tokens,
            "output": self.output_tokens,
            "cache_read_fraction": self.cache_read_tokens / total if total > 0 else None,
            "accuracy": self.accuracy,
        }


def usage_for_runtime(runtime: str, **counts: object) -> AggregateUsage:
    """Legacy persisted counters use the same semantics as their backend."""
    return AggregateUsage.normalized(
        **counts, input_includes_cache=runtime in {"codex", "grok"},
        accuracy="unknown" if runtime in {"hub", "unknown", "antigravity"} else "reported",
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
            # Keep cache_read (legacy integer) untouched; the complete nullable contract
            # is namespaced as well as exposing the new non-conflicting fields.
            "normalized_usage": aggregate.derived(),
            **{key: value for key, value in aggregate.derived().items() if key != "cache_read"},
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
