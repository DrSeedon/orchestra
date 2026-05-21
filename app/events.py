"""Unified event model for all agent backends."""

from dataclasses import dataclass, field


@dataclass
class AgentEvent:
    type: str
    content: str = ""
    metadata: dict = field(default_factory=dict)

# type values:
# "text"              — agent text output
# "tool_use"          — tool invocation (content = "tool_name: input_summary")
# "tool_result"       — tool output
# "file_change"       — file edit (content = "add /path" or "update /path")
# "turn_end"          — turn completed (metadata: session_id, cost_usd, input_tokens, context_pct, ok, stop_reason, ...)
# "error"             — error message
# "status"            — lifecycle event
# "subagent_start"    — sub-agent spawned
# "subagent_progress" — sub-agent working
# "subagent_end"      — sub-agent finished
