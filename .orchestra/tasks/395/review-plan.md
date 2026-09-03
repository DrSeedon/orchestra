<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Summary

The plan is directionally coherent, but not ready for implementation approval. I found two blocking safety/oracle gaps and four non-blocking plan/test weaknesses. The committed RED tests do identify real missing behavior, but several mandatory ACs remain untested and could pass vacuously.

## Findings

blocking: `docs/tasks/395/plan.md:26-30,45-47` — receipt-only readiness treats non-empty resource hashes as proof of healthy payload/FTS data, while #405 corruption recovery currently validates stored rows and FTS contents. A corrupted payload with unchanged non-empty receipts would be accepted without detection → define an O(1) authenticated/validated receipt invariant or retain a bounded corruption check, and add a corruption test.

blocking: `docs/tasks/395/plan.md:31-37,64-66,104-109` — crash ordering is underspecified across canonical JSON/events, SQLite projection/meta, runtime heads, and the request coordinator. A crash after canonical files commit but before projection/coordinator/debt persistence can leave no durable debt; a crash between canonical commit and `ACTIVE_COMMITTED` must also be recoverable without duplicate ownership → specify the recovery state machine and test crash points, including expected/observed heads and retry behavior.

blocking: `docs/tasks/395/plan.md:225-236` — T5’s oracle does not cover the mandatory HTTP/canonical/status paths. The test only checks MCP symbol presence (`assert hasattr(mcp, "task_create_status")`), a shadow-mode legacy failure, and direct canonical-store replay; it does not exercise canonical HTTP create, `X-Request-ID` fallback, generated compatibility keys, key validation, status authorization/response, canonical crash recovery, `PENDING`, or same-key conflicts in canonical ownership → add behavioral tests for those paths before accepting the ticket.

suggestion: `app/tm.py:1758-1804` vs `docs/tasks/395/plan.md:203-211` — canonical `api_list_tasks` and `api_get_task` still execute the legacy read first, so production reads are not solely one canonical SQLite snapshot. T3’s direct `TaskStore` tests do not cover these API consumers → specify and test the canonical/shadow routing behavior in `app/tm.py`.

suggestion: `tests/test_tm_projection_hotpath_395.py:122-177` — T2’s failure test monkeypatches `_refresh_current_projection` wholesale rather than injecting failure into the targeted SQLite CAS/update seam. It therefore does not prove that the old projection receipt/rows survive a real targeted transaction failure or that expected/observed heads are recorded → inject failure in `update_current_records`/CAS and assert the durable debt fields.

suggestion: `docs/tasks/395/compare_benchmark.py:57-77` — the comparator accepts median latency, so a multi-iteration run can pass despite an individual run exceeding 30 seconds. The plan calls this a `≤30.000` criterion but does not state that median is the acceptance statistic → choose and document a per-run/max criterion, or explicitly make median the requirement and add a maximum regression guard.

question: `docs/tasks/395/plan.md:215-223` — T4 is marked `blocked-by: T1`, but fallback-only query behavior is independently implementable and testable through `_query_projection`; it does not require startup admission or deferred repair to exist. Should T4 be unblocked, or is there a specific shared receipt API dependency that needs to be named?

## Verdict

NEEDS WORK. Do not begin implementation until the two blocking safety/oracle gaps are resolved. Luna review via the external Codex reviewer was unavailable in this session; this verdict is based on the requested source-only review.

## Author disposition after Round 1

- Receipt blocker — PARTIAL premise, ACK outcome: an O(1) singleton receipt cannot authenticate
  every later projection byte. The plan no longer calls it proof of content integrity; it is an
  atomic commit marker. Selected payload hashes/semantic results are verified before service,
  full #405 validation remains background, and new RED payload+FTS corruption cases require
  canonical fallback without inline repair (`85017d25`).
- Crash-order blocker — ACK: added explicit canonical pending-marker, canonical/task/current/runtime
  six-step state machine and five-step request coordinator recovery. New RED cases cover real
  SQLite trigger rollback, canonical/projection head-gap restart and an interrupted canonical
  head switch with a durable pending marker (`85017d25`, `eefe4f84`).
- T5 oracle blocker — ACK: added behavioral HTTP fallback/generated/validation/status authorization,
  canonical HTTP replay/conflict, PENDING-after-canonical recovery, and concurrent PENDING
  Retry-After cases. The exact T5 command now has 8 missing-behavior failures (`85017d25`).
- Canonical read suggestion — ACK: plan and RED test require canonical API list/get to avoid legacy;
  shadow mode retains legacy-first comparison (`85017d25`).
- T2 injection suggestion — ACK: a SQLite abort trigger now checks row/FTS/meta rollback; the
  facade test separately checks durable expected/observed debt.
- Comparator suggestion — ACK: frozen comparator now uses the maximum across every measurement row,
  not median (`85017d25`).
- T4 dependency question — KEEP T1 dependency: T4 consumes T1's O(1) receipt classification,
  debt reasons and single background-repair owner; that shared API is now named in the plan.

- Attempt 2: tool refusal — context validator required a literal caller task + PROJECT CONTEXT block; no reviewer output, round not consumed.
- Attempt 3: started — same evidence-backed Luna follow-up with the required context block.

## Round (2026-08-27T08:03:53Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-luna"} -->

## Round 2

## Prior findings

- **FIXED:** Receipt semantics now explicitly distinguish commit markers from payload integrity; selected reads validate digest/semantic consistency and fall back on corruption. Evidence: `plan.md:45-51`; RED coverage in `test_t4_corrupt_current_data_is_never_served_before_background_validation`.
- **FIXED:** Canonical pending markers, head-gap recovery, CAS rollback, and debt ordering are now specified. Evidence: `plan.md:147-190`; T2 RED coverage includes trigger rollback, restart head-gap, and pending-marker cases.
- **FIXED:** T5 now covers HTTP fallback/generated/invalid keys, canonical replay/conflict, PENDING recovery, Retry-After, MCP, and status authorization. Evidence: `plan.md:292-300`; tests `test_t5_http_fallback_generation_validation_and_status_authorization`, `test_t5_canonical_http_replay_conflict_and_pending_crash_recovery`.
- **FIXED:** Canonical API reads explicitly avoid synchronous legacy reads, with a dedicated RED test. Evidence: `plan.md:94-96,267-270`; `test_t3_canonical_api_reads_do_not_open_legacy_owner`.
- **FIXED:** T2 now injects failure at the targeted SQLite transaction seam and checks rollback of rows, FTS, and receipt. Evidence: `test_t2_targeted_sqlite_failure_rolls_back_rows_fts_and_receipt`.
- **FIXED:** Comparator now applies the maximum across all after-rows. Evidence: `compare_benchmark.py:73-85`.
- **FIXED:** T4’s dependency on T1’s receipt/debt/repair contract is explicitly named. Evidence: `plan.md:58-60`.

## New findings

blocking: `tests/test_tm_projection_hotpath_395.py:285-321` — the interrupted-generation test proves only that `pending-generation.json` exists and contains fields; it never executes recovery or verifies that recovery completes C1/reconstructs C0 and clears the marker. The plan promises that “explicit recovery verifies the staged event/state digests and either completes C1 or reconstructs C0” (`plan.md:156-159`) → add a restart/recovery invocation and assert the resulting canonical receipt, state/event set, projection relationship, and marker cleanup. Otherwise an implementation with a durable but unusable marker passes the RED suite while still losing or stranding task state.

suggestion: `tests/test_tm_projection_hotpath_395.py:41-74` — T1 still calls `owner._refresh_current_projection()` directly rather than exercising `app.main.lifespan` through the readiness boundary. It does not verify that `Application startup complete` is emitted before repair, that exactly one background repair is owned, or that the actual readiness path avoids O(N) work → add a focused lifespan/readiness seam test or explicitly document why this method is the authoritative readiness seam.

suggestion: `tests/test_tm_projection_hotpath_395.py:255-282` — the “restart derives debt” test also invokes `_refresh_current_projection()` directly and only forbids repair methods; it does not prove that real startup admission records the expected/observed heads without repairing inline → cover the startup admission entry point.

suggestion: `tests/test_tm_projection_hotpath_395.py:325-405` — T3 verifies lock independence and `_states()` avoidance, but not that list/get observe one complete old/new SQLite snapshot under concurrent mutation. A reader could combine rows or heads from different snapshots while satisfying the current assertions → add a concurrent two-connection snapshot consistency assertion.

suggestion: `docs/tasks/395/compare_benchmark.py:10-27,41-50` — corpus identity is checked per artifact, but before/after measurement-row counts are not required to match. A truncated after artifact can pass the maximum threshold with fewer observations → require equal non-summary row counts and reject missing metric fields explicitly.

## Verdict

NEEDS WORK. All prior findings are fixed, but the pending-generation test is still insufficient to establish crash recovery and leaves a blocking data-loss/recovery gap. Luna was not callable in this session; no Sol review was performed.

## Post-ceiling resolution

The second Luna prose round is the ceiling; no third round was run.

- New blocking finding — ACK and fixed in `58704831`: the interrupted-generation RED now invokes
  `recover_pending_generation()` and requires completed C1, the intended canonical receipt,
  materialized state/event, old P0 as explicit task-projection debt, and marker removal. The plan
  defines both complete-C1 and digest-mismatch rollback-C0 outcomes.
- T1/startup suggestions — documented: `_refresh_current_projection()` is the unique synchronous
  projection seam in the exact lifespan call chain; its `repair_required` return is handed to one
  post-yield owner, while the same-corpus timer covers `knowledge_runtime_mode()` entry.
- T3 snapshot suggestion — accepted in `58704831`: a two-connection RED holds a read transaction
  across meta+rows during the targeted writer and requires complete P0 followed by P1.
- Comparator suggestion — accepted in `58704831`: unequal row counts and absent metrics now fail
  before thresholds; the maximum of every row remains the statistic.

No blocking reviewer finding remains recorded-and-ignored. The artifact's final model verdict
remains `NEEDS WORK` because the fix was necessarily post-ceiling; completion evidence is the
immutable RED command and commit above, not a fabricated third approval.
