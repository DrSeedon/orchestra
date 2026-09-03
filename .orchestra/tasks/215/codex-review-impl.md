Usage is explicitly labeled with a model that the standalone CLI command does not pin, and requester attribution still depends on mutable name-based resolution. Both can silently corrupt accounting despite the added tests passing.

Full review comments:

- [P1] Pin the model passed to the Codex CLI — /home/kesha/orchestra/worktrees/home-kesha-orchestra/back/app/mcp_stdio.py:2237-2240
  The usage row is always attributed to `gpt-5.6-sol`, but the generated `codex exec` command does not pass `--model` and therefore executes whichever model the machine-local Codex configuration currently selects. If that default changes or differs between hosts, costs and model telemetry are silently assigned to the wrong model; pass the same explicit model to the CLI that is stored here.

- [P1] Preserve the immutable requesting session ID — /home/kesha/orchestra/worktrees/home-kesha-orchestra/back/app/mcp_stdio.py:2234-2242
  The new accounting configuration does not carry the requesting session ID, so `/api/bg/jobs` continues resolving it later from the mutable `target_name`/scope pair. If that worker is replaced under the same name between the session lookup and job creation—or before a retried request—the review usage is attributed to the replacement session rather than the immutable requester, violating the accounting invariant. Capture the caller's session ID during the initial session lookup and persist it with the job instead of re-resolving by name.

## Round (2026-08-12T06:04:54Z)

## Re-review status

- FIXED — Codex CLI model is explicitly pinned for fresh, resume, and stale-session fallback invocations.
- FIXED — Immutable requester session ID is captured, scope-validated, and persisted without name-based re-resolution.
- NEW BUG — None.

Tests: `65 passed, 1 skipped`.

Exact changed source line:

> `requesting_session_id = str(info.get("id") or "").strip()`

## Verdict

APPROVED

## Round (2026-08-12T06:18:18Z)

Re-review status:

- FIXED — explicit model pinning.
- FIXED — immutable requester attribution.
- FIXED — deployment-window compatibility.
- NEW BUG — None.

Tests: `53 passed`.

Exact changed source line:

> `usage_event_id = f"codex-review:{uuid.uuid4()}"`

Verdict: APPROVED
