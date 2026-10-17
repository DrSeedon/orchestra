## Summary

Reviewed the complete diff from `58ff5529a9980cdd657590c77bb663190189f976` to `4a26f406b0761ea65b920a851d1ddff7c94c0d21` and traced its startup calls through session persistence and auto-resume.

## Findings

### Blocking

- `app/bootstrap.py:59-95` — `get_all_sessions()` excludes archived sessions by default, but the database enforces `UNIQUE(name, scope)` across archived rows too. If an archived session is named `orchestrator` in `/workspace/project`, bootstrap sees no orchestrator, then `save_session()` raises `sqlite3.IntegrityError`. Since this runs in FastAPI lifespan without a handler, startup fails. Bootstrap needs to account for archived rows before attempting the insert.

### Suggestion

- `app/bootstrap.py:37-53` — Workspace setup treats any existing directory as fully initialized. If the directory already exists but lacks `.git` or `CLAUDE.md`, bootstrap skips setup and does not repair it. Consider ensuring the required artifacts independently of whether the directory exists.

## Verdict

NEEDS WORK — an archived default-name session can prevent the service from starting.