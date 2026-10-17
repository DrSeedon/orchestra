## Summary

Reviewed the complete diff between the pinned commits. The change detects unread state from the orchestrator’s own `running` → non-`running` transition, so a worker finishing no longer marks its orchestrator’s tab unread. The unread dot is synchronized consistently when tabs render and when their status updates.

## Findings

### Blocking

None.

### Suggestion

None.

### Question

None.

## Verdict

APPROVED.