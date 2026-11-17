# Step1 isolated live stand — BLOCKED before live

VERDICT: PhaseA preflight integration fixes implemented and verified offline.
The single controlled live stand driver stopped BEFORE creating the stand or profile,
starting FastAPI, launching agy, initializing/authenticating, or sending a prompt.
Reason: an already running, non-owned agy-vendor.elf PID894529 (GID977, sleeping,
parent814096) violates the required zero-existing-vendor precondition. It was preserved.
The owner was asked which active session owns it. No automatic retry was made.
This is NOT a live success, account-compatibility result or production acceptance.

Base8bbf60d929af2a89326074695f924fff10c780ea, branch agy-acp-safe.
Imported app: /home/kesha/orchestra-worktrees/agy-acp-safe/app/__init__.py.

## PhaseA changes and evidence

- manager._make_mcp_config reads ORCHESTRA_URL with unchanged8888 default. The stand
  value18889 reaches stdio MCP. Other callback entry points already honor the variable;
  remaining8888 occurrences are defaults/comments. No production configuration changed.
- ensure_interactive_input permits explicit user input or an agent report only for a
  durable orchestrator whose every sender is a same-scope durable direct child. Parent
  id or parent name is verified from DB, not an in-memory label. Unknown/unrelated,
  system/platform/background/scheduler/cron/timer/dreaming/limit retry still fail closed.
  compact explicitly refuses child-agent input. The same check exists in HTTP, session,
  start-turn and backend boundaries. Queued child reports retain provenance through
  actual flush; no conversion to pretend user input. Actual turn_signals/on_idle callback
  and HTTP proof delivery are exercised with mock stdio. Taskless ACP orchestrator
  child reports avoid the worker-assignment branch; non-ACP behavior is unchanged.
- ANTIGRAVITY_AUTH_HOME now reads env. cli_environment explicitly retains the caller's
  disabled-provider file. Conversation context prefers antigravity-acp SQLite then
  antigravity-cli only if the ACP file is absent; both remain read-only.
- MCP stdio commands use existing clean-exec. On this host ~/.local/bin/agy-clean-exec
  does not exist; /usr/local/bin/agy-clean-exec is the installed executable symlink to
  orchestra-agy-ipc.py. It restores kesha:kesha for tools and strips provider proxies.
  No symlink, wrapper, service, settings or infrastructure file was edited.
- Cached OAuth selection matches offered id oauth-personal without imposing type agent;
  absent type and type oauth work in synthetic tests. Unsupported wireVersion2 remains
  refused. Static protected ELF read (no execution/help/version) found1.5.9 and OAuth/
  ACP struct strings; actual initialize protocolVersion/authMethods remain UNMEASURED.
- Hydrogen registry mapping and orchestrator quota exemption tested. Luna admission uses
  the canonical gate with cache/unknown policy, not a bypass or fabricated free quota.
  Driver prepares only a read-only copy of the latest redacted Codex quota snapshot and
  disables refresh in this separate test process. No quota requests or provider model
  probes were made. Actual creation/spawn is still unverified because live did not start.

## Exact checks

Final focused regression+receipt+compact+foreground+R4 run:84 passed,0 failed,0 skipped,
2 warnings,31.51s (offline-final-2.log). Real fake stdio, real AgentSession/listener,
real HTTP, actual auto-report callback; no real provider in offline tests.
The shared synthetic fixture now awaits its actual durable session write before its
first dependent journal write; no assertions weakened. An earlier combined run exposed
that setup race (83P/1F); the previous intermediate preflight48P also passed. First
preflight43P/5F exposed the additional admission boundaries and fixture assumptions;
all intermediate outputs are retained, not counted as successful final checks.
Instruction contract, Python syntax, git diff and focused added-diff credential scan PASS.
Warnings: existing websockets legacy/WebSocketServerProtocol deprecations.
Exact command/deadline/log integrity: live-stand/commands.json.

## Live telemetry — NOT RUN

| Metric | Actual result |
|---|---|
| Existing foreign vendor | PID894529, GID977, stateS, parent814096 |
| Owned PID_ACP / stand server | none / none |
| initialize/authenticate/session-new | 0/0/0 |
| User/model prompts / worker spawns | 0/0 |
| Turn1 tokens/cache/duration | not measured |
| Turn2 warm reuse/tokens/cache/duration | not measured |
| Worker unittest/worktree/logs | not created |
|45s post-turn silence | not run; no completed turn |
| Proxy preflight |178.93.29.64, NL/Amsterdam, AS215294 Lumina broadband UAB |
| nft skgid977 read-only snapshot |0 packets,0 bytes |
| nft live-cycle delta |not measured; no live interval |
| Temporary stand/profile copy |not created |
| OAuth refresh/copyback |none; token contents not read/copied by this wave |
| Owned leftover server/vendor/mock PIDs |0 |

The one driver invocation exited1 at the preexisting-process guard. No second driver
invocation occurred. Its guard was subsequently moved inside structured evidence
handling, and cleanup made conditional on newly owned stand creation; that observability
correction did NOT trigger another attempt. The prepared driver remains an unexecuted
live-path artifact pending the external precondition, not evidence that PhaseB/C works.
Read-only IPinfo and nft checks happened independently after the stop and are labeled
as snapshots, not a fabricated45s silence audit. Source auth profile remains untouched.

## Isolation, cleanup and remaining action

Production /home/kesha/orchestra remains main4e4e58dcba8eca8f4e961a2095be7efda1322d0e,
with the exact3 preexisting tracked modifications. Its disabled list remains
[antigravity,claude,grok]. Port8888, service processes and user settings were not changed.
No push/merge/deploy/restart, real agy/Google/OAuth/TG/model/quota requests, paid fallback,
hub/proxy/billing change, identity masking or provider-setting edits.
Offline runner keeps kernel lo-only namespace, fake-only executable audit and protected
SQLite/file guards. No full production lifespan, background jobs or TG poller was started.
Do not call this100% ban-safe: native account eligibility/traffic remains unverified.

The operator must identify/finish the preexisting vendor session before a zero-vendor
stand can run. This task does not authorize killing a foreign active session, sharing
its account daemon or relaxing the required baseline. No autonomous retry is queued.

Evidence directory /home/kesha/orchestra-worktrees/agy-acp-safe/.orchestra/tasks/agy-acp-safe-20261117/live-stand/:
verification.json, preflight-blocker.json, cleanup.json, commands.json,
offline-final-2.log, live-run.log, instructions-final.log.
Sources: app/{manager,antigravity_acp,backend_antigravity,session}.py,
app/routes/sessions.py, tests/test_antigravity_live_preflight.py,
scripts/verify_antigravity_live_stand.py.
