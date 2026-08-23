"""Unified event model for all agent backends."""

from dataclasses import dataclass, field

from app.usage_contract import TurnUsage


@dataclass(frozen=True)
class InjectedMessage:
    """Server-owned user input with provenance unavailable to model-authored text."""

    text: str
    origin: str
    job_id: str
    event_id: str

    def __contains__(self, value: object) -> bool:
        return isinstance(value, str) and value in self.text

    def lower(self) -> str:
        return self.text.lower()

    def __str__(self) -> str:
        return self.text


@dataclass
class AgentEvent:
    type: str
    content: str = ""
    metadata: dict = field(default_factory=dict)
    usage: TurnUsage | None = None

# type values:
# "text"              — agent text output
# "thinking"          — agent reasoning/thinking output
# "tool_use"          — tool invocation (content = "tool_name: input_summary")
# "tool_result"       — tool output
# "file_change"       — file edit (content = "add /path" or "update /path")
# "turn_end"          — turn completed (metadata: session_id, cost_usd, input_tokens, context_pct, ok, stop_reason, ...)
# "error"             — error message
# "status"            — lifecycle event
# "subagent_start"    — sub-agent spawned    (metadata: subagent_id, phase, description, task_type, sdk_session_id, tool_use_id)
# "subagent_progress" — sub-agent working     (metadata: + last_tool_name, total_tokens, tool_uses, duration_ms)
# "subagent_end"      — sub-agent finished    (metadata: + status, summary, output_file, raw_json, usage)
# "subagent_stream"   — sub-agent live text   (metadata: subagent_id) — broker only, ephemeral
