# Retro — codex-orchestration-plugin research

## Metrics

- Tool calls: ~75 across reconnect | Retries: 1 benchmark harness route, 1 review fallback | Turns: 1 logical research turn + reconnect
- Files: 4 documentation artifacts, no production code
- Codex: first review found 2 blocking recommendation flaws; targeted Round 2 `APPROVED`
- Tests: upstream `189/189 OK`; effort benchmark had one `exit 1` and one reconnect-invalidated run
- User corrections this task: 0 content corrections; orchestrator requested immediate commit after reconnect

## What went wrong (signal → root cause)

- **Signal:** first parallel effort harness returned live session IDs, but the orchestration script discarded them; exact completion/output for the early runs was lost and the commands had to be stopped/re-run. **Root cause:** the fan-out assumed `exec_command(yield_time_ms=30000)` would complete rather than returning resumable sessions. **Category:** process.
- **Signal:** benchmark `high` async case exited `1` without preserved raw JSONL, and the `xhigh` path case became unusable after reconnect. **Root cause:** measurement capture stored parsed summaries instead of raw output/session lifecycle before declaring the run usable. Unknown model/runtime failure cause was correctly left unknown. **Category:** process.
- **Signal:** adversarial review found two blockers: Phase-2 hot-add ignored the `exec resume` branch, and “read-only MCP” conflated bridge flags with transport/sandbox guarantees. **Root cause:** the first recommendations followed the fresh-session happy path and attributed a component-specific property to the integration surface. **Category:** correctness.
- **Signal:** fallback GPT-5.5 review consumed `606 s` and 12,575 output tokens. **Root cause:** `high` was used for an open-ended full-report review after the normal MCP review tool disappeared on reconnect. **Category:** process.

## What went well (keep doing)

- The predeclared benchmark rubric prevented failed/high-latency runs from being reinterpreted as quality evidence.
- Fresh adversarial review caught both load-bearing pilot flaws before commit; code verification plus targeted Round 2 closed them with `VERDICT APPROVED`.
- All production mutations stayed out of scope: plugin config was isolated under `/tmp`, disabled after testing, and only docs changed.

## Proposed changes (Tier-2 — NOT applied, awaiting approval)

| Target | Change | Evidence | Status |
| --- | --- | --- | --- |
| none | No fleet-wide process change from one reconnect/task | n=1 measurement-harness failure | logged, not promoted |

## Written to worker memory (Tier-1 — applied)

- none — n=1; retain in this retro until recurrence.
