## Summary

Reviewed all Python files in `app/`. Main remaining risk is security: auth can be accidentally bypassed completely, and several “internal/admin” paths assume a trusted local deployment. I also found two real correctness races in agent routing/sending and a few reliability issues around sync/logging.

## P0 (blocking)

- [app/auth.py](/mnt/data/Projects/Python/orchestra/app/auth.py:41), [app/main.py](/mnt/data/Projects/Python/orchestra/app/main.py:75): `check_internal_token()` returns `True` when `INTERNAL_TOKEN` is unset, and `AuthMiddleware` checks it before dashboard auth. Result: if `DASHBOARD_USER/PASSWORD` are set but `INTERNAL_TOKEN` is missing, every protected route is public. Impact includes `/api/bg/jobs` shell execution, `/api/restart`, file reads, session control, proxy switching, and task/payment mutation.

## P1 (wrong behavior)

- [app/session.py](/mnt/data/Projects/Python/orchestra/app/session.py:196): `AgentSession.send()` checks `self.status == RUNNING` before acquiring `_lifecycle_lock`, then does not re-check after waiting for the lock. Two concurrent sends to an idle agent can both proceed as active sends. For Codex this can start a second subprocess and overwrite `self._proc`; for Claude it can interleave turn state, pending messages, and logs.

- [app/main.py](/mnt/data/Projects/Python/orchestra/app/main.py:524), [app/manager.py](/mnt/data/Projects/Python/orchestra/app/manager.py:705): several endpoints fall back from scoped lookup to `ensure_loaded_any(name)`. A typo, stale scope, or duplicate worker name across projects can send/compact/restart the wrong agent in another scope.

- [app/tg_bridge.py](/mnt/data/Projects/Python/orchestra/app/tg_bridge.py:979): the Telegram `/restart` handler does not verify `config["group_id"]`, topic, sender, or admin status. Any group/supergroup where the bot receives `/restart` can trigger `sudo systemctl restart orchestra`.

- [app/tg_bridge.py](/mnt/data/Projects/Python/orchestra/app/tg_bridge.py:1136): `start_bridge()` writes the bot token into `data/tg_bridge.json`. That turns an env secret into a persistent plaintext file; combined with the file API’s broad `/mnt/data` allowlist, this is easy credential exposure.

- [app/main.py](/mnt/data/Projects/Python/orchestra/app/main.py:665): renaming a loaded session mutates `session.name` before the DB unique constraint is enforced. If `new_name` already exists in the same scope, async `_persist()` logs an error but the endpoint can still return success and memory/DB diverge.

- [app/tm.py](/mnt/data/Projects/Python/orchestra/app/tm.py:687): `_fire_sync()` marks the pending YouGile sync row as `ok` in `finally`, even if `yougile_sync_task()` raises. That can hide failed syncs from retry logic.

## P2 (suggestion)

- [app/main.py](/mnt/data/Projects/Python/orchestra/app/main.py:1193): `/uploads` is mounted outside auth, while `/api/upload` accepts browser-renderable extensions such as `.html`/`.svg`. Treat uploads as private/authenticated or force inert download MIME types.

- [app/main.py](/mnt/data/Projects/Python/orchestra/app/main.py:262): file access uses a denylist for secrets. It misses common credential files such as `.npmrc`, `.pypirc`, `.netrc`, `.docker/config.json`, `.kube/config`, and project-specific token JSON.

- [app/tools.py](/mnt/data/Projects/Python/orchestra/app/tools.py:79): this SDK MCP server appears dead and stale. It references removed manager fields/methods like `archived` and `archive_by_id`, while current runtime uses `mcp_stdio.py`.

- [app/session.py](/mnt/data/Projects/Python/orchestra/app/session.py:902): logs are fire-and-forget executor writes with no tracked future/drain. Under shutdown or heavy logging, ordering and durability are best-effort.

## Verdict

Not production-safe until the auth bypass is fixed. After that, I’d prioritize the concurrent-send race and scoped lookup fallback because they can misroute work or corrupt agent state under normal multi-agent use.