# #320 — hot static quota policy

## Scope

Implemented the operator-controlled static admission policy requested for the Luna threshold follow-up. The policy is stored in SQLite, read once for each `get_worker_admission` decision, and does not change orchestrator exemption or any adaptive `q95` calculation. No live database, process, restart, or deployment was touched.

## Implementation

- `app/db.py`: added versioned `quota_controller_policy` rows for `sol`, `luna`, and `spark`; defaults are 95/98/95. Added append-only audit rows with actor, UTC timestamp, old/new JSON, reason, revision, and action. Schema checks cover the new tables, index, and immutable audit triggers. Updates use `BEGIN IMMEDIATE` and optional revision CAS; rollback writes an audited revision.
- `app/quota_gate.py`: `get_worker_admission` consumes the SQLite snapshot. Existing direct-call defaults remain exactly 95% for Sol/Spark and 98% for Luna when no policy snapshot is available. Codex-primary alternatives use the corresponding lane threshold.
- `app/routes/system.py`: authenticated GET/PUT `/api/usage/quota-controller/policy` and authenticated POST `/api/usage/quota-controller/policy/rollback`. Actor identity is derived from the authenticated server environment, never request JSON. Invalid Luna values and stale revisions fail closed.
- `app/quota_controller.py`: status and empty-status payloads expose the static policy, revision, source, label, reason, and audit history without changing shadow/adaptive authority.
- Analytics renders separate Sol/Luna Fast/Spark rows, revision/source, `TEMPORARY STATIC OVERRIDE`, reason, and a rollback control. No prompts, secrets, decision IDs, or q95 formula claims are exposed.

## Verification

Focused policy/API/browser suite:

```text
uv run python -m pytest -q tests/test_quota_policy.py tests/test_quota_policy_api.py
10 passed
uv run python -m pytest -q tests/test_t314_analytics_browser.py tests/test_routes_surface.py
6 passed
uv run python -m pytest -q tests/test_routes_surface.py tests/test_db.py tests/test_runtime_router_db.py tests/test_runtime_router_auth.py tests/test_quota_gate.py tests/test_quota_policy.py tests/test_quota_policy_api.py tests/test_t314_analytics_browser.py
165 passed
```

Immutable #291 oracle suite remains green and untouched:

```text
uv run python -m pytest -q docs/tasks/291/oracles/test_t1_schema_and_topology.py docs/tasks/291/oracles/test_t2_adaptive_gate.py docs/tasks/291/oracles/test_t3_shadow_delivery.py docs/tasks/291/oracles/test_t4_replay_evidence.py
21 passed
```

`uv run python -m py_compile app/db.py app/quota_gate.py app/quota_controller.py app/routes/system.py` and `git diff --check` pass. The #291 oracle files remain byte-identical to their frozen baseline.

## Review

Sol technical review was attempted first and was quota-blocked (`Codex 97%` against the 95% admission threshold). The strongest available same-family Luna fallback reviewed the exact initial implementation commit `8cd49afc` and returned APPROVED with no blockers; its focused command reported `16 passed`, and the immutable #291 command reported `21 passed`. The fallback explicitly records that it is not an independent cross-family verdict; Opus was unavailable in the worker registry. It suggested keeping arbitrary audit reasons out of Analytics, which was applied in follow-up commit `03bf3d49`; the focused and immutable suites were rerun after that change.

## Breaking / follow-up

No intentional breaking changes. Existing static admission behavior remains the fallback when policy storage is unavailable. The operator UI requires a valid dashboard cookie; internal worker tokens cannot mutate policy.
