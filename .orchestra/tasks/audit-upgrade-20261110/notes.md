# Orchestra audit upgrade, 2026-11-10

Source: owner-approved five-block brief in T3 mcp:a314dbda-73ac-40b3-bd46-d7b2a1d07c31, position 47; continuation after Claude daily limit. Work stays on orchestra-vps. No model calls, paid probes, public publishing or telegram-bot-api restart.

## Findings on takeover
- Existing worktree fix/stream-b-audit-20261110 contains all five blocks except worker-memory-only prompt delta. No audit commits were deployed.
- Historical full run: 8106 passed, 17 failed, 11 skipped, 120 subtests. Source log: /tmp/ceo-audit-20261110/full-suite.log. Nine failures pin old Opus admission or old context windows.
- Other failures: missing worktree .venv, runtime list predating Antigravity, model catalog fixture picks disabled static Heretic by dict order, mocked harness tests do not register their model, catalog flag test lacks upstream fixture.
- Five browser failures were already observed in the starting checkout: provider-column expectations/layout and a source-range localStorage assertion. No UI changes in this package.
- Full-cycle DOES spawn in current manifest (can_spawn nonempty; owner decision 2026-10-16), so model-routing remains necessary there. Audit premise that this role cannot spawn is false; preserve its contract.
- Newly issued global model quota split controls THIS agent execution (Codex only here). This package preserves the approved product model registry and performs no Claude/Hub model calls.

## Final review follow-ups (queued during focused test run)
- Candidate extraction still caps lists at 400 and ban lines at 400 chars, contrary to the requested complete mechanical recall aid. Remove those caps; tool-result numbers also need extraction.
- Add every requested orchestrator-only name, including dormant names absent in current schemas (interrupt_worker, wake_timed_out_worker, wf_create/list/delete).
- Catalog flag fixture needs replace=True after live_harness_route seeded registration; production admission stays unchanged.

Focused R1: 1895 passed, 4 deselected, 3 setup errors (duplicate catalog fixture registration). Both instruction/manifest checks passed. Corrected the fixture in one step; finalized complete candidate extraction and all requested tool names. Full run was briefly launched before a failed edit was noticed and stopped by its exact pytest PID; it is not a validation result. Full non-live/non-browser run follows the corrections.

Full sequential run reached ~65% and reported seven failures after the targeted regression checks passed. Awaiting final traceback section; no deployment until triage.

Full result: 8126 passed, 8 failed, 11 skipped, 266 deselected, 120 subtests in 1087.75 seconds. Failures classified: four old full-prompt assertions after memory-only update; three backup tests spending their module-import job budget while waiting for execution; one nested pytest timeout firing during collection (2-second fixture). Product code was unchanged after the full run. Updated these tests in one fixture/contract correction step and run one bounded follow-up. No second full-suite loop.

Publication guard found two forbidden literals in inherited merge 9e06272db, also present in the existing origin/main head. Values were never printed. Preserved all old local commits on fix/stream-b-audit-20261110; publication branch starts at origin/main and applies the complete accepted tree diff. Redacted the two legacy evidence files, keeping application/tests/pipeline content identical to tested dd9119a16. No force push or disabled hook. The original local history remains available privately; historical public copies require a separate credential/history decision.
