## Why

Role effort was configured by runtime, but Sol and Luna share the Codex runtime and need different effort levels. Existing sessions also retained stale values until restart or manual database repair.

## What Changes

- Allow role effort to be either a scalar or a mapping keyed by exact model, runtime, and `default`.
- Resolve exact model before runtime and `default`, while preserving scalar compatibility.
- Reconcile each live session from the manifest at the next turn boundary without interrupting an active turn.
- Reject unknown effort levels, retain unknown model keys with a warning, and leave a live session unchanged when reconciliation cannot produce a valid value.
- Apply the model-specific map to worker, full-cycle, orchestrator, and sub-orchestrator roles.

## Capabilities

### New Capabilities

- `agent-effort-routing`: Model-aware role effort selection and safe next-turn reconciliation for live agent sessions.

### Modified Capabilities

None; no pre-existing OpenSpec capability corpus is assumed in this brownfield reconstruction.

## Impact

Affected code: pipeline schema/loading, session creation and turn-boundary reconciliation, the default pipeline manifest, and focused pipeline/manager/session tests. No new API, MCP tool, database field, or route is introduced; the pipeline manifest remains authoritative.

