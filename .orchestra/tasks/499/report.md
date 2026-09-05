# #499 — lifecycle quarantine visibility, convergent repair, shared task allocation

## Root causes

1. Lifecycle quarantine was derived only inside `SessionManager._auto_switch_before_delivery` by
   `task_binding_requires_quarantine`. Nothing stored or projected that result, so `list_agents`,
   `worker_wip`, and keyed message acceptance had no state from which to report it. The fix keeps
   quarantine derived: `SessionManager.lifecycle_quarantine` calls the same predicate used by the
   delivery refusal, and every reader renders that projection. No session column was added.
2. `TaskStore.task_update_if_current` compared the current global canonical head with the historical
   `canonical_head` stored on the last generation that changed one task. Any unrelated task update
   advanced the global head without rewriting that task snapshot. The CAS therefore reused the same
   stale expected digest forever; retrying could not converge.
3. Legacy allocation skipped surviving `.orchestra/tasks/<n>/` directories while canonical
   allocation did not. Equality correctly refused the two incompatible candidates, but no retry
   could change either rule. `_next_available_task_number` now applies the artifact reservation to
   both candidates before the equality gate; genuine store divergence still refuses.

## Frozen RED evidence

Command: `uv run pytest -q -s tests/test_lifecycle_quarantine_499.py`

```text
DELIVERY_RESULT=Message accepted to 'worker'; delivery_id=c6612fe2-8619-46ee-a052-33e38b9e9a82; state=QUEUED.
WIP_RESULT='worker' | idle: clean — no uncommitted changes, no unmerged commits (vs main)
CAS_ATTEMPT_1=ConcurrentTaskUpdateError: canonical head changed: expected sha256:old, found sha256:new
CAS_ATTEMPT_2=ConcurrentTaskUpdateError: canonical head changed: expected sha256:old, found sha256:new
2 failed in 2.19s
```

Frozen first at commit `3c68799c`. The first CAS oracle was replaced after owner tracing proved that
the tm-layer identity-map workaround was the wrong seam; the real `TaskStore` interference oracle
was frozen in `c68c92a9` before the owner fix.

Allocator RED before implementation:

```text
IdentityConflictError: task display counter mismatch in project: canonical=2, legacy=4
FAILED tests/test_lifecycle_quarantine_499.py::test_shared_allocator_skips_surviving_artifact_directories
1 failed, 1 passed, 8 deselected in 1.93s
```

## Real-state read-only check

Source opened with `sqlite3.connect('file:/mnt/data/Projects/Python/orchestra/data/orchestra.db?mode=ro', uri=True)`
and copied using `Connection.backup()` into `:memory:`. No production write occurred.

```text
sessions_has_quarantined_at=False
rows=[('painter-canvas', 'idle', '90', None)]
count=1
```

Because `sessions.quarantined_at` does not exist (the similarly named column belongs to
`tg_file_deliveries`), the live count used the exact durable inputs to the derived predicate:
non-archived `needs_switch=1` plus a non-empty task binding. The only live specimen was
`painter-canvas`; it was not modified.

## Acceptance and final checks

- Quarantined keyed delivery refuses before receipt creation with `LIFECYCLE_QUARANTINED`,
  `retryable=false`, and the exact existing-tool call.
- `list_agents`, `worker_wip`, and delivery use one predicate. The test toggles
  `task_binding_requires_quarantine` once and all three outputs change together.
- `switch_worker_branch(name="worker", task_id="90", from_ref="main")` repairs current binding;
  the second call reports `already_current` and makes no change.
- `LEGACY_MERGE_CONTINUE` includes the exact repair call.
- Unrelated-task interference advances the global head and target-task CAS still succeeds.
- Same-task revision contention still returns `prevalidated task revision changed`.
- Artifact directories 2 and 3 make both durable and non-durable task creation allocate 4.
- A canonical=2 / legacy=4 divergence without artifact reservations still refuses.

Commands:

```text
uv run pytest -q tests/test_lifecycle_quarantine_499.py
15 passed

uv run pytest -q tests/test_task_binding_418.py::test_two_readers_must_agree_on_project_and_display_identity
1 passed

uv run pytest -q tests/test_api.py tests/test_message_delivery_receipts_380.py tests/test_mcp_stdio.py tests/test_manager.py tests/test_adhoc_switch.py tests/test_task_binding_418.py tests/test_task_create_idempotency_395.py tests/test_tm.py -k 'not test_t401_quota_refusal_is_returned_before_receipt_or_user_log'
482 passed, 1 deselected in 32.73s

uv run pytest -q tests/test_knowledge_runtime_debt_361.py tests/test_tm_projection_hotpath_395.py tests/test_task_repair_completion_422.py tests/test_lifecycle_quarantine_499.py
45 passed in 4.18s
```

`test_t401_quota_refusal_is_returned_before_receipt_or_user_log` remains independently red because
its fixture now produces `QuotaDecision(state='available', gated=False)` for Claude at 95%; PDB
confirmed the admission service was awaited once. Neither its test nor quota policy was changed.

## Mutation evidence

- Derived quarantine disabled once: marker `1 → mutant 1 → restored 1`; `2 failed`; restored `2 passed`.
- Current-binding repair skipped: marker `1 → mutant 1 → restored 1`; repair returned
  `already_current` instead of `lifecycle_repaired`; restored `1 passed`.
- Fresh global head reverted to historical task head: marker `1 → mutant 1 → restored 1`;
  `ConcurrentTaskUpdateError` reproduced; restored run printed `UNRELATED_INTERFERENCE=True` and
  `SAME_TASK_CONTENTION={'ok': False, 'error': 'prevalidated task revision changed'}`.
- Exact warning tool name changed: marker `1 → mutant 1 → restored 1`; warning test failed;
  restored `1 passed`.
- Shared artifact skip disabled: marker `1 → mutant 1 → restored 1`; both create paths allocated 2
  instead of 4 while the divergence control stayed green; restored `3 passed`.
- Global head read moved back after revision validation: marker `1 → mutant 1 → restored 1`;
  deterministic same-task interleaving was wrongly accepted; restored test rejected it.
- Receipt acceptance lock removed: marker `1 → mutant 1 → restored 1`; concurrent repair entered
  before receipt commit; restored test held it outside until commit.
- Actual-branch comparison disabled: marker `1 → mutant 1 → restored 1`; drift repair returned a
  success dict instead of 409; restored test refused drift.
- Non-mutating repair validator replaced with `bind_task_to_session`: marker
  `1 → mutant 1 → restored 1`; a missing task binding was created; restored test left both owners
  unchanged and returned 409.

Every mutation restored with the backup followed by `touch` and a green rerun.

## Pre-mortem

1. `app/routes/sessions.py::send_message`: healthy workers could be falsely refused. Checked by
   `test_healthy_delivery_and_status_remain_healthy` and the 482-test delivery/lifecycle run.
2. `app/manager.py::list_sessions` and `session_wip`: readers could recompute a different state.
   Checked by `test_one_predicate_drives_list_wip_and_delivery_together` plus predicate mutation.
3. `app/ia/task_store.py::task_update_if_current`: accepting unrelated interference could also
   accept same-task races. Both directions run in
   `test_unrelated_interference_converges_but_same_task_contention_loses`.
4. `app/routes/sessions.py::switch_branch`: repeated repair could mutate or reopen work. Checked by
   first-call `lifecycle_repaired`, second-call `already_current`, persisted `needs_switch=0`.
5. `app/tm.py::api_create_task`: sharing the artifact skip could weaken the identity gate or diverge
   durable/non-durable calls. Both paths allocate 4; a genuine mismatch still raises.

## Review decision inputs

- Author: `gpt-5.6-sol`, Codex runtime (production session metadata, not inferred from name).
- Changed consumers: shared direct-message acceptance and dispatch preflight, session list API,
  WIP API, MCP list/WIP/send/switch rendering, merge warning, branch/task lifecycle transition,
  canonical task CAS, legacy/canonical task creation.
- Named AC: the eight bullets under Acceptance above.
- Strong oracle: frozen RED `tests/test_lifecycle_quarantine_499.py`, plus the unmodified #418
  identity contract and existing lifecycle/delivery suites with exact outputs above.
- Route: high-risk shared delivery/lifecycle/persistence surface. Sol review was not explicitly
  authorized; one independent Luna implementation review is requested under `codex-debate`.

## Review round 1

Luna reviewed the pinned implementation and ran the task suite (`11 passed in 3.28s`). The review
artifact is `.orchestra/tasks/499/codex-review-impl.md`. Four P1 blockers were verified and fixed:

1. Global-head adoption happened after revision validation, leaving a same-task interleaving.
   Fixed by snapshotting the global head before reading/validating target state; deterministic
   interleaving now rejects while unrelated prior interference succeeds.
2. Lifecycle preflight and durable receipt acceptance were not in one target-session critical
   section. Both new acceptance and failed-before-submit retry now hold the session lock through
   receipt commit.
3. Same-task repair trusted the durable branch string. It now reads actual Git branch/head and
   refuses drift before clearing `needs_switch`.
4. Repair called the mutating binder before lifecycle persistence. It now uses
   `validate_task_binding_repair`, which checks both owners and task status without writes; every
   failure therefore leaves both owners unchanged.

Each review fix has its own committed oracle and red/restore mutation evidence above. Round 2 is a
same-session Luna re-review of these four changes, as permitted after accepted blockers changed the
implementation.

## Review round 2

Luna marked all four round-1 blockers **FIXED** and ran
`uv run pytest -q tests/test_lifecycle_quarantine_499.py` → `15 passed in 3.50s`. It found two new
P1 blockers; both reproduced and were fixed:

1. Applying artifact reservations before comparing candidates could turn a genuine raw
   canonical=2 / legacy=4 divergence into normalized 4 / 4. `_agreed_next_task_number` now compares
   raw store candidates first and only then applies the one shared reservation rule. The negative
   control includes the masking directories 2 and 3.
2. Same-task repair accepted `from_ref` even though it did not switch branches, overwriting the
   persisted lifecycle base. Repair now retains `previous_base_branch`; its test supplies
   `from_ref="release"` and proves the stored base remains `main`.

Round-2 mutations:

- Raw candidate gate disabled: marker `1 → mutant 1 → restored 1`; the genuine divergence test did
  not raise; restored shared-allocator run `3 passed`.
- Repair base changed back to `from_ref`: unique four-line marker
  `1 → mutant 1 → restored 1`; stored base became `release`; restored test `1 passed`.

Round 3 is the final permitted executable-artifact review round and checks only these two accepted
fixes plus regression of the six already-closed blockers.

## Review round 3 — final

Luna marked all six prior blockers **FIXED**, found no new findings, and returned **APPROVED**.
Independent command evidence in the review artifact:

```text
$ uv run pytest -q tests/test_lifecycle_quarantine_499.py
...............                                                          [100%]
15 passed in 2.39s
```

Review route: Luna (Sol not explicitly authorized)

Rounds: 3/3 executable-artifact ceiling

Verdict: APPROVED

Findings: blocking 6 total, all 6 reproduced and fixed; new findings in final round: 0

Evidence: `.orchestra/tasks/499/codex-review-impl.md`; receipt
`review-receipt:de814406-eb6f-48f8-9d4e-c1b9a78354ac`.
