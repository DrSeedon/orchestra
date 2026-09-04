<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Attempt journal

- Attempt 1: `review-receipt:ebd279a3-7a14-44ef-a161-1f95c8f06010`; tool timeout after 600 s, receipt `interrupted`, no reviewer conclusion/artifact output.
- Attempt 2: `review-receipt:978360c1-f022-4e77-9899-cf6fb67f42c3`; completed with a verdict and exact quotes from `research.md`.
- Resolution: all three non-blocking precision findings were accepted and applied to `research.md`; no second completed prose round was opened.

Apparently the gate is both enforced and inactive—quantum compliance. 🫠

## Summary

A is logically established: the prose identifies an optional writer and a completion path that ignores `author_outcome`. B is preserved explicitly for `skipped` and `unavailable`. C is better supported than B/C under the same-table/no-duplicate constraint, but its join invariant needs tightening. D is asserted, not demonstrated field by field.

## Findings (blocking/suggestion/question)

### [suggestion] Clarify current versus post-T4 enforcement

> “Existing #462 admission and execution revalidation then make the step non-bypassable before Git [S2][S4].” — [research.md:111](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/run-receipt/.orchestra/tasks/466/research.md:111)

This conflicts with the later statement that “The current #462 gate is inactive until its T4 skill marker is merged” ([research.md:195](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/run-receipt/.orchestra/tasks/466/research.md:195)). Mark the non-bypassability claim as conditional on T4, while retaining the separate conclusion that the existing workflow is bypassable.

### [question] State the invariant that makes the sibling-row join deterministic

> “Review rows need no new `task_run_id`: `(scope, session_id, task_id, requested_at within the non-overlapping run interval)` is a deterministic join.” — [research.md:137](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/run-receipt/.orchestra/tasks/466/research.md:137)

The partial unique index only prevents two open runs; it does not establish that every review row falls inside exactly one run interval, especially across recovery, reassignment, or late receipt creation. The design is still preferable to B/C, but the exact-one-match invariant and boundary behavior should be stated.

### [question] Prove non-derivability for each of the five fields

> “**LIKELY — each field closes a measured non-derivable gap; final names remain an architecture choice.**” — [research.md:125](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/run-receipt/.orchestra/tasks/466/research.md:125)

The prose measures aggregate owner availability and acceptance timing, but does not show why each field cannot be reconstructed from the named canonical task, session, prompt, or merge owners. Add a field-by-field map distinguishing required join keys from duplicated facts, especially for `task_stable_id` and `terminal_operation_id`.

## Verdict

No blocking findings. A and B pass; C passes comparatively with a missing join invariant; D needs explicit field-level justification before implementation approval. The design currently has a beautifully documented lock and a note saying the lock is still waiting for T4.
