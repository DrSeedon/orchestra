# #332 — current post-#309 dead-code reachability audit

## Question

Context: Orchestra `main` at `1c5bf6db975322025fdc9413ae94fdee7abbcd54` (#331), covering
`app/`, `scripts/`, `app/static/js/`, `app/templates/`, and prompt-owned runtime references.

Change under test: classify code that appears cold or unreachable after #309 using Serena/LSP
as a candidate generator plus AST/import/call evidence, FastAPI route decorators, FastMCP
decorators/allowlist, runtime registry, dynamic dispatch, JS DOM/event/fetch references,
templates, prompts, scripts, and systemd/NetworkManager entrypoints.

Baseline: the pre-#309 surface inventory and its proposed deletion rows in
`docs/tasks/309/`; zero LSP references, zero named telemetry, static similarity, or a missing
current route are not sufficient deletion evidence.

Outcome: for each candidate, decide whether a production entry is proven, whether rare
safety/recovery or compatibility prevents deletion, and what exact future behavioral/mutation
oracle would be required. No production/test/pipeline implementation or deletion is authorized
in this phase.

## Hypotheses and falsifiers

1. **H1 — #309 leftovers include truly unreachable implementation.**
   Falsifier: every candidate has a decorator/registry, dynamic string, DOM/template caller,
   external entrypoint, or safety tombstone once all applicable arms are checked.
2. **H2 — Serena zero-reference results identify deletion-safe symbols.**
   Falsifier: a zero-reference result is reached through FastMCP/FastAPI decorators, runtime
   registration, string dispatch, prompt/tool delivery, or is a deliberate tombstone.
3. **H3 — stale proxy scripts are still current production entrypoints.**
   Falsifier: no installed NetworkManager hook/systemd/script caller exists and the external
   proxy-manager service owns route selection.
4. **H4 — route/UI/prompt files with no direct Python calls are dead.**
   Falsifier: a generated/decorator registry, browser event/inline handler, template asset,
   manifest, or runtime worktree consumer reaches them.

## Method and scope controls

- Read-only baseline was checked with `git rev-parse main`, `git log`, `git diff HEAD..main`,
  and `git check-ignore`; the branch advanced from #307 to #331 during the run. A fresh
  `git archive main` was parsed in a temporary directory for the main AST count; no checkout,
  service, DB, environment, provider, or model state was changed.
- Python AST inventory covered all 92 `app/**/*.py` and `scripts/*.py` files. It records
  definitions, calls, imports, decorators, `getattr`/`__import__` candidates, and syntax
  errors. It is candidate generation, not a verdict.
- FastAPI source registry was reconstructed from all route decorators and `app/main.py`
  router inclusion. FastMCP source registry was reconstructed from all `@mcp.tool()`
  decorators and compared with Codex's runtime registry consumer.
- JS checks covered all five loaded JS files, function/name tokens, inline template handlers,
  DOM/event/fetch literals, script order, template asset existence, and `node --check`.
- Prompt checks covered pipeline role skill/module names, file existence, and the repository's
  own `scripts/check_pipeline_manifest.py --check` delivery check.
- External entrypoint checks were read-only: current user systemd unit, installed
  NetworkManager dispatcher path, and repo production references. `check-proxies.sh` was not
  executed because it writes `.env`/proxychains and recommends a service restart.
- Legacy payment/YouGile DB rows/schema, rare recovery/safety mechanisms, model routing #298,
  and live provider probes are excluded as requested. OpenCode is included only for static
  registry/call evidence; no provider/CLI probe was run.

## Findings

### F1 — One production-unreachable JS duplicate is confirmed

`deleteOrchestrator` at `app/static/js/app.js:1646-1657` occurs exactly once in the complete
JS/template/test search: its declaration. No event listener, inline handler, `window` export,
dynamic string, or test names it. The live path is
`initTabContextMenu` → `openDeleteOrchModal` (`app.js:2017,2026-2058`) → the modal's DELETE
handler; `dashboard.html:102-115` supplies that modal. The old function is therefore a
production-unreachable duplicate. **CONFIRMED** — direct JS/DOM search plus positive live-path
source evidence (tier 1 static measurement + primary source).

Proposed action is `DELETE` (12 LOC), but no deletion is made in Phase 1. The required future
oracle is an absence mutation that changes the old declaration count 1→0 while a browser-shaped
positive control still issues `DELETE /api/orchestrators/{name}` and refreshes tabs. A compound
mutation removing both the old helper and the live modal route must fail the positive control;
this prevents a source-only absence check from passing on a broken UI.

### F2 — The two proxy scripts are likely stale, not deletion-proven

`scripts/99-orchestra-proxy` (26 LOC) only installs a NetworkManager dispatcher hook and calls
`scripts/check-proxies.sh`; `scripts/check-proxies.sh` (128 LOC) parses `PROXY_LIST`, mutates
HTTP(S) proxy values in a hard-coded Orchestra `.env`, edits `/etc/proxychains4.conf`, and
requests an Orchestra/Telegram restart. No current `deploy/`, `app/`, `pipelines/`, `.github/`,
or `tests/` production caller invokes them. The installed dispatcher path is absent. The current
user service is `/home/maxim/.config/systemd/user/ai-proxy-manager.service` with
`ExecStart=.../ai_proxy_manager.app --config ...`, and current code documents the external
proxy manager as route owner. **LIKELY stale** — direct local/systemd measurements (tier 1) and
primary current config, but operator-installed copies/manual invocation outside the repository
remain unknown.

Proposed action is `DELETE` only after owner confirmation and a safe synthetic harness. The
required future oracle must inject temporary env/proxychains paths (the current hard-coded
script must not be run), prove no production route depends on the old hook, and retain a
positive `ai-proxy-manager.service` owner control. Deletion dependencies include historical
`CLAUDE.md`, `.env.example`, `CHANGELOG.md`, `docs/tasks/proxy-fix/`, and any operator-installed
copy outside this checkout. No script was executed.

### F3 — Serena false negatives are present and explainable

Serena 1.7.1.dev0, Python LSP ready, returned `{}` for `update_progress`,
`cleanup_old_logs`, `fan_id_for_reducer`, and `refresh_models_endpoint`. Each is not an
automatic deletion candidate:

- `update_progress` is a FastMCP decorator at `app/mcp_stdio.py:1640`, sends the HTTP route at
  `app/routes/sessions.py:2059`, persists live session fields, and is in the worker-facing
  tool/prompt path. The detached-session 404 is intentional. **CONFIRMED live; KEEP.**
- `cleanup_old_logs` is an explicit loud tombstone at `app/db.py:2062-2072` with no callers;
  direct calls must fail rather than delete research history. **CONFIRMED unreachable
  implementation, KEEP compatibility/safety tombstone.**
- `fan_id_for_reducer` has no current caller, but is a reducer safety helper at
  `app/fan_barrier.py:298-308`; the current send path uses `peek_summary` and manifest
  delivery. External reducer integrations are not observable in this repository.
  **UNKNOWN; KEEP.**
- `refresh_models_endpoint` is a FastAPI-decorated route at `app/routes/system.py:389-393`
  and JS calls `/api/models/refresh` at `app/static/js/app.js:7546`. **CONFIRMED live; KEEP.**

These are counterexamples to H2: zero LSP references were refuted by decorators, strings,
runtime entrypoints, and safety semantics (primary source + direct static measurement).

### F4 — Runtime and prompt candidates are reachable

`OpenCodeBackend` is connected by `_opencode_factory` (`app/runtime_registry.py:309-317`) and
the builtin `opencode` definition (`:338-390`); Serena found the factory and backend/routing
tests. `app/backend_harness.py` similarly imports the harness loop/tools/MCP client, and the
`harness` builtin is registered. OpenCode has no current static selectable model in the frozen
manifest, but dynamic catalog/provider routing and tests remain; model/provider execution is
excluded. **CONFIRMED reachable; KEEP.**

`inject_skills_to_worktree` is called by manager/session spawn and refresh paths and is covered
by real-copy/tracked-skill tests. The six pipeline skill files all have manifest consumers,
and the manifest checker is green. **CONFIRMED reachable; KEEP.**

### F5 — Current route/MCP registries contain no post-#309 duplicate surface

The current main archive has 40 FastMCP decorator tools (42 before #309; payment tools are
excluded), and Codex builds its allowlist from the authoritative FastMCP manager with an empty
exclusion set (`app/backend_codex.py:747-758`). The FastAPI decorator scan has 100 routes and
zero duplicate `(verb,path)` keys. `POST /api/models/refresh` has one current definition;
`POST /api/models/catalog/refresh` is distinct. The duplicate warning and duplicate route in
`docs/tasks/309/evidence/route-inventory.csv` are pre-#309 baseline evidence, not a current
candidate. The legacy merge path has no route decorator; middleware keeps a typed 426 migration
guard. **CONFIRMED current registry state; no deletion row.**

### F6 — Templates and JS assets are delivered, with one false-positive parser class

Five JS assets are loaded in dependency order by `dashboard.html`; all 14 `g.asset(...)` paths
exist. `node --check` passed for all five. Inline handler names resolve to definitions; the
scanner's `fetch` and `if` names are language constructs, not missing handlers. Tool-renderer
functions that appeared zero-use in a naive definition counter are called by `app.js` (for
example `toolIcon`, `renderEditDiff`, `renderGrepResults`), so they are KEEP. **CONFIRMED
delivered; static name count alone is rejected.**

### F7 — Other scripts remain manual/operational entrypoints

`build-tailwind.sh` is named by dashboard comments and the Tailwind test; the manifest checker,
blob inventory, migration, CLI inventory, restart rehearsal, process guard/calibration, and
grill scripts have explicit documentation or operational roles. A script's lack of an in-repo
caller is not a production-unreachable verdict: manual/systemd/operator invocation is a valid
entry class. `replay_quota_controller.py` is excluded by the task's #298 model-routing rule.
**LIKELY/CONFIRMED per row; no additional DELETE candidate proven.**

## Counter-evidence

- The stale #309 generated route inventory reports duplicate model-refresh entries, but current
  source has one route and current AST registry has no duplicate key; using the old artifact as
  current truth would create a false candidate.
- Serena's `{}` for decorator/registry/string-dispatch symbols demonstrates LSP undercoverage.
- `fan_id_for_reducer` and the proxy scripts have no in-repo production callers, but external
  reducer/manual operator callers cannot be disproven from this checkout; this keeps the rows
  UNKNOWN/LIKELY rather than CONFIRMED DELETE.
- Static JS token counts can classify inline handlers and object/DOM dispatch incorrectly;
  `deleteOrchestrator` is retained as a candidate only because both template/event and dynamic
  export arms were checked, with `openDeleteOrchModal` as a positive control.
- Existing tests-only evidence is not production liveness: every candidate table row records
  tests separately and does not treat tests as a runtime entry unless paired with a production
  seam.

## Candidate decisions

The fixed decision table is [`candidate-table.csv`](candidate-table.csv). It records exact
behavioral RED, positive control, valid future alternate, compound/fallback mutation, deletion
dependencies, and LOC for each candidate. No row authorizes deletion in this phase.

## Affected files, risks, and edge cases

- Candidate deletion: `app/static/js/app.js:1646-1657`; preserve the modal, route, DOM controls,
  and tab refresh behavior.
- Stale proxy candidates: both scripts plus historical docs/config examples; never execute them
  against the user environment, `.env`, proxychains, Telegram, or Orchestra service.
- Safety/compatibility: `app/db.py` retention tombstone, `app/fan_barrier.py` reducer seam,
  `update_progress`, handoff/merge/recovery, and runtime registry are KEEP/UNKNOWN regardless of
  low or zero observed calls. Legacy payment/YouGile DB schema is intentionally not re-opened.
- Main moved during the run; all source conclusions are keyed to `1c5bf6db`. Evidence scripts
  themselves are Phase-1 artifacts in this branch and are not production code.

## Sources / evidence

1. `docs/tasks/332/evidence/commands.txt` — exact sanitized commands and outputs.
2. `docs/tasks/332/evidence/main-static-summary.txt` — fresh main archive AST parse.
3. `docs/tasks/332/evidence/registry-summary.txt` — FastMCP/FastAPI/prompt/template registry.
4. `docs/tasks/332/evidence/serena.txt` — Serena version, startup, probes, and false negatives.
5. `docs/tasks/332/evidence/js-summary.txt` — DOM/event/fetch/asset and JS candidate audit.
6. `docs/tasks/332/evidence/script-entrypoints.txt` — scripts/systemd/NetworkManager checks.
7. `app/main.py`, `app/mcp_stdio.py`, `app/backend_codex.py`, `app/runtime_registry.py`,
   `app/routes/*.py`, `app/db.py`, `app/fan_barrier.py`, `app/prompting.py` — primary current
   source files at the audited main SHA.
8. `docs/tasks/309/research.md`, `docs/tasks/309/report.md`, and its evidence CSVs — pre-#309
   baseline; stale route duplicate is explicitly not reused as current evidence.

## Confidence summary

- CONFIRMED: one production-unreachable JS duplicate (`deleteOrchestrator`), loud retention
  tombstone (`cleanup_old_logs`), current route/MCP/prompt/asset registry facts, and live runtime
  consumers.
- LIKELY: proxy scripts are stale and proposed for future deletion, pending operator-copy and
  owner confirmation.
- UNKNOWN: `fan_id_for_reducer` external reducer compatibility; keep.
- REFUTED: “zero Serena refs means delete”, “old #309 duplicate route still exists”, and
  “zero direct JS function refs means dead”.
