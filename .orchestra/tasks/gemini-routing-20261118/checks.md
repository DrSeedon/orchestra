# Gemini g1-pro routing/admission
Imported app: /home/kesha/orchestra-worktrees/gemini-routing-20261118/app

Verified: contracts-verified.log — 456 passed in 11.16s.
Files: test_gemini_g1_routing.py, test_default_pipeline.py, test_prompting.py,
test_local_delegation_prompts.py, test_models.py, test_runtime_registry.py,
test_quota_gate.py, test_pipeline.py.
Instruction contract PASS (instructions.log). Syntax/diff/secret-pattern checks PASS.
Tests ran with candidate .venv via scripts/run_antigravity_offline.sh --local-contracts:
synthetic HOME/DB, kernel loopback-only network namespace, real provider launch denied.
Only fake ACP and bounded synthetic local Git were admitted; Google/OAuth/quota/model traffic=0.

New cases cover exact 11-ID defaults + hard native subscription exception, all seven aliases,
non-listed local IDs denied even with stored true, stale stored false preserved until explicit
owner flag update (other flags untouched), disabled-provider precedence, local Claude 5.5 scope
ban, scheduled wake rejection, and actual MCP spawn entrypoints with real request schema +
canonical server admission before mocked initial delivery. No claim of real generation tests.

A focused synthetic case first demonstrated the fixed g1-pro ID turning into nonexistent
-high from generic role fallback (fixed-model-before.log: 1 failed).
Exact fixed-ID handling now ignores only GENERIC role fallback, retaining explicit scalar/
model-specific effort and backend model ACK/refusal behavior. Subsequent fake stdio prompt passed.

Intermediate fixtures: focused-r1.log 68 passed / 3 failed (nonexistent synthetic cwd);
contracts-r1.log 453 passed / 3 failed (mock delivery receipt did not match generated ID).
Corrected fixtures without weakening application or frozen safety assertions; final 456 passed.

Passport distinguishes VPS execution/history from remote Google inference, 1M context from the
1 MiB ACP frame limit, shared Gemini quota from Codex, one-shot events from forbidden cron/
timers/polling, suggested 1–2 workers from shared Semaphore(3), and Hub-admitted projects from
Hub-prohibited scopes. Local Carbon/legacy IDs are explicitly not usable agent routes.
