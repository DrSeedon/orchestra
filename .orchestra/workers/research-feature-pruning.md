# research-feature-pruning — reusable notes

- For usage audits, freeze one `max(logs.ts)` completed-event cutoff from a WAL-safe in-memory backup and make every window query use that timestamp; do not refresh the live DB between tables.
- Treat route/UI counts as UNKNOWN unless the DB has path/control telemetry. Generated OpenAPI/FastMCP registries prove existence and static consumers, not usage.
- Import generated registries from the repository root (`sys.path.insert(0, repo_root)` in standalone evidence scripts); otherwise route generation can fail for environment-dependent imports while a direct `uv run python -c 'from app.main import app'` succeeds.
- When a frozen RED oracle turns green on the intended change but fails a later representation-only assertion → stop, preserve the valid historical RED evidence, supersede/exclude only the false premise in a new oracle commit, and verify the behavioral contract separately.
