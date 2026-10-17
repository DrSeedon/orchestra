## Summary

Reviewed the complete diff between the pinned commits. No blocking crash, corruption, or security issue found.

## Findings

### Suggestion

- **Enterprise mode still polls Anthropic usage in the background.** The new auth checks make `/api/usage` return `{"usage": null}` and `/api/usage/history` return `[]`, but `_usage_snapshot_loop()` still reads OAuth credentials, calls Anthropic, and stores usage snapshots every five minutes. If disabling usage in enterprise mode is intended to stop that activity as well as hide it from the dashboard, skip the polling loop when auth is enabled. See [system.py](/home/kesha/v918-work/v918-bad-cand-16.r0-np70bqtz/app/routes/system.py:554).

## Verdict

APPROVED