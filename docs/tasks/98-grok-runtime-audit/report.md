# Report #98 — implementation slices

Date: 2026-07-28.

## T1 — Fail-closed, identity-aware Grok MCP conformance

Status: **MERGED** as `6356f23`.

### What changed

- `app/backend_grok.py`
  - Expected and observed MCP servers are compared by normalized transport,
    command/URL, args, and env pairs, not name alone.
  - Environment values participate in in-memory equality but are never
    rendered in diagnostics.
  - `_verify_mcp_isolation()` now uses one 20-second deadline and fails on:
    - missing expected server;
    - unexpected server;
    - same-name/different-identity server;
    - expected server that did not report `ready`;
    - unknown/zero aggregate MCP tool count for a non-empty launch plan.
  - The pre-init roster proves identity and foreign presence only. Per-server
    status proves readiness; a different expected server cannot mask a failed
    Orchestra server by contributing tools.
  - The empty launch-plan case also waits for initialization, so implicit
    autodiscovery cannot pass before the roster arrives.
- `tests/test_backend_grok.py`
  - Added the full observable-roster 2×2:
    required present/absent × foreign present/absent.
  - Added same-name identity substitution and secret-redaction coverage.
  - Added zero-tool, empty-plan, and mixed readiness regressions.

Production diff at final review:

```text
app/backend_grok.py        +123/-16
tests/test_backend_grok.py +179/-10
```

### Acceptance evidence

Targeted final run:

```text
18 passed, 60 deselected in 2.26s
```

Required mutation check temporarily replaced the missing-server calculation
with an empty set. The matrix failed exactly where expected:

```text
missing-only          FAILED: DID NOT RAISE GrokMcpIsolationError
missing-and-unexpected FAILED: missing-required diagnostic absent
2 failed, 2 passed
```

The production branch was restored, targeted tests returned green, and the
final full suite passed:

```text
1132 passed, 20 skipped in 112.24s
```

Logs:

- `/tmp/pytest-98-t1-targeted.log`
- `/tmp/pytest-98-t1-mutant.log`
- `/tmp/pytest-98-t1.log`

### Codex review

- Plan: **APPROVED** in `codex-review-plan.md` after one infrastructure timeout
  and a bounded resume.
- Implementation round 1 found one P1: aggregate `mcpToolCount > 0` could be
  supplied by another expected MCP while Orchestra itself was unavailable.
- The finding was reproduced against the stored ACP ordering, fixed with
  per-server readiness/failure state and a mixed-roster regression.
- Implementation round 2: prior P1 **FIXED**, no new findings,
  **APPROVED** in `codex-review-impl-t1.md`.

### Breaking behavior

Intentional fail-closed change: a Grok backend no longer connects when its MCP
launch result is incomplete or ambiguous. This can surface previously silent
MCP startup failures as `GrokMcpIsolationError`.

### Remaining uncertainty

The historical root cause remains **UNCERTAIN**. Current OAuth is expired, so
this slice does not claim a positive live trust transition or choose between
trust filtering and same-name precedence. It secures the observable outcome
regardless of which upstream mechanism caused it.

No live database write or service restart was performed.

## T2 — Typed aggregate/current/known usage and fail-soft compaction

Status: **DONE; awaiting orchestrator merge.**

### What changed

- `app/usage_contract.py`
  - Added distinct immutable `AggregateUsage`, `KnownContext`,
    `UnknownContext`, and `DeferredContext` values.
  - `TurnUsage` carries billed aggregate usage and current occupied context as
    different types; compatibility metadata is generated only at the event
    boundary.
  - Missing, negative, non-finite, and `current > max` values become
    `UnknownContext` without dropping billed usage or the terminal event.
- All four backends now emit the typed value through `AgentEvent.usage`.
  - Grok no longer reads aggregate `usage.totalTokens` as current context.
    Only ACP chunk `_meta.totalTokens` can populate the current-context type.
  - Claude marks result-event context as deferred to its separate
    `context_usage()` channel.
  - Codex keeps cumulative-thread delta usage distinct from last-call context.
  - OpenCode preserves its existing input/context mapping through the shared
    validator.
- `CostTracker` consumes aggregate token totals from the typed value and marks
  session context explicitly known or unknown.
- `TurnManager` derives one `allow_context_compaction` decision. Both the
  immediate generic compact and delayed precompact use the same
  `schedule_context_compaction()` path.
  - Unknown context clears stale `100%`, cancels an existing timer, emits a
    visible status diagnostic, and cannot enter either compaction path.
  - Claude may re-enter the same shared path only after a successful
    unknown-to-known API refresh.
  - `subscription_limited` and `max_turns` auto-continue suppress both the
    ordinary turn path and deferred-refresh path.
- The existing orchestrator 21:00–06:00 Asia/Krasnoyarsk window remains a
  later gate inside the one timer scheduling/fire implementation. Unknown
  context never evaluates the window.

### Acceptance evidence

The measured Grok incident payload is pinned in tests:

```text
aggregate inputTokens = 1,665,949
aggregate totalTokens = 1,678,471
modelCalls            = 25
current context       = unknown
reported context_pct  = 0
```

A separate valid ACP current value produces:

```text
current/max = 84,482 / 500,000
context_pct = 16
context_known = true
```

Focused backend/contract/session run before final review:

```text
309 passed in 12.15s
```

Required mutation temporarily removed `and context_known` from the shared
turn gate. The regression failed on the forbidden decision:

```text
Expected '_schedule_precompact_timer' to not have been called.
Calls: [call(0)].
1 failed
```

The production branch was restored. After all review fixes, the final full
suite passed:

```text
1174 passed, 20 skipped in 93.21s
```

Logs:

- `/tmp/pytest-98-t2-mutant.log`
- `/tmp/pytest-98-t2-targeted.log`
- `/tmp/pytest-98-t2-final2.log`

### Provider compatibility

- Claude: a previous known API context retains the existing timer and generic
  worker-compaction behavior; a first deferred result schedules exactly once
  after the API supplies a valid context.
- Codex: known last-call context still arms native precompact at the existing
  threshold and never invokes the generic handoff compact.
- Grok: aggregate usage/cost remains recorded while unsupported current
  context is unknown.
- OpenCode: valid input/max values still produce the same percentage and
  compatibility metadata.

### Codex review

- The first `review` invocation reproduced the known infrastructure failure:
  it ignored the exact target, read `BUGS.md`, timed out, and produced no
  artifact. One bounded `exec` retry was used.
- Round 1 found two non-blocking defects: first-turn Claude deferred context
  did not re-arm compaction after a valid refresh, and `OverflowError` violated
  fail-soft normalization. Both were reproduced and fixed.
- Round 2 confirmed both fixes and returned **Approve with suggestion**, with
  no crash/corruption/security finding. Its final suggestion showed that the
  deferred path also needed the subscription/max-turn gates; the final
  `allow_context_compaction` value now drives both entry points, with focused
  regressions and the full suite green.
- Full transcript: `codex-review-impl-t2.md`.

### Breaking behavior

Intentional: a backend without a valid typed current-context value no longer
inherits a stale percentage for automatic compaction. Billed aggregate usage,
cost, dashboard compatibility keys, and the terminal turn remain available.

No live database write or service restart was performed.

## Pending slice

- T3 — inventory/migrate model routing, remove the implicit OpenCode catch-all,
  retain or separately recommend removal of the adapter based on evidence.
