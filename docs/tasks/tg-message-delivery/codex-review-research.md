# Codex second opinion — research

**Reviewer:** GPT-5.5 via isolated read-only `codex exec` because the `codex_review` MCP method was unavailable in this worker session.  
**Target:** `docs/tasks/tg-message-delivery/research.md` plus `app/tg_bridge.py` and `tests/test_tg_bridge.py`.  
**Verdict:** core mechanics confirmed; implementation blocked until limiter scope and starvation policy were made explicit.

## Findings

- **blocking:** Locking only `_tg_send_safe()` would leave `_send_expandable`, photos, edits, files, topic status, and mirrors outside control. Either route message-producing calls through a shared per-chat limiter now or narrow the claimed fix.
- **blocking:** The 1-second lock-free race is real and sufficient to violate the documented group limit, but Telegram does not fully document every shared flood bucket. Do not claim it exactly explains every 429 or that `GetUpdates` necessarily shares the same bucket.
- **blocking:** `_tg_send_safe()` returning `None` does make the caller's Bot API fallback unreachable. Clarify that the fallback still works when `md_convert()` itself raises.
- **blocking:** `send_message` pretty formatting has a separate entity-range bug: it splits converted text but applies the full-message entity list to chunk 1. Recompute entities or send split chunks plain.
- **question:** Holding a lock through a 40-second retry prevents a stampede but may starve other topics. Specify priority/drop/backlog behavior and accept the tradeoff explicitly.
- **suggestion:** Treat timeout retry as an at-least-once policy and log it as ambiguous because Telegram exposes no `sendMessage` idempotency key.
- **suggestion:** The exact 3720→5262 row is strong live evidence together with the code path, but it is not stored in repository fixtures yet; add a deterministic regression test.

## Resolution

- **ACK:** implementation scope now covers all primary-group message-producing calls through a per-chat limiter; mirrors use separate per-chat state.
- **ACK:** research wording now calls the limiter defect sufficient and likely major, not an exhaustive explanation of every internal flood bucket.
- **ACK:** the `md_convert()` fallback qualification was corrected.
- **ACK:** the implementation plan will make multi-chunk formatted messages plain, so entities cannot cross chunk boundaries.
- **ACK:** important sends wait in per-stream SQLite order; non-important traffic drops before queueing; no extra unbounded queue is introduced. Cross-topic fairness after long flood waits remains an accepted MVP risk.
- **ACK:** ambiguous network retries will be bounded and explicitly logged.

## Final verdict

No research conclusion was falsified. The tightened scope is suitable for planning and implementation.
