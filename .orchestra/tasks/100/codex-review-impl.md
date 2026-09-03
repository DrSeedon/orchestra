## Summary

FIFO is apparently optional when the test marks every text `important` 😏. I found two blocking AC failures and three concrete suggestions. The targeted image/stats selection passes: 10 tests.

## Findings

### blocking: Preserve order behind previously admitted normal text

[app/tg_bridge.py:1268](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-order/app/tg_bridge.py:1268) — Confidence: 1.0

`ordered=True` places markers in `state.reliable`, while ordinary `_tg_send_safe(..., important=False)` text enters telemetry. `_tg_pick_next` prioritizes reliable items, so an earlier normal text followed by an image produces `IMAGE-MARKER, TEXT-1`; I reproduced this directly. The chronology test uses `important=True` for both texts and therefore misses the production path. Use a shared admission sequence/FIFO barrier across text and marker lanes, and test with non-important text.

---

### blocking: Revalidate delivery state after clearing it

[app/tg_bridge.py:833](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-order/app/tg_bridge.py:833) — Confidence: 0.94

When two submissions encounter the same stale-loop state, both can await `_clear_tg_chat`; after the first installs a replacement, the second unconditionally creates and assigns another state without rereading `_tg_delivery_states`. Both states can then have active dispatchers and distinct `rate_lock` instances for the same chat, breaking the state-identity and atomic-rate-slot ACs. Recheck the registry after the await and preserve any replacement already installed.

---

### suggestion: Keep snapshots alive while an edit is in flight

[app/tg_bridge.py:1628](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-order/app/tg_bridge.py:1628) — Confidence: 0.96

The cleanup callback runs whenever the raw completion future becomes done, including `Future.cancel()`. If a consumer awaiting that future is cancelled after `edit_message_media` starts, cancellation propagates to the future and deletes `owned_path` while the independent image dispatcher may still be opening or uploading it. The dispatcher should own cleanup after it exits, or consumers should receive a cancellation-shielded completion handle.

---

### suggestion: Clean the rendered PNG when marker admission is cancelled

[app/tg_bridge.py:2408](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-order/app/tg_bridge.py:2408) — Confidence: 0.98

This await now lasts through marker admission and delivery. If `stream_logs` is cancelled during that interval, `asyncio.CancelledError` bypasses the existing `except Exception`, leaving the original `diff-*.png` behind; only the internal `tg-image-*` snapshot is cleaned. Transfer ownership explicitly or use `finally`/an explicit cancellation branch.

---

### suggestion: Assert the exact delivery-stats schema

[tests/test_tg_bridge.py:1014](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-order/tests/test_tg_bridge.py:1014) — Confidence: 1.0

The test named “complete” uses a subset assertion, so arbitrary extra or misspelled fields can be added while the exact-schema AC remains green. Assert equality for the complete key set or the complete response object.

## Verdict

**Changes requested — incorrect.** The marker design separates slow edits successfully, but it currently violates chronology for ordinary text and has a state-replacement race that defeats atomic dispatch guarantees.

Right now the marker preserves its place in line by cutting ahead of someone already waiting. Very Telegram of it.

## Round (2026-07-29T05:52:17Z)

## Summary

The marker learned FIFO only after reaching the front of the queue—impressive timing 😏. Four prior findings are resolved; chronology is only partially fixed. I independently confirmed all 109 tests pass in 2.45s, then reproduced two uncovered ordering failures.

## Findings

### blocking: Block later telemetry while a marker remains behind reliable backlog

[app/tg_bridge.py:1068](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-order/app/tg_bridge.py:1068) — Confidence: 1.0

The barrier activates only when the ordered marker is the reliable head. If four reliable calls precede it, later telemetry becomes age-eligible, and fairness dispatches that telemetry after the third reliable call but before the marker. A deterministic `_tg_pick_next` check produced `R1, R2, R3, TEXT-2` with the marker still queued. Suppress post-marker telemetry whenever any earlier ordered marker remains in the reliable queue.

---

### blocking: Include markers waiting for reliable admission in the barrier

[app/tg_bridge.py:1347](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-order/app/tg_bridge.py:1347) — Confidence: 1.0

Cross-marker coalescing checks only markers already appended to `state.reliable`. While a marker is waiting for reliable capacity, a later same-key telemetry submission coalesces into the pre-marker item and retains its earlier sequence; once admitted, that later payload is drained before the marker. I reproduced a waiting marker with the telemetry count becoming `2` under the original pre-marker sequence. Track pending ordered admissions or reserve their barrier before waiting.

## Verdict

**Changes requested.** State replacement, cancellation shielding, both cleanup paths, stats schema, counters, and rate/flood rechecks look correct. The remaining two cases still violate the chronology AC, so approval waits on extending the sequence barrier across the marker’s entire queued/admission lifetime.

Currently FIFO works perfectly once nothing is standing in front of it.

## Round (2026-07-29T06:00:02Z)

## Summary

The barrier now works—until a completed marker keeps clutching its ticket for one extra event-loop turn 😏. Both Round 2 blockers are fixed, and all 111 tests independently pass in 2.01s. One uncovered multiple-marker ordering failure remains.

## Findings

### blocking: Release a completed marker’s barrier before selecting again

[app/tg_bridge.py:1360](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-order/app/tg_bridge.py:1360) — Confidence: 1.0

After marker A completes, `_settle_tg_item` merely schedules its waiting caller; the dispatcher immediately loops before that caller’s `finally` removes A from `ordered_admissions`. With telemetry sequence 3 between completed marker A sequence 2 and queued marker B sequence 4, the stale barrier filters telemetry 3 and prevents B’s preceding-telemetry drain, so B is selected first. I reproduced this directly. Remove an ordered sequence synchronously when its dispatcher item reaches a terminal state, including cancellation; retain caller cleanup for pre-queue admission failures.

## Verdict

**Changes requested.** Round 2’s backlog and pending-admission failures are resolved, and lifecycle, cleanup, counters, rate/flood behavior, and spin prevention look correct. Approval is blocked only by the terminal handoff race between consecutive markers.

The first marker currently returns its queue ticket after the second marker has already walked past the text.

## Round (2026-07-29T06:04:54Z)

## Summary

All prior blockers are resolved; the queue finally behaves like a queue without requiring legal supervision 😏. I independently confirmed all 112 tests pass in 3.04s. One non-blocking cancellation improvement remains.

## Findings

### suggestion: Exclude cancelled queued markers from the barrier

[app/tg_bridge.py:1049](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-order/app/tg_bridge.py:1049) — Confidence: 1.0

`_tg_ordered_sequences` includes queued ordered items whose futures are already cancelled, although the dispatcher will skip them without sending a marker. When such an item sits behind reliable backlog, later telemetry cannot use normal 3:1 fairness until the cancelled item reaches the head; I reproduced `R1, R2, R3, R4` instead of `R1, R2, R3, TEXT`. Ignore cancelled queued items while retaining cancelled in-flight markers, whose Telegram call may already be committed.

## Verdict

**Approved with suggestion.** Round 3’s terminal handoff race is fixed, and pending → queued → in-flight → terminal transitions, coalescing, wait filtering, lifecycle, and existing fairness are otherwise correct under the MVP rubric.

The only leftover is a cancelled customer whose discarded ticket still holds up the line.

## Round (2026-07-29T06:06:34Z)

## Summary

The discarded ticket no longer controls the queue—civilization survives 😏. The Round 4 suggestion is correctly resolved: cancelled queued markers are ignored, while cancelled in-flight markers retain the barrier. All 113 tests pass independently in 2.26s.

## Findings

No blocking, suggestion, or question findings.

## Verdict

**Approved.** Ordering, cancellation lifecycle, coalescing, fairness, cleanup, counters, and pending/queued/in-flight transitions satisfy the stated MVP acceptance criteria.

Five rounds later, the queue has finally stopped inventing new meanings for “next.”
