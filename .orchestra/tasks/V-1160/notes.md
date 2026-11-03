# V-1160 / V-1167 — harness steer/interrupt/mailbox/restart path

## Reported shape (from the parent's safe V-1161 handoff)
T1 interrupted 157 s after an owner steer whose exact bytes are in the native rollout as
`role=user/input_text`. At turn end: 4 steers requeued, WAITING (bg jobs), mailbox 6 =
3 `codex_steer_backup` + 3 `direct_message_recovery`. T2 started 2 s later with a 23 916 B
user input of six `[from:]` blocks = the `_deliver_mailbox` batch. The "huge message" is
the mailbox payload, not a system/developer/history bundle.

## Reachable chain before the fix
1. `AgentSession.send` RUNNING codex → `mailbox.enqueue(codex_steer_backup_pending)` + log
   `user_message` + `turn/steer`; durable deliveries log at `prepare_message_delivery`.
2. Turn ends `ok=False` → `requeue_failed_turn` copied ALL steered receipts of the turn into
   the mailbox; backups complete only on `ok=True`, so they stayed pending.
3. `finish_turn_status` → WAITING; `after_turn_idle_actions` claims the mailbox →
   `_deliver_mailbox` → `send(...)` logged the whole batch as a new `user_message` and started
   T2 with every steer again.
4. `restart-cli` during a turn: `_disconnect_backend` drops `session._backend` before the
   listener is cancelled, so the listener's `finally` takes the plain-IDLE branch: no failed
   terminal, no `requeue_failed_turn` → durable steers the killed CLI never added stayed
   SUBMITTED (silent loss). Reproduced by `test_restart_cli_requeues_the_steers_of_the_cut_turn`.

Synthetic replay: `repro_trigger.py` (temp DB, real `CodexBackend`, fake JSON-RPC). Before:
`user_message: '[from:user] owner steer 1\n\n[from:user] owner steer 2'` after
`mailbox: 2 — продолжаю ход вместо пробуждения`. After: the chat gets
`mailbox: re-sending 2 message(s) from the interrupted turn; they are shown above`; the model
input is unchanged there (that replay has no rollout → unknown → at-least-once).

## Fix (current, after QA 0c907)
- Native rollout evidence is withdrawn. Rounds V-1167, 21ac and 0c907 each found a loss in the
  rollout-scan dedupe (facts suffix, unbounded read, initial input, late flush, and finally a
  replaced backend / history beyond the remembered horizon). No installed Codex version has a
  verified per-turn identity in its rollout that this task could check offline (no CLI, no
  provider, no live rollouts), so the only fail-closed rule is: every steer of a failed turn is
  redelivered. The model may see a steer twice; nothing is lost. Re-enabling a dedupe needs a
  verified rollout turn-identity sample from the installed version — a parent/owner decision.
- `requeue_failed_turn`: skips turns without SUBMITTED steered receipts; commits
  `kv steer_recovery_pending:<session>:<turn>` first, then in one transaction requeues, writes
  `steer_recovery:<session>:<turn>` and deletes the pending key. A failed transaction leaves
  the pending key: `sweep_stuck_deliveries` → `retry_pending_steer_recoveries` finishes it
  (QA 0c907 #2). A failure before the pending key is durable → `TurnManager._retry_steer_recovery`
  (1/5/30 s). The done key keeps a repeat terminal from requeuing a receipt that
  `complete_recovered_mailbox_delivery` returned to SUBMITTED under the same `steered:<turn>`.
- QA 62e32c: `complete_recovered_mailbox_delivery` used to return the receipt to SUBMITTED with
  the finished `steered:<turn-1>`, so a second interruption could not see it. `AgentSession.send`
  now returns its route (`("steer", turn, has_backup)`, `("turn", turn, False)` or None) and the
  receipt names the carrying turn: steer without backup → `steered:<turn-n>` (requeued again on
  failure); steer with a backup row → plain turn (the backup owns recovery, no double copy);
  initial input of a turn → plain turn; unknown → NULL.
- Boundary for the initial-input case: it is not requeued when that turn is interrupted, the
  same contract as any message that started a turn. Codex accepted it with `turn/start`, and the
  V-1161 trace shows such input persisted natively 1.1 s after the turn started; an interrupt
  inside that window is the same pre-existing exposure every ordinary first message has.
- Chat: recovery copies (`direct_message_recovery`, `codex_steer_backup*`) are re-sent to the
  model but logged as a status; fresh after-turn input is still shown.
- `restart-cli`: captures the active turn before disconnect and requeues its durable steers;
  no automatic turn. Backups of owner steers were already pending in the mailbox.
- Sweeper wakes WAITING as well as IDLE; compacting (V-1150) and RUNNING are still skipped.
- `_runtime_context`: a rollout vanishing between glob and stat, or an unreadable `exists`,
  is "not located"; the usage baseline no longer aborts `turn/start`.
- Manual Stop unchanged; its retry guard is covered by a committed test.
- Dual backup+receipt for one steer: unreachable (confirmed by QA), no code for it.

## QA be000c6
(1) `_deliver_mailbox` called `send` while the session could only queue in memory
(compaction, deferred interrupt pending, no mid-turn input, failed steer without backup); the
rows were acknowledged and the receipts set SUBMITTED/NULL, so a process death before the
flush lost the text. Now `send(require_submit=True)` raises `DeliveryDeferred` in those
branches before logging or queueing; `_defer_mailbox` releases the claim (rows stay
undelivered in the DB) and starts `_deliver_mailbox_when_free` (1 s checks, ≤ 900 s) for the
compaction case; a running turn takes the rows at its own end. `mailbox.claim` is atomic, so
the waiter and the turn end cannot both deliver. Tradeoff: after a compaction, messages queued
in memory during it (newer) may start their turn before the deferred mailbox rows (older).

(2) Death before the recovery intent. Minimal recovery implemented, bounded to the existing
boot obligation: `auto_resume_all` already captures sessions persisted `running`/`interrupted`
(`restart_cut_turns`). For each, `requeue_cut_turn_steers` requeues SUBMITTED `steered:<turn>`
receipts whose `updated_at` is after the session's last logged `turn ended` status (steers are
accepted only during a turn), through `requeue_failed_turn` (done marker respected).
Limits, stated plainly:
- Old successful turns are not touched (their receipts predate the last turn end); idle,
  waiting, archived sessions are not touched at all.
- QA 09f496: the bound was the `ts` of the highest `turn ended` row id; rows are written by a
  thread pool, so an older turn's end could get the higher id and a finished turn's steers
  were requeued. The bound is now `MAX(ts)` (event time captured when `_log` is called);
  `test_startup_bound_uses_event_time_not_log_write_order`, red with the id-based query
  (`red_checks_round8.txt`; baseline 80 passed with the mailbox/562/966/433/1057 files).
- Remaining at-least-once duplicate: a successful turn whose `turn ended` row never reached
  the DB (death inside the executor flush window, or a failed write) is treated as cut, so its
  steers can be delivered again; nothing is lost. The current event-time bound remains in use.
- Integration boundary set by Orchestra-orchestrator for this owner-approved task
  (2026-11-02): no receipt-contract variants B/C; retain the documented at-least-once
  duplicates. No per-turn success marker or receipt reinterpretation is added to suppress them.
- Steers of a cut turn that Codex had already recorded natively are delivered again (duplicate).
- Death before the steer's own receipt reached SUBMITTED is the receipt layer's existing
  DISPATCHING → DELIVERY_UNKNOWN_ORPHANED path (at-most-once, unchanged).
- SQLite here: WAL, `synchronous=2` (FULL) — committed markers survive power loss.

## `cli_pid` in the 14:34 snapshot
`sessions.cli_pid` exists in `app/schema.sql` but no current `app/` code writes it
(`rg cli_pid app/*.py` → 0 hits), so "stored CLI PID absent" is the expected contract, not
evidence of a dead process. `active_turn_id` is in-memory backend state, not persisted. The
"running with no active turn" snapshot is not explained by these records.

## Checks (raw output in `private/` here, git-ignored by this folder's `.gitignore`)
Runner: provisioned uv 0.11.28, `uv run --frozen python -m pytest ... -m 'not live_probe'`;
imported `app` = this copy's `app/__init__.py` (absolute path in `private/imported_app_path.txt`).
- V-1160 + 562 + 966 + 433 files: 43 passed (`run9.txt`).
- Red checks (`red_round7.sh` → `red_checks_round7.txt`): 18 mechanisms reverted one at a time,
  each red; baseline 43 passed. One mutation ("mailbox delivery drops the send route") first
  targeted a line that no longer existed and stayed green; updated to the current line it is
  red (3 tests) — both results are in the file.
- Targeted set (131 files, `-n 4`, live probes deselected), `targeted_round7.txt`:
  `8 failed, 3124 passed, 14 skipped`, rc=1, 16.5 min. Two were real: `tests/test_mailbox.py`
  doubles did not accept the new `send` keyword (`require_submit`); their signatures now take
  `**_options`, assertions unchanged. Environment as before: `test_service_lifecycle_537`,
  `test_shell_policy`, `test_workspace::test_different_repos_no_collision`, `test_undelivered`
  debounce. Load-only: `test_tg_bridge::TestTgSendSafe::test_serializes_concurrent_group_sends`,
  `test_manager::...removes_worktree_and_branch`. Serial rerun of mailbox/codex-mailbox/
  limit-wake/owner-auto-report/V-1160/562/433/1057 files plus the two load-only tests:
  140 passed (`rerun_round7.txt`).
- Full `scripts/run_tests.py`: not completed on the hub (rc=124, ~33 %, `full_suite.txt`).
- Earlier-round artifacts describe earlier versions.

## Live provider calls made by the targeted runs (must-fix outside this task)
The targeted command did not pass `-m "not live_probe"`; `tests/conftest.py` only declares the
marker, `scripts/run_tests.py` alone excludes it. So `test_pinned_runtime_semantically_recalls_long_native_history`
ran with the hub's real CLIs: Claude spent a turn in rounds 3 and 4 (`cache_create` 1 148 733 and
1 131 846, `stop_reason=refusal`); round 2 returned zero usage; round 1 not established. Codex
was refused by the version gate (0.164.0 vs pinned 0.160.0) before any provider call. Recorded
in TODO.md; round 5 ran with `-m 'not live_probe'`.

## Open
- Manual Stop is followed at once by the mailbox continuation (T2 2 s after abort); policy
  decision belongs to the parent/owner. Unchanged; guarded by the manual-stop test.
- Duplicate model context for interrupted turns is back (fail-closed); a dedupe needs a
  verified per-turn rollout identity from the installed Codex version.
- A steer marked SUBMITTED after its turn's recovery already ran is not requeued
  (pre-existing ordering; not observed in the trace).
- `kv` keeps one `steer_recovery:` row per failed Codex turn that had durable steers.
