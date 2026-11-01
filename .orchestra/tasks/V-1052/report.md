# V-1052: merge guard scans the squash result

- `forbidden_strings.scan_tree(repo, base, head, rules, message="")` scans the final base->head tree
  diff (new paths, added lines, archive contents via V-1050) plus the squash message.
- `merge_worker` (app/workspace.py) now calls it, passing `_build_squash_message(...)` built from
  the worker commit subjects and the acceptance note (what the squash commit contains).
- `scan_range` and the pre-push hook are unchanged (per-commit).
- Tests in tests/test_publish_guard.py: (a) add-then-remove passes while scan_range still refuses
  it (pre-push behaviour, d); (b) final-tree leak refused with file:line; (c) leak only in a
  tar.gz refused; message/path leaks refused.

## Orchestrator completion (host)

`scan_tree` now diffs from the merge-base (empty tree for unrelated histories), so changes main made after the fork are not attributed to the worker. Added `test_merge_gate_allows_leak_removed_before_squash`, which goes through `merge_worktree_to_main` and so covers the wiring. Host run: 128 passed, 85 subtests (publish guard, V-1047, secret gate). Mutation: routing the merge gate back to per-commit `scan_range` fails exactly that test.
