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

## Owner scope update and complete worker delivery
The owner's later explicit approval adds six OUR Antigravity Claude 5.5 IDs (17 total).
Only those six bypass the project Claude restriction; direct Anthropic/Hub-Claude remain
Multicast-only. Their scarce third bucket is reserved for rare difficult escalation, not routine.
Quotas, concurrency, no-credit settings and scheduled-wake restrictions are unchanged.
expanded-contracts.log: 484 passed, 2 dependency deprecation warnings, 13.09s.
expanded-instructions.log: instruction contract PASS.

A deeper end-to-end check found initial worker tasks still rejected by the interactive-input
guard (parent-delivery-before.log). Idle-only deployment attempt 1 was deliberately stopped
before merge/restart; its busy observations are deployment-attempt1.json.
Added only a durable direct-parent/receipt event admission branch; native initial HTTP ingress
requires the actual parent's MCP proof. Other providers' ingress is unchanged.
parent-delivery-after/diagnostic failures were caused by converting an orchestrator fixture:
save_session intentionally does not rewrite is_orchestrator/scope identity. Correct worker and
foreign-scope fixtures now exercise the real case, without changing application identity rules.
The actual HTTP+SessionManager+stdio test receives SUBMITTED after write/drain, succeeds,
and exact duplicate delivery creates no new prompt. Missing/wrong proof, foreign parent,
wrong scope and sender spoof all reject before any provider RPC. Manual compact and scheduled
provenance remain denied for parent-sent worker input.
