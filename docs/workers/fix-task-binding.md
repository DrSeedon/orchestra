# fix-task-binding

- Maintenance code that mutates a Git-backed task store must receive the already-open process-owned store; opening another `TaskStore` risks competing Git locks and divergent state.
- An internal FastAPI maintenance route still needs an explicit `INTERNAL_TOKEN` check even when dashboard auth is disabled; global auth middleware otherwise permits unauthenticated requests in dev mode.
