# Orchestra Bug Reports (from agents)

No open bugs.

## [2026-05-19 09:10 UTC] merge_worker fails with "unrelated histories" for separate repos
- **Reporter:** Parsing-orchestrator
- **Scope:** /mnt/data/Projects/Python/Parsing
When a worker is spawned with repo_path pointing to a separate git repo (e.g. /mnt/data/Projects/Python/Parsing/zahoron-laravel which is kislinsky/zahoron), merge_worker fails with:

```
fatal: отказ слияния несвязанных историй изменений
```

This happens because the worktree is created from the parent project's git (Parsing), but the worker pushes directly to the separate repo's master branch.

Workaround: worker pushes to master directly, CI deploys. merge_worker is skipped.

Expected: either detect separate repo and merge correctly, or skip merge and report "worker already pushed to remote".
