# Plan #98 — Grok runtime hardening and runtime-contract cleanup

Date: 2026-07-28.

## Scope and sequencing

Implementation is split into three mergeable vertical slices. Each slice gets
its own full `pytest`, implementation review, commit, and STOP for the
orchestrator to merge before the next slice starts.

The slices are deliberately ordered:

1. fail closed when the required Orchestra MCP is absent, foreign, or replaced;
2. stop aggregate turn usage from masquerading as occupied context;
3. make model/runtime/provider routing exhaustive and remove OpenCode's
   implicit catch-all only after inventory and migration.

No slice restarts the live service or writes to the live database. OpenCode is
not deleted in this task. `docs/tasks/98/` remains untouched.

## Assumptions and measured constraints

- The historical Grok startup root cause remains **UNCERTAIN**. No historical
  request payload proves whether trust filtering, same-name precedence, or
  both removed the generated server.
- `GrokBackend` does not receive a `projectTrusted` flag. Its security boundary
  is the authoritative `_x.ai/mcp/servers_updated` roster. The automated 2×2
  therefore varies two observable outcomes: required identity present/absent ×
  autodiscovered foreign identity present/absent. It does not invent a trust
  branch in production code.
- The current Grok OAuth token is expired. Stable CI tests must not depend on a
  live subscription or encode an unmeasured positive trust transition.
- `_x.ai/mcp/servers_updated` exposes enough non-secret structure to identify a
  server (`type`, command/URL, args, and env pairs). Identity comparison may
  inspect env values in memory but must never log, persist, or include them in
  an exception.
- Existing `AgentEvent.metadata` remains compatible while typed usage is added;
  storage and UI migration are not prerequisites for stopping false compaction.

## Cross-slice verification

After each ticket:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest -x -q \
  > /tmp/pytest-98-tN.log 2>&1
```

Then review that slice's diff with Codex. Any blocking finding is verified
against the code and fixed or debated to consensus. The worker commits and
stops; the orchestrator performs the merge.

## Tickets

### T1 — Fail-closed, identity-aware Grok MCP conformance

- Files:
  - `app/backend_grok.py`
  - `tests/test_backend_grok.py`
  - `docs/tasks/98-grok-runtime-audit/report.md`
  - `docs/tasks/98-grok-runtime-audit/codex-review-impl-t1.md`
- Implementation:
  - Normalize expected ACP MCP configs and observed
    `_x.ai/mcp/servers_updated` entries into comparable identities.
  - Ignore discovery-only metadata such as `source`; compare transport,
    command/URL, args, and env pairs. Never render env values in diagnostics.
  - Preserve both expected and observed identities, not only names.
  - Track per-server `ready`/failed status; the pre-init roster proves identity
    and foreign presence, but not successful startup.
  - Wait for MCP initialization even when the expected set is empty, then fail
    on each independent condition:
    - a required name/identity is missing;
    - an unexpected server is present;
    - an expected name is present with a different identity.
    - required servers produce no MCP tools.
  - Keep the root-cause statement scoped: this guard detects the unsafe result;
    it does not claim to resolve historical trust/precedence.
- AC:
  - Exact expected identity and no foreign server passes.
  - A 2×2 parametrized test covers required identity present/absent × foreign
    autodiscovered identity present/absent. Only present/absent passes.
  - A separate same-name test supplies two `orchestra` configs with different
    commands/env and fails without exposing either env value.
  - Missing-only and unexpected-only tests assert distinct diagnostics.
  - An empty expected set still waits for the ready notification and rejects a
    foreign roster.
  - A matching required roster with `mcpToolCount=0` fails closed.
  - When Orchestra fails but another expected MCP is ready and contributes
    tools, conformance still fails specifically on Orchestra readiness.
  - Mutation check: temporarily remove the missing-required branch; the
    missing-only/2×2 test fails, then restore the branch and rerun green.
  - Targeted tests and the full suite pass; Codex approves the slice.
- blocked-by: none

### T2 — Typed aggregate/current/known usage and fail-soft compaction

- Files:
  - `app/events.py` or one new small usage-contract module
  - `app/backend_claude.py`
  - `app/backend_codex.py`
  - `app/backend_grok.py`
  - `app/backend_opencode.py`
  - `app/session_cost.py`
  - `app/session_turns.py`
  - focused backend/session tests
  - `docs/tasks/98-grok-runtime-audit/report.md`
  - `docs/tasks/98-grok-runtime-audit/codex-review-impl-t2.md`
- Implementation:
  - Add one typed turn-usage value that distinguishes cumulative billed input,
    current occupied context, maximum context, and `context_known`.
  - Validate context without throwing away `turn_end`: negative values,
    `current > max`, missing current, or unproved semantics become unknown;
    billed usage/cost remains intact and a visible non-secret diagnostic is
    emitted.
  - Translate every backend's raw usage through the typed value while
    preserving existing metadata keys for consumers.
  - Grok must never use `turn_completed.usage.totalTokens` as current context.
    Use a per-call/runtime field only if its semantics are verified; otherwise
    emit unknown.
  - `CostTracker` and `TurnManager` must clear stale context on explicit
    unknown and must not schedule either generic compact or precompact from an
    unknown/invalid value.
- AC:
  - The measured Grok payload (`inputTokens=1_665_949`,
    `totalTokens=1_678_471`, no supported current value) preserves aggregate
    usage/cost and emits `context_known=false`, not 100%.
  - A valid 84,482/500,000 current value produces 16% and remains known.
  - `current > max`, negative, and absent current values preserve `turn_end`
    but log a warning and schedule no compaction.
  - Valid known context still drives the existing threshold behavior.
  - Contract tests cover all four backends; full suite passes; Codex approves.
- blocked-by: T1

### T3 — Exhaustive model/runtime/provider routing; retire implicit OpenCode selection

- Files:
  - `app/models.py`
  - `app/runtime_registry.py`
  - `app/usage_analytics.py`
  - provider metadata API/view consumed by
    `app/static/js/utils.js`, `app/static/js/analytics.js`, and
    `app/static/js/usage.js`
  - routing, analytics, API, and frontend tests
  - `docs/tasks/98-grok-runtime-audit/opencode-inventory.md`
  - `docs/tasks/98-grok-runtime-audit/report.md`
  - `docs/tasks/98-grok-runtime-audit/codex-review-impl-t3.md`
- Implementation:
  1. Inventory every known deployment, live proxy model response, and
     `ORCHESTRA_RUNTIME_PLUGINS` configuration read-only. Record only sanitized
     model/runtime/provider mappings and consumer counts.
  2. Migrate every model currently relying on `_infer_backend()` to an explicit
     runtime mapping. A proxy model must supply `runtime`/`backend` or match a
     reviewed explicit mapping; it may not silently acquire OpenCode.
  3. Remove the unknown-model → OpenCode catch-all. Unknown model/runtime/
     provider combinations fail loud before a session starts.
  4. Preserve separate flat entities:
     - `ModelSpec` owns model → runtime/provider/context;
     - `RuntimeDefinition` owns harness/capabilities;
     - provider metadata owns accounting/cache/UI presentation.
     Add one exhaustive validator over their references rather than combining
     them into a mega-registry.
  5. Generate analytics bucketing and frontend provider metadata from the
     explicit provider set. Historical/unknown rows use an explicit `unknown`
     bucket, never `ELSE claude`.
  6. Do not delete `backend_opencode.py`. End with a separate evidence-backed
     decision: retain it for explicit consumers, or recommend a later deletion
     ticket when the inventory count is zero everywhere.
- AC:
  - Inventory artifact covers local and registered remote deployments, proxy
    models, and runtime plugins without credential values.
  - Every registered model references an existing runtime and provider; every
    provider has accounting/cache/UI metadata.
  - Dynamically loaded models without an explicit/reviewed runtime fail with a
    diagnostic naming the model.
  - No analytics SQL or frontend fallback classifies an unknown provider as
    Claude; tests enumerate every registered provider.
  - Explicit OpenCode `ModelSpec` entries, if inventory finds any, still route
    correctly; arbitrary unknown models do not.
  - Validation runs against all distinct live persisted model/runtime/provider
    combinations via a read-only DB query before merge.
  - Full suite passes; Codex approves; OpenCode deletion is not part of diff.
- blocked-by: T2

## What is intentionally not changed

- Provider-specific process lifecycle, transport, event dictionaries, tool
  permission handling, compact/resume behavior, and error classifiers remain
  inside their adapters.
- No backend base class is introduced for the 2.8–21.3% exact clone share.
- No historical MCP root cause is declared without a reproducible positive
  trust/collision experiment.
- No service restart, deployment mutation, credential rotation, or live DB
  write is performed.
