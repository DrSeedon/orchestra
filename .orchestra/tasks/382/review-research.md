<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

The escaped-key root-cause analysis is well supported by the named code: `_tool_arguments_json()` serializes an inner JSON string, `_tool_use()` reserializes the outer object, and `_NAMED.gap` cannot consume the resulting `\":` key terminator.

The research is not ready for approval because its proposed oracles leave a streamed-secret case uncovered, and the IndexedDB epoch protocol lacks stale-response ordering protection. The persistence inventory is useful but broader than the RED coverage derived from it.

## Findings

1. `blocking: docs/tasks/382/research.md:394 — O3 tests complete producer-shaped payloads but not secrets divided across stream chunks. app/live_broker.py:50-58 masks each payload before concatenating it into _accum, so a key/value split between two publish() calls bypasses masking in both the immediate queue and replay buffer. The document acknowledges this at research.md:514 as a “known limitation,” but the acceptance rule says no streamed copy may expose the canary. Add a split-boundary RED oracle and define a stateful buffering/redaction boundary, or explicitly narrow the blocking acceptance rule.`

2. `blocking: docs/tasks/382/research.md:317 — LOG_CONTENT_EPOCH is called monotonic, but the protocol only specifies action “on mismatch.” Concurrent requests can complete out of order: after epoch N+1 clears the mirror, a delayed epoch-N response can mismatch, roll stored metadata back to N, and repopulate stale rows. Atomic clear+epoch update does not prevent this ordering failure. Require rejection of response epochs lower than the highest observed epoch, serialize epoch transitions and row writes behind one barrier, and add an O7 case where an old response completes after the N+1 clear.`

3. `blocking: docs/tasks/382/research.md:394 — O3 does not cover every live event branch named in F4. app/session.py:1937-1992 publishes stream, subagent_stream, thinking_stream, tool_stream, tool_patch, turn_diff, and subagent_event, while O3 names only tool_stream, subagent_event, and stream. Because blocking includes any streamed raw canary, either mechanically prove the omitted types share an invariant exercised below their branching point or add coverage for every branch capable of carrying arbitrary content.`

4. `blocking: docs/tasks/382/research.md:364 — The RED suite does not close the document’s own persistence inventory under its stated global confidentiality rule. initial_deliveries.message is deferred to a later decision, while sessions.last_summary, RAG log_chunks/fts_logs, and persistent runtime_handoffs.packet_json lack direct raw-storage oracles. A canary repeated into user/text/summary content can therefore remain in an Orchestra-created persistent copy while O1–O8 pass. Classify each as in-scope or explicitly outside the acceptance rule; every in-scope sink needs direct-storage mutation coverage.`

5. `suggestion: docs/tasks/382/research.md:416 — O5 says removing egress masking from “each branch” must independently fail, but it does not select the ownership seam. If masking is centralized in db.py getters, REST/SSE/TG branch mutations may remain green because another layer still masks them; if duplicated per consumer, the design violates the proposed canonical ownership. Specify one canonical egress boundary and test consumers as wiring tests, while mutation-testing the canonical boundary itself.`

6. `suggestion: docs/tasks/382/research.md:347 — The first-rollout procedure depends on every pre-feature tab being closed, but O7 only models new-code tabs. Add an explicit acceptance check for the operational gate or state plainly that same-version code cannot mechanically erase or make unreachable copies retained by an old page. Otherwise “cannot be recovered from a stale browser IndexedDB mirror” is stronger than the proposed implementation guarantee.`

## Verdict

NEEDS WORK — 4 blocking security/oracle gaps. The serializer-to-`_NAMED` root cause itself is confirmed, but the streaming and cache-epoch guarantees are incomplete.

## Round (2026-08-23T16:40:49Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

All four prior blockers are closed. Both suggestions were addressed without introducing a new blocking contradiction.

## Findings

1. `FIXED (prior blocking 1): docs/tasks/382/research.md:420 — O3 now tests split boundaries across multiple publish() calls and requires buffering to logical completion or withholding partial content. This directly covers app/live_broker.py:50-58, where masking currently occurs before chunk concatenation.`

2. `FIXED (prior blocking 2): docs/tasks/382/research.md:329-350 — The epoch protocol now rejects R < H, atomically clears on R > H, and serializes all row writers. O7 includes a delayed epoch-N response released after N+1 and interleavings among _storeSync, _storePut, and SSE. This covers the writers at app/static/js/app.js:617-688 and 2298-2305.`

3. `FIXED (prior blocking 3): docs/tasks/382/research.md:423-438 — O3 enumerates all seven arbitrary-content branches: stream, subagent_stream, thinking_stream, tool_stream, tool_patch, turn_diff, and subagent_event. Per-branch wiring mutations ensure none bypasses the shared invariant in app/session.py:1937-1992.`

4. `FIXED (prior blocking 4): docs/tasks/382/research.md:476-493 — O6b adds direct-storage assertions and independent mutations for initial_deliveries.message, sessions.last_summary, RAG log_chunks/fts_logs, and runtime_handoffs.packet_json.`

5. `FIXED (prior suggestion 1): docs/tasks/382/research.md:450-464 — O5 names one db.py row-sanitization helper as the canonical egress boundary and correctly treats REST/SSE/TG checks as wiring tests rather than duplicate masking implementations.`

6. `FIXED (prior suggestion 2): docs/tasks/382/research.md:358-380 — The document now states that old-page copies cannot be mechanically invalidated, requires operator-confirmed closure as a rollout precondition, and leaves the guarantee UNCERTAIN when that evidence is absent.`

## Verdict

APPROVED

Verbatim evidence from the revised target:

> A fixed-size suffix buffer is not sufficient for the unbounded grammar.
