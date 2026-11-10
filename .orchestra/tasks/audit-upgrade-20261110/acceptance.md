# Orchestra audit upgrade — acceptance

## Scope and authority

Approved by Maxim: five-block Orchestra audit repairs and compaction upgrade; merge to main, push origin and restart orchestra.service on orchestra-vps. The continuation runs on Codex without children or model probes. Source: T3 mcp:a314dbda-73ac-40b3-bd46-d7b2a1d07c31, original brief at position 47, continuation 2026-11-10.

## Implemented

1. Compaction keeps origin/senders, strips static platform prompt re-delivery, retains both ends of long speech, and writes full USER_MESSAGES.md plus complete regex candidates (including measured tool-result numbers). AUDIT and FINAL stay inside the warm Claude session; start_ack_turn stays enabled. Live configuration AGENTIC_COMPACT_ENABLED is true.
2. Claude resume supplies the current appended system prompt. Equivalent system-channel content is not duplicated in user history; only changed temporary rules/personal memory are delivered when static content is unchanged. Identity follows static prompt modules.
3. Six core repairs: full-path reread keys and reset after writes/edits; on-disk torn-JSONL repair; bounded persistence retries retaining dirty state; prompt test selection and one target archive per mutation gate; secret scanning of exactly the bytes archived; cached checkout/secret sources with stat invalidation. Duplicate temp-rule fingerprint definitions removed.
4. Free auto context 131072; Argon and Antigravity Opus long-context routes 1000000; Hub Opus admission and explicit effort policy, current quota hints, specialist data-permission consistency. Existing model admission, provider flags, quota and no-automatic-fallback guards remain tested.
5. Worker schema profile excludes 21 management names. Three prompt modules reduced by 1708 bytes in total (28384 to 26676 bytes), with instruction and manifest contracts preserved.

## Checked discrepancy in the original brief

The running full-cycle role has can_spawn=[worker, full-cycle, reducer, specialist], explicitly documented in the manifest and covered by role tests. It needs model-routing to dispatch correctly, so that module is retained. Its spawning authority was not changed.

## Verification

- Imported app: /home/kesha/orchestra/worktrees/stream-b-audit-20261110/app/__init__.py.
- Focused R1: 1895 passed, 4 deselected, 3 catalog-fixture setup errors. Fixed duplicate registration in that fixture without changing production admission.
- Final targeted regression run: 58 passed in 9.56 s.
- Instruction contract and pipeline manifest checks: passed.
- Full run: 8126 passed, 8 failed, 11 skipped, 266 deselected, 120 subtests in 1087.75 s. Four failures pinned the superseded full-prompt replay, three backup fixtures inherited an expired module-import budget, one nested pytest fixture timed out during collection. These test contracts/fixtures were corrected without changing product code.
- Follow-up: 267 passed in 32.55 s, including all eight failed cases, prompt delivery, all new regressions and instruction contracts. No full-suite rerun after these test-only corrections. Final instruction and manifest checks passed again. Commands/output: verify.py, full-results.json/full-1.log and followup-results.json/followup-1.log in the VPS worktree task directory.
- Test and production Python environments have identical claude-agent-sdk 0.2.164, FastAPI 0.136.3, Pydantic 2.13.4, HTTPX 0.28.1 and pytest 9.0.3. No dependency installation or paid API/model calls.

## Known verification limits

Five historical browser failures were observed before continuation: three quota-strip tests involving the Antigravity column and two frontend source-range assertions involving the answers-only preference. Browser and live-provider checks are excluded from this backend/prompt package; UI files were not changed. Historical evidence: /tmp/ceo-audit-20261110/full-suite.log and original T3 activity positions 408–418.

## Deployment

Code verification complete. Publication initially blocked by two forbidden literals in legacy evidence already present in origin/main. They were redacted from current files. Publication is reconstructed from origin/main without the unsafe inherited merge; all original local commits are preserved privately, and application/test/pipeline content is identical to tested dd9119a16. No force push or gate bypass. Old public Git history still contains those literals; no credential rotation/history rewrite was performed. Authorized push/restart follows. Unrelated uncommitted video-artifact changes in the production checkout must remain untouched. telegram-bot-api must retain its original PID and start time. Runtime evidence will be recorded separately in deployment.json.
