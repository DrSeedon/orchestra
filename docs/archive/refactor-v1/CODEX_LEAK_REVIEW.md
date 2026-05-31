# CODEX Leak Review

Checked scope: `app/session.py` and `app/manager.py`.

Facts found:
- `_client` is created only in `AgentSession.start()` via `_create_client()` (`app/session.py:48`, `app/session.py:111`).
- Manager call sites that create/connect SDK clients are `create_session()` (`app/manager.py:100`), `ensure_loaded()` (`app/manager.py:193`), and `auto_resume_orchestrators()` (`app/manager.py:246`).
- Serial `start()` calls do attempt to disconnect the old client before assigning a new one (`app/session.py:105`).

blocking: `app/session.py:105` - `start()` swallows `disconnect()` failures and then overwrites `self._client` at `app/session.py:111`. If the old Claude SDK client fails to disconnect, the code loses the only handle to that live CLI process and immediately creates a second one. Fix: if disconnect fails, do not replace the client; surface the error or force a stronger cleanup path before assigning a new client.

blocking: `app/session.py:104` - `start()` is not serialized by `_lock` or a dedicated lifecycle lock. Two concurrent `start()` calls on the same `AgentSession` can both pass the old-client check and each create/connect a separate SDK client, with the last assignment winning and the other process becoming unreachable. Fix: guard all client replacement with a lifecycle lock.

blocking: `app/session.py:119` - `start()` replaces the client without cancelling/awaiting an existing `_turn_task` or `_debounce_task`. A restart while a turn is running can leave the old receive loop active while `self._client` is swapped underneath it, producing concurrent consumers or a detached old process. Fix: drain/cancel current turn and debounce before disconnect/recreate.

blocking: `app/manager.py:192` - `ensure_loaded()` discards the transient `AgentSession` when `session.start()` raises, but never calls `session.stop()` or disconnects its partially-created client. If `ClaudeSDKClient.connect()` starts a process and then raises, this returns `None` while the CLI can remain alive. Fix: cleanup the session in the `except` before returning.

blocking: `app/manager.py:100` - `create_session()` has the same partial-start leak: the `except` cleans the worktree and persists `ERROR`, but it does not disconnect/stop the `AgentSession` if `session.start()` created a client before failing (`app/manager.py:104`). Fix: call `await session.stop()` or a non-archiving cleanup helper in the failure path.

blocking: `app/manager.py:246` - `auto_resume_orchestrators()` also drops a partially-started session on failure without disconnecting it (`app/manager.py:250`). Startup resume is exactly where stale SDK state is likely, so this can leak a Claude CLI before the session is ever registered in `self.sessions`. Fix: cleanup the local session in the `except`.

blocking: `app/manager.py:223` - `auto_resume_orchestrators()` does not check whether an orchestrator is already present in `self.sessions` before creating and starting a new `AgentSession`. If this method is invoked twice in-process, the second run overwrites `self.sessions[session.id]` at `app/manager.py:247` and loses the handle to the first live client. Fix: skip already-loaded ids/names or stop the existing session before replacing it.

blocking: `app/manager.py:263` - `shutdown_all()` cancels an orchestrator `_turn_task` and awaits it, but catches only `Exception` at `app/manager.py:267`. In modern Python, `asyncio.CancelledError` is not reliably caught by `Exception`, so shutdown can abort before reaching `_client.disconnect()` at `app/manager.py:271`. Fix: catch `asyncio.CancelledError` explicitly as `AgentSession.stop()` already does.

suggestion: `app/manager.py:257` - `shutdown_all()` manually reimplements a special orchestrator stop path instead of using one session-owned cleanup method. This path does not reset `_is_connected` or clear `_client`, while `AgentSession.stop()` has similar but not identical logic. A dedicated `disconnect(persist_status=...)`/`pause_for_resume()` helper would make worker shutdown, orchestrator shutdown, and partial-start cleanup share the same process-kill behavior.

suggestion: `app/session.py:254` - after successful `disconnect()`, `stop()` leaves `self._client` pointing at the disconnected client. This is not a direct leak if disconnect succeeds, but it makes ownership ambiguous and causes later lifecycle paths to operate on stale client objects. Clearing `self._client = None` after disconnect would make leaked-handle detection and restart semantics cleaner.
