# Retro — usage-analytics (control-room upgrade)

## Metrics

- Tool calls: more than 50 across a multi-turn implementation; exact count was not retained across upstream interruptions.
- Retries: four Codex follow-up rounds; two hit the 10-minute timeout. Two implementation turns were interrupted by upstream 503s.
- Files: 27 before report/retro (`+4739/−283`).
- Codex: Round 3 **APPROVED** after two P1s and seven P2s were fixed.
- Tests: final `847 passed, 20 skipped`; focused red tests reproduced every late metric finding before its fix.
- User/orchestrator corrections: one — commit completed units more frequently while the upstream was flapping.

## What went wrong (signal → root cause)

- **Signal:** Codex P1 found synchronous telemetry writes could block SQLite for five seconds and abort turn finalization. **Root cause:** the first collector path reused correct storage helpers without preserving the event loop's failure-isolation contract. **Category:** correctness.
- **Signal:** Codex found boundary-day inflation, mutable provider/model attribution, missing structured-only segments, and cumulative task attribution. **Root cause:** the first aggregation mixed retained log parsing with mutable session state instead of defining one immutable event-time turn source. **Category:** correctness.
- **Signal:** Codex Round 2 found a task spanning collector rollout received an exact-looking partial cost. **Root cause:** coverage was modeled for the requested time window but not for each task's lifetime. **Category:** correctness.
- **Signal:** the full suite initially exposed frontend fixture races and live background-job state leaking into session tests. **Root cause:** isolated feature tests had not yet exercised shared global browser/session state. **Category:** process.
- **Signal:** two Codex resumes timed out after rerunning broad tests, including Chromium in an incompatible sandbox. **Root cause:** the first follow-up prompts requested re-review without constraining the reviewer to static inspection of already-supplied green test evidence. **Category:** process.

## What went well (keep doing)

- Codex review caught every material metric defect before handoff; Round 3 confirms all P1/P2 findings are closed.
- TDD regressions reproduced provider switching, structured-only auto-continue, migration, stale requests, and rollout coverage before fixes.
- The final full suite and isolated mobile Playwright check stayed green after the review-driven corrections.
- Small commits preserved every completed correction across transient upstream failures.

## Proposed changes (Tier-2 — NOT applied, awaiting approval)

| Target | Change | Evidence | Status |
|---|---|---|---|
| `codex-debate` skill | On a follow-up after test evidence is supplied, allow an explicit static-only review mode that forbids broad test reruns in a mismatched sandbox. | Two 10-minute review timeouts in this task; n=1 task. | logged, not promoted |

## Written to worker memory (Tier-1 — applied)

- none
