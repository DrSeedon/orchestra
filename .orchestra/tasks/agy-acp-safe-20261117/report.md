# Antigravity inside Orchestra — foreground mock implementation wave
Date:2026-11-17. Base f68c2335c55efb1300a446be922ab0e1164f215c.
VERDICT: foreground Python/mock contracts implemented and tested; overall gate RED.
Full browser renderer/visual acceptance remains OPEN; this is not production readiness.

Worktree /home/kesha/orchestra-worktrees/agy-acp-safe, branch agy-acp-safe.
Exact imported app /home/kesha/orchestra-worktrees/agy-acp-safe/app.
Corrected immutable commit is in final handoff; production main remains4e4e58dcb.

## Delivered foreground contract

1. Native session/request_permission is handled asynchronously. The reader does not
   wait for the human; it routes each RPC through a bounded native request bridge.
   UI uses chat cards/buttons and authenticated operator+CSRF endpoints; TG uses actual
   app/tg_bridge.py callback/formatter, creator+destination/topic ACL. Deferred approvals
   and mailbox wake are not used. Responses never create an inference prompt.
2. Native records bind Orchestra owner, native session, explicit profile epoch, random
   transport generation, turn, RPC identity, original payload hash and offered option IDs.
   Owner/session/epoch/transport/option checks reject foreign/stale callbacks. Exact
   duplicate RPC is ignored, changed payload under same RPC ID closes transport.
   Decisions are deduplicated, deadline/cancel/EOF invalidate pending work. Restarted app
   cannot answer an old live RPC. UI lists current requests and disables historical cards.
3. interaction_* requests implement only the statically verified T3 choice-question
   convention over the same native method. Arbitrary text answers/other elicitation
   schemas are not invented. Unsupported client methods fail closed.
4. ToolReducer merges per-tool snapshots: absent/null raw fields do not clear old state;
   status-only completion keeps output; initial completed/failed yields call+result;
   same terminal status with new content is retained; repeated snapshots deduplicate.
   Programmatic name and nested MCP identity are separate from title/kind. A nameless
   tool remains tool. IDs are namespaced by native session/turn. Text diff/resource
   previews are retained; nontext/image types are explicitly unsupported, not fetched.
5. Text/thinking segments flush at type/tool/native-card/terminal boundaries. Stable
   segment IDs reach live broker replay and immutable log event IDs. Ordered writes
   and a terminal journal barrier apply only to ACP, preserving other runtime policies.
   Parent auto-report gets the full assembled assistant reply, not just the last segment.
6. Actual Telegram bridge now prefers structured tool_name with legacy fallback. ACP
   primary-topic delivery has a durable per-destination/event/chunk outbox and cursor.
   First attachment skips existing history; restart resumes a known unsent tail. Shared
   rate admission happens before SENDING; one API attempt follows. Sent chunks are not
   duplicated, ambiguous sends block and require operator reconciliation. Absolute
   exactly-once external delivery and automatic unknown-send recovery are not promised.
7. Fixed profile epoch binds local native sessions and callbacks. Explicit user resume
   and restart are supported for that same bound profile; stale/foreign binding refuses.
   This does NOT detect an account change in the same HOME. No generation migration,
   credential extraction or account workflow was added. Model/effort uses only exact
   offered variants/config ACK; mismatch/unknown refuses before prompt, no nearest or
   paid/provider fallback. Wire v1 is explicit; v2 is rejected rather than misread as v1.
8. f68 receipt boundary remains before prompt-write/after write+drain, with ambiguity
   UNKNOWN/no replay and interruptible profile/backpressure waits. No mid-turn injection,
   cron/timer/self-resume/swarm/child-agent capability was enabled.

## Actual verification and explicit limits

| Check | Measured result | Evidence |
|---|---|---|
| Final scoped ACP/foreground + existing always-on/registry/usage |248passed,0failed/skipped,2 dependency warnings,43.85s|acceptance-final.log|
| Final pure tool-name/null/initial completed+failed clarification |1passed,3.16s|tool-name-final.log|
| Two sessions x two turns |1spawn/initialize/authenticate,2new sessions,4prompts|ordered-transcript.json,verification.json|
| Native allow/deny/cancel/timeout/two/questions/ACL/stale/EOF |PASS; one response per represented RPC,0extra prompts|verification.json|
| Ordered DB -> real loopback HTTP SSE |PASS; durable IDs and order preserved|foreground-http-sse.json|
| Actual TG formatter/callback, fake transport, restart/ambiguity |PASS|fake-tg-transcript.json,acceptance-matrix.json|
| Instruction/syntax/diff/secret boundaries |PASS|instructions.log,cleanup.json; staged scan before commit|
| Headless browser renderer |OPEN:3bounded attempts, last completed-tool selector timeout|ui-r1.log,ui-r2.log,ui-final.log|

The248 run preceded the final pure fallback clarification for a tool without an
advertised programmatic name; that final branch and both initial terminal statuses
were checked separately by the1passed targeted check. No other application code
changed afterwards. No old frozen acceptance set or timeout bundle was rerun.
Historical225passed/1failed and15F/18P/79E are not overwritten by this green selection.

### UI acceptance blocker (no hidden fourth attempt)
The browser ran actual local chat/tool-renderers/live-activity JS in a headless Chromium
inside a loopback-only namespace. It read the real synthetic journal. Native choice
click and synthetic HTTP response wait completed before the later tool selector failed.
R1 fixture omitted utils.js locale; R2 expected all historical tool snapshots visible
at once; final attempt searched transient data-last-tool, removed by the production
renderer after completion. Static fixture selector was corrected to data-tool-raw-name,
but was NOT rerun after the headless budget. Full UI/tool-renderer assertions, screenshots
and CEO visual verdict are therefore NOT claimed. UI native endpoint/CSRF/ACL to real
fake-stdio RPC is independently covered by Python integration, not by a real-account
browser session. This gate needs a later explicit bounded check/review decision.

## Isolation / no activation / cleanup
Core tests use candidate .venv (read-only link to existing dependencies), existing
kernel namespace runner, lo only/external_routes0, synthetic HOME/profile/SQLite,
exact fake-only process allowlist and external DNS/socket/protected SQLite audit guards.
Explicit negative controls reject Google/Telegram DNS and blocked provider executables
BEFORE resolution/exec. Fake child receives no credential files. The Python audit hook
is not a general filesystem sandbox and does not propagate to the controlled fake.
The separate UI checker permits only local inline assets and intercepted loopback
synthetic endpoints in its namespace; real app/provider/TG lifespans never start there.
No actual native agy/version/help, Google/account/OAuth/model/quota/onboarding/refresh,
keyring/.env/credential reads or copies, Telegram API or paid routes were used.
No production/provider/T3/proxy/billing changes, push/merge/deploy/restart/publication.
Owned fake/runner/UI/browser processes0. An unrelated live browser tree was left alone.
Production HEAD, its3preexisting dirty tracked files and disabled antigravity/claude/grok
are unchanged (cleanup.json). No new dependencies/downloads, helpers or reviewer runs.

## Capabilities and remaining gates
See capabilities.json and authenticated GET /api/native-requests/capabilities.
- One Orchestra process/event loop owns callbacks; no multi-worker callback routing.
- Choice-only interaction_* questions; no arbitrary free text/unknown extension API.
- Forced file-store credential-presence readiness only; keyring autodetection unsupported.
- Role instructions are first-turn USER context, not system priority. Native
  systemPrompt.append advertisement/extension remains unverified and is not used.
- Foreground updates only; late/background/swarm/native internal fanout not made a
  supported public contract. Profile semaphore does not bound all vendor internal calls.
- TG guarantees represented primary-topic recovery only; legacy mirrors and manual
  reconciliation UI for unknown external sends are not implemented by this wave.
- Same-HOME account switch/generation detection unsupported; fixed profile only.
- Real installed native CLI compatibility, internal traffic/telemetry, auth eligibility
  and exact personal-Pro/custom-Orchestra-VPS support remain unverified. Existing
  FAQ/terms research is unchanged; no account-ban immunity/invisibility guarantee.
- Overall acceptance remains RED for UI, legacy migration and native/live authorization.

## Main source / evidence pointers
app/native_requests.py; app/routes/native_requests.py; app/acp_tools.py;
app/acp_tg_delivery.py; app/antigravity_acp.py; app/backend_antigravity.py;
app/session.py; app/live_broker.py; app/tg_bridge.py; app/static/js/chat.js.
Tests: test_antigravity_foreground{,_delivery,_sse}.py; existing receipt/mock suites.
commands.json has exact scoped command/deadline; notes.md records intermediate failures.
Required input research read in production task directory: astra-t3-parity-20261117-r1.md,
parent-final-receipt-review.md, astra-native-reverse-r1.md. Current T3 bundle read statically:
/usr/lib/node_modules/t3/dist/binCli-m7voabU-.mjs. No T3 gateway/client impersonation copied.
Protocol references: https://agentclientprotocol.com/protocol/v1/tool-calls and
https://agentclientprotocol.com/protocol/v1/session-config-options .
