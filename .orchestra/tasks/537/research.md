# #537 — automatic recovery of surviving Codex writers

## Question
Context: Orchestra restarts while a Codex app-server survives. Change under test: persist process identity at pipe publication, keep a usable adopted transport when process replacement cannot be verified, and reconcile a surviving turn when abrupt shutdown saved no turn ID. Baseline: pipe-only publication and unconditional adopted-backend refresh, followed by CODEX_WRITER_CONFLICT. Outcome: a post-restart delivery reaches the original thread through the surviving transport without signalling an unidentified process. Detached writers without recoverable transport remain a separate, unresolved fallback decision.

## Hypotheses considered
- Missing process identity causes adopted refresh to discard a transport without retiring its writer. Falsifier: publication already saves identity, or missing identity still permits safe process replacement. Source inspection confirms the first omission; the previous live incident is recorded in #536.
- Fixing PID identity alone makes crash adoption complete. Falsifier: a surviving active turn has no recorded active_turn_id and is reconstructed as idle. This alternative is refuted by the crash-shaped test: the old generation publishes identity and pipes while the DB has no turn ID; the new generation must query the live turn and steer it.
- An inherited pipe pair itself proves the process can be replaced. Falsifier: a missing/reused process identity still has a working pipe transport. Both negative cases pass real JSON-RPC delivery in the new tests; replacement is deferred while delivery remains possible.

## Findings and confidence
- CONFIRMED, tier 2: the original publish_backend_fds wrote no identity. save_handover_state was the independent graceful owner of PID/starttime, active turn and buffered bytes. References: app/manager.py:2869, app/db.py:4162; baseline git show 74edb1da:app/manager.py.
- CONFIRMED, tier 1: the initial six tests passed with valid/missing/reused identities, DB persistence, rollback and actual pipe submission. The expanded nine-test run passed in 11.41s, including manager auto_resume_all, a saved identity and inherited duplicated pipe ends, live active/completed turn reconciliation, and a retry after a failed adoption query. The fake CLI exchanges real JSON-RPC bytes; it never invokes a model. Final expanded regression suite is running separately; restart-tests.log will carry its result.
- CONFIRMED, tier 2: Codex 0.153.4 generated schema accepts thread/turns/list with limit, descending sort and itemsView=notLoaded; TurnStatus is completed/interrupted/failed/inProgress. Command: codex app-server generate-ts --out /tmp/writer-537-schema; inspected v2/ThreadTurnsListParams.ts, TurnItemsView.ts, TurnStatus.ts and ThreadTurnsListResponse.ts. The generated schema is disposable; relevant values are reproduced here.
- CONFIRMED, tier 2: thread/fork copies stored history and does not require resuming the original writer [1]. This is a recovery candidate, not implemented proof. Data written by an inaccessible writer after a fork would not join its copy automatically. An inaccessible old turn might still perform external actions; zero-loss/exactly-once recovery cannot be promised by copying history alone.

## Counter-evidence and limits
The reported ec1a4252 FAILED_BEFORE_SUBMIT receipt is evidence supplied by the orchestrator, not a fresh live measurement made here. No service was restarted, no live writer was signalled, and KillMode was not changed. Local tests simulate a restart; they do not prove the running service has adopted the new code. A successful pipe write is not a model completion. Abrupt supervisor death may lose userspace buffered events even when the native history survives.

The frozen instant-restart tests and graceful adoption tests are included in the expanded run without editing their criteria. Retaining an unidentified adopted writer postpones tool/config replacement; that is preferable to discarding its only working transport. This does not establish recovery when no usable transport remains.

## Affected files and risks
app/db.py and app/manager.py persist identity and clear consumed graceful handover state. app/backend_jsonrpc.py checks replacement eligibility. app/backend_codex.py also guards its separate config-refresh disconnect path and queries a missing live turn ID. app/session.py keeps the transport, retries unresolved adoption before admission, and exposes recovering state. tests/test_writer_restart_537.py exercises these paths.

Pre-mortem: PID reuse must not authorize a signal; missing DB rows must not report protected publication; an identity write failure removes both published ends; a failed turn query must leave admission retryable rather than submit against unknown state; the previous generation's leftover must not replay on a later crash. The detached-writer fallback remains pending the owner's choice about the price of a native fork.

## Verification environment
Imported module: /home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-stuck-writer/app/manager.py.
The first background command ran from the repository root, so its relative test path did not exist: `ERROR: file or directory not found: tests/test_writer_restart_537.py`, `no tests ran in 0.03s`, exit 4. The replacement job explicitly changes to the worker worktree. Test processes use nice=15 and a 2 GiB address-space limit; MemoryMax scope creation is unavailable here (no user bus; system scope requires interactive authentication; sudo has no-new-privileges). No host policy was changed to bypass that restriction.

## Sources
1. Tier 2, fetched in this session: https://raw.githubusercontent.com/openai/codex/rust-v0.153.4/codex-rs/app-server/README.md — thread/fork, metadata-only history, turn pagination and native writer restrictions.
2. Tier 2: current source files and generated installed CLI schema described above.
3. Tier 1: `uv run --frozen python -m pytest tests/test_writer_restart_537.py -q` — 9 passed in 11.41s before the final two DB-edge tests were added.

## Expanded regression result
The completed job on d66537a3 ran `uv run --frozen python -m pytest tests/test_writer_restart_537.py tests/test_instant_restart.py tests/test_fd_adopt.py tests/test_codex_writer_conflict_536.py -q`: `67 passed in 21.14s`. Raw result: restart-tests-fixed.log. The prior run was `1 failed, 66 passed in 23.38s`; the shared AsyncMock did not define the new recovery method and returned another truthy mock as an active turn. Defining its idle response as None fixed the double without changing any acceptance assertion. Raw failure: restart-tests.log.

A subsequent lifecycle inspection found that explicitly retiring a transport after a failed recovery could leave the pending-recovery flag attached to an empty backend. The flag now clears only after backend retirement succeeds; a regression covers subsequent admission. Broader backend/session/manager/hibernate coverage is queued for this additional lifecycle edge and the shared fixture change.

The broader completed run on aab39b66 used `uv run --frozen python -m pytest tests/test_writer_restart_537.py tests/test_backend_codex.py tests/test_session.py tests/test_manager.py tests/test_session_hibernate.py -q`: `559 passed in 95.65s (0:01:35)`. Raw result: lifecycle-tests.log. This includes the retirement regression. The implemented transport-preserving portion is verified; full #537 remains incomplete while the detached-writer recovery policy is unresolved. No external model review has been run for this partial result.

## Model review and repeated-crash correction
Luna reviewed source HEAD 46be5d06 against merge base 715f0fc; report: review.md. The blocker was real: before querying the live turn, adoption persisted idle; a failed query then another crash caused startup to skip recovery. The new test `test_failed_recovery_is_requeried_after_second_restart` failed on the reviewed source with `AssertionError: assert 'idle' == 'running'` (`1 failed in 4.69s`, recovery-two-restarts-red.log). Adoption now retains running until the live query positively establishes idleness. The test simulates two separate SessionManager generations against the same isolated DB and verifies both query attempts. With the correction, `uv run --frozen python -m pytest tests/test_writer_restart_537.py tests/test_fd_adopt.py tests/test_instant_restart.py -q` returned `62 passed in 16.58s` (recovery-two-restarts-green.log).

The review traced the completion race through queued notifications and the turn event loop, and found no blocker in that path. PID/starttime equality plus the existing pidfd/argv checks protects ordinary PID reuse. A process with identical PID, starttime and accepted argv is indistinguishable under that existing identity scheme; no stronger guarantee is claimed. No new signalling was added by this correction.

The orchestrator subsequently relayed owner approval of variant C: a native fork may be used only with positive evidence the old turn is inactive, otherwise visible refusal; no signals to the old writer, and copy provenance/cost visible to sender and dashboard. This supersedes the earlier pending-policy note, but C implementation is explicitly the next block after this reviewed portion is handed off for merge. Unchanging worktree mtime alone is not treated as positive proof of an inactive turn.

## Reviewed transport-preserving handoff
The resumed Luna review evaluated source HEAD 5fcd8676 and resolved the original blocker with no additional blocking/suggestion findings. The reviewer independently ran the focused suite: `62 passed in 15.82s`. Both review rounds are preserved in review.md; the latest verdict is APPROVED. The post-review commit contains evidence only, with no application or test changes. The remaining equal-PID/equal-starttime/equal-argv identity assumption is stated above. This portion is ready for merge with task_outcome=continue; the authorized C recovery block is not included.
