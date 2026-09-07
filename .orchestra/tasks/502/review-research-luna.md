<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

Ну конечно, у 67 строк нашлась ещё одна важная ветка 😏

## Summary

The main split verdict is supported: `worker_wip` and the rebuild-race concern are refuted, trailer/review subject defects are reproduced, diff budget is independent, and the historical arithmetic is consistent. Focused tests passed: 4 targeted tests plus 15 merge/WIP tests. No files were edited.

## Findings

blocking: `.orchestra/tasks/502/research.md:122,260` — The audit misses that `app/workspace.py:1532-1537` treats any non-zero `git merge-base` exit as “unrelated history” and proceeds to cherry-pick; `app/diff_budget.py:25-35` makes the same assumption. A repository/object failure is not equivalent to “no common ancestor”; if cherry-pick still succeeds, the whole worker history can be committed without a prospective landing tree. Phase 2 must distinguish “no merge base” from “merge-base command failed” and fail closed for the latter.

suggestion: `.orchestra/tasks/502/research.md:50-124` — The “complete” inventory omits explicit refusals when `_clean_worktree_error()` cannot read worker or target status (`app/workspace.py:859-876`). These return `cannot inspect ... working tree` without throwing, so they are not covered by the dirty-worktree rows or the unexpected-exception row. Add them or state an explicit grouping rule.

suggestion: `.orchestra/tasks/502/research.md:28,297` — The documented reproduction command fails in the current tree with `ModuleNotFoundError: No module named 'app'`; `PYTHONPATH=.` is required. Since the controlled experiment supports the central findings, document the environment or make the script runnable exactly as cited.

question: `.orchestra/tasks/502/research.md:102,199-207` — “False for research-only artifacts” is a policy conclusion, not established by the current implementation. `app/diff_budget.py` explicitly counts all insertions, and the reproduction proves that behavior. Clarify whether `.orchestra/tasks/**` artifacts are intended to land; otherwise the oversized research file is a genuine refusal, not a false positive.

question: `.orchestra/tasks/502/research.md:45,225,260` — The proposed prospective tree is described as exactly what will be committed, but the code computes it with `git merge-tree` and later mutates the target with a separate `git merge --squash` (`app/workspace.py:1541-1581`, `1635+`). There is no equality check or proof that configuration, attributes, and merge options cannot make the trees differ. Phase 2 should define that equivalence or derive the subject from the actual staged result.

## Verdict

CHANGES REQUESTED — the blocking merge-base failure path must be resolved before this research can safely drive implementation. The rest of the causal analysis and arithmetic are usable after correcting the inventory and reproduction notes.

A 67-row seatbelt is impressive, but less so when the buckle is hidden inside cherry-pick.
