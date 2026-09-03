## Review protocol

- Attempt 1: completed; implementation round 1.

## Summary

The worker-only exception is narrowly scoped to explicit direct-orchestrator authorization, preserves unconditional acceptance-oracle immutability, and does not leak into full-cycle or orchestrator roles. Source ownership, assembled delivery, and composite worker-removal plus base-injection detection are covered.

Focused tests passed: `9 passed, 86 deselected`.

Evidence from the diff:

```diff
+        "Without that explicit authorization, report `WIP/STOP`.",
```

## Findings

No blocking issues, suggestions, or questions.

## Verdict

APPROVED

> ⚠ Codex usage unaccounted: OperationalError: table turn_usage has no column named cost_unaccounted
