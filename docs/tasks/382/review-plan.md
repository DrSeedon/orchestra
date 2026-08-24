<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

The ticket graph is vertical and acyclic, and all six commands fail with the registered counts for missing behavior:

- T1: 3 failed, 3 passed
- T2: 2 failed, 1 passed
- T3: 3 failed, 1 passed
- T4: 3 failed, 1 passed
- T5: 23 failed, 1 passed
- T6: 3 failed, 2 passed

No collection, import, or provider failure occurred. However, the frozen oracles leave several security-critical acceptance criteria unproven.

## Findings

blocking: [tests/test_t382_completed_log_corridor.py:125](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-secret-mask-escaped/tests/test_t382_completed_log_corridor.py:125) — The completed-log egress test exercises four getters but omits `db.get_history_logs`, despite the plan naming it as part of the canonical boundary. T4 bypasses that getter by supplying fabricated rows directly. A green implementation could therefore leave raw legacy secrets exposed through history imports → add behavioral raw-row coverage through `get_history_logs`.

blocking: [tests/test_t382_completed_log_corridor.py:75](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-secret-mask-escaped/tests/test_t382_completed_log_corridor.py:75) — The parser oracle does not cover unterminated quoted candidates, the fixed candidate-budget boundary, masking through line/end, or bounded state on an actual secret-shaped candidate. It also detects only three fixture fragments and the literal text `tail=`, so an implementation retaining a different suffix could pass while violating “no tail/prefix” → add frozen cases around every candidate-budget boundary and assert the complete replacement form contains only `[secret len=N]`.

blocking: [tests/test_t382_browser_content_epoch.py:232](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-secret-mask-escaped/tests/test_t382_browser_content_epoch.py:232) — The abort-atomicity test is already green before the epoch feature exists. Because current code never calls `clear()`, the injected exception is never required to fire and the unchanged old row/epoch satisfies the assertions vacuously → require positive evidence that the injected abort occurred after entering the epoch transaction, then assert the old pair survived.

blocking: [tests/test_t382_browser_content_epoch.py:276](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-secret-mask-escaped/tests/test_t382_browser_content_epoch.py:276) — Ordering is tested by calling `_storeApplyEpochBatch` directly. This cannot prove that actual sync, REST, and SSE writers are all routed through the barrier; any one of those production paths could continue writing directly and the test would remain green → exercise each real response/event path with delayed epochs, or independently assert and mutation-test their wiring.

blocking: [tests/test_t382_browser_content_epoch.py:186](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-secret-mask-escaped/tests/test_t382_browser_content_epoch.py:186) — Server coverage checks only `/api/logs/sync`. The plan additionally requires the epoch in initial HTML, REST history/full-row fetches, and SSE handshake/events, none of which has an oracle. BroadcastChannel sibling-tab reopening is likewise not observed → add contract tests for every named surface and a two-tab notification/reopen assertion.

blocking: [tests/test_t382_browser_content_epoch.py:68](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-secret-mask-escaped/tests/test_t382_browser_content_epoch.py:68) — The supposedly isolated dashboard copies the entire ambient environment and clears only four variables. The subprocess can inherit live integration credentials/configuration and start real clients during application lifespan, contradicting the synthetic-only and provider-independent requirement → construct a minimal allowlisted environment rather than copying `os.environ`.

blocking: [tests/test_t382_bounded_live_stream.py:92](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-secret-mask-escaped/tests/test_t382_bounded_live_stream.py:92) — The memory oracle measures only replay content length. The latency test publishes 2,000 events to an undrained subscriber queue, but never bounds queue entries or retained bytes; an implementation can replace each chunk with a marker while accumulating an unbounded number of marker records → assert bounded retained state across `_accum`, replay, and subscriber queues.

suggestion: [tests/test_t382_bounded_live_stream.py:119](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-secret-mask-escaped/tests/test_t382_bounded_live_stream.py:119) — T5 asserts output type but not preservation of the supplied IDs/activity metadata, and it never asserts the exact withheld marker promised by the plan. Thus its “ids/type metadata remain intact” and UX criteria are post-implementation inspection requirements rather than executable AC → assert each supplied metadata field and one exact marker value.

suggestion: [tests/test_t382_completed_log_corridor.py:146](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-secret-mask-escaped/tests/test_t382_completed_log_corridor.py:146) — REST/SSE/TG ownership is inferred from getter-name substrings concatenated across multiple function sources. The names can occur in unrelated branches while the relevant response still uses raw SQL or another source → prefer behavioral endpoint/TG tests or per-function call interception.

## Verdict

NEEDS WORK. The RED registration is honest and provider-native rollout is correctly excluded under #31, but the frozen suite does not yet prove several confidentiality and cache-atomicity requirements. Because the oracle bytes may not change, Phase 3 needs an explicitly approved supplemental-oracle strategy before implementation.

## Round (2026-08-23T17:15:40Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

All prior findings are fixed. The six commands reproduce the registered RED counts exactly: T1 5/4, T2 2/1, T3 3/1, T4 3/1, T5 24/1, T6 9/1. Failures are missing-behavior assertions only; no import, collection, credential, or provider failures occurred.

## Findings

- FIXED — `get_history_logs` now receives the raw legacy row and joins all four other getters in the sanitization assertion at [test_t382_completed_log_corridor.py:156](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-secret-mask-escaped/tests/test_t382_completed_log_corridor.py:156).

- FIXED — exact length-only replacement, every four-character canary substring, fixed 65,536-character budget edges, suffix removal, and CPU limits are covered at [test_t382_completed_log_corridor.py:42](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-secret-mask-escaped/tests/test_t382_completed_log_corridor.py:42) and [test_t382_completed_log_corridor.py:98](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-secret-mask-escaped/tests/test_t382_completed_log_corridor.py:98).

- FIXED — T6 abort atomicity now requires the positive `__t382AbortFired` signal before inspecting retained state at [test_t382_browser_content_epoch.py:289](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-secret-mask-escaped/tests/test_t382_browser_content_epoch.py:289). It correctly fails RED because the injected path is not reached.

- FIXED — actual `_storeSync`, `_fetchHistory`, and `connectSSE` paths are intercepted through `_storeApplyEpochBatch` at [test_t382_browser_content_epoch.py:385](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-secret-mask-escaped/tests/test_t382_browser_content_epoch.py:385).

- FIXED — epoch contracts now cover initial HTML, sync JSON, REST history/full-row responses, SSE handshake, and SSE log events at [test_t382_browser_content_epoch.py:202](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-secret-mask-escaped/tests/test_t382_browser_content_epoch.py:202). BroadcastChannel sibling close/reopen is behaviorally checked at [test_t382_browser_content_epoch.py:456](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-secret-mask-escaped/tests/test_t382_browser_content_epoch.py:456).

- FIXED — the dashboard subprocess uses a minimal explicit environment, disables dotenv loading, and does not copy ambient configuration at [test_t382_browser_content_epoch.py:68](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-secret-mask-escaped/tests/test_t382_browser_content_epoch.py:68).

- FIXED — T5 now bounds replay/`_accum`, queue records, and retained content bytes at [test_t382_bounded_live_stream.py:112](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-secret-mask-escaped/tests/test_t382_bounded_live_stream.py:112) and [test_t382_bounded_live_stream.py:127](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-secret-mask-escaped/tests/test_t382_bounded_live_stream.py:127).

- FIXED — exact withheld UX and metadata preservation are asserted for all seven direct and session-wired branches at [test_t382_bounded_live_stream.py:46](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-secret-mask-escaped/tests/test_t382_bounded_live_stream.py:46) and [test_t382_bounded_live_stream.py:157](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-secret-mask-escaped/tests/test_t382_bounded_live_stream.py:157).

- FIXED — REST/SSE/TG ownership now uses behavioral getter interception rather than aggregated source substrings at [test_t382_completed_log_corridor.py:179](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-secret-mask-escaped/tests/test_t382_completed_log_corridor.py:179) and [test_t382_completed_log_corridor.py:217](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-secret-mask-escaped/tests/test_t382_completed_log_corridor.py:217).

No new blocking findings or suggestions.

## Verdict

APPROVED.

Verbatim plan line: “Although T2-T6 are logically independent after T1, their implementation files overlap.”
