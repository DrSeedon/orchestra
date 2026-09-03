# #290 — Phase 3 implementation report

## Outcome

Implemented one server-owned cross-runtime handoff transaction. The source remains authoritative
until the exact packet, total-context preflight, tools-disabled ingress, independent capability
receipt, exact normal-profile target id and atomic SQLite confirmation all succeed. Unknown or
ambiguous states fail closed; there is one bounded packet-only fallback and no summary/fresh-target
success path.

All three cross-runtime capabilities remain explicitly disabled. Codex 0.146.0 and Grok 1.0.3
cannot mechanically prove an empty validation tool surface. Claude CLI 2.1.197 / SDK 0.2.114 can
prove tools-disabled ingress, but the real semantic canary is blocked by the current Anthropic
weekly quota and the provider-private normal surface is not exactly serializable before process
creation. A connected normal-profile receipt now accounts the provider-reported complete context
and effective live surface before source release; it is a safety gate, not permission to enable the
capability. No live session was modified.

## Tickets

### T1 — deterministic packet and scoped raw references

- Added additive `runtime_handoffs` and `runtime_handoff_attempts` ledgers. Preparation drains
  pending writes, then freezes metadata, log boundary, rows, tracked project bytes and packet in one
  SQLite transaction.
- The canonical packet labels transcript content untrusted, omits hidden reasoning and free-form
  tool bodies, redacts model-visible secrets, carries completed effect hashes with
  `repeat_policy="never"`, and blocks pending/ambiguous effects.
- Raw refs are operator-only: dashboard cookie + CSRF is required; internal bearer access and MCP
  exposure are rejected; session/snapshot/type/id/count/visible-budget bounds are enforced.

### T2 — fail-closed Codex target path

- Added the common exact-manifest preflight, attempt ledger, structured failure classifier, source
  release ordering, atomic confirmation, response/UI contract and recovery decisions.
- Codex 0.146.0 cannot prove a universally tools-disabled app-server ingress. Its registry
  capability remains false; no forged rollout, instruction-only guard or silent summary fallback is
  used.

### T3 — Claude through the same transaction

- Claude validation uses an isolated provider home and the pinned SDK's mechanically empty tool
  configuration. Ingress must emit an exact checksum ACK and a successful terminal `turn_end` with
  no `tool_use`/tool result event.
- A separate normal-profile capability receipt now connects the exact validated target before
  source disconnect, rechecks CLI/SDK versions and actual SDK options, fingerprints the live
  initialization/MCP surface, and applies the shared reserve formula to provider-reported complete
  context. The target id must remain unchanged.
- Review established that the pinned CLI does not expose its complete preset/built-in/resolved tool
  schemas for exact pre-process serialization. The Claude capability therefore stays false; the
  transaction scaffold cannot become a production path by silently trusting constructor data.

### T4 — Grok stop condition

- Grok uses the common packet/manifest builder, so a marker inside a real tool-result body remains
  absent from staged components.
- The production `grok agent ... stdio` seam has no measured disable-all-tools control. The registry
  remains unsupported and the source is retained with `handoff_capability_unsupported`.

### T5 — native-resume preflight and release gates

- Same-provider resume now counts the target adapter's complete declared manifest plus the current
  native-context telemetry before reconnect. Missing telemetry or a smaller target window blocks
  before disconnect; an eligible switch preserves the native id.
- Added pinned-version/isolated semantic canaries and documented safe capability rollback. The
  upstream Codex renderer benchmark is a bounded post-release A/B trigger, not a reason to relax
  context admission.

## Verification evidence

Frozen oracle integrity and result:

```text
cmp tests/test_runtime_handoff_v2.py \
  <(git show a1f0a94ba6f00ea78b4eb31a07b80eb4f128264c:tests/test_runtime_handoff_v2.py)
exit 0

.venv/bin/python -m pytest -q tests/test_runtime_handoff_v2.py
39 passed, 2 warnings in 8.46s
```

Focused behavioral suite:

```text
.venv/bin/python -m pytest -q \
  tests/test_runtime_handoff_v2.py tests/test_runtime_handoff_recovery.py \
  tests/test_runtime_history.py tests/test_backend_claude.py tests/test_session.py \
  -k 'runtime_handoff or handoff or state_packet or \
      codex_model_switch_preserves_native_thread or two_db_backed_claude or \
      connected_normal_handoff or lazy_id_load or completed_failed_log'

76 passed, 234 deselected, 2 warnings in 15.26s
```

Broader changed-seam regressions:

```text
.venv/bin/python -m pytest -q \
  tests/test_runtime_handoff_v2.py tests/test_runtime_handoff_recovery.py \
  tests/test_runtime_history.py tests/test_backend_claude.py \
  tests/test_runtime_registry.py tests/test_db.py tests/test_manager.py \
  tests/test_session.py
583 passed, 2 warnings in 156.06s

# review-blocker async subset, three consecutive executions
10 passed, 241 deselected in 5.80s
10 passed, 241 deselected in 5.35s
10 passed, 241 deselected in 5.42s
```

Final post-review verification on immutable HEAD
`90587ba6a040f9d5b355dfde0b3dbfed3f715f17` repeated the complete frozen oracle and the
full changed-runtime regression set:

```text
cmp -s tests/test_runtime_handoff_v2.py \
  <(git show a1f0a94ba6f00ea78b4eb31a07b80eb4f128264c:tests/test_runtime_handoff_v2.py)
exit 0

.venv/bin/python -m pytest -q tests/test_runtime_handoff_v2.py
39 passed, 2 warnings in 9.62s

.venv/bin/python -m pytest -q \
  tests/test_runtime_handoff_v2.py tests/test_runtime_handoff_recovery.py \
  tests/test_runtime_history.py tests/test_backend_claude.py \
  tests/test_runtime_registry.py tests/test_db.py tests/test_manager.py \
  tests/test_session.py
583 passed, 2 warnings in 159.29s
```

`git merge-tree --write-tree HEAD b0b72d65` and the stricter check against the then-current
local `main` (`03025cbe`) both exited 0. No file changed on `main` after `b0b72d65` overlaps the
#290 diff.

The `test_api.py` failure is present in current `main`: its direct call still supplies two
arguments while current `main:app/routes/sessions.py` defines
`merge_session(name, req, request)`. #290 neither changed that function nor edited the test.
The full-suite run requires the global lock and explicit approval; its disposition remains open.

Seven one-variable mutations were each RED, then GREEN after restoration: dropping the completed
log-write failure generation, bypassing lazy-load recovery lookup, replacing provider-reported
context with zero, failing to disconnect the connected normal target during retirement,
suppressing an SDK disconnect failure, and continuing a same-provider switch after an ambiguous
source release, plus restoring the old same-runtime early return that skipped the durable ledger.

Migration, longest-session and provider evidence is recorded verbatim in
`docs/tasks/290/canary.md`. The final focused regressions, full-suite disposition and implementation
review verdict are appended before DONE.

## Recovery and rollback

- Before `source_released`, startup retires every persisted target locator and resumes the unchanged
  source.
- At `source_released`, only exact source-id reconnection resolves automatically. Failure or any
  owner/hash mismatch becomes `recovery_required`; sends are rejected.
- Confirmation updates the session owner and ledger in one `BEGIN IMMEDIATE` transaction.
- Safe rollback disables runtime capability flags. It does not drop audit tables and never restores
  the old optimistic native-import/summary success path.

## Pre-mortem

| Consumer-visible regression | Observable symptom | Check |
|---|---|---|
| late tool result omitted from snapshot | pending effect accepted or fact lost | frozen log-drain race oracle |
| transcript gains system/repository authority | marker instruction executes | authority and exact-manifest marker oracles |
| provider canary uses a tool or never completes | side effect or hanging validation | `tool_use` rejection + mandatory terminal receipt |
| normal target differs from preflighted target | first useful turn overflows or gains tools | manifest object/config hash + capability fingerprint checks |
| crash chooses the wrong native owner | duplicate/lost turn after restart | phase table recovery tests + exact source/target id checks |
| retry allocates an unbounded target | orphaned provider stores | attempt cap 2 + cleanup locator retention |
| UI renderer speedup is mistaken for context relief | raw import still reaches context ceiling | post-release A/B separates renderer metrics from token admission |
| a completed log write failed before snapshot | external effect disappears from packet | monotonic failure-generation test blocks preparation after callback cleanup |
| lazy load bypasses startup recovery selection | staged target and source both appear usable | every `_load_from_db` call resolves the latest unfinished ledger row |
| provider disconnect fails after local cleanup | old and target owners may both remain usable | disconnect re-raises after `finally`; same-provider switch records `recovery_required` and does not commit target ownership |

## Breaking / remaining gate

- Cross-runtime changes no longer succeed via summary or fresh empty target. Unsupported capability,
  overflow, pending effect, auth/network error and ambiguous recovery are visible failures with the
  source retained.
- The real Claude semantic canary must pass after the weekly quota reset before any production
  activation. The test remains collected and red on provider rate limit; it is not skipped.
- Claude is now explicitly disabled as well as Codex and Grok. A future enablement gate must prove
  the exact normal-profile boundary or explicitly approve the connected provider-context receipt;
  changing only the registry flag is not a supported release procedure.
- Codex and Grok cross-runtime handoff remain disabled until a pinned release supplies and passes a
  mechanical tools-disabled ingress seam.

## Implementation review

Codex round 1 rejected four paths: incomplete normal-context accounting, a constructor-only
capability receipt, completed failed log writes disappearing before snapshot drain, and lazy loads
that did not receive startup recovery state. The implementation now adds a connected normal target
receipt before source release, keeps Claude disabled while its provider-private pre-process surface
remains opaque, retains a monotonic log-write failure generation after future callbacks remove the
future, and resolves unfinished recovery inside the common `_load_from_db` path. Round 2 confirmed
all four fixes and found that Claude disconnect errors were still suppressed. Disconnect now cleans
local state in `finally` and re-raises; both cross-runtime and same-provider source-release paths
become `recovery_required` instead of committing ambiguous ownership. A durable same-provider
switch now uses the same attempt ledger and atomic confirmation rather than leaving a `prepared`
operation behind. Round 3 confirmed the disconnect fix, then found that an older same-runtime early
return made this new ledger path unreachable. That early return is removed and a real SQLite test
proves `preferred_mode=native_resume` is persisted. The permitted three-round ceiling is exhausted;
the recorded final Sol verdict therefore remains REJECT, not APPROVED. The orchestrator selected
post-ceiling mechanical verification instead of a fourth self-review: commit `90587ba6` removes the
early return, persists the durable `native_resume` ledger, and the frozen plus runtime suites above
are green. Cross-family verdict unavailable: Opus could not be run at Claude weekly quota 100%.

## Reconciliation onto current main (2026-08-17)

The implementation was replayed from
`preserve/290-feat-runtime-switch-fde5f8ec` onto current `main`
`b604ef4491c79300f4421ca3b1a4c1d8084672ff`. The ten requested #290 commits were
cherry-picked in the supplied order; merge commit `b7d661a0` was not replayed. Explicit conflicts
in `app/backend_codex.py`, `app/runtime_history.py`, and `app/session.py` were resolved by retaining
both sides of the contracts: #290 manifest/preflight/recovery wiring, #314 server-owned
role/task-class/Luna Fast inputs, and the existing #305 managed-home sanitizer/state preparation.
The auto-merged manager/session paths retain #311 durable initial delivery and #314 Sol-to-Luna
runway routing.

Post-reconciliation evidence on the fresh base:

```text
git show a1f0a94b:tests/test_runtime_handoff_v2.py | cmp - tests/test_runtime_handoff_v2.py
exit 0

.venv/bin/python -m pytest -q tests/test_runtime_handoff_v2.py
39 passed, 2 warnings in 12.36s

.venv/bin/python -m pytest -q \
  tests/test_runtime_handoff_v2.py tests/test_runtime_handoff_recovery.py \
  tests/test_runtime_history.py tests/test_backend_claude.py \
  tests/test_runtime_registry.py tests/test_db.py tests/test_manager.py \
  tests/test_session.py
586 passed, 2 warnings in 140.28s

.venv/bin/python -m pytest -q \
  tests/test_db.py tests/test_initial_deliveries.py \
  tests/test_initial_delivery_review_regressions.py tests/test_manager.py \
  tests/test_mcp_stdio.py tests/test_routes_surface.py tests/test_session.py
598 passed in 144.58s

.venv/bin/python -m pytest -q \
  docs/tasks/314/oracles/test_t314_enforcement.py \
  docs/tasks/314/oracles/test_t314_session_integration.py \
  docs/tasks/314/oracles/test_t314_analytics.py
24 passed

.venv/bin/python -m pytest -q tests/test_t314_analytics_browser.py
3 passed in 6.43s

.venv/bin/python -m pytest -q \
  tests/test_manager.py::TestEnsureLoadedSingleFlight \
  tests/test_codex_managed_state.py \
  tests/test_backend_codex.py::test_startup_exit_surfaces_sanitized_stderr_after_drain
18 passed in 7.19s
```

The first #314 browser attempt did not enter a test body because Playwright Chromium v1223 was
absent; its three setup errors were environmental, while the 24 non-browser #314 assertions were
already green. Installing that exact test browser made all three browser checks green. The
installer refreshed the user cache by removing unused Chromium v1234 and adding v1223; either is
recoverable with the matching `playwright install chromium` command. `uv.lock` remained unchanged.
No service restart, deployment, push, or production-state mutation was performed.
