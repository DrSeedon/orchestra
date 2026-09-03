# Report — Codex cache indicator and compact architecture

## Outcome

- Added one runtime cache-policy source in `app/models.py`:
  - Claude and existing fallback runtimes: `3600s`, exact.
  - Codex: `1800s`, approximate/reference-only.
- Applied the policy to active and persisted non-archived session payloads and orchestrator payloads without a DB migration.
- Updated dashboard and MCP pills to use proportional thresholds:
  - `hot > 50%`, `warm >= 20%`, `cooling > 0`.
  - Exact Claude expiry remains `cold`.
  - Approximate Codex expiry becomes `unknown`; it never claims the ChatGPT cache was definitely evicted at 30 minutes.
- Added Codex `≈` labels and tooltips explaining that the actual ChatGPT TTL is not guaranteed.
- Documented why Orchestra fresh-thread compact loses Codex reliable thread-key matching while Claude can reuse stable cross-session prefix layers.

## Tickets

### T1 — Codex cache status end-to-end

Done. Runtime policy, manager/orchestrator serialization, dashboard, MCP rendering, and exact/approximate tests are implemented.

### T2 — Compact cache architecture

Done. `research.md` distinguishes invalidated conversation history from reusable stable prefixes and avoids claiming that a new Codex thread guarantees zero cache hits.

## Files

- `app/models.py` — `cache_policy_for_runtime()`.
- `app/manager.py` — session payload cache metadata.
- `app/routes/system.py` — orchestrator payload cache metadata.
- `app/static/js/app.js` — exact/approximate cache-pill state machine.
- `app/mcp_stdio.py` — matching textual cache-pill semantics.
- `tests/test_backend_routing.py` — cache-policy unit contract.
- `tests/test_manager.py` — active and persisted session payloads.
- `tests/test_api.py` — Claude/Codex orchestrator payloads.
- `tests/test_frontend.py` — Codex approximate/unknown and Claude exact thresholds.
- `tests/test_mcp_stdio.py` — matching MCP states and environment isolation.
- `docs/tasks/codex-cache-research/research.md` — compact architecture.
- `docs/tasks/codex-cache-research/codex-review-impl.md` — adversarial implementation review.

## Verification

- Targeted touched modules: `178 passed`.
- Full suite against an initialized temporary SQLite DB:
  - `756 passed, 20 skipped in 70.07s`.
- JavaScript syntax: `node --check app/static/js/app.js` passed.
- `git diff --check` passed.
- Codex implementation review: “No high-confidence regressions were identified”; runtime policy, payload wiring, dashboard, MCP, and tests were judged coherent.

The first full-suite attempt used the worktree's stale default SQLite file and failed in unrelated `tests/test_session.py` paths because table `bg_jobs` was absent. Re-running the same suite with a freshly initialized `/tmp` database passed completely; production/session code was not changed to mask the fixture problem.

## Compatibility and remaining risk

- Breaking changes: none.
- DB migration: none; fields are derived from existing `backend_type`.
- Codex `1800s` remains an honest UI reference/minimum, not a guaranteed ChatGPT-auth eviction boundary.
- Orchestra was not restarted. Python changes require an explicit restart command after merge; frontend files themselves do not.
