# T1 verification evidence

Date: 2026-08-11. Worktree: `quota-routing`.

## Focused regression

Command:

```bash
uv run python -m pytest -q \
  tests/test_runtime_router_db.py tests/test_runtime_router.py \
  tests/test_runtime_router_api.py tests/test_runtime_router_auth.py
```

Result after Codex fixes, all DB/store tests, and mutation restores: `194 passed in 26.84s`.
The four async admission/PUT/policy/latch race tests were also run three consecutive times:

```text
run=1  4 passed in 3.97s
run=2  4 passed in 4.13s
run=3  4 passed in 4.18s
```

## Schema and concurrency mutations

Every mutation used a fresh `cp F F.bak`, restored with `mv F.bak F`, and verified the
original marker after restore. Each mutant made its focused test red:

| Mutant | Red proof |
|---|---|
| move `BEFORE DELETE` trigger away from `runtime_routing_latches` | `DELETE FROM runtime_routing_latches`: `Failed: DID NOT RAISE`; `1 failed, 2 passed` |
| change latch insert to broad `INSERT OR IGNORE` | invalid empty window: `Failed: DID NOT RAISE`; `1 failed` |
| overwrite `first_decision_id` on the second decision | second decision raises `runtime routing latch cannot be replaced`; `1 failed` |
| commit the decision before inserting its latch | `routing_last_decision()` remained present after latch failure; `1 failed` |
| replace revision-mismatch recompute with `raise` | `PolicyRevisionError: policy changed before decision commit`; `1 failed` |
| remove the admission lock from `RuntimeRouter.admission` | observed `['first', 'second']` before releasing the first admission; `1 failed` |
| remove transactional latch-snapshot comparison | stale decision no longer raises `RoutingLatchSnapshotMismatch`; `1 failed` |
| accept a configured placeholder instead of the actual dashboard password | forged empty-key cookie was accepted for partial credentials; `1 failed, 1 passed` |

Post-restore marker counts were respectively `1`, `1`, `1`, `1`, and the admission module
again contained all three expected `async with self._policy_lock` sites.

## Full suite

The full command was run twice under the Orchestra global test lock:

```bash
uv run python -m pytest -x -q
```

Both runs stopped on the same unrelated frontend test before reaching the router tests:

```text
FAILED tests/test_frontend.py::test_header_has_orch_tabs
1 failed, 677 passed, 3 skipped in 175.32s
1 failed, 677 passed, 3 skipped in 148.58s
```

The failure is order/environment dependent: the exact failed test immediately passed alone:

```text
tests/test_frontend.py::test_header_has_orch_tabs  1 passed in 7.88s
```

No T1 file touches frontend code or the live dashboard fixture. The orchestrator accepted this
as task **#197**: the test reads live server state and has also failed for another worker.

A third run deselected only that known test and reached 1,118 passes before a second baseline
failure in a live-home probe:

```text
FAILED tests/test_migrate_agent.py::test_encoding_matches_real_cli_directories
1 failed, 1118 passed, 3 skipped, 1 deselected in 263.12s
```

Unlike the frontend failure, this one is independently persistent: the exact test alone also
failed because archived `~/.claude/projects/-tmp-tmp-*` transcripts encode `/tmp/tmp.*`
differently from current `migrate_agent.enc_cli_dir`. Neither the migration utility nor the live
home directory is in T1 scope; its owner is task **#195**.

## Inertness proof

Against pre-T1 parent `13b85507`, existing workload files are byte-identical:

```bash
git diff --exit-code 13b85507 -- \
  app/manager.py app/session.py app/mcp_stdio.py app/routes/sessions.py app/quota_gate.py
# exit=0
```

All references to the new router outside `app/runtime_router.py` are the three inert control-plane
routes in `app/routes/system.py` (`status`, `replace_policy`, `explain`). Existing workload paths
still call the legacy gate:

```text
app/session.py:827:        from app.quota_gate import get_worker_admission
app/session.py:863:                from app.quota_gate import require_worker_admission
app/session.py:1540:                from app.quota_gate import QuotaGateError, require_worker_admission
app/session.py:1700:                    from app.quota_gate import require_worker_admission
app/manager.py:634:            from app.quota_gate import get_worker_admission, require_worker_admission
app/routes/system.py:1206:    from app.quota_gate import get_worker_admission, worker_readiness_envelope
```

Therefore merging T1 creates schema/control-plane candidates but changes no existing spawn,
turn, reconnect, review, or readiness decision path.
