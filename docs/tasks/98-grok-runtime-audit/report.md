# Report #98 — implementation slices

Date: 2026-07-28.

## T1 — Fail-closed, identity-aware Grok MCP conformance

Status: **DONE; awaiting orchestrator merge.**

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

## Pending slices

- T2 — typed aggregate/current/known usage and fail-soft compaction.
- T3 — inventory/migrate model routing, remove the implicit OpenCode catch-all,
  retain or separately recommend removal of the adapter based on evidence.
