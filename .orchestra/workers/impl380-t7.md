# impl380-t7

- `AgentSession.compact()` holds `_lifecycle_lock` across Claude's blocking summary `backend.send`, unlike native Codex compact, which only creates a task under the lock. A durable direct receipt accepted while `_compacting` must park before acquiring that lock; the compact finalizer, not `_pending_messages`, owns its wake.
