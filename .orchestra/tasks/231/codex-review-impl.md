## Summary

The implementation has several at-least-once delivery races that can duplicate work, plus two paths that can permanently suppress required delivery. The current tests cover sequential success/failure but not concurrent drains, ambiguous send outcomes, or the silent auto-report reducer path.

## Findings

1. **blocking: Concurrent mailbox drains can deliver the same rows multiple times.**  
   Evidence: `queued = mailbox.pending(s.name, s.scope)` reads without claiming or leasing rows, and later `mailbox.mark_delivered([m["id"] for m in queued])` updates them in a separate transaction. Two turn endings or processes can select the same pending IDs, both call `send()`, then both mark them delivered. WAL and one SQLite writer serialize the marks, but not the preceding reads or external sends. The drain needs an atomic claim/lease keyed to a delivery attempt, or a per-recipient cross-process lock.

2. **blocking: A crash or ambiguous exception after the external send duplicates the entire batch.**  
   Evidence: `await s.send(text)` occurs before any durable delivery record. If the backend accepts the continuation and the process dies before `mark_delivered`, or `send()` raises after acceptance, every row remains pending and the complete concatenated batch is replayed. Because multiple mailbox rows become one non-idempotent send, the system cannot identify partial acceptance. This requires an idempotency key/durable outbox handshake or explicit acceptance of at-least-once semantics with downstream deduplication.

3. **blocking: Failed mailbox injection can strand the mailbox indefinitely and skip hibernation.**  
   Evidence: the exception path ends with `return` after logging: `s._log("error", f"mailbox: выдача не удалась, {len(queued)} остались "`. The caller already returned before auto-report, pending-message flushing, and hibernation, while `wake=False` deliberately supplies no future wakeup. Unless unrelated work arrives, there is no next turn end to retry the retained rows; the session may also remain unscheduled for hibernation. Failure must schedule a bounded retry or restore the normal idle tail, including hibernation.

4. **blocking: The silent auto-report path can release a fan despite a concurrent mailbox enqueue.**  
   Evidence: `if fan_barrier.record_terminal(s.name, "done"):` does not pass `require_drained_scope`. The preceding `mailbox.pending()` check is in another transaction, so a `wake=False` enqueue between that check and `record_terminal()` allows the child to become terminal with unread work. The explicit-report path closes this race, but the silent path does not. Pass `require_drained_scope=s.scope` here as well.

5. **blocking: Silent child completion still wakes the parent instead of the configured reducer.**  
   Evidence: the auto-report release branch uses `target = fan_barrier.parent_of(fan_id) if fan_id else None`. Reducer routing was added only to the explicit `send_message` route. A child that finishes silently therefore bypasses the reducer and wakes the expensive parent, violating T6 and producing different behavior based solely on whether the child explicitly reports.

6. **blocking: `claim_summary` can permanently lose the manifest when delivery fails.**  
   Evidence: `UPDATE fan_barriers SET summarised = 1 WHERE fan_id = ?` commits inside `claim_summary()` before the route executes `await manager.send(session.id, body)`. Any exception, cancellation, process crash, or ambiguous send outcome after the claim leaves `summarised=1`; later reducer messages will never attach that manifest. Claiming and successful delivery cannot be made atomic across SQLite and the session backend, so this needs a claim/ack state with retry and idempotency rather than a permanent boolean set on read.

7. **suggestion: Validate fan deadlines as finite and positive.**  
   Evidence: `deadline_seconds: float | None = None` accepts caller-controlled values without bounds. Zero or negative values create immediately expired fans, while non-finite values such as NaN can produce a barrier that never satisfies `deadline_at <= ?`. Use a constrained finite positive float and define a reasonable maximum.

## Verdict

**Changes requested.** The mailbox currently provides neither exactly-once delivery nor safe retry behavior, and both the silent completion path and `claim_summary` contain concrete message-loss/routing defects. These are blocking for shared runtime deployment.

## Round (2026-08-12T14:50:08Z)

## Round 2

## Findings

1. **STILL BROKEN — blocking: failed or cancelled delivery can still strand messages indefinitely.**  
   Evidence: after failure, the code calls `self._idle_tail(live_pct, allow_auto_report=allow_auto_report)`. That tail only auto-reports, flushes in-memory messages, or schedules hibernation; it never retries/reclaims the mailbox. Although `release_claim(ids)` makes rows eligible immediately, nothing initiates another drain because `wake=False` creates no future wake. Cancellation is worse: `except Exception as exc:` does not catch `asyncio.CancelledError` on Python 3.12, leaving the lease held; after 300 seconds it becomes eligible, but lease expiry itself schedules no drain. Add a bounded retry/wakeup mechanism rather than relying on a future turn.

2. **NEW BUG — suggestion: the lease lacks ownership, so an expired attempt can release a newer claimant’s lease.**  
   Evidence: `f"UPDATE mailbox SET claimed_at = NULL WHERE id IN ({placeholders})"` clears claims solely by row ID. If attempt A exceeds 300 seconds, B reclaims the rows, then A fails, A’s `release_claim()` clears B’s active lease and permits attempt C to deliver concurrently. Return a claim token/generation and require it in both `release_claim` and `mark_delivered`.

3. **NEW BUG — suggestion: concurrent reducer messages can both attach the same manifest.**  
   Evidence: `reducer_fan = fan_barrier.peek_summary(req.sender, req.scope)` is a pure read followed by an awaited external send before `mark_summarised`. Two requests can both observe `summarised = 0`, both send the manifest, then both mark it. This matches the accepted at-least-once preference, so it is not message loss, but it defeats the stated exactly-once attachment during normal concurrency. Use a claim/lease analogous to the mailbox, with acknowledgement after send.

4. **NEW BUG — suggestion: the broad claim exception converts persistent mailbox defects into ordinary idle behavior without arranging recovery.**  
   Evidence: `except Exception as exc:` catches programming errors and persistent schema/query failures as well as the intended missing-table test fixture. Every affected turn can auto-report/hibernate while durable messages remain untouched. Catch the expected SQLite missing-table condition specifically; unexpected exceptions should fail loudly or schedule an explicit recovery path.

### Re-review status

- F1 concurrent drains: **FIXED for claims completing within the lease**, subject to finding 2.
- F2 crash after send: **ACCEPTED as an explicit at-least-once contract.** The lease does not bound replay count across repeated crashes and duplicated prompts may repeat agent side effects, not merely token spend. However, without backend idempotency, eliminating that risk would require a durable delivery ID plus consumer-side deduplication/state-machine support. Given the stated preference for visible duplication over silent loss, this is a defensible tradeoff rather than a blocker.
- F3 failed injection/idle lifecycle: **STILL BROKEN**; normal idle-tail execution does not schedule mailbox retry.
- F4 silent release with pending mailbox: **FIXED**.
- F5 silent completion routing: **FIXED**.
- F6 manifest lost before delivery: **FIXED for failure-before-success**, with the concurrency duplication in finding 3.
- F7 deadline validation: **FIXED**.

The extracted `_idle_tail()` is not called twice on the inspected paths, and `fire_auto_report()` is likewise invoked once per path. The named regression suite completed successfully.

## Verdict

**Changes requested.** The remaining blocker is recovery after failed, cancelled, or interrupted mailbox delivery: reclaimability alone is insufficient when no event triggers the next claim. The ownership and reducer races are real improvements but non-blocking under the explicitly accepted at-least-once model.

## Round (2026-08-12T14:56:26Z)

## Round 3

## Findings

1. **STILL BROKEN — blocking: unknown or unloaded recipients are still queued, contrary to the stated fix.**  
   Evidence: `if target is None or busy:` sends both busy recipients and `target is None` recipients into the mailbox. An unloaded recipient may never have another turn end, so its message can remain indefinitely. The condition should enqueue only when `busy`; `target is None` must fall through to ordinary waking delivery.

2. **STILL BROKEN — blocking: interruption after claiming still provides no recovery trigger.**  
   Evidence: `_deliver_mailbox` catches only `except Exception as exc:`. On Python 3.12, task cancellation raises `asyncio.CancelledError`, which is outside `Exception`; therefore cancellation or process termination after the claim skips release and escalation. The lease eventually expires, but expiry does not initiate another claim. The busy gate does not close this path because the message was legitimately queued while busy. Recovery needs cancellation handling where possible and, for process death, a startup/lease-expiry drain or wake mechanism.

### Re-review status

- F3: **STILL BROKEN** for unloaded recipients and interrupted claimed deliveries.
- Busy-check race: no intra-process check→enqueue race; there is no `await` between the status read and synchronous enqueue.
- Escalation ambiguity: duplicate delivery remains possible if continuation succeeds then raises, but that is covered by the accepted at-least-once contract.
- `claimed_at` after escalation: it remains set, but `delivered_at` excludes the row from subsequent claims, so this is not a functional defect.
- Prior lease-ownership, reducer concurrency, and broad claim exception findings: unchanged non-blocking decisions.

## Verdict

**Changes requested: F3 remains open because unloaded recipients are queued and cancelled/crashed claims have no event that triggers recovery.**
