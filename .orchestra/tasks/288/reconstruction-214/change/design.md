## Context

See `proposal.md` for motivation. Role resolution already has canonical model and runtime values at spawn time. A backend receives effort only when it is constructed, while live session state persists its current effort. The pipeline file is the intended single source of truth.

## Goals / Non-Goals

**Goals:**

- Preserve scalar configuration while adding deterministic exact-model/runtime/default precedence.
- Make manifest changes take effect on the next turn for both idle and currently running sessions.
- Prevent a partial but syntactically valid manifest write from rebuilding live backends with an intermediate value.

**Non-Goals:**

- No new route, MCP tool, database field, manual bulk update, mid-turn interruption, or model change.
- No last-known-good shadow owner for pipeline configuration.

## Decisions

1. Define one `EffortSpec` union and one `resolve_effort(effort, model, runtime)` owner. Resolution order is exact canonical model, runtime, `default`, then no value. Runtime names are validated before model aliases so `codex` and `grok` keep runtime semantics.
2. Unknown levels fail manifest loading because the level set is closed. Unknown model keys remain with a warning because the registry is populated dynamically.
3. Re-read the manifest at the existing session turn boundary. Mid-turn injection returns before reconciliation. When the resolved value changes, disconnect the old backend first, then persist the new effort; the next backend build receives it without resetting the native session id.
4. Cache parsed manifests by pipeline name, path, modification time, and size. Re-stat after reading and retry up to three times when metadata changes; never cache an unstable parse.
5. If loading or resolution fails, or the session lacks pipeline/role identity, keep the current effort and backend. A missing replacement is not permission to fall through to a different effort.

## Risks / Trade-offs

- A misspelled effort level blocks new agent spawns until corrected; this is accepted to prevent silent model routing changes.
- Every pipeline field becomes hot-read, so an editor's non-atomic write can briefly make spawns fail. Stable read/retry protects live sessions from a torn-but-valid snapshot; writers should still replace atomically.
- Disconnect failure leaves the manifest change pending for the next turn rather than committing a value the backend did not receive.

## Migration Plan

Change the four default roles to the same model-aware map: Opus `high`, Sol `xhigh`, Luna `high`, and `default: high`. Existing sessions converge at their next turn boundary; no service restart or SQL update is required. Rollback is a manifest edit and is applied by the same boundary.

