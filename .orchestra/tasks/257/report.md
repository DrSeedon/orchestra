# #257 — explicit silent-turn marker for Telegram

## Contract

The marker is exactly:

```text
[[ORCHESTRA:SILENT_TURN]]
```

Only a `logs.type == "text"` row whose raw content equals that token byte-for-byte is omitted
from Telegram delivery. Leading/trailing whitespace, a prefix, a suffix, a newline with an
explanation, the old `_` placeholder, and the same token in `user_message` or `error` rows all
remain visible.

The filter lives in `stream_logs`, after the immutable log was read from SQLite and before both
the primary topic send and the TG mirror send. It therefore does not alter persistence, dashboard
history, session history, status/turn anchors, or tool telemetry; only the agent-text Telegram
payload is skipped. Because the marker does not set `_spoke_this_turn`, a genuinely silent
orchestrator turn also does not generate an owner mention.

## Failure direction

- Agent omits or mistypes the marker → the literal text is delivered, matching today's noisy but
  observable behavior.
- Filter broadens beyond exact agent-text equality → tests fail on four near-misses plus the same
  token as user/error content. This is the protected, dangerous direction because broad matching
  would hide real messages.

The existing `important=False` cosmetic lane is not reused as the semantic decision. It is a
best-effort transport lane: such traffic may be delivered or dropped depending on load. Sending
the marker there would still expose it sometimes, while classifying other text as cosmetic would
reintroduce silent loss. `stream_logs` remains the single owner of log-type-to-Telegram policy;
the exact marker is one additional branch beside its existing status suppression.
