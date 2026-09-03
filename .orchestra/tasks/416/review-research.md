<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

The target branch survived the review, which is apparently the exciting part. 🙃

## Summary

No blockers. F1–F3 are supported by the cited code and focused pytest checks. The current normalizer does collapse dirty, conflict, and `TARGET_HEAD_CHANGED` outcomes when snapshots are equal and zero commits are reported.

## Findings

### question: Define “success claim” as a complete predicate

`research.md:116-120` says coercion should apply only to results claiming success or an achieved commit point, but this is underspecified. The current predicate at `app/merge_operations.py:1020-1036` also matches `state="conflict"` and typed `TARGET_HEAD_CHANGED` failures; direct probes confirmed both become `NO_COMMITS_MERGED`. Since the artifact lists those as regression risks at lines 150–152, Phase 2 should define an explicit truth table covering `ok`, `state`, `commit_point`, existing `code`, and conflicts.

### suggestion: Add a snapshot-backed failed control

The existing normalizer tests for dirty/pre-merge failures omit equal `target_before`/`target_after` snapshots, so they do not exercise the faulty predicate. Add a control with `ok=false`, `state=failed`, `commit_point=not_reached`, equal snapshots, zero commits, and the workspace dirty error; assert `TARGET_DIRTY`, the original message, and `git.status == "DIRTY"`. Retain the existing #413 contradictory post-commit test and add equivalent snapshot-backed controls for conflict/head-change if those contracts are intended to survive.

Focused pytest checks passed: 6 tests, then 7 tests. No files were edited.

## Verdict

**Approve Phase 1 research with follow-up.** The incident diagnosis is well-supported; only the future normalization boundary needs a precise predicate and matching regression oracle.

Proof-of-read quote:

> Raw error второй операции потерян при нормализации; по сохранённой БД восстановить его нельзя.

The current guard is a clerk who sees a fire, a conflict, and a no-op, then stamps all three “nothing merged”—efficient, if losing the plot was the goal. 🙃
