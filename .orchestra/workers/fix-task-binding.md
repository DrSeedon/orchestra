# fix-task-binding

- Maintenance code that mutates a Git-backed task store must receive the already-open process-owned store; opening another `TaskStore` risks competing Git locks and divergent state.
- An internal FastAPI maintenance route still needs an explicit `INTERNAL_TOKEN` check even when dashboard auth is disabled; global auth middleware otherwise permits unauthenticated requests in dev mode.
- When an API result embeds an historical operation error, keep it in a separate success metadata field; `_api` treats a top-level `error` as failure before MCP can inspect the domain state.
- For long-running operations, intermediate result JSON can lag durable progress columns; overlay live state/stage/time before formatting a retry response.
- For dual-store finalization, whitelist only service-counter debt alongside an applied status and render every rejected field with both store values.
