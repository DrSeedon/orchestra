## Summary

Checked `docs/tasks/35/review-correctness.md` from the `review-correctness` worktree against the current main checkout. Most compact/persist/session-state concerns are real, but several severities are overstated for MVP scale, and two merge/stat findings are false as written.

Highest-priority real risks: compact re-entry/session_id loss, unordered full-row `_persist()` writes, auto-compact racing a new turn, and `auto_resume_all()` rewriting archived/error/waiting rows to `idle`.

## Findings

### blocking

- P0-1: REAL - `compact()` has no re-entry guard and clears `_compacting` before the fresh-session ack turn, so manual/auto compacts can overlap and race `session_id`, `_backend`, and pending messages.
- P1-1: REAL - `compact()` sets `self.session_id = None` and then `send()` persists a running snapshot with `session_id=NULL`; restart in that window drops the session from `auto_resume_all()`.
- P1-3: REAL - `_persist()` snapshots a whole row and dispatches unordered executor writes, so an older running/cwd/cost snapshot can commit after a newer idle/current snapshot.
- MISSED: REAL - `_auto_compact()` sleeps 2s and calls `compact()` without rechecking `status`; a queued or user-started next turn can be running by then, and compact will cancel the listener/backend mid-turn.
- MISSED: REAL - `auto_resume_all()` runs `UPDATE sessions SET status='idle' WHERE status != 'idle'`, which also resurrects `archived`/`error` sessions, not just stale `running` rows.
- MISSED: REAL - `_cherry_pick_branch()` ignores `git commit` failure in the unrelated-history fallback and still returns `ok=True`; the caller can then hard-reset the worker branch to target and lose the unmerged worker commits from that branch.

### suggestion

- P0-2: REAL, title overstated - listener recreation after compact is OK because `_backend` is set to `None`, but the 60s poll can return `ok=True` without proving the ack turn completed or context dropped.
- P0-3: REAL as duplicate of P1-3 - the specific `_refresh_context_from_api()` stale-running example is not the main path, but unordered full-row persists are a real state race.
- P0-4: REAL, severity overstated - `remove_worktree()` is not serialized with the merge lock, so merge/remove can fail or leave confusing git state; branch deletion/corruption is overstated.
- P1-2: REAL - cost accounting assumes monotonic `total_cost_usd`; a new Claude session after compact can undercount, and a process resume can also double-count if the SDK reports cumulative resumed-session cost.
- P1-4: REAL - prompt hash/injected flags are mutated before `_ensure_backend()`/`backend.send()` succeeds, so a failed send can suppress future prompt refresh.
- P1-6: REAL - waiting sessions are excluded from `resumable` and then rewritten to `idle`, losing bg-job waiting state across restart.
- P2-1: REAL - Claude listener reconnect can retry every ~2s indefinitely with no cap; noisy but not data-corrupting.
- P2-3: REAL - `_idle_hibernate()` ignores `_pending_messages`; more importantly, an already scheduled hibernate can disconnect an idle backend while compact is using it.
- P2-4: REAL - `_load_from_db()` runs `git rev-parse` synchronously inside async resume; startup stalls are real but not correctness-critical at this scale.
- P3-1: REAL nit - `_codex_reasoning_effort()` has a dead branch returning `"high"` both ways.
- P3-3: REAL nit - `old_session_id` in `compact()` is unused.
- P3-4: REAL nit - `_on_task_done()` leaves `_turn_start` non-zero on silent listener death.
- MISSED: REAL - `manager.remove()` only removes a worktree when the session is loaded in memory; deleting an unloaded DB row leaves its worktree/branch orphaned and can block a future spawn with the same name.
- MISSED: REAL - `create_session()` deletes the DB row on failure after `create_worktree()`, but does not remove the just-created worktree/branch; retrying the same worker can then fail forever on `worktree already exists`.
- MISSED: REAL - `_parse_merged_commits()` uses `_TASK_REF_RE.search()`, so a squash commit mentioning multiple task refs links stats only to the first ref, not all refs.

### question

- P1-5: FALSE-POSITIVE as written - `_fire_auto_report()` copies `last_texts` before scheduling, and `_turn_logs` never contains `stop_reason=` from `_handle_turn_end()` anyway; the real issue is simply that `sr` is always empty.
- P1-7: FALSE-POSITIVE as written - `_parse_merged_commits()` uses `search()`, not `finditer()`, so it does not double-count stats across multiple task refs; it under-attributes to the first ref instead.
- P2-2: FALSE-POSITIVE - `get_session_lock()` is used by merge and switch-branch endpoints in `app/main.py`, so it is not dead code.
- P3-2: FALSE-POSITIVE - `_extract_tool_result()` has no `KeyError` path for missing `result`; this is just a narrow display contract.

## Verdict

The review is directionally useful but over-severes several items. Treat compact/session persistence as blocking work, fix `auto_resume_all()` status rewriting before relying on archived/waiting state, and harden the unrelated-history merge fallback. The merge-stat double-count claim and dead-lock claim should not be carried forward as stated.
