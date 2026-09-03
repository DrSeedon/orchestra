# #441 — capture Claude rate-limit telemetry

## Diagnosis

`claude_agent_sdk 0.2.114` exposes `RateLimitEvent`; its `RateLimitInfo.raw` contains the
complete CLI payload, including fractional `utilization` and `unifiedWindows`. The dispatcher
in `app/backend_claude.py` had no `RateLimitEvent` branch, so the payload was discarded before
session logging.

## Fix

- Import `RateLimitEvent` in a guarded `try/except ImportError`; older SDKs leave the optional
  class unset and continue through the existing dispatcher.
- Convert the event to the existing `status` path with content beginning with the literal
  `RATE_LIMIT_RAW ` followed by `json.dumps(info.raw, ensure_ascii=False)`. Python's JSON encoder
  preserves the float representation (`0.16327272727272726`) without percentage rounding.
- No database schema, session code, or live application code was changed.

## Evidence

- Acceptance: `uv run pytest -q tests/test_rate_limit_capture_441.py` → `2 passed`.
- Existing Claude suite on the branch: `uv run pytest -q tests/test_backend_claude.py` → `31 passed`.
- Existing Claude suite on `main`: same command → `31 passed`.
- Node-id comparison in one command (`pytest --collect-only`, sorted, `diff -u`): `31` IDs on
  `main` and `31` on the branch, with no diff.
- Mutation: the serialization was changed to
  `round(raw['utilization'] * 100)`. Production marker `_json.dumps(raw, ensure_ascii=False)`
  counted `1` before mutation, `0` during mutation, and `1` after `mv app/backend_claude.py.bak
  app/backend_claude.py` plus `touch`. Mutated acceptance run: `1 failed, 1 passed` (the exact
  fractional/raw assertion failed). Green repeat after rollback: `2 passed`.
- Read-only production DB session count around the acceptance run: `sessions_before=599`,
  `sessions_after=599`.

Python changes are loaded only after service restart; this task was checked with tests only, not
against a restarted service or provider.

## Review gate

- Changed files and consumers: `app/backend_claude.py` (`ClaudeBackend._convert`) feeds the
  existing `AgentSession._handle_event` status branch and its durable `logs` row/UI; the new
  `tests/test_rate_limit_capture_441.py` is the named regression oracle; this report records
  evidence.
- Author metadata from the live session row: model `gpt-5.6-luna`, runtime/backend `codex`.
- Named AC and command: exact raw payload, exact fractional representation, and guarded import;
  `uv run pytest -q tests/test_rate_limit_capture_441.py` → `2 passed` (and mutation red as
  recorded above).
- Route: `Review: none — Sol not authorized`. This is a data-loss/persistence surface, whose
  floor is Sol; the task did not authorize an additional Sol model call. No lower route was used.
- Independence evidence: the oracle is deterministic and its mutation is red, but it was added
  in this implementation, so it is not a pre-existing strong independent oracle; the unchanged
  31-test backend suite and the explicit mutation are the available self-checks.
