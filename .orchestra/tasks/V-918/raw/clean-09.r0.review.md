## Summary

Reviewed the complete diff between the specified commits. The change marks the orchestrator data fresh after `loadOrchestrators()` receives it, preventing the next refresh cycle from immediately requesting the same list again.

## Findings

None.

## Verdict

APPROVED