# cli-home-cleanup

- `bg_create(type="run")` does not inherit the worker's cwd or user-bus environment. Set the worktree with an explicit `cd`; for `systemd-run --user`, pass the observed `XDG_RUNTIME_DIR` and `DBUS_SESSION_BUS_ADDRESS`. Otherwise output redirection or scope startup fails before the command runs.
- A transient systemd scope accepts `MemoryMax=2G`, but rejects `-p Nice=15`; run `nice -n 15 <command>` inside the scope.
