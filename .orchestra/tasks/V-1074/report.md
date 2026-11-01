# V-1074 — durable cron result delivery during restart drain

Worker: `fix-cron-drain-delivery`; broker destination: `task-V-1074/fix-cron-drain-delivery`.
One worker; no delegated agents, model reviews, providers, live SSH, production databases or service actions.
Files are edited in the broker copy; committing, host acceptance, merge/push/CI and live activation remain host operations.

## Result and implementation

- Ordinary cron and matching cron-command notifications use the existing `message_deliveries` receipt/runner.
- An occurrence UUID derives from job id and its scheduled UTC minute. Re-observation finds the existing receipt before executing a completed command again.
- Acceptance inserts the immutable receipt and updates `fire_count`, `last_fired_at`, `last_delivery_id` in one transaction. The existing `db.bg_cron_record_fire` remains the marker owner and preserves its legacy return behavior.
- The receipt stores full decoded stdout+stderr in `message`; `rendered_message` retains the existing instruction and last-3000 output display, including nonzero exit status. Later ticks may update job `last_output` without altering the accepted receipt.
- Actual `DrainingRefused` before submission leaves a cron receipt `QUEUED`, removes its provisional user log, and stops the runner. Existing startup recovery dispatches it; no command is rerun and no new cron retry timer exists.
- Follow-up: `manager.end_drain()` now asks the existing delivery owner to resume `QUEUED`/`PREPARING` targets on an actual closed-to-open transition. A runner still exiting after refusal gets a one-shot done callback; there is no retry timer, orphan recovery or state rewrite. Optional scan/wake failure is logged after admission reopens.
- Cancellation of a cron runner before submission likewise retains its accepted receipt. Cancellation of the schedule after acceptance leaves the result owned by delivery recovery.
- Recipient id/task/branch/needs-switch generation is captured at acceptance and checked before and after lifecycle switching. A stale or unavailable recipient produces a terminal receipt and an idempotent warning in its journal, without waking an agent to acknowledge failure.
- Refused cron instructions are removed from provisional user-message history so a later task cannot inherit them indirectly. Their immutable receipt and warning remain available.
- Cron receipts bypass fan-report interpretation. Failed-turn steering recovery retains the same durable receipt, body and generation instead of transferring cron into the legacy name-keyed mailbox. Ordinary direct-message recovery retains its existing path.
- Quota refusals use the existing `WAITING_QUOTA` queue/releaser. Existing quota admission policy and background-origin exemptions are unchanged.
- Ambiguous provider submission is never automatically replayed; existing unknown/orphaned states retain the uncertainty.
- Timeout notifications, match validation, recurrence and pre-acceptance cancellation/missing-target behavior retain their existing semantics. No `error_watch.py`, restart watcher, privacy policy or transport code changed.
- The handwritten root [CHANGELOG](../../../CHANGELOG.md) records the behavior and normal idle-restart lifecycle.

## Source index

| Location | Responsibility |
| --- | --- |
| [bg_jobs.py:1068](../../../app/bg_jobs.py#L1068) | Stable occurrence key and durable cron acceptance; both firing branches. |
| [db.py:2177](../../../app/db.py#L2177) | Borrowed acceptance transaction and canonical fire marker. |
| [message_deliveries.py:379](../../../app/message_deliveries.py#L379) | Atomic eligibility recheck and receipt insertion. |
| [message_deliveries.py:66](../../../app/message_deliveries.py#L66) | Durable terminal warning without an acknowledgement turn. |
| [message_deliveries.py:910](../../../app/message_deliveries.py#L910) | Cron identity and failed-steer recovery ownership. |
| [message_deliveries.py:1028](../../../app/message_deliveries.py#L1028) | Drain/cancellation deferral and existing quota/ambiguity dispatch. |
| [message_deliveries.py:1255](../../../app/message_deliveries.py#L1255), [manager.py:538](../../../app/manager.py#L538) | Safe live-process queue wake on drain abort; ambiguous barriers stay with their owner. |
| [manager.py:1145](../../../app/manager.py#L1145) | Actual drain gate and generation checks around lifecycle switching. |

## Behavioral evidence

New repository test file (broker commit pending): [test_cron_drain_delivery_v1074.py](../../../tests/test_cron_drain_delivery_v1074.py).
All database rows, paths, private-file contents, processes and transports in these tests are invented fixtures.

| Test index | Contract |
| --- | --- |
| lines 101, 153 | Actual drain exception; atomic accepted fire; cancel/restore/restart; full output and stable rendered body across a later non-match. |
| lines 172, 258, 352 | Double observer, occurrence retry, lost SQLite commit acknowledgement, ambiguous provider acknowledgement and no automatic duplicate dispatch. |
| lines 186, 217, 228, 244 | Changed generation, rename, missing target, lifecycle switch and ordinary authority errors remain strict; no stale history entry; visible terminal failure. |
| lines 283, 308, 321, 341 | Existing quota release; cancellation during command; final eligibility recheck; transaction rollback leaves neither receipt nor fire marker. |
| lines 394, 410, 429 | Runner cancellation, restoration of active recurrence without command replay, and generation-safe failed-steer recovery. |
| lines 462, 510 | Recovered pending text does not attach a referenced synthetic private file; empty/nonmatching/invalid source does not fabricate a match. |

Existing cron manager and Telegram topic-boundary fixtures were adapted to the durable acceptance boundary; their behavior assertions remain.
Frozen receipt/initial-delivery acceptance files were not edited.

Follow-up tests: [test_cron_drain_abort_v1074.py](../../../tests/test_cron_drain_abort_v1074.py), eight cases.
- `test_actual_abort_resumes_cron_once_after_nonmatch_without_command_replay`: actual `system._abort_restart` reopens both admissions without process replacement; process-guard disarm and unrelated inbox scheduling are fake boundaries. The real durable runner resumes exactly once, both after its refusal observer exits and while that runner is still returning.
- `test_abort_keeps_ambiguous_head_and_its_queued_follower_unchanged` and `test_abort_does_not_orphan_or_duplicate_a_live_provider_dispatch`: unchanged `DISPATCHING`/`DELIVERY_UNKNOWN` rows, blocked followers and one live dispatch; calling either orphan-recovery entry point fails the test.
- `test_optional_abort_wake_failure_does_not_close_admission`: metadata and runner-wake failures leave admission open and the accepted row unchanged.
- `test_canonical_direct_preflight_switches_before_generation_capture_and_dispatches`: actual keyed REST route, proof authentication, manager preflight, admission and lifecycle publication; only Git/process boundaries are fake. The captured generation contains the new branch and normal direct delivery succeeds once. The strict post-switch generation guard remains intact.

Parent-reported host result (Orchestra-orchestrator message; worker did not read host logs): **1 failed / 723 passed / 1 platform skip / 4 subtests passed**. The sole reported failure was `test_instant_restart.py::test_t6_grok_spawns_with_parent_owned_pipes`: inherited `ORCHESTRA_AGENT_CGROUP_REQUIRED=1` without a cgroup stopped it before its fake spawn oracle.
The authorized fixture-only correction clears those two irrelevant cgroup variables inside that test. Numeric fd/pipe assertions and the production fail-closed guard remain unchanged; the local reproduction below also checks the existing fail-closed oracle.

## Actual verification

Required runner: provisioned uv **0.11.28**, default `.venv`; no interpreter/lock replacement.
Every test shell prepends `$HOME/.local/share/orchestra/tools/uv/0.11.28/bin` to PATH.
Test commands use `nice -n 15 uv run --frozen python -m pytest <paths> -q --basetemp="$TMPDIR/<run>"`.
`TMPDIR` stays under this task's generated `tmp/`; fixtures use only synthetic Git author/committer identity.
An initial startup test lacked a sandbox Git author; setting fixture-only identity resolved that setup failure without changing production code or frozen tests.

| Check | Result | Full actual stdout/stderr |
| --- | --- | --- |
| New cron behavior baseline | 29 passed | [cron-drain.stdout.txt](cron-drain.stdout.txt) |
| Initial delivery/restart/DB baseline | 520 passed, 1 skipped, 4 subtests passed | [delivery-restart.stdout.txt](delivery-restart.stdout.txt) |
| Follow-up abort/direct and original cron behavior | 37 passed | [drain-abort.stdout.txt](drain-abort.stdout.txt) |
| Final follow-up delivery/restart/DB neighbors, after restoring mutations | 528 passed, 1 skipped, 4 subtests passed | [drain-abort-neighbors.stdout.txt](drain-abort-neighbors.stdout.txt) |
| Pipe fixture under the reported required-but-missing-cgroup environment, env isolation, existing fail-closed oracle | 4 passed | [pipes-cgroup.stdout.txt](pipes-cgroup.stdout.txt) |
| Initial V-1062/63/64/66/1069/1073 input/privacy baseline | 204 passed | [privacy-input.stdout.txt](privacy-input.stdout.txt) |
| Source mutation proof; acceptance tests unchanged | Eight killed; source restored | [mutation-summary.stdout.txt](mutation-summary.stdout.txt) |
| Syntax, import provenance and publication-form scan | PASS syntax and publication-form scan | [verification.stdout.txt](verification.stdout.txt) |

Final compatibility command paths, relative to `tests/`:
`test_cron_drain_abort_v1074.py test_cron_drain_delivery_v1074.py test_bg_jobs.py test_tg_bridge.py::TestCronCommandTopicBoundary99`
`test_message_delivery_receipts_380.py test_message_delivery_failure_notices_741.py`
`test_initial_deliveries.py test_initial_delivery_review_regressions.py test_quota_wait_queue.py`
`test_restart_durable_transfer.py test_restart_cut_recovery_1057.py test_restart_continuation_919.py`
`test_restart_inbox.py test_restart_generation_liveness.py test_seamless_restart.py test_instant_restart.py`
`test_manager.py test_durable_steering_562.py test_db.py`.

Cgroup reproduction adds `ORCHESTRA_AGENT_CGROUP_REQUIRED=1`, unsets `ORCHESTRA_AGENT_CGROUP`, and runs `test_instant_restart.py test_agent_cgroup_env_isolation_v928.py test_workflow_scheduler.py::test_missing_systemd_delegation_skips_setup_but_delegate_failure_stays_required` through the same frozen runner. No cgroup or provider process is actually configured/launched by those oracles.

Privacy command paths, relative to `tests/`:
`test_hub_inputs_v1062.py test_hub_inputs_v1063.py test_hub_download_v1064.py`
`test_hub_message_v1066.py test_optional_worker_memory_v1069.py test_hub_file_policy_v1073.py`.

Mutation command: `uv run --frozen python .orchestra/tasks/V-1074/mutation_check.py`.
The [reproducible runner](mutation_check.py) changes production source temporarily and restores it in `finally`.
Each selected behavioral oracle independently fails when its protection is removed:
[drain-drop](mutation-drain-drop.stdout.txt), [truncate-source](mutation-truncate-source.stdout.txt),
[rerun-command](mutation-rerun-command.stdout.txt), [ignore-generation](mutation-ignore-generation.stdout.txt),
[split-acceptance](mutation-split-acceptance.stdout.txt), [abort-no-wake](mutation-abort-no-wake.stdout.txt),
[abort-orphan-recovery](mutation-abort-orphan-recovery.stdout.txt), [direct-without-preflight](mutation-direct-without-preflight.stdout.txt).
Each log contains the actual expected failing pytest run. The route source is restored after its temporary preflight mutation; there is no production route/API change.
These are local mutation checks, not a claim of independent host review of a committed branch.

## Non-obvious findings and limits

- A durable source field and display field have different meanings. Generic failed-steer mailbox recovery would have discarded cron's display instruction and captured task generation; cron therefore keeps its existing receipt owner throughout recovery.
- A rejected prepared user log is an indirect stale-instruction route through later history. Cron failures clear it while preserving the receipt and terminal warning; frozen ordinary direct-message history behavior is unchanged.
- Acceptance is the atomic boundary. A crash before acceptance is outside this delivery guarantee; already-lost historical outputs are not reconstructed or fabricated.
- Once provider submission starts, an ambiguous acknowledgement cannot prove delivery. Existing uncertainty states avoid automatic replay and duplicates; no stronger distributed exactly-once claim is made.
- The intentional skip is the existing process-group signaling test on a runner without the required group-signal support.
- Full repository `scripts/run_tests.py`, real provider/SSH/service activation, host Git diff/commit verification and CI were not run here. Relevant model-free suites and local mutations are the evidence above.
- The 204-case privacy log is the initial worker baseline; privacy production code did not change in the abort follow-up. The parent owns the final combined host rerun after this broker update.
- Form scanning uses only `scripts.secret_scan.scan_text` over changed files/task artifacts. No actual credential inventory or operator activity was accessed. Host-only literal/inventory publication checks remain required.
- Broker commit and host acceptance/merge/push/CI remain pending. Activation belongs solely to the existing idle watcher; it was not changed or invoked.

Absolute imported `app`: `/home/<private-identifier>/orchestra-ws/vmi3407579/hub-5f38173ec88e469f/app/__init__.py`.
The [verification log](verification.stdout.txt) also records the interpreter and source hashes for host comparison.

## Root host acceptance
Entire updated report, all production/test diffs and both new regression modules read in full. Final unfiltered host selection735passed,1existing process-group platformskip,4subtests; instructioncontractPASS. app imported from /home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-cron-drain-delivery/app/__init__.py. Independent in-memory full-source truncation and split fire/receipt commit mutants each fail the committed oracle; disabling abort queue wake fails both exiting-runner cases. Product files were never edited by root mutations. Initial inherited-cgroup unit-oracle failure was reproduced and resolved by the fixture-only isolation; actual cgroup failclosed controls passed in final selection. Public copies replace forbidden runtime identifiers; originals remain privately retained, with publication-redactions.json recording hashes. No model review under owner freeze, no live command/provider/database/service/restart or PD cleanup. Live Python activation requires existing idle watcher; existing drain callback can lose that first activation notice, so a read-only PID watch will verify it without initiating restart.
