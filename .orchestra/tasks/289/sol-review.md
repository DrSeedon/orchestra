## Summary

Only Q4 has a blocker: important messages can be abandoned after three transient failures.

Exact line read: `# Frozen blind review corpus`

## Case K2

**blocking:** None. Model-policy telemetry fails open as required; the independent delivery-admission gate retains its fail-closed contract.

**suggestion:** Run delivery admission before `create_session` to avoid creating a session when admission subsequently rejects the request.

**verdict:** PASS

## Case M7

**blocking:** None. The capability, model-change behavior, and backend resume context consistently preserve the supported native thread.

**suggestion:** None.

**verdict:** PASS

## Case Q4

**blocking:** Important operations are abandoned after three `RetryAfter`, `NetworkError`, or `ServerError` failures. The helper returns `None` without delivering the operation, directly violating “Important messages must not be lost.” The observable consequence is message loss during sustained transient failures.

**suggestion:** None beyond fixing the blocker, which requires durable retry rather than a fixed three-attempt limit.

**verdict:** BLOCK

## Case T9

**blocking:** None. `relative_to()` correctly rejects sibling-prefix and traversal escapes; the excluded concurrent-mutation threat does not create a TOCTOU blocker.

**suggestion:** None.

**verdict:** PASS

## Verdict

K2: PASS  
M7: PASS  
Q4: BLOCK  
T9: PASS