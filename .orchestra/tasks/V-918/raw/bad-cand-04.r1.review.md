## Summary

Reviewed the complete diff between the pinned commits. It removes the visible Profile, Pipeline, and Role fields and adds fallback values for creating an orchestrator.

## Findings

### Blocking

None.

### Suggestion

The fallback profile value `personal` is sent explicitly when the profile dropdown has not finished loading or its request fails. That overrides the server’s existing empty-profile default, which uses the process environment for a root orchestrator. This can silently select a different profile than the established default.

### Question

None.

## Verdict

NEEDS WORK