# Task #45 — Security Fixes Research

## Source
Full Codex GPT-5.5 review: `docs/codex-full-review.md`

## P0 — Auth Bypass (CRITICAL)

**File:** `app/auth.py:41-44`
**Bug:** `check_internal_token()` returns `True` when `INTERNAL_TOKEN` env var is unset/empty. `AuthMiddleware` (main.py:75) checks internal token FIRST — if it returns True, request passes with no further auth.
**Impact:** If DASHBOARD_USER/PASSWORD set but INTERNAL_TOKEN missing → ALL routes public. Includes `/api/bg/jobs` (shell exec), `/api/restart`, session control, task/payment mutation.
**Fix:** Return `False` when token is empty. Never allow bypass.

## P1 — 6 Bugs

### P1.1 — Concurrent send race
**File:** `app/session.py:196-220`
**Bug:** `send()` checks `self.status == RUNNING` at line 203 BEFORE acquiring `_lifecycle_lock` at line 220. Two concurrent sends to an idle agent both see status!=RUNNING, both acquire lock sequentially, both set status=RUNNING.
**Fix:** Move the status check inside the lock, or re-check after acquiring.

### P1.2 — Scoped lookup fallback
**File:** `app/main.py:524,550,563`
**Bug:** `send_message`, `compact_session`, `restart_cli` endpoints fall back to `ensure_loaded_any(name)` which ignores scope. A duplicate name in another project routes action to wrong agent.
**Fix:** Remove fallback — if scoped lookup fails, return 404. The MCP tools always provide scope.

### P1.3 — TG /restart without auth
**File:** `app/tg_bridge.py:979-983`
**Bug:** Any group where bot is member can send `/restart` → `sudo systemctl restart orchestra`. No check on group_id, no admin check.
**Fix:** Verify `msg.chat.id == config["group_id"]` and check sender is admin/creator.

### P1.4 — Bot token persisted in plaintext
**File:** `app/tg_bridge.py:1137-1139`
**Bug:** `config["token"] = token` + `save_config()` writes token to `data/tg_bridge.json`. Combined with file API's broad allowlist = credential exposure.
**Fix:** Don't store token in config dict. Only read from env.

### P1.5 — Rename memory/DB diverge
**File:** `app/main.py:681`
**Bug:** `session.name = new_name` mutates in-memory object BEFORE DB unique constraint check. If new_name exists, DB fails but memory already mutated → divergence.
**Fix:** Try DB update first, mutate in-memory only on success.

### P1.6 — YouGile sync false ok
**File:** `app/tm.py:690-695`
**Bug:** `_do()` marks sync as 'ok' in `finally` block — executes even when `yougile_sync_task()` raises. Failed syncs appear successful.
**Fix:** Mark 'ok' only in try body after successful call. Mark 'error' in except.

## P2 — 4 Issues

### P2.1 — /uploads without auth
**File:** `app/main.py:1193`
**Bug:** `StaticFiles` mount is outside middleware — no auth check.
**Fix:** Mount before middleware or add auth wrapper.

### P2.2 — Denylist incomplete
**File:** `app/main.py:262`
**Bug:** Missing `.npmrc`, `.pypirc`, `.netrc`, `.docker/config.json`, `.kube/config` from denylist.
**Fix:** Add to `_DENIED_PARTS`.

### P2.3 — app/tools.py dead code
**File:** `app/tools.py`
**Bug:** Stale SDK MCP server referencing removed manager fields. Runtime uses `mcp_stdio.py`.
**Fix:** Delete file.

### P2.4 — Logs no drain
**File:** `app/session.py:902`
**Bug:** `_log()` fires executor writes with no tracked future. Under shutdown, ordering/durability best-effort.
**Status:** Already partially addressed. Low priority — verify current state.

## Risk Assessment
- P0 is a **live production vulnerability** on VPS deployment
- P1.3 is also security — remote restart from any TG group
- P1.4 is credential leak — token in plaintext file
- All others are correctness/reliability
