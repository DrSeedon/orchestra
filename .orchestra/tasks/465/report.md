# #465 — implementation report

## Review decision inputs

- Changed production consumers: `app/mcp_stdio.py::switch_worker_branch` public MCP request/result; `app/routes/sessions.py::switch_branch` shared lifecycle route; `app/workspace.py` Git ref promotion/rollback; `app/tm.py` task claim CAS; `app/manager.py::_auto_switch_before_delivery` delivery guard.
- Author metadata: `fix-merge-deadlock`, Codex runtime, `gpt-5.6-sol` from live `list_agents`.
- Exact AC: frozen T2 command at `6ce2570f` is green; T1 normal `NULL + done` and #103 switch guard stay green; every promotion/failure keeps the pinned HEAD reachable; tests remain byte-identical to `6ce2570f`.
- Oracle evidence: T2 was `11 failed` on fresh `main@1a86f403` with the original first assertion, then `11 passed in 2.81s`; T1 + #103 guard were `2 passed in 1.68s`; oracle diff is empty.
- Risk floor: high — shared session/task lifecycle plus Git data-loss path. Sol is the technical route but no auxiliary Sol run is authorized; implementation review uses Luna.

## Delivered

- Explicit `promote_current=True` public mode; `force=True` is mutually exclusive.
- Dedicated Git branch rename at the identical HEAD, with target-absence/content checks and ownership-guarded reverse rename. Existing `switch_worktree_branch` and its detach/reset guard are unchanged.
- Task claim repeats `new`, unowned, unreserved, identity, revision, and session-owner checks at the mutation point.
- Exception, canonical partial, shadow write failure, shadow rejection, or any projection debt keeps the promoted ref and a blocked lifecycle state instead of resetting work.
- Legacy `task_id + needs_switch` recovery remains allowed for a scope without a task project and for exact `done`/owner-NULL completion; a missing task inside a task-managed project or any unfinished/owned task blocks delivery.
- No `merge_worker`, prompt, schema, live DB, force semantics, automatic repair, or restart change.

## Pre-mortem checks

1. Existing completed/stale task bindings stop auto-switching → `tests/test_adhoc_switch.py` exposed the overly broad first implementation; task-state-aware quarantine preserved the old path and the file is `10 passed`.
2. `app/mcp_stdio.py` overwrites #462 review work → direct coordination reported #462 touches only `record_review_outcome`/`codex_review`; #465 diff is limited to `switch_worker_branch`.
3. Reservation arrives between preflight and claim → frozen reservation interleaving test leaves task `new`, session taskless, original HEAD reachable.
4. Shadow/canonical debt is read as success → four frozen parameter arms require partial/unknown plus delivery block.
5. Promotion accidentally reaches detach/reset or weakens #103 → HEAD/ref assertions plus `TestSwitchWorktreeBranch::test_real_unmerged_content_blocks_without_moving_or_creating_branch` (`1 passed`).

## Mutation evidence

Each mutation used a fresh `cp`, printed production marker counts before/after restore, restored with `mv` + `touch`, and reran the green oracle.

| ID | Mutated seam | Marker before/after | Mutant result | Restored result |
|---|---|---:|---:|---:|
| M1 | MCP promotion payload forced false | 1/1 | 1 failed, 10 passed | 11 passed |
| M2 | `promote_current && force` guard disabled | 1/1 | 1 failed, 10 passed | 11 passed |
| M3 | HEAD-preserving rename replaced with `reset --hard` | 1/1 | 7 failed, 4 passed | 11 passed |
| M4 | target `status == new` guard disabled | 1/1 | 1 failed, 10 passed | 11 passed |
| M5 | reservation guard disabled | 1/1 | 1 failed, 10 passed | 11 passed |
| M6 | clear-failure restore branch disabled | production 1/1; mutant 1/0 | 2 failed, 9 passed | 11 passed |
| M7 | projection-debt classification disabled | production 1/1; mutant 1/0 | 2 failed, 9 passed | 11 passed |
| M8 | delivery quarantine disabled on final code | 1/1 | 4 failed, 7 passed | 11 passed |
| M9 | Git failure allowed to continue into task binding | 1/1 | 1 failed, 10 passed | 11 passed |
| M10 | normal completion retained old task id | 1/1 | T1 1 failed | T1 1 passed |

## Test evidence

- `tests/test_workspace.py`: `116 passed`.
- `tests/test_task_tracker_integration.py`: `39 passed`.
- `tests/test_mcp_stdio.py`: `118 passed`.
- `tests/test_api.py`: `131 passed`.
- `tests/test_adhoc_switch.py`: `10 passed`.
- `tests/test_task_completion_421.py`: `6 passed`.
- `tests/test_tm.py`: `22 passed`.
- `tests/test_task_binding_417.py`: `5 passed`; `tests/test_task_binding_418.py`: `4 passed`; `tests/test_audit0901_tm.py`: `10 passed`.
- `tests/test_initial_deliveries.py`: `20 passed`; `tests/test_identity_drift.py`: `12 passed`; `tests/test_merge_branch_drift.py`: `7 passed`.
- `tests/test_manager.py`: `170 passed, 1 failed`. The sole failure is `TestCreateSession::test_planned_initial_turn_is_refused_before_session_publish`; detached `main@1a86f403` reproduces the same failure (`ValueError: scope '/s' has no task project`), so it is not introduced by #465.
- `py_compile` for all five production files: green. `git diff --check`: green. Oracle paths versus `6ce2570f`: byte-identical.

## Review outcome

- Route: Luna; Sol was the high-risk preference but no auxiliary Sol run was authorized. One initial Luna attempt timed out with no reviewer output/artifact and did not consume a round.
- Round 1 found four blocking risks: fail-open missing-task lookup, missing durable idle/lifecycle recheck, alleged reservation gap after canonical update, and unquarantined post-rename verification failure.
- Three findings were accepted and fixed. The reservation finding was disputed with the actual final legacy CAS: it repeats `require_unreserved`, and rejection after canonical write returns `canonical_applied=True` debt. Round 2 accepted that evidence and marked all four fixed.
- Round 2 found one new blocker: post-rollback inspection could raise after the reverse rename, and the clear-binding caller did not quarantine structured rollback failure. Both paths were fixed.
- Direct Git probe forced the second rollback inspection to raise after a successful reverse rename: helper returned `rollback_failed` with the original adhoc branch and pinned HEAD; actual Git matched both values.
- Round 3 verdict: **APPROVED**, no findings. Verified artifact quote: `"error": f"promotion rollback verification failed: {error}",` in `app/workspace.py`.

## Files and commits

- Production: `app/manager.py` +21, `app/mcp_stdio.py` +9, `app/routes/sessions.py` +280, `app/tm.py` +149, `app/workspace.py` +207.
- Frozen tests: `tests/test_mcp_stdio.py` +25; `tests/test_task_tracker_integration.py` +494. `tests/test_workspace.py` unchanged.
- Task/KB evidence: `.orchestra/tasks/465/` research, plan, three review artifacts, report; `.orchestra/kb/task-storage-architecture.md` +4.
- Implementation/review-fix commits: `45cb3dd7`, `11b3ace7`, `6f900262`, `8fe664bd`, `d1fe3d6c`; fresh-main merge `52e83a45` includes `main@1a86f403` without rewriting frozen RED `6ce2570f`.

## Breaking/TODO

- Public API addition is backward compatible (`promote_current=False`).
- The 10 live blocked sessions are not mutated automatically. Each needs an explicit new task and promotion; nine real Git conflicts remain real conflicts after ownership is repaired.
- No restart performed; orchestrator owns restart after merge.

## Merge-gate repair after DONE

- `tests/test_manager.py::TestCreateSession::test_planned_initial_turn_is_refused_before_session_publish` was red on both the task branch and detached `main@1a86f403`: `app/tm.py:407 ValueError: scope '/s' has no task project`.
- `git log -S'has no task project' main -- app/tm.py` traced the downstream error to #248 commit `6f874ace` on 2026-08-24; it is not a fresh foreign change. The test itself originated in #168 (`647452c1`, 2026-08-08) and was adjusted by #343 (`0707d925`, 2026-08-19).
- Root cause: process env and `.env` both set `QUOTA_GATED_LANES=`. The test built a live-policy Claude decision, which therefore became `state='available'`; manager correctly continued into task allocation, where the intentionally absent `/s` project raised. The production order already remains quota admission before task creation.
- Minimal test-only repair: the manager-order test now returns an explicit `QuotaDecision(state='blocked')` instead of depending on deployment quota configuration.
- Verification: the exact node is `1 passed in 3.17s`; full `tests/test_manager.py` is `171 passed in 14.70s`.
- Review: skipped — test-only closed fixture correction, no production consumer changed; the named node and full owning file are deterministic green oracles.

## Snapshot-bound review receipt after #462

- Active #462 merge gate required `codex_review(mode="implementation")` for the current production snapshot; the earlier content review predated receipt enforcement.
- First implementation attempt timed out without reviewer output. The first completed round was blocked because an overly strict caller instruction withheld the Git diff; no code changed.
- The next round reviewed the pinned diff and raised one task-attribution blocker: omitted explicit `worker_session_id`. Code inspection disproved it: `api_update_task_if_current` calls `_infer_task_worker_session` for `in_progress`, transactionally revalidates the unique session, and the frozen T2 assertion checks `('in_progress', found.id)` before a successful merge.
- Final evidence-backed round retracted the finding and returned **APPROVED** with exact source quote `"in_progress", found.id,`. No code or test changed during the snapshot debate.
