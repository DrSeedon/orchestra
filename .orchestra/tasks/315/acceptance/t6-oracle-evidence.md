# T6 merge-receipt/cleanup oracle evidence

Date: 2026-08-25. No production, application-test, live database, service, provider, model, eval or
review call was made while freezing this oracle.

## Current production trace

- Merge-operation-v1 persists the accepted worker branch/head, target admission and acceptance oracle
  before running (`app/merge_operations.py:384-496`, `app/merge_operations.py:682-761`).
- `workspace.merge_worktree_to_main` accepts pinned worker and target heads and rejects target movement
  under the repo lock (`app/workspace.py:1229-1244`, `app/workspace.py:1344-1367`).
- The first SQLite mutation after Git is `checkpoint_merge_commit`; its own docstring explicitly says
  task links and lifecycle depend on it, but it does not create a canonical task/evidence/head receipt
  (`app/merge_operations.py:538-565`).
- Session finalization applies task links and lifecycle, marks the DB finalization applied, and only
  then schedules RAG (`app/routes/sessions.py:1568-1691`). Current result normalization already keeps
  SUCCEEDED/PARTIAL/UNKNOWN/FAILED distinct and treats RAG as secondary
  (`app/merge_operations.py:957-1148`).
- The HTTP adapter exposes operation-v1 POST/GET/resolve/capabilities and preserves FAILED/UNKNOWN as
  typed top-level errors (`app/routes/merge_operations.py:19-98`).
- `app/ia/merge_receipts.py` is absent from the current tree; therefore no durable canonical receipt
  binds target commit, task stable ID/#N, evidence manifest/head, projection heads and acceptance
  revision in one object.

## Frozen selection and controls

The oracle contains five invariant controls and six behavior nodes. Controls pin twelve T1–T5
contract/record hashes plus four deferred #298 files; prove the four current terminal states and
operation-v1 capability; materialize the exact temp DB/session/workspace/accepted-operation harness;
execute the #309 progress/legacy-route/single-refresh/proxy/route-snapshot oracles plus a real local
middleware 426 request; and accept an order-varied/additive-metadata receipt while rejecting a forged
task binding.

Control command:

```text
uv run python -m pytest docs/tasks/315/acceptance/test_t6_merge_receipt_cleanup_behavior.py::test_t6_control_fixture_hash_denominators_t1_t5_and_298_are_frozen docs/tasks/315/acceptance/test_t6_merge_receipt_cleanup_behavior.py::test_t6_control_current_operation_states_and_capability_are_distinct docs/tasks/315/acceptance/test_t6_merge_receipt_cleanup_behavior.py::test_t6_control_operation_harness_session_db_and_workspace_boundary_execute docs/tasks/315/acceptance/test_t6_merge_receipt_cleanup_behavior.py::test_t6_control_309_surfaces_and_426_recovery_remain_exact docs/tasks/315/acceptance/test_t6_merge_receipt_cleanup_behavior.py::test_t6_control_receipt_shape_valid_alternate_and_forgery_detector_are_material -q
```

Exact output:

```text
.....                                                                    [100%]
5 passed in 4.31s
```

## Pre-implementation RED

Command:

```text
uv run python -m pytest docs/tasks/315/acceptance/test_t6_merge_receipt_cleanup_behavior.py -q
```

Exact summary and exit:

```text
.....FFFFFF                                                              [100%]
6 failed, 5 passed in 2.82s
exit 1
```

Every behavior node fails inside `_load_t6_api` with
`#315 T6 missing behavior: cannot import app.ia.merge_receipts: No module named 'app.ia.merge_receipts'`.
Collection and all controls succeed; this is the missing durable receipt owner, not a route/path smoke.

## Frozen hashes

| Artifact | SHA-256 | Git blob before commit |
|---|---|---|
| `test_t6_merge_receipt_cleanup_behavior.py` | `684826daec4952e861dda29ac84721ee398cdfa591dbb2d8a850121682f6dce1` | `6d3829b91f1d865bbb685f8df02ce0782cc2cf22` |
| `fixtures/t6_merge_receipt_contract.json` | `68e7bfba0331080d3c9c0fb1e6f352bccd9e66f9d597166fa7cabf738d59e476` | `2ba426e214fecada4ed90465f3d02d82c70fa7d4` |
| `fixtures/t6_merge_receipt_records.json` | `79a0111839ee4eb70f8903e748b5f69881ec673b863b7e88a826c4c7f254638d` | `aa55e74bf43899979ac931ec202539800123c107` |
