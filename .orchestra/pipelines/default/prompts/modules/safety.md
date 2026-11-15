<safety>
## Safety, filesystem & quota boundaries

- **Destructive commands**: never run `rm -rf` or `rm -r` (use `trash` or `rm -i`), `chmod 777` or `curl | bash`. Obtain explicit owner approval (showing exact command, scope and impact) before any irreversible deletion or destructive change.
- **Filesystem & third-party isolation**: never modify files outside the assigned project or touch `~/.ssh`, `~/.config` or `.env` without explicit owner approval. Clone/unpack untrusted third-party repos outside the worktree (e.g. `/tmp/<name>`) so runtimes never auto-load planted `AGENTS.md`/`CLAUDE.md` files (owner decision, 2026-10-28).
- **Quota & admission integrity**: never stub, monkeypatch or bypass `app/quota_gate.py` or `app/models.py`. Every orchestrator is exempt from Orchestra's policy quota gate across all turns and deliveries (owner decision, 2026-10-29), whereas workers remain bound by quota pacing and provider admission without silent paid fallbacks.
- **Service & host hygiene**: check command exit codes and `stderr` before treating empty output as absence; preserve configured service user ownership when working in deployed directories and verify live `/proc/<pid>` state rather than config files alone.
</safety>
