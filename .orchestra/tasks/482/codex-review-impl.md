<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Because one filesystem apparently wasn’t enough to make diagnostics trustworthy 😏, the core OR fix is sound, but I found one definite reporting bug and two path-contract issues.

## Summary

The OR matches the stated acceptance criterion. It intentionally misses “worker branch deleted, checkout still has it”; that is a semantic blind spot, not a regression under the chosen rule.

Within the reviewed hunks, `exists: None` is preserved correctly and no consumer treats it as strictly boolean. The adjusted test preconditions strengthen isolation rather than weaken coverage.

## Findings

### [suggestion] `app/orchestra_layout.py:246-249`

When a legacy-unmapped path is absent from the checkout and the worktree is unavailable, the code sets `exists=None` but then overwrites the reason with `"legacy path outside..."`. The reason no longer names that the worktree was unchecked, violating the promised tri-state diagnostic and potentially making an unknown state look actionable.

### [suggestion] `app/orchestra_layout.py:233-234`

If the worktree root is accessible but an owned path cannot be `stat`ed—for example, due to permissions or an inaccessible mount—`Path.exists()` returns `False`, so the entry is reported as genuinely absent. That creates the same false alarm the tri-state was intended to avoid; stat errors for child paths need to remain `exists=None`.

### [question] `app/orchestra_layout.py:199-204`

Relative `worktree_path` values are resolved against the service’s current working directory. On multi-project startup this can inspect an unrelated directory and suppress attention. If stored paths are required to be absolute, reject relative values as unchecked; otherwise resolve them against an authoritative worktree root.

### [question] `app/orchestra_layout.py:233-234`

`mapped` is joined without enforcing that it is relative to the selected root. Absolute paths discard the root, and `..` components can escape it, allowing an outside path to suppress attention. If `owned_dirs` is guaranteed to contain normalized repository-relative paths, that invariant should be enforced or covered at this seam.

## Verdict

**Correct with non-blocking follow-ups.** The main fix satisfies the requested behavior, but the legacy/unchecked reason should be corrected, and path/stat assumptions should be made explicit.

The supplied test result was `27 passed`; my local rerun could not collect because `dotenv` is missing in this environment. The legacy case is currently a worker with no worktree wearing a “left verbatim” badge.
