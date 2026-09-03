# #248 — implementation report

## Delivered

Task Manager is now part of the platform lifecycle rather than a manual side channel:

- canonical task allocation and atomic spawn/send binding;
- pre-Git scoped task-ref validation and canonical squash headers;
- explicit `continue|complete` merge outcomes;
- durable completion/assignment reservations and one transactional finalizer;
- exact operation trailer recovery after restart, without replaying Git;
- safe operator resolution of genuinely unknown outcomes;
- archive-time binding recomputation;
- platform-owned lifecycle status at the MCP boundary;
- fresh bounded task state in `list_agents` and the shared task-management prompt.

The route keeps direct-call compatibility (`request=None`) only for non-waived calls. A missing
FastAPI `Request` can never authorize `waive_diff_budget`.

## Verification

- Frozen #248 oracle is byte-identical to `b7ad6c76`.
- Before implementation: `23 failed`.
- Final task/recovery/ref/MCP set: **32 passed**.
- Broad compatibility: **980 passed / 5 failed** initially; all five were stale test seams for
  atomic publish or the intentionally added full-cycle module. After adaptation, the affected
  `tests/test_manager.py tests/test_default_pipeline.py` set is **302 passed**.
- The five formerly failing nodeids are **5 passed** directly.
- WAL-consistent copy of the live SQLite database: migration created `tm_task_reservations`,
  `finalization_stage`, and `finalization_json`; `PRAGMA foreign_key_check` returned no rows.
- `py_compile`, `git diff --check`, frozen-oracle comparison: green.

Four required mutations were each RED and green after byte-clean restoration:

1. disable exact reservation deletion on resolve;
2. disable `PREPARED` repository reconciliation;
3. remove platform-owned lifecycle statuses;
4. disable the `list_agents` task slice.

## Intentional contract changes

- Agent MCP `task_create`/`task_update` cannot manually set `in_progress` or `done`; spawn/send and
  merge/archive own those states. Human/API paths retain their authority.
- Schema-v2 merge callers provide `task_outcome=continue|complete`; operation-v1 callers remain a
  safe legacy continuation and cannot implicitly close a task.
- `list_agents` adds one server-side task read for orchestrators and shows at most five `new` rows,
  plus active rows.
- Full-cycle roles now receive the shared task-management module.

## Review status

The old independent Opus review supplied the three blockers above; all are closed on the current
tree. A new independent model round was unavailable: Claude OAuth expired, Sol worker admission was
quota-blocked, and Grok credentials were absent. Final validation therefore uses the frozen oracle,
the review-blocker oracle, broad compatibility, live-schema migration, and four mutations; no new
independent `APPROVED` verdict is claimed.

No deploy, restart, or live database mutation was performed.
