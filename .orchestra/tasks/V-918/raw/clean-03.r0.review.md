## Summary

Reviewed the complete diff from `2e95d85c4de230610891d5a9df7aac08b3ce2017` to `ccc5192bfba29c86d02895c1c4cc76fcfa85b615`. It adds checks against symlinked task records and writes, rejects symlinked task-store markers, and validates project entries in incoming Git trees.

The diff contains no changes to migration-copy retirement.

## Findings

### Suggestion

`_tree_records()` now rejects every symlink, submodule, or non-`100644` entry anywhere under `projects/` before checking whether the path is a task JSON record. Previously that check applied only to task records. If non-task project files are valid in this repository, a remote change to one of them can now block task sync. Consider limiting the rejection to paths covered by the task-store contract, or documenting that all `projects/` content must be regular files.

## Verdict

APPROVED — no blocking correctness or security issue found in the diff. Migration-copy retirement is outside the reviewed changes.