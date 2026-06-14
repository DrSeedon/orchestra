"""CostTracker — turn cost/token accounting system over AgentSession state.

Stateless method-holder (ECS style): all fields live on the session; this class
only encapsulates the delta-based cost arithmetic. Extracted AS-IS from
AgentSession — the delta→total rewrite suggested by the audit is a deliberate
non-goal (behavior-preserving refactor).
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.session import AgentSession


class CostTracker:
    def __init__(self, s: "AgentSession") -> None:
        self.s = s

    def apply_turn_result(self, meta: dict) -> tuple[bool, str, int]:
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
        # Delta from last known cumulative — gives per-turn cost without SDK support
        s._turn_cost = max(0, new_cost - s._last_cost)
        s.cost_usd += s._turn_cost
        s._context_cost += s._turn_cost
        s._session_cost += s._turn_cost
        s._last_cost = new_cost
        new_cost_cached = meta.get("cost_usd_cached", 0)
        s.cost_usd_cached += max(0, new_cost_cached - s._last_cost_cached)
        s._last_cost_cached = new_cost_cached
        s.total_turns += nt
        s.total_input_tokens += meta.get("input_tokens", 0)
        s.total_output_tokens += meta.get("output_tokens", 0)
        return ok, sr, nt

    def update_context_from_turn(self, meta: dict) -> None:
        """Update context window stats from turn metadata."""
        s = self.s
        ctx_pct = meta.get("context_pct", 0)
        ctx_tokens = meta.get("context_tokens", 0)
        if ctx_pct:
            s._last_context["percentage"] = ctx_pct
            s._last_context["total_tokens"] = ctx_tokens
        s._last_context["max_tokens"] = meta.get("max_tokens", 200000)
        s._last_context["cache_hit"] = meta.get("cache_hit", 0)
        s._last_context["cache_read"] = meta.get("cache_read", 0)
        s._last_context["cache_create"] = meta.get("cache_create", 0)
