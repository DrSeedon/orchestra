# Task #45 — Implementation Plan

## Order: P0 → P1 → P2

---

## P0 — Auth Bypass

**File:** `app/auth.py`
**Function:** `check_internal_token()` (line 41-47)
**Change:** When `token` (from env) is empty → return `False` instead of `True`

```python
# BEFORE
def check_internal_token(auth_header: str) -> bool:
    token = os.environ.get("INTERNAL_TOKEN", "")
    if not token:
        return True  # BUG: bypasses all auth

# AFTER
def check_internal_token(auth_header: str) -> bool:
    token = os.environ.get("INTERNAL_TOKEN", "")
    if not token:
        return False  # No token configured = no internal access
```

---

## P1.1 — Concurrent send race

**File:** `app/session.py`
**Function:** `send()` (line 196-259)
**Change:** Re-check status INSIDE `_lifecycle_lock`. If status became RUNNING while waiting for lock, queue message instead of starting new turn.

```python
async with self._lifecycle_lock:
    # Re-check: another send() may have started a turn while we waited for lock
    if self.status == AgentStatus.RUNNING:
        if self.backend_type != "codex":
            # Claude: try mid-turn inject (same as pre-lock path)
            try:
                backend = await self._ensure_backend()
                await backend.send(message)
                return
            except Exception as e:
                logger.warning(f"[{self.name}] mid-turn inject failed in lock, queueing: {e}")
        self._pending_messages.append(message)
        self._log("user_message", message)
        self._log("status", f"message queued (race, {len(self._pending_messages)} pending)")
        return
    # ... rest of lock body unchanged
```

**Codex suggestion addressed:** Preserves Claude mid-turn inject behavior inside the lock re-check path.

---

## P1.2 — Scoped lookup fallback

**File:** `app/main.py`
**Endpoints:** `send_message` (524), `compact_session` (550), `restart_cli` (563)
**Change:** Remove `ensure_loaded_any()` fallback from all three. Scoped lookup or 404.

Delete the fallback pattern in all 3 endpoints:
```python
    if not session:
        session = await manager.ensure_loaded_any(name)
```

Also fix same pattern in `app/bg_jobs.py` (lines 277, 309, 358) — 3 occurrences.

**Codex suggestion addressed:** bg_jobs has same fallback, fixing there too.

---

## P1.3 — TG /restart without auth

**File:** `app/tg_bridge.py`
**Function:** `handle_restart` (line 979-983)
**Change:** Check `msg.chat.id == config["group_id"]` before executing restart.

```python
@dp.message(F.chat.type.in_({"group", "supergroup"}), F.text, lambda msg: msg.text and msg.text.strip() == "/restart")
async def handle_restart(msg: types.Message):
    if msg.chat.id != config.get("group_id"):
        return
    # Check sender is admin/creator
    member = await msg.chat.get_member(msg.from_user.id)
    if member.status not in ("administrator", "creator"):
        await msg.reply("⛔ Only admins can restart.")
        return
    await msg.reply("🔄 Перезапуск Orchestra...")
    import subprocess
    subprocess.Popen(["sudo", "systemctl", "restart", "orchestra"])
```

**Codex suggestion addressed:** group_id check + admin/creator check.

---

## P1.4 — Bot token in plaintext

**File:** `app/tg_bridge.py`
**Function:** `start_bridge()` (line 1137-1139) and `save_config()` calls
**Change:** Don't assign token to config dict. Remove `config["token"] = token`. Keep token as local var only.

**Two changes:**

1. In `save_config()` — always strip token before writing:
```python
def save_config():
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    safe = {k: v for k, v in config.items() if k != "token"}
    CONFIG_PATH.write_text(json.dumps(safe, indent=2))
```

2. In `load_config()` — if legacy token found on disk, scrub immediately:
```python
def load_config():
    global config
    if CONFIG_PATH.exists():
        config = json.loads(CONFIG_PATH.read_text())
    if config.get("token"):
        config.pop("token", None)
        save_config()  # immediately remove from disk
```

3. In `start_bridge()` — don't assign token to config. Use local var only:
```python
token = os.getenv("TG_BRIDGE_TOKEN", "")
# NOT: config["token"] = token
```

**Codex feedback addressed:** legacy token on disk is scrubbed on first load, not just at start_bridge time.

---

## P1.5 — Rename memory/DB diverge

**File:** `app/main.py`
**Function:** `rename_session()` (line 665-717)
**Change:** Do the DB UPDATE first (catches IntegrityError on unique constraint). Only mutate in-memory session AFTER DB succeeds.

For loaded sessions: do DB update first, then mutate `session.name`:
```python
import sqlite3
scope = session.scope if session else found.get("scope", "")
try:
    from app.db import _conn
    with _conn() as c:
        c.execute("UPDATE sessions SET name=? WHERE id=?", (new_name, sid))
except sqlite3.IntegrityError:
    return JSONResponse({"error": "name already taken"}, status_code=409)
# DB succeeded — NOW safe to mutate in-memory
if session:
    session.name = new_name
    ...
```

For unloaded sessions: the existing DB path already catches via constraint, just wrap in try/except.

**Codex feedback addressed:** SELECT-then-mutate has a race. UPDATE-first-then-mutate is atomic.

---

## P1.6 — YouGile sync false ok

**File:** `app/tm.py`
**Function:** `_fire_sync()` → inner `_do()` (line 687-695)
**Change:** Move 'ok' update from `finally` to after successful call. Add `except` to mark 'error'.

```python
async def _do():
    try:
        await yougile_sync_task(task_id)
        with _conn() as c:
            c.execute(
                "UPDATE tm_sync_log SET status = 'ok', completed_at = ? WHERE id = ? AND status = 'pending'",
                (_now(), sync_log_id),
            )
    except Exception as e:
        logger.error("YouGile sync failed for task %d: %s", task_id, e)
        with _conn() as c:
            c.execute(
                "UPDATE tm_sync_log SET status = 'error', completed_at = ? WHERE id = ? AND status = 'pending'",
                (_now(), sync_log_id),
            )
```

---

## P2.1 — /uploads without auth

**File:** `app/main.py` (line 1193) + `app/auth.py` (line 50)
**Change:** Add `/uploads/` to `requires_auth()` so AuthMiddleware covers it. Replace StaticFiles mount with an authenticated endpoint that forces download MIME.

In `app/auth.py:requires_auth()`:
```python
if path.startswith("/uploads/"):
    return True  # uploads require auth
```

In `app/main.py`, replace `app.mount("/uploads", ...)` with:
```python
from starlette.responses import FileResponse

@app.get("/uploads/{filename:path}")
async def serve_upload(filename: str):
    path = UPLOADS_DIR / filename
    if not path.exists() or not path.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path, headers={"Content-Disposition": f"attachment; filename={filename}"})
```

This way auth middleware covers `/uploads/*` AND files force-download.

---

## P2.2 — Denylist incomplete

**File:** `app/main.py` (line 262)
**Change:** Add credential files to `_DENIED_PARTS`:

```python
_DENIED_PARTS = {".env", ".ssh", ".git", ".credentials", ".gnupg", ".aws",
                 ".npmrc", ".pypirc", ".netrc", ".docker", ".kube"}
```

---

## P2.3 — Delete app/tools.py

**File:** `app/tools.py`
**Change:** Delete the file. Verify no imports reference it.

---

## P2.4 — Logs no drain

**File:** `app/session.py` (line 902)
**Status:** Low priority, fire-and-forget is acceptable for MVP scale. Skip — not worth the complexity.

---

## What NOT to touch
- No changes to `app/manager.py` beyond what's needed
- No refactoring of auth system
- No changes to DB schema
- No changes to frontend
- No changes to `app/mcp_stdio.py`
