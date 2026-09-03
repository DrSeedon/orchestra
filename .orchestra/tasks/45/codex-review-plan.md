## Summary

The plan is mostly correct on priority and direction. P0 auth bypass fix is right and should ship first. P1.6, P2.2, P2.3, and skipping P2.4 look reasonable for MVP.

Do not implement the plan as-is: a few proposed fixes are incomplete and would leave security/correctness issues open.

## Findings (blocking/suggestion/nit)

**blocking**

- P2.1 `/uploads` fix is not actually authenticated. Current auth only protects `/` and `/api/*` in [app/auth.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-security/app/auth.py:50), so replacing `StaticFiles` with `@app.get("/uploads/{filename}")` still leaves `/uploads/*` public unless `requires_auth()` is changed or the route moves under `/api`. Also the snippet uses `FileResponse` without importing it. Fix: either add `path.startswith("/uploads/")` to `requires_auth()` or serve from an authenticated `/api/uploads/{filename}` route.

- P1.5 rename fix is not strong enough. A preflight `SELECT` before mutating memory still has a race: another rename can take the name before `_persist()` writes, and `_persist()` is async in [app/session.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-security/app/session.py:874). If SQLite raises on the unique constraint, memory is already renamed. Fix should perform the DB update first and mutate the loaded session only after the DB operation succeeds, catching `sqlite3.IntegrityError` and returning `409`.

- P1.4 token scrub migration may leave the plaintext token on disk. If `TG_BRIDGE_TOKEN` is not in env, `start_bridge()` returns before `save_config()`, so merely setting `config["token"] = ""` in memory does not clean `data/tg_bridge.json`. Fix: when `load_config()` detects a legacy token, remove it and immediately write the safe config, or always call the stripping `save_config()` before the disabled return path.

**suggestion**

- P1.3 should also check sender admin/creator, as research says. The proposed `group_id` check stops arbitrary external groups, but any member of the configured group can still run `sudo systemctl restart orchestra` via [app/tg_bridge.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-security/app/tg_bridge.py:979). For a tiny trusted group this may be acceptable, but it is still an auth boundary for a restart command.

- P1.1 race fix should preserve existing Claude behavior or explicitly accept the regression. Current code injects mid-turn for non-Codex backends in [app/session.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-security/app/session.py:203); the proposed in-lock snippet queues for all backends. That is safe, but changes live-message behavior for Claude.

- P1.2 should consider the same scoped fallback in background jobs. [app/bg_jobs.py](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-security/app/bg_jobs.py:275) falls back to `ensure_loaded_any()` after scoped lookup fails, so completed/timed-out/cron job messages can still go to a same-name agent in another scope.

**nit**

- None worth tracking.

## Verdict

Revise before implementation. P0 is correct, but P2.1 and P1.5 need concrete changes before this is a safe security-fix plan.