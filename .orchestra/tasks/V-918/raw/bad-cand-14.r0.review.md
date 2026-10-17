## Summary

Reviewed the complete diff between the specified commits. The retry counter is reset at turn end, which prevents the configured retry limit and backoff sequence from working across failed turns.

## Findings

### Suggestion

- [app/session_turns.py](/home/kesha/v918-work/v918-bad-cand-14.r0-otof33bx/app/session_turns.py:90): `handle_turn_end` resets `_rate_limit_retries` on ordinary turn completion. A rate-limit error schedules a delayed retry, then the failed turn ends and resets the counter before that retry runs. Repeated rate limits therefore keep scheduling a `30s` retry; the `60s` and `90s` delays and three-retry cap are not reached. Preserve the count across rate-limit failures and reset it after a successful turn.

## Verdict

NEEDS WORK