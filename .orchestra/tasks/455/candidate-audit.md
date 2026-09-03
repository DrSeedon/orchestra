# #455 — manual audit of structural candidates

## Reachability graph

The corrected current-snapshot graph parsed 3,044 definitions with 492 conservative production
roots and zero syntax errors. Every `app/` and `scripts/` module body is a root; every decorated
definition and dunder method is a root; direct names, imported aliases (including aliases inside
functions), terminal attribute names, passed/stored function objects, and literal-string dispatch
are edges. This deliberately biases toward declaring code live.

The 42 prompt-bearing structural merges introduced 741 changed lines in 31 stable definitions that
still had no production-root path at frozen `main`. The test-inclusive count below is recomputed from
both `tests/` and task-local `*/acceptance/*.py`; this matters because #315's frozen tests live with the
task rather than in `tests/`. That graph parsed 9,431 definitions with 4,640 roots (pytest tests,
fixtures/decorated definitions, and framework hooks—not every helper): **all 31
production-unreachable definitions are reached by at least one test or frozen acceptance oracle**.
Compact graph evidence: `evidence/current-reachability-summary.json`; attribution:
`evidence/per-merge-summary.json`. Full generated graphs are reproducible from the frozen ref and
retained script; their discarded hashes are in `evidence/discarded-generated-outputs.json`.

| Merge | Task | Production-unreachable changed lines | Closed graph seam |
|---|---:|---:|---|
| `80eefd5b42` | #1 | 1 | `models.unregister_model`; tests are the only callers |
| `d19f68cfce` | #335 / #315 T1 | 25 | `classify_private_fields`, `canonical_bytes`, `canonical_content_head`; no reachable production edge |
| `6e5aa86089` | #342 / #315 T3 | 27 | module wrappers `promote_fact`, `query_facts`; no production incoming edge |
| `e493f20825` | #352 / #315 T5 | 272 | `SessionManager.commit_session_archive → AgentSession.commit_archive → recovery.commit_archive`; every production incoming source is itself unreachable; `wait_extraction` has no incoming edge |
| `c2ea45fa0c` | #358 / #315 T7 | 341 | `scripts.ia_migrate_documents.migration_api → cutover_api → {_shadow,_canonical,_resolve,_rollback}`; the script wrapper has no tracked CLI/main caller |
| `0ce9151a04` | #361 | 5 | `KnowledgeRuntime.receipt_bytes`; no production incoming edge |
| `6461ec9afa` | #436 | 56 | `review_receipt_create/get`; task-specific tests call them, production uses later reserve/finalize APIs |
| `f8e00522e8` | #430 | 14 | project-local `read_record/write_record` helper arms and `require_project_layout`; tests are the only roots |
| **Total** | | **741** | |

This is a production-reachability verdict, not a deletion verdict. There are zero attributed lines
that are unreachable from both production and the complete tracked test/acceptance corpus. The 741
lines are dormant/admin/tested seams, not untested inert text. Removal would need its own consumer
contract and mutation oracle.

## Computed `getattr`

The production graph reported 15 unresolved/non-literal `getattr` sites; none can name one of the 31
candidate definitions:

- 1 site reads a usage data field (`backend_claude.py`, receiver `usage`, name `k`);
- 2 sites dispatch methods on the concrete `RagMemory` receiver (`rag.py`, name `method`); no
  candidate is a `RagMemory` method;
- 1 site reads one of the declared runtime-manifest data fields (`runtime_history.py`);
- 1 site copies four `prepared` namespace fields (`session.py`);
- 10 sites update `_TgDeliveryState` counters whose names are derived from `traffic_class`
  (`tg_bridge.py`).

Literal `getattr` names and finite literal name sets were already inserted as graph edges. Exact sites
and receivers are in `evidence/controls.json` and `evidence/current-reachability-summary.json`.

## Exact AST clone candidates

The negative control passed: current `app/tm.py` contains 11 copies of the legal three-line
`except Exception: / conn.rollback() / raise` form and the detector returned zero clone groups for
the equivalent three-statement scratch body. The four-statement positive control returned exactly one
group. Instrument output was byte-identical in three runs.

Across all 42 merges the detector attributed 15 unique added lines (0.0955% of 15,700 added Python
lines) to six new four-statement-window hashes in four merges:

| Merge | Label | Added clone-candidate lines | Manual reading |
|---|---|---:|---|
| `4b862eb6e1` (#167) | explicit | 2 | overlapping windows in two quarantine fallback branches copy four lifecycle-field assignments |
| `e2ecc033da` (#293) | ambient | 4 | the same lifecycle fields are written to a DB snapshot and then to the in-memory session; two distinct state owners |
| `db8708aaa2` (#319) | ambient | 5 | terminal-reader disconnect clears the same transport fields as normal finalization, but the poisoned path cannot use normal finalization unchanged |
| `6e5aa86089` (#342) | ambient | 4 | the canonical temporary-file write pattern is repeated across typed-storage modules with different error/atomicity contracts |

The clone detector therefore measures exact structural candidates, not harmful duplication. It passed
the required three-line negative control but still finds repeated state synchronization that cannot be
called removable without a behavioral oracle. The observed explicit-versus-ambient clone contrast is
not a simplification verdict.

## Invalidated path

The first full run lacked function-local `ImportFrom.asname` edges and falsely classified the live
portfolio watchdog. `app/main.py` imports `ensure_task as ensure_portfolio_watchdog` and calls the
alias. The run was excluded, alias resolution was added, and controls/full run/noise/comparison were
repeated. The compact receipt is `evidence/invalidated-run.json`; invalid raw outputs were removed.
