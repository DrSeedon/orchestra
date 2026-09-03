"""Unified event model for all agent backends."""

import json
from dataclasses import dataclass, field
from typing import Any

from app.usage_contract import TurnUsage


MESSAGE_ORIGINS = frozenset({
    "user", "agent", "background_task", "platform", "system", "unknown",
})


@dataclass(frozen=True)
class MessageProvenance:
    """Canonical authorship carried with server-delivered user input."""

    origin: str
    senders: tuple[str, ...]
    subtype: str = ""
    ref: str = ""

    def __post_init__(self) -> None:
        if self.origin not in MESSAGE_ORIGINS:
            raise ValueError(f"invalid message origin: {self.origin!r}")
        if isinstance(self.senders, str):
            raise ValueError("message senders must be a non-empty sequence")
        try:
            raw_senders = tuple(self.senders)
        except TypeError as error:
            raise ValueError("message senders must be a non-empty sequence") from error
        normalized: list[str] = []
        seen: set[str] = set()
        for sender in raw_senders:
            if not isinstance(sender, str) or not sender.strip():
                raise ValueError("message sender must be a non-empty string")
            sender = sender.strip()
            if sender not in seen:
                seen.add(sender)
                normalized.append(sender)
        if not normalized:
            raise ValueError("message senders must not be empty")
        object.__setattr__(self, "senders", tuple(normalized))
        for field_name in ("subtype", "ref"):
            value = getattr(self, field_name)
            if not isinstance(value, str):
                raise ValueError(f"message {field_name} must be a string")
            if value and not value.strip():
                raise ValueError(f"message {field_name} must not be blank")
            object.__setattr__(self, field_name, value.strip())

    def detail(self) -> dict[str, Any]:
        value: dict[str, Any] = {"senders": list(self.senders)}
        if self.subtype:
            value["subtype"] = self.subtype
        if self.ref:
            value["ref"] = self.ref
        return value

    def to_storage(self) -> tuple[str, str]:
        return (
            self.origin,
            json.dumps(
                self.detail(), ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            ),
        )

    @classmethod
    def from_storage(cls, origin: str, detail: str | dict[str, Any]) -> "MessageProvenance":
        try:
            value = json.loads(detail) if isinstance(detail, str) else detail
        except json.JSONDecodeError as error:
            raise ValueError("message origin_detail must be valid JSON") from error
        if not isinstance(value, dict):
            raise ValueError("message origin_detail must be an object")
        extra = set(value) - {"senders", "subtype", "ref"}
        if extra:
            raise ValueError(f"unknown message origin_detail keys: {sorted(extra)!r}")
        senders = value.get("senders")
        if not isinstance(senders, list):
            raise ValueError("message origin_detail senders must be a JSON array")
        return cls(
            origin=origin,
            senders=senders,
            subtype=value.get("subtype", ""),
            ref=value.get("ref", ""),
        )


@dataclass(frozen=True)
class InjectedMessage:
    """Server-owned user input with provenance unavailable to model-authored text."""

    text: str
    provenance: MessageProvenance
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
