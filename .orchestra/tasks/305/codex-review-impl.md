<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

The in-loop manager single-flight, cancellation shielding, WAL-safe SQLite backup, rollback path, and stderr sanitization are directionally sound. However, two required fail-closed guarantees are missing.

## Findings

- blocking: `app/backend_codex.py:321-324` — `_managed_home_lock()` is scoped to one event loop in one process. A second loop or Orchestra process receives a different `asyncio.Lock`, so both may concurrently inspect/move the same SQLite target and launch app-server initialization against one canonical managed home. The tests at `tests/test_codex_managed_state.py:235-273` exercise only two tasks on one loop, so they pass despite this gap. Use a filesystem-backed inter-process lock keyed by canonical home and hold it through state preparation plus the complete initialize/resume handshake; add a multiprocessing/subprocess contention test.

- blocking: `app/backend_codex.py:378-386,482-495` — the pinned CLI version is checked, but its supported migration signature/version is not. Any successful migration set found in the mutable base DB becomes the authority. If another Codex version has migrated the base and stale target to a newer yet column-compatible schema, pinned CLI `0.146.0` will accept and copy it. This violates fail-closed handling of unsupported provider state and can make startup crash after replacing the old target. Validate the exact migration signature expected by `0.146.0`, independently of the base database, and test rejection of an otherwise healthy source/target carrying an extra or changed migration.

## Verdict

CHANGES REQUESTED

## Round (2026-08-17T07:47:40Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

Both prior blockers are fixed. The filesystem `flock` now provides cross-loop/process exclusion through the full initialization handshake, with cancellation-safe late acquisition cleanup. Migration validation now uses an immutable exact signature for Codex CLI 0.146.0 rather than the mutable base database.

## Findings

- Prior blocking 1 — FIXED: `app/backend_codex.py:374-425`; non-vacuous subprocess coverage at `tests/test_codex_managed_state.py:293-334`.
- Prior blocking 2 — FIXED: `app/backend_codex.py:509-524`; exact validation is applied to target, base, source, and copied state before replacement.
- No new blocking or suggestion-level findings.

## Verdict

APPROVED
