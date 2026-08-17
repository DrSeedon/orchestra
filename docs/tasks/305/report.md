# #305 — managed CODEX_HOME cold-start single-flight and state recovery

## Production path and reproduced race

Both HTTP routes load the session before acting:

- `POST /api/sessions/{name}/send` → `SessionManager.ensure_loaded()` →
  `SessionManager.send()` → `AgentSession.send()` → `_ensure_backend()` →
  `CodexBackend.connect()`;
- `POST /api/sessions/{name}/change-model` → `SessionManager.ensure_loaded()` →
  `AgentSession.change_model()` → `_change_to_codex_with_history_locked()` →
  `_ensure_backend()` → `CodexBackend.connect()`.

`AgentSession.send()` and `change_model()` already serialize on the same
`AgentSession._lifecycle_lock`. The race was earlier: `SessionManager.ensure_loaded()` checked the
in-memory registry and then called `_load_from_db()` without a manager-level single-flight. Two
requests could therefore construct two `AgentSession` objects for the same immutable DB id. Each
object owned a different lifecycle lock and a different `CodexBackend`; both used the same
`ORCHESTRA_SESSION_ID` and private CODEX_HOME.

The deterministic RED oracle started model-change and send while the first cold load was held.
Before the fix it observed two `_load_from_db()` calls and two concurrent owners:

```text
uv run pytest -q tests/test_manager.py::TestEnsureLoadedSingleFlight
2 failed
assert load_calls == 1  # actual 2
assert max_active == 1  # actual 2
```

The backend REDs also showed that there was no managed-state preparation API and that a process
exiting after writing the exact backfill diagnostic still raised only
`Codex app-server exited with code 1`.

## Fix

1. All three lazy-load entry points (`ensure_loaded`, `ensure_loaded_by_id`,
   `ensure_loaded_any`) converge on one lock keyed by immutable session id and recheck the registry
   inside it. Cancellation releases the lock; a waiter retries without overlapping the cancelled
   load.
2. Managed CODEX_HOME connects serialize by canonical home path around config/state preparation and
   the complete app-server initialize/resume handshake. A per-loop lock avoids wasting executor
   threads; a filesystem `flock` provides the actual cross-loop/cross-process exclusion. A cancelled
   waiter cannot leak a late-acquired file lock, and cancellation cannot release the lock while an
   off-thread SQLite operation is still running.
3. A fresh state index is seeded with `sqlite3.Connection.backup()`, never file copy. Codex 0.146.0's
   exact 44 `(version, checksum)` SQLx migration identities are immutable code authority; the mutable
   base DB must match them. Among complete matching managed indexes, the source with the most
   `threads` rows is selected. This avoids seeding the live measured base index (452 rows) when a
   fuller matching managed index exists (580 rows in the read-only acceptance check).
4. A target is left byte-for-byte untouched when its backfill state is `complete` and
   `last_success_at` is non-null. Automatic recovery is allowed only for the incident shape
   `status='running' AND last_success_at IS NULL`: a state that has never completed. Its SQLite
   database and any WAL/SHM sidecars are moved to a unique `state-recovery-*` directory before the
   validated seed is installed. Failed installation restores the old target. Other states,
   migration mismatch, corrupt/partial source, and an unpinned CLI version fail closed.
5. The provider-internal contract is explicit and checked: Codex CLI must be the pinned `0.146.0`;
   `_sqlx_migrations`, `backfill_state`, and `threads` tables/columns must match; all migrations must
   be successful; source and copied DB pass `PRAGMA quick_check`; stale source/target migration
   signatures must match the exact pinned SQLx checksums.
6. The stdout reader waits for the bounded stderr drain before completing pending startup futures.
   It exposes the existing sanitizer's redacted stderr in the raised API error and process-exit
   metadata. Raw credentials remain only in the private in-memory tail.

## Read-only validation against the preserved incident

The validator was run read-only against the preserved broken state and the repaired home:

```text
recovery-20260817T063512Z running None 9 44 44
85f0ba7a-0d8a-401e-a909-eb57c40fb02f complete 1786871175 468 44 44
```

The source selector, also read-only, selected a schema-matching complete managed state with 580
threads and migration 44. No production file, live database, service, or process was changed.

## Verification

Focused RED→GREEN suite after implementation:

```text
uv run pytest -q \
  tests/test_manager.py::TestEnsureLoadedSingleFlight \
  tests/test_codex_managed_state.py \
  tests/test_backend_codex.py::test_startup_exit_surfaces_sanitized_stderr_after_drain
18 passed in 70.79s
```

This covers simultaneous model-change+send, cancellation of the single-flight owner, ten repeated
same-home races, fresh WAL-backed seed, stale-running retry and idempotence, healthy-home no-op,
partial/corrupt source refusal, CLI-version refusal, rollback after an injected install failure,
freshest compatible source selection, and visible/redacted stderr.

It also includes a subprocess contention oracle and changed/extra migration signatures. On the
green implementation, removing only the file lock made the subprocess oracle fail because the
child acquired the home while the parent still held its home critical section (`1 failed`).
Removing only the source migration validation made both changed/extra cases seed successfully
(`2 failed`). Both mutations were restored, `touch`ed, and the 18-test green suite was rerun.

Adjacent manager/backend/state regression suite:

```text
uv run pytest -q tests/test_manager.py tests/test_backend_codex.py tests/test_codex_managed_state.py
266 passed in 303.46s
```

## Targeted Sol review

Round 1 returned `CHANGES REQUESTED`: the lock was process-local, and the mutable base DB was still
the migration authority. Both findings are addressed by the file lock and immutable 0.146.0
migration signature above. Round 2 confirmed both findings `FIXED`, found no new blocking or
suggestion-level issues, and returned the exact verdict `APPROVED`.
