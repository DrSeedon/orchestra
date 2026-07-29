## Summary

Naturally, the “tiny placeholder” contains the largest reliability trap. 🙃

Claim (1) holds, and reserving capacity before creating the placeholder in claim (3) is correct. Claim (2) is the simplest successful-path design, but it does not provide the document’s absolute guarantee under ambiguous placeholder delivery. No materially simpler compliant alternative was found.

## Findings

### blocking: Reliable placeholder delivery is not exactly-once

The design calls the placeholder a normal reliable send and assumes one returned `message_id` ([research.md:176](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-order/docs/tasks/100/research.md:176)). However, reliable sends retry ambiguous network errors ([tg_bridge.py:866](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-order/app/tg_bridge.py:866)), as explicitly verified by [test_tg_bridge.py:884](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-order/tests/test_tg_bridge.py:884). If Telegram accepts the first attempt but its response is lost, the retry creates another placeholder; only the returned one can be edited, leaving an orphan marker. If every response is lost, a placeholder may exist with no known ID. Therefore the exact final history guarantee is impossible under ambiguous delivery. Either scope the AC to acknowledged successful sends or specify this degradation explicitly.

### suggestion: Keep the image worker inside the shared rate authority

The instruction that media edits must never use the shared rate path or update `_tg_flood_until` ([research.md:171](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-order/docs/tasks/100/research.md:171)) confuses execution isolation with Telegram rate isolation. Current traffic shares `_tg_last_send` and `_tg_flood_until` ([tg_bridge.py:782](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-order/app/tg_bridge.py:782)), and tests deliberately enforce one per-chat rate authority ([test_tg_bridge.py:1321](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-order/tests/test_tg_bridge.py:1321)). A concurrent edit can receive or induce 429, after which an unaware text send immediately hits the same flood window and stalls on its own retry. Isolate upload execution, but retain shared rate admission and propagate `retry_after`; define “non-blocking” as not awaiting the upload, not immunity from Telegram throttling.

### suggestion: Snapshot Read-image files before asynchronous editing

Read-image delivery currently passes the original path ([tg_bridge.py:2419](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-order/app/tg_bridge.py:2419)), while `FSInputFile` is created only when the eventual request starts ([tg_bridge.py:1376](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-order/app/tg_bridge.py:1376)). With an isolated queued editor, the agent can overwrite or delete that file after placeholder acceptance but before upload, producing the wrong image or a permanent marker. The reservation lifecycle should own an immutable temporary copy for Read images, just as generated PNGs own their temporary file.

### suggestion: Make reset cleanup state-identity safe

The research requires cancellation and reservation release during reset ([research.md:239](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-order/docs/tasks/100/research.md:239)), but a worker keyed only by `chat_id` can finish after a new state has been created and decrement or unregister the replacement worker. The existing dispatcher avoids this by comparing both task and state identity before removing ownership ([tg_bridge.py:1054](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-order/app/tg_bridge.py:1054)). Require the image worker and its completion callbacks to mutate their captured state and unregister only on identity match; add a reset-then-immediate-resubmit test.

## Verdict

The architecture is viable and remains the simplest evaluated approach, but the research conclusion is overstated as written. Claim (2) is valid only for cleanly acknowledged placeholder delivery; strict final history cannot be guaranteed across ambiguous network outcomes. Claims (1) and (3) survive review.

Verification: five targeted existing queue/image/retry tests passed. No files were edited.

Telegram has managed to turn one loading marker into a distributed-delivery contract—very economical of it. 📬

## Round (2026-07-29T05:06:50Z)

Один ACK починили, зато документация решила поспорить сама с собой. 🙃

## Round 2

### Re-review status

- **RESOLVED** — ambiguous marker delivery is scoped correctly, uses one attempt, and documents the unavoidable unknown marker.
- **RESOLVED** — image and text workers share an atomic rate-slot gate and `_tg_flood_until`.
- **RESOLVED** — Read images require immutable bridge-owned snapshots.
- **RESOLVED** — cleanup requires matching state/task identity and reset-resubmit coverage.

### New findings

- **NEW BUG (suggestion):** The opening outcome still promises unconditional final history ([research.md:11](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-order/docs/tasks/100/research.md:11)), contradicting the acknowledged-delivery scope elsewhere. Qualify this sentence too.
- **NEW BUG (suggestion):** The plan attaches temporary-file cleanup to edit completion ([plan.md:66](/mnt/data/Projects/Python/orchestra/worktrees/mnt-data-projects-python-orchestra/fix-tg-order/docs/tasks/100/plan.md:66)), but marker failure creates no edit. Require immediate PNG/Read-snapshot cleanup on marker failure, overload, or stopped state; otherwise repeated failures can leak files after reservations are released.

### Verdict

**APPROVED.** No blocking research issue remains. The two documentation gaps should be corrected before implementation, but the selected architecture and load-bearing conclusions now hold.

Telegram ordering is settled; only the cleanup crew and the headline missed the memo. 📬
