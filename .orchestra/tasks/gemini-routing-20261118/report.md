# VERDICT: DEPLOYED_ADMISSION_VERIFIED

Code: 3e21fd28bd472e7e6b4d2971f628157cb8471ffd, fast-forwarded into production main.
Candidate/tested app: /home/kesha/orchestra-worktrees/gemini-routing-20261118/app
Deployed app: /home/kesha/orchestra/app

## Checks
- 484 passed, 2 dependency deprecation warnings (expanded-contracts.log).
- Instruction contract, syntax and diff checks PASS.
- Isolated HOME/DB, network namespace, fake ACP: real provider prompts 0.
- Real HTTP + SessionManager + AgentSession + fake stdio initial delivery verified;
  durable parent/receipt binding and MCP proof enforced; duplicate submits once.
- Scheduled, foreign and unproved inputs remain denied.

## Deployment and admission
Idle-only controller waited for all active turns/compactions to finish, then restarted
only orchestra.service. Actual PID changed 2777040 -> 2862666, service active.
restart_cut_turns = 0; Telegram service PID unchanged. No second restart required.
Live catalog and canonical admission PASS for exact 17 local g1-pro routes:
11 Gemini + 6 OUR local Antigravity Claude 5.5; 11 aliases verified.
Stored flag repairs needed: 0. Runtime errors after restart: 0.
Direct Anthropic and Hub-Claude remain Multicast-only; local Carbon and legacy routes
remain closed. Quotas, no-credit controls, cron/timer guards and disabled providers preserved.
Local Claude is documented for rare complex escalation, not routine or bulk work.
Foreign tracked files preserved byte-for-byte; existing session models, effort and native
session IDs preserved. No real generation was requested for this deployment verification.
Admission evidence does not claim successful native generation on every model.

## Evidence
- deployment.json: live catalog, guards, aliases, unchanged-state checks and idle observations.
- checks.md and expanded-contracts.log / expanded-instructions.log: exact test evidence.
- before.json / disabled-before.sha256: pre-deployment preservation baseline.
- deployment-attempt1.json / deployment-attempt2.json: earlier bounded waits; no interrupted turns.
- deploy_verify.py: exact idle-only deployment controller.

Production main was merged and restarted once. No push, provider settings change,
Telegram API call or telegram-bot-api restart was performed by this wave.
