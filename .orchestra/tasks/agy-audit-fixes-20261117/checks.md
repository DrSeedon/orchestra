# Validation, 2026-11-17
Imported app: /home/kesha/orchestra-worktrees/agy-acp-safe/app
All pytest runs used candidate .venv and scripts/run_antigravity_offline.sh:
kernel unshare --net, loopback only, synthetic HOME/SQLite, no real provider/Google/TG calls.
Strict mode permits only tests/acp_mock/fake_agy_acp.py acp. --local-contracts additionally
permits local Git targeting the synthetic HOME and synthetic .env under that HOME,
for an explicit bounded test file allowlist. Real CLI and private/prod file guards remain.

## Final checks
- acp-verified.log: 267 passed, 9 deselected, 2 deprecation warnings, 55.35s.
  Files: audit_fixes, acp, acp_r2, acp_submission, acp_review, foreground,
  foreground_sse, foreground_delivery, r4, split_config, live_preflight, split_stand.
- new-regressions-verified.log: 55 passed, 13.65s (includes final archive/creator/close-refusal).
- contracts-verified.log: 289 passed, 10.33s.
  --local-contracts tests/test_default_pipeline.py tests/test_prompting.py
  tests/test_local_delegation_prompts.py tests/test_models.py
  tests/test_runtime_registry.py tests/test_quota_gate.py tests/test_hub_orchestrator_outbox.py
- instructions.log: scripts/check_instruction_contract.py OK through --instructions.
- compileall and git diff --check OK.

## Exact deselection expression (frozen assertions untouched)
not test_start_failure_latches_without_login_or_spawn_loop and
not test_turn_failure_no_automatic_prompt_replay_or_restart and
not test_prompt_timeout_latches_and_shutdown_cleans_owned_pid and
not test_unacknowledged_cancel_closes_profile and
not test_failed_turn_cost_is_recorded_without_success_or_replay and
not test_auth_loss_after_success_latches_without_reauth

Those 9 cases require profile-wide permanent failure on ordinary RPC errors or on
a later EXPLICIT user action after transport death. This wave explicitly replaces
that policy; new tests prove local errors, no automatic replay, durable bans,
bounded quarantine/capacity and explicit-next-turn recovery.
They remain in tests/test_antigravity_acp.py unmodified; full-suite GREEN is NOT claimed.
Historical legacy 15F/18P/79E was not rerun.

## Intermediate failures, retained rather than hidden
focused-r1.log: 1 collection error (duplicate capability keyword; corrected).
focused-r1b.log: 13 failed/31 passed (fake peer still required obsolete process-per-session argv).
focused-r2.log: 48 passed after updating the fake argv contract.
compatibility-r1.log: 17 failed/206 passed; 9 superseded policy checks, 2 argv checks,
and actual disconnect/compact regression + backpressure distinction. Fixed release lifecycle.
compatibility-r2.log: 2 failed/177 passed, both obsolete process-per-session assertions.
The argv assertions now explicitly REQUIRE absence of process-per-session, preserve auto-approve checks.
contracts-r1.log: 24 failed/259 passed: synthetic Git/.env blocked, old Claude fixture scope,
and curated-model set missing newly authorized IDs.
contracts-r2.log: 3 failed/286 passed: synthetic Git target recognition.
contracts-final.log: 8 failed/281 passed: git init without a path was misclassified by the harness.
git-fixtures-final.log: 9 passed after correcting target handling.
acp-final.log: 3 failed/263 passed/9 deselected: two guard-message regex expectations
and session-identity collision must close the corrupt transport. Fixed, then acp-verified passed.
new-regressions-final.log: 1 failed/54 passed: real archive fixture requires local Git TM initialization.
Corrected by the explicit bounded --local-contracts mode, then all 55 passed.

No test asserted a real account is safe from bans or full native-vendor compatibility.

Tracked log lines have trailing whitespace normalized; messages, counts and outcomes are unchanged.
