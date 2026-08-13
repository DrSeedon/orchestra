## Summary

Implementation correctly suppresses only exact `text == TG_SILENT_TURN_MARKER` Telegram delivery while preserving the immutable log and avoiding primary/mirror delivery, owner mentions, and queue-policy changes.

## Findings

No blocking issues or suggestions found.

## Verdict

APPROVED

Verified with:

`uv run pytest -q tests/test_tg_bridge.py::TestTurnEndMention`

Result: `20 passed in 5.61s`.
