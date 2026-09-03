<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Summary

The two-ticket split and production symbol references are valid. Both named commands reproduce the frozen baseline:

- T1: `7 failed, 7 passed, 313 deselected`
- T2: `4 failed, 171 deselected`

No positive missing-behavior oracle is already green; T1’s seven passing cases are intentional negative controls. The frozen oracle files are byte-identical to commit `ecd19610f67bcac4b35a0e79fb50b58dd141ca0d`.

Evidence that I read the plan: “Existing sessions/jobs/log rows remain valid.”

## Findings

blocking: [tests/test_backend_codex.py:1961](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-deferred-turn-spoof/tests/test_backend_codex.py:1961) — both failure-path tests replace `CodexBackend.disconnect` with an `AsyncMock`, so they cannot prove the critical claim that the real `disconnect()` does not issue a second `turn/interrupt`; `_request.await_count == 1` only covers code before the mocked boundary → add a frozen oracle that exercises the real `disconnect()` with a harmless mocked process/teardown seam and verifies one interrupt total, or narrow the AC instead of claiming this invariant is frozen.

blocking: [tests/test_backend_codex.py:1827](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-deferred-turn-spoof/tests/test_backend_codex.py:1827) — the authorization predicate is underspecified by the immutable negatives: there is no case for wrong/missing `threadId` or `turnId`, wrong tool name, `structuredContent.error`, mismatched `event_id`, wrong fixed values, or extra provenance keys. An implementation accepting those cases could satisfy the frozen suite while violating plan lines 56–64 → freeze explicit negative controls for every authorization-bound field before Phase 3.

blocking: [tests/test_backend_codex.py:1758](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-deferred-turn-spoof/tests/test_backend_codex.py:1758) — the quarantine oracle contains only same-turn assistant delta/final events. It never injects another-turn assistant output or non-assistant telemetry while pending, so a global assistant filter—or broader event suppression—can pass despite plan lines 76–78 requiring only same-turn assistant messages to be hidden → add cross-turn assistant and thinking/tool/warning controls to the frozen oracle.

blocking: [tests/test_bg_jobs.py:1135](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-deferred-turn-spoof/tests/test_bg_jobs.py:1135) — T2 exercises only an idle session. It does not freeze the stated running/compacting queue contract: provenance must be logged once before queuing, the queue must retain only text, provider submission must not create another history row, and `event_id` must remain in history/sync → add at least a running-state queued-delivery oracle before implementation.

## Verdict

NEEDS WORK.

The architecture and scope boundaries are sound—structured provenance is not text-derived, usage remains native, `logs.event_id` is reused without exactly-once claims, the prompt is base-owned, and DB/frontend/native-history expansion is explicitly excluded. However, four high-risk invariants claimed by the plan are not protected by the immutable RED suite, so Phase 3 should not begin with the current freeze.

## Round (2026-08-23T19:34:42Z)

<!-- codex-review-metadata: {"reviewer_model": "gpt-5.6-sol"} -->

## Re-review status

- F1 — FIXED. [tests/test_backend_codex.py:2081](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-deferred-turn-spoof/tests/test_backend_codex.py:2081) retains real `CodexBackend.disconnect()`, mocks only `_disconnect_direct` and `_finalize_disconnect`, and asserts one total `_request` call.
- F2 — FIXED. [tests/test_backend_codex.py:1963](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-deferred-turn-spoof/tests/test_backend_codex.py:1963) covers missing/wrong thread and turn IDs, wrong tool, structured error, mismatched event ID, wrong fixed values, and extra keys. Earlier server/text/item-error controls remain.
- F3 — FIXED. [tests/test_backend_codex.py:1784](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-deferred-turn-spoof/tests/test_backend_codex.py:1784) requires other-turn assistant output and same-turn reasoning, warning, and tool results to remain visible while same-turn assistant output is quarantined.
- F4 — FIXED. [tests/test_bg_jobs.py:1249](/home/kesha/orchestra/worktrees/home-kesha-orchestra/fix-deferred-turn-spoof/tests/test_bg_jobs.py:1249) covers RUNNING delivery, one provenanced history/sync row, text-only queuing, one later backend submission, and no duplicate user row.
- All five frozen oracle files are byte-identical to `f6460dcf7db8038debf842d15a767c3c27099ade`; the bounded uncommitted diff is empty.
- RED baselines reproduced:
  - T1: `7 failed, 18 passed, 313 deselected`
  - T2: `5 failed, 171 deselected`

The failures correspond to absent production behavior; the new authorization and visibility controls pass as intended.

Evidence from the revised plan: “The artifact changed, so one evidence-backed follow-up review of the same session is permitted.”

## New findings

None.

## Verdict

APPROVED.
