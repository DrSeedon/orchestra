# Strict Sol self-review — #173

External `codex_review` was attempted once after the implementation and regression suite. It was
rejected before job creation with:

```text
weekly_quota_upgrade_required: New Codex worker turn blocked: the FastAPI readiness server does not provide worker-weekly-v1. Deploy the compatible FastAPI server before this MCP client; stop/model change remain available.
```

Per the task constraint, there was no retry, alternate model, direct CLI invocation, or readiness
bypass. External verdict is unavailable.

## Adversarial checks

1. **Can old memory retain later precedence?** `strip_worker_memory()` removes every persisted
   memory block before one current block is appended. The duplicate-block mutation (restoring the
   old `count=1` behavior) made the dedicated regression fail. No path intentionally concatenates
   a stored memory block into `prompt_overlay`.
2. **Can overlay or ownership disappear on reload?** Fresh sessions persist the formatted custom
   overlay and ownership separately. Reload with a changed base uses that stored component
   byte-for-byte; unchanged-base legacy rows are split at the exact current base. A legacy row
   whose base boundary cannot be proven is preserved as a full-prompt override after memory
   removal; the code does not guess a boundary and drop authority text.
3. **Can another writer resurrect a stale overlay?** Creation, hydration, upsert, live/detached
   full-prompt replacement, rename, and list serialization were traced. Full replacement resets
   `prompt_overlay` to the legacy/full-override sentinel and updates `_current_prompt`; rename
   rewrites identity in both persisted components and the live refresh source.
4. **Can a review silently regain fictional scale?** `context` is required in the FastMCP schema,
   and the function rejects blank/no-`PROJECT CONTEXT` input before any readiness or background-job
   call. Both `review` and `exec` build from the caller text plus a scale-neutral rubric. Injecting
   the removed MVP sentence made the high-load regression fail. Shell syntax is parsed in tests.
5. **Are the Codex facts another frozen snapshot?** `CLAUDE.md` labels `131072` machine-local and
   instructs the reader to re-read config; native skill and compact claims point to current runtime
   routes. The generated `AGENTS.md` mirror was not edited.
6. **Could the schema migration confuse explicit empty with legacy unknown?** The column is
   nullable: `NULL` means unsplit legacy/full override, while `""` is a separated empty overlay.
   Migration and round-trip regressions cover both states.

## Bounded tradeoff

An old row with `prompt_overlay IS NULL` whose stored full prompt no longer starts with the current
base has no recoverable custom/base boundary. The safe fallback keeps that full prompt (minus all
old memory) rather than fabricating a split. It therefore preserves custom/ownership authority but
does not apply the changed base until the prompt is explicitly normalized. New rows and legacy rows
whose base still matches do not have this limitation.

## Verdict

No unresolved blocking defect was found in the authorized P0 scope. The legacy unmatched-base
tradeoff is explicit and data-preserving; guessing would be the higher-risk behavior.
