# #435 — merge `origin/laptop-sync` and reserve the VPS task range

## Inputs

- VPS main: `52cfc2f0`.
- Laptop tip: `origin/laptop-sync` `6c9016a1`, 28 commits after common ancestor
  `e9cb39ead6e702a9f5bbe97b8dae7d69ae375fed`.
- Existing VPS work preserved before the laptop merge: #395 task-create request identity,
  #428 finalization mismatch handling, and #434 `codex_connect_stage` instrumentation.

## Conflict resolution

`app/tm.py` contained two valid but incompatible task-create policies. The merged policy keeps
both contracts by using the caller's durable request key as the boundary:

- caller-held request key: retain #395 replay semantics, so an ambiguous timeout can return or
  replay the first durable task instead of creating a duplicate;
- internally generated/no-caller key: retain the laptop fail-loud policy, compensating only a
  legacy row whose canonical absence is proven;
- canonical creates validate/write legacy before canonical, while a post-canonical exception
  probes the deterministic request identity before any compensation.

The laptop's other task-store audit fixes merged without conflict. The two #428 tests still pass,
and `codex_connect_stage` remains in both `app/session.py` and `app/backend_codex.py`.

Both contours had independently created `docs/tasks/426/research.md` and
`review-research-luna.md`, despite the initial inventory saying the names differed. The active VPS
latency research keeps the canonical names. Laptop finalization evidence is preserved as
`research-laptop-merge-finalization.md` and
`review-research-laptop-merge-finalization-luna.md`; the laptop KB evidence links were updated to
those names.

## Temporary number range

`_VPS_TASK_PAR_FLOOR = 500` applies only when `tm_projects.scope` equals
`/home/kesha/orchestra`. `_next_par` still skips existing `docs/tasks/<n>/` directories. When the
canonical counter is still below the temporary floor, `api_create_task` uses the same legacy-issued
number for both stores. A project with a different ID but the VPS scope is covered; a foreign scope
still starts at `1`.

## Acceptance

Command, without `-x` and without a pipeline:

```text
.venv/bin/python -m pytest -q -m "not live_probe" \
  tests/test_audit0901_db.py tests/test_audit0901_delivery.py \
  tests/test_audit0901_harness.py tests/test_audit0901_mcp.py \
  tests/test_audit0901_session.py tests/test_audit0901_sysquota.py \
  tests/test_audit0901_tg.py tests/test_audit0901_tm.py \
  tests/test_audit0901_workspace.py tests/test_backend_claude.py \
  tests/test_bg_jobs.py tests/test_db.py tests/test_mcp_stdio.py \
  tests/test_message_delivery_receipts_380.py tests/test_routes_surface.py \
  tests/test_session.py tests/test_session_hibernate.py \
  tests/test_task_number_floor_435.py tests/test_tg_bridge.py \
  tests/test_tm.py tests/test_workspace.py
```

Result: `952 passed, 1 skipped in 433.91s`, `MERGE_GATE_RC=0`. Pytest emitted a non-failing
`BaseSubprocessTransport.__del__`/closed-event-loop warning after the result. Full raw output is in
`merge-gate-vps-sync.txt`.

Additional focused checks:

- merged task-create seams: `14 passed in 32.14s`, RC=0;
- exact-scope floor + canonical recovery + rejection ordering: `3 passed in 12.04s`, RC=0;
- KB contract: `KB contract OK`, RC=0;
- conflict markers: zero; `git diff --check`: clean.

## Review

Decision inputs: persistence and shared task lifecycle are high-risk; the author runtime is
`gpt-5.6-sol`; consumers are HTTP/MCP task creation, internal spawn allocation, legacy SQLite and
Git-canonical `TaskStore`; the exact AC is the 21-file command above. Auxiliary Sol review was not
authorized, so the allowed route was Luna.

Round 1 found one blocker: range selection compared `project_id`, not stored `scope`. The fix reads
`tm_projects.scope` and the test now deliberately uses `project_id="orchestra"` with the VPS scope.
Round 2 verdict: `APPROVED`; reviewer reran the three focused tests (`3 passed in 11.97s`) and
quoted the updated `vps_task_range = (` line. Artifact: `review-vps-merge-luna.md`.

## Compatibility

No existing task is renamed. Task numbering changes intentionally only for exact VPS scope;
other project scopes retain their previous sequence.
