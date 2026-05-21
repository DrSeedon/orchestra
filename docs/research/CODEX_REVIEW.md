## Tests
Not applicable (no test suite for session management).

## Summary
Phase 1 has the right high-level shape: hibernate is only scheduled after Claude turns end, the latest `session_id` is used for resume, and project MCP servers are merged below Orchestra's MCP config. The MCP merge order is correct (`scope` first, Orchestra second), so a project-level `orchestra` server should not override the platform server. The main risk is lifecycle correctness: hibernate depends on `_disconnect_backend()` actually killing the Claude CLI/MCP process tree, but the current cancellation order can skip the explicit backend disconnect. There is also no serialization between `send()` and hibernate teardown, so a message arriving during disconnect can reuse a backend that is already being torn down.

## Findings
blocking: `app/session.py:565` - `_disconnect_backend()` cancels and awaits `_listen_task` before it calls `self._backend.disconnect()`, but `_claude_event_loop()` handles that cancellation by setting `self._backend = None` at `app/session.py:209`. That makes the `if self._backend:` check at `app/session.py:571` false, so the explicit Claude SDK disconnect is skipped and the CLI/MCP children may stay alive while the session is marked hibernated. Fix by capturing `backend = self._backend` before cancelling tasks, clearing `self._backend` only once in `_disconnect_backend()`, and always calling `await backend.disconnect()` in a `finally`; do not let the cancelled listener erase the backend before the owner disconnects it.

blocking: `app/session.py:135` - `send()` cancels `_hibernate_task` but does not wait for a hibernate task that is already inside `_disconnect_backend()`. In that window `_backend` can still be non-`None` while heartbeat/listener/client teardown is in progress, so `_ensure_backend()` can return a half-disconnected backend and `backend.send(message)` can fail or send into a client whose listener was just cancelled. Fix with a per-session lifecycle lock around `send()`, `_idle_hibernate()`, and `_disconnect_backend()`, or at minimum await a non-current cancelled hibernate task before `_ensure_backend()`.

suggestion: `app/session.py:357` - `_idle_hibernate()` calls `_disconnect_backend()`, and `_disconnect_backend()` immediately cancels `self._hibernate_task` at `app/session.py:555`; when called from hibernate, that is the current task. Today it usually survives only because later awaits catch `CancelledError`, but it is fragile and can abort disconnect if the heartbeat/listener awaits are absent or already done. Fix by skipping hibernate-task cancellation when `asyncio.current_task() is self._hibernate_task`, or split timer cancellation from backend disconnect.

suggestion: `app/session.py:27` - `_load_scope_mcp_servers()` silently swallows malformed JSON, unreadable files, and invalid `mcpServers` shapes. That is safe from crashes, but it can make a worker resume without expected project MCP servers and leave no clue in logs. Fix by logging a warning with the settings path for parse/shape errors while still ignoring bad project config.

## Verdict
needs fixes.

## Round 2

### Previous findings

FIXED: `app/session.py:209` / `app/session.py:567` - `_claude_event_loop()` no longer clears `self._backend` on cancellation, and `_disconnect_backend()` now captures the backend reference before cancelling the listener. The explicit `backend.disconnect()` call at `app/session.py:576` can no longer be skipped by the listener clearing shared state.

FIXED: `app/session.py:136` / `app/session.py:353` - `send()` and `_idle_hibernate()` now share `_lifecycle_lock`, so a message cannot enter `_ensure_backend()` while hibernate teardown is inside `_disconnect_backend()`. This closes the specific wake-vs-hibernate race from Round 1.

FIXED: `app/session.py:557` - `_disconnect_backend()` now skips cancelling `_hibernate_task` when the current task is the hibernate task. `_idle_hibernate()` no longer relies on self-cancellation being swallowed by later awaits.

FIXED: `app/session.py:38` - `_load_scope_mcp_servers()` now logs the settings path and exception when project MCP settings cannot be parsed.

### New bugs introduced

None found in the fixes for the four reviewed issues.

### Round 2 Verdict

ACK.
