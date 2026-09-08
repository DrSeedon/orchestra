<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

The V-539 implementation correctly derives proofs as `HMAC-SHA256(INTERNAL_TOKEN, "mcp-proof:" + session_id)`. Empty, foreign, and session-mismatched proofs remain rejected, with constant-time comparison.

Changing `INTERNAL_TOKEN` invalidates existing proofs, including adopted processes from the previous generation. This is fail-closed and appropriate if token rotation is intended to revoke old processes.

## Findings (blocking/suggestion/question)

### Blocking

None.

### Suggestion

- `tests/test_mcp_proof.py:321` reloads the proof module in the same process; it does not actually create a new server process and adopt an existing MCP process. It would fail against the old in-memory implementation because reload clears `_proofs`, but it only simulates generation loss. A subprocess-based test would better prove the production restart boundary.

- No test explicitly verifies token rotation: proof generated with token A is rejected after switching to token B, while a proof generated with B is accepted. The implementation behaves correctly for this case.

### Question

None.

Verification: reviewed the exact requested full diff; `py_compile` passed. Pytest could not run because this environment lacks both `pytest` and the project dependencies.

## Verdict

APPROVED — no blocking security or restart-correctness defects found.
