"""CostTracker — turn cost/token accounting system over AgentSession state.

Stateless method-holder (ECS style): all fields live on the session; this class
only encapsulates the delta-based cost arithmetic. Extracted AS-IS from
AgentSession — the delta→total rewrite suggested by the audit is a deliberate
non-goal (behavior-preserving refactor).
"""

from typing import TYPE_CHECKING

from app.usage_contract import (
    DeferredContext,
    KnownContext,
    TurnUsage,
    UnknownContext,
    current_context,
    deferred_context,
)

if TYPE_CHECKING:
    from app.session import AgentSession


class CostTracker:
    def __init__(self, s: "AgentSession") -> None:
        self.s = s

    def apply_turn_result(
        self, meta: dict, usage: TurnUsage | None = None,
    ) -> tuple[bool, str, int]:
        """Update session_id, costs, token totals from turn metadata."""
        s = self.s
        ok = meta.get("ok", True)
        sr = meta.get("stop_reason", "unknown")
        nt = meta.get("num_turns", 0)
        s._last_turn_ok = ok
        s._last_stop_reason = sr

        sid = meta.get("session_id")
        if sid and sid != s.session_id:
            # SDK reports cost_usd cumulative per session_id — reset baseline
            # when a new session starts (e.g. after compact creates a fresh session)
            s._last_cost = 0.0
            s._last_cost_cached = 0.0
            s._context_cost = 0.0
        if sid:
            s.session_id = sid
        new_cost = meta.get("cost_usd", 0)
        is_delta = bool(meta.get("cost_is_delta"))
        # Claude SDK reports cumulative session cost; CodexBackend normalizes its own
        # cumulative thread counters to a per-turn delta before emitting metadata.
        s._turn_cost = max(0, new_cost) if is_delta else max(0, new_cost - s._last_cost)
        s.cost_usd += s._turn_cost
        s._context_cost += s._turn_cost
        s._session_cost += s._turn_cost
        s._last_cost = 0.0 if is_delta else new_cost
        new_cost_cached = meta.get("cost_usd_cached", 0)
        if is_delta:
            s.cost_usd_cached += max(0, new_cost_cached)
            s._last_cost_cached = 0.0
        else:
            s.cost_usd_cached += max(0, new_cost_cached - s._last_cost_cached)
            s._last_cost_cached = new_cost_cached
        s.total_turns += nt
        aggregate = usage.aggregate if usage is not None else None
        s.total_input_tokens += (
            aggregate.input_tokens if aggregate else meta.get("input_tokens", 0)
        )
        s.total_output_tokens += (
            aggregate.output_tokens if aggregate else meta.get("output_tokens", 0)
        )
        s.total_cache_read_tokens += (
            aggregate.cache_read_tokens if aggregate else meta.get("cache_read", 0)
        )
        s.total_cache_create_tokens += (
            aggregate.cache_create_tokens if aggregate else meta.get("cache_create", 0)
        )
        return ok, sr, nt

    def update_context_from_turn(
        self, meta: dict, usage: TurnUsage | None = None,
    ) -> tuple[bool, str | None]:
        """Update context stats and return whether compaction has valid input."""
        s = self.s
        if usage is not None:
            context = usage.current
        elif meta.get("context_deferred"):
            context = deferred_context(
                meta.get("max_tokens"),
                str(meta.get("context_source") or "external"),
            )
        elif meta.get("context_known") is True:
            context = current_context(
                meta.get("context_tokens"),
                meta.get("max_tokens"),
                percentage=meta.get("context_pct"),
            )
        else:
            try:
                max_tokens = max(0, int(meta.get("max_tokens") or 0))
            except (TypeError, ValueError, OverflowError):
                max_tokens = 0
            context = UnknownContext(
                max_tokens,
                str(
                    meta.get("context_unknown_reason")
                    or "turn_end omitted a valid typed current context"
                ),
            )

        if isinstance(context, KnownContext):
            s._last_context["percentage"] = context.percentage
            s._last_context["total_tokens"] = context.tokens
            s._last_context["max_tokens"] = context.max_tokens
            s._last_context["known"] = True
            known = True
            reason = None
        elif isinstance(context, DeferredContext):
            if context.max_tokens:
                s._last_context["max_tokens"] = context.max_tokens
            known = s._context_is_known()
            reason = None
        else:
            s._last_context["percentage"] = 0
            s._last_context["total_tokens"] = 0
            if context.max_tokens:
                s._last_context["max_tokens"] = context.max_tokens
            s._last_context["known"] = False
            known = False
            reason = context.reason

        s._last_context["cache_hit"] = meta.get("cache_hit", 0)
        s._last_context["cache_read"] = meta.get("cache_read", 0)
        s._last_context["cache_create"] = meta.get("cache_create", 0)
        return known, reason
