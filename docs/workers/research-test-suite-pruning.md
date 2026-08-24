# research-test-suite-pruning

- For read-only pytest inventory on this host, `os.pidfd_open` is absent from CPython; use an in-process `os.pidfd_open=lambda *a: -1` shim only for `--collect-only` or deterministic unit groups, and record the unpatched collection errors rather than treating the shim as a production fix.
- Route-surface mutant runners must preload the worktree `tests` package; ambient `PYTHONPATH` can resolve `/mnt/data/Projects/Python/orchestra/tests` and trigger `ImportPathMismatchError`.
