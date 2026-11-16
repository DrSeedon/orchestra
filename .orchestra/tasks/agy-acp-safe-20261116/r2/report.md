# Bounded Astra R2 correction wave — 2026-11-16

VERDICT: three proven R2 defects corrected in offline mock tests. Overall gate RED.
No production activation or full-suite approval follows from this result.
Base: 120cb528faaefcf0fddd688e4ab300469aeb3fc8; corrected commit in final handoff.
Worktree: /home/kesha/orchestra-worktrees/agy-acp-safe; branch agy-acp-safe.
Exact imported app: /home/kesha/orchestra-worktrees/agy-acp-safe/app.

## Disposition of the three defects

1. Nested structured account ban: existing canonical provider_safety classifier now
   follows bounded, well-defined error/data/cause/errors/details wrappers, excluding
   response prose. Root/nested/list/cause suspension payloads persist the existing
   circuit-breaker with the same FIXED safe reason. Auth-required, quota, invalid model
   and generic internal/response prose do not persist a ban. All state is synthetic.
2. Real compact ACK: explicit operator compact starts the actual per-turn reader after
   ACK-send. Tests use normal _make_backend, _ensure_backend and _turn_event_loop with
   fake stdio, no finish_ack replacement. Exactly one summary + one ACK, no auto-retry.
   ACK occupied context is adopted from typed telemetry; known case 700 -> 200 tokens
   (70 -> 20 percent). Missing context remains known=false and receipt post/after/drop
   fields are null, not invented zero/savings. ACK refusal rolls back native ID and
   prior context without creating a successful history entry; DB agrees with memory.
   Automatic compact is still denied before any RPC. Runtime registry policy unchanged.
3. Model confirmation: config-option selection consumes returned metadata. Explicit
   mismatch OR absent current model refuses before prompt. Healthy sibling runs on
   the same daemon, no replay/fallback/restart. Correct confirmation and config updates
   pass. Legacy set_model empty success is its existing contract; explicit contradictory
   metadata is rejected there too. Unknown config confirmation is never fabricated.

## Actual checks

| Check | Result | Evidence |
|---|---|---|
| ACP/review/R2 + always-on/registry/usage + two existing pure safety contracts | 210 passed, 0 failed/skipped, 2 warnings, 21.63s | acceptance.log |
| Real normal/unknown/failing compact ACK | PASS, each 1 spawn/init/auth, 2 new sessions, 3 prompts including initial turn | real-compact-*.json |
| Actual HTTP receipt + duplicate receipt + interrupt + compact | PASS: 1 spawn/init/auth, 4 prompts, 1 cancel; duplicate did not prompt | http-receipts-interrupt-compact.json |
| Instruction contract / syntax / diff | PASS | instructions.log, notes.md |
| Original four-file compact/mailbox diagnostic | TIMEOUT 60s, exit124, 29 collected, no completed node | timeout-command.json, timeout-diagnostic.log |
| Frozen legacy set | Last measured 15 failed / 18 passed / 79 setup errors; not rerun this wave | prior legacy-final.log |

Exact green command: scripts/run_antigravity_offline.sh tests/test_antigravity_acp.py
 tests/test_antigravity_acp_review.py tests/test_antigravity_acp_r2.py
 tests/test_always_on_agents.py tests/test_runtime_registry.py tests/test_usage_contract.py
 tests/test_provider_safety_contract.py::test_permanent_ban_circuit_breaker_trips_only_on_unambiguous_bans
 tests/test_provider_safety_contract.py::test_redteam_401_ban_marker_trips_while_token_expired_and_429_stay_safe
 -q --tb=short -p no:faulthandler

First targeted run: 13 passed/1 fixture assertion failure because fake ACK tail carried
INITIAL_CONTEXT and fake itself reported700. Corrected the fake discriminator once;
assertion semantics unchanged. Second targeted run: 15 passed. Final210 includes new
malformed/reset USD accounting cases and the unchanged read-only SQLite/WAL/protobuf
assertions reused from legacy. Previous new test's fake finish_ack was replaced with
stronger real-lifecycle assertions. Frozen original test files were not changed.

## Timeout: exact remaining acceptance blocker

One bounded diagnostic reconstructed the ORIGINAL four files, adding only verbose
node progress, captureoff and disabled faulthandler. It collected29, then stalled after:
 tests/test_compact_pending_ack_467.py::test_pending_user_input_waits_until_compact_ack_succeeds
No completion result appeared before timeout60s/exit124. No SIGSEGV or stack-trigger
attempt was made. A node announcement does not distinguish fixture setup from body;
root cause and relationship to ACP ACK are UNPROVEN. No repeated bundle, no timeout
increase, no weakening/patching that test. This is an unresolved blocker, not labelled
unrelated. Exact argv/deadline and full bounded log are retained in this commit.

## Boundaries, cleanup and open semantics

Kernel network namespace: loopback only, external_routes=0; only exact fake executable
may run; synthetic credential-free HOME/DB. Python audit includes protected SQLite
path/URI/PathLike. It is not a general filesystem sandbox and fake does not inherit
that Python audit hook. No real agy/Google/account request or credential read/copy.
No enablement, push, merge, deployment, production/Telegram restart, billing/proxy/T3
changes. t3-bg --info still returns HTTP401; owned test processes were awaited rather
than abandoned. No runner/fake PIDs remain; production HEAD and original dirty files
and disabled providers are unchanged (cleanup.json).

Remaining gates: unresolved first-node timeout; frozen per-turn NDJSON/token-copy/
active-probe/login expectations require reviewed migration, not forbidden behavior
restoration. Account-generation/rotation isolation without token inspection is still
NOT implemented: profiles are canonical but no automatic account-generation detection
or migration is claimed. Billed token totals remain unknown; malformed/reset USD costs
are now tested, not a substitute for absent vendor telemetry. Real installed CLI
compatibility/internal traffic/consumer eligibility remain untested. Parent owns a
fresh independent review of the corrected immutable commit; no account-ban immunity
or overall GREEN is claimed.

Pointers: app/provider_safety.py; app/backend_antigravity.py; app/session.py;
tests/acp_mock/fake_agy_acp.py; tests/test_antigravity_acp_r2.py;
verification.json (exact per-test mock counters and isolation), notes.md.
